#!/usr/bin/python3
#
import sqlite3 

import pytz, os
from datetime import datetime, timezone

import time
import traceback
from chargemanagercommon import initDatabase
from chargemanagercommon import getPowerRange
import logging
import configparser

# --------------------------------------------------------------------------- #
# Chargemanager is responsible for calculating the right charge strategy based 
# PV values
# --------------------------------------------------------------------------- #

config = configparser.RawConfigParser()
config.read('chargemanager.properties')

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/chargemanager.log', filemode='w', level=logging.INFO)
log = logging.getLogger()

PHASES = config.get('Car', 'charging.phases')

# IMPORTANT: if you want to change this interval pls recalculate checkCloudyConditions!
READ_INTERVAL_SEC = 10
availablePowerRange = 0
powerChangeCount = 0
cloudyWeatherProbabilityCount = 0
house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc'))
batteryProtectionCounter = 0

def checkCloudyConditions(oldPowerRange, newPowerRange):
    global cloudyWeatherProbabilityCount

    # check if powerrange moves a lot, this might be an indicator for cloudy weather
    if (newPowerRange < oldPowerRange):
        # increase higher than decrease, to avoid to quick changes between cloudy or not
        cloudyWeatherProbabilityCount +=4
        if (cloudyWeatherProbabilityCount > (90)): 
            cloudyWeatherProbabilityCount = (90)
    else:
        cloudyWeatherProbabilityCount -=1
        if (cloudyWeatherProbabilityCount < 1): 
            cloudyWeatherProbabilityCount = 0

    # if powerrange jumps > 17 times up and down in 90*10 seconds (15 minutes), weather might be cloudy 
    if (cloudyWeatherProbabilityCount > 17):
        logging.debug("CloudyWeatherProbabilityCount [range: 0-90] is true with: " + str(cloudyWeatherProbabilityCount) + " newRange: " + str(newPowerRange) + " oldRange: " + str(oldPowerRange))
        return True
    else:
        logging.debug("CloudyWeatherProbabilityCount [range: 0-90] is false with: " + str(cloudyWeatherProbabilityCount) + " newRange: " + str(newPowerRange) + " oldRange: " + str(oldPowerRange))
        return False
#
# Calculte the efficient charging strategy
#
def calcEfficientChargingStrategy():
    global availablePowerRange,powerChangeCount, house_battery_soc_threshold_start_charging, batteryProtectionCounter
    currentAvailablePower = 0
    previousAvailablePowerRange = 0
    newAvailablePowerRange = 0
    chargingPossible = 0
    currentBatteryPower = 0
    soc = 0

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("select avg(availablepower_withoutcharging),avg(availablepowerrange),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-4 minute','localtime') AND datetime('now','localtime') UNION select avg(availablepower_withoutcharging),avg(availablepowerrange),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-10 minute','localtime') AND datetime('now','-4 minute','localtime')")
        rows = cur.fetchall()
        first = True
        index = 0
        for row in rows:
            
            temprow0 = 0
            temprow1 = 0
            temprow2 = 0
            temprow3 = 0

            if (row[0] != None):
                temprow0 = row[0]
            if (row[1] != None):
                temprow1 = row[1]
            if (row[2] != None):
                temprow2 = row[2]
            if (row[3] != None):
                temprow3 = row[3]

            if (first):
                # correct avg value from database
                previousAvailablePowerRange = getPowerRange(temprow1)
            else:
                # newer data
                currentAvailablePower = temprow0
                # correct avg value from database
                newAvailablePowerRange = getPowerRange(temprow1)
                currentBatteryPower = temprow3
                soc = temprow2
            if (index >= 2):
                logging.error("SQL returns more than 2 rows! ") 
                break
            logging.debug(str(first) + " previousAvailablePowerRange: " + str(previousAvailablePowerRange) + " currentAvailablePower:" + str(currentAvailablePower) + " newAvailablePowerRange:" + str(newAvailablePowerRange) + " soc:" + str(soc) + " currentBatteryPower:" + str(currentBatteryPower))
            index += 1
            first = False
    except:
        logging.error(traceback.format_exc())  
    cur.close()
    con.close()

    # check if weather is cloudy
    cloudyConditions = checkCloudyConditions(previousAvailablePowerRange,newAvailablePowerRange)
    # due to cloudy conditions we want to charge with low rates to increase stability
    
    minCharge = 0
    # get min charge threshold based on PHASES configuration from properties file
    if (int(PHASES) == 2):
        minCharge = 2500
    elif (int(PHASES) == 3):
        minCharge = 4500

    if (cloudyConditions and newAvailablePowerRange >= minCharge):
            newAvailablePowerRange = minCharge

    # enable charging when battery soc is high enougth and useful power is existing
    if (int(soc) >= house_battery_soc_threshold_start_charging and currentAvailablePower > minCharge):
        chargingPossible = 1
        # allow to get 5% out of house-battery for stabel charging conditions
        house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc')) - 5
    elif (currentAvailablePower > int(config.get('Chargemanager', 'battery.max_input'))):
        # in this case we have quite enought power and battery cannot get more because limit is at 5000
        chargingPossible = 1
    else:
        chargingPossible = 0
        house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc'))

    # 5 minutes / 300 seconds
    changeTimeSec = 300

    logging.debug("Current (set) available power: " + str(currentAvailablePower) + " previous range:" + str(previousAvailablePowerRange) + " new range:" + str(newAvailablePowerRange) + " availablePowerRange:" + str(availablePowerRange))
    logging.debug("powerChangeCount: " + str(powerChangeCount) + " changeTimeSec:" + str(changeTimeSec) + " cloudy: " + str(cloudyConditions) + " currentBatteryPower: " + str(currentBatteryPower))

    # check if battery consumption is very high
    if (currentBatteryPower < (int(config.get('Chargemanager', 'battery.max_consumption')) * -1)):
        batteryProtectionCounter += 2
        if (batteryProtectionCounter > 200):
            batteryProtectionCounter = 200
    else:
        # decrease slower than increase...
        batteryProtectionCounter -= 1
        if (batteryProtectionCounter <= 0):
            batteryProtectionCounter = 0

    # if battery-consumption is very high, stop charging as soon as possible / 2 minutes (24 * 10 sec with ++2)
    if (batteryProtectionCounter > 24):
        powerChangeCount = 10000
        availablePowerRange = 0
        chargingPossible = 0
        logging.info("Battery protection activated, stop charging now!")

    # guarantee stable power for at least 5 minutes and also avoid to start / stop charging to much
    if ((powerChangeCount >= (changeTimeSec / READ_INTERVAL_SEC))):
        availablePowerRange = newAvailablePowerRange
        powerChangeCount = 0

        con = sqlite3.connect('/data/chargemanager_db.sqlite3')
        cur = con.cursor()
        try:
            cur.execute("UPDATE controls set availablePowerRange = " + str(availablePowerRange) + ", chargingPossible=" + str(chargingPossible))
            con.commit()
        except:
            logging.error(traceback.format_exc()) 
        cur.close()
        con.close()
        logging.info("Current available power range changed to: " + str(newAvailablePowerRange) + " last available power range was:" + str(availablePowerRange))

    # check if ranges changes
    if (availablePowerRange != newAvailablePowerRange):
        powerChangeCount += 1
    else:
        powerChangeCount = 0

#
#	Delete data older 72 h
#
def cleanupData():
    logging.debug("Try connecting sqllite...")
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    try:
        cur = con.cursor()
        cur.execute("delete from chargelog where timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("vacuum")
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close() 

#
#	Main, init and repeat reading
#
if __name__ == "__main__":
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()

    initDatabase()   
    
    try:
        while True:
            time.sleep(READ_INTERVAL_SEC)
            logging.debug("sleeped " + str(READ_INTERVAL_SEC) + " seconds")
            try:
                calcEfficientChargingStrategy()
                cleanupData()
            except:
                logging.error(traceback.format_exc())
    except KeyboardInterrupt:
        pass
    


