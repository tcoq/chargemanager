#!/usr/bin/python3
#
import sqlite3 

import pytz, os
from datetime import datetime, timezone

import time
import traceback
import chargemanagercommon
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

# IMPORTANT: if you want to change this interval pls recalculate checkCloudyConditions!
READ_INTERVAL_SEC = 10
availablePowerRange = 0
# init value with a high number to enable charging directly after software startup
powerChangeCount = 10000
house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc'))
# calculate threshold depending on peak performance of total solar-power, 
# ... tested on 9400 watt system with std_dev_threshold of 585, which results in divisor of 16
STD_DEV_THRESHOLD = int(config.get('Solaredge', 'modules.peak')) / 16
CHARGEMODE_AUTO = int(config.get('Chargemanager', 'chargemode.auto'))
batteryProtectionCounter = 0
batteryProtectionEnabled = False
cloudyCounter = 0
cloudyModeEnabled = False
toggleToTrackedMode = True

#
# Method checks the standard derivation of the solar production of the last 15 minutes
# returns :
# 0 = not cloudy
# 1 = cloudy
#
def checkCloudyConditions():
    global logCount, cloudyCounter, cloudyModeEnabled
    
    cloudy = 0
    
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()

    stdDev = 0
    trend = None
    try:
        cur.execute("select pvprod from modbus WHERE timestamp between datetime('now','-15 minute','localtime') AND datetime('now','localtime') order by timestamp asc")
        result = cur.fetchall()
        cur.close()
        if (len(result) <= 1):
            con.close()
            return cloudy

        data = [row[0] for row in result]
        # calculate trend if trend[0] is negativ it is a negative trend otherwise it is a positve trend
        trend = [b - a for a, b in zip(data[::1], data[1::1])]
        # negative trend:
        # we only want stddev calcs at negative trends...
        if (int(trend[0]) <= 0):
            cur = con.cursor()
            con.create_aggregate("stdev", 1, chargemanagercommon.StdevFunc)
            cur.execute("select stdev(pvprod) from modbus WHERE timestamp between datetime('now','-15 minute','localtime') AND datetime('now','localtime') AND pvprod > 10")
            result = cur.fetchone()[0]
            cur.close()
            if (result != None):
                stdDev = int(result)
    except:
        logging.error(traceback.format_exc()) 
    con.close() 

    # check if it is cloudy
    if (stdDev > STD_DEV_THRESHOLD):
        cloudyCounter += 2
        if (cloudyCounter >= 60):
            cloudyCounter = 60
    else:
        # decrease slower than increase...
        cloudyCounter -= 1
        if (cloudyCounter <= 0):
            cloudyCounter = 0

    if (cloudyCounter > 35):
        if (cloudyModeEnabled == False):
            cloudyModeEnabled = True
            cloudyCounter = 60
        cloudy = 1
        logging.debug("Stdev: " + str(stdDev) + " cloudy: " + str(cloudy) + ", trend: " + str(trend[0]) + ", cloudyCnt: " + str(cloudyCounter) + ", cloudymodeEnabled: " + str(cloudyModeEnabled))
    else:
        cloudyModeEnabled = False

    return cloudy
#
# Calculte the efficient charging strategy
#
def calcEfficientChargingStrategy():
    global availablePowerRange,powerChangeCount, house_battery_soc_threshold_start_charging, batteryProtectionCounter, batteryProtectionEnabled, toggleToTrackedMode
    currentAvailablePower = 0
    previousAvailablePowerRange = 0
    newAvailablePowerRange = 0
    chargingPossible = 0
    currentBatteryPower = 0
    soc = 0

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("select avg(availablepower_withoutcharging),avg(availablepowerrange),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-4 minute','localtime') AND datetime('now','localtime') UNION select avg(availablepower_withoutcharging),avg(availablepowerrange),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-8 minute','localtime') AND datetime('now','-4 minute','localtime')")
        rows = cur.fetchall()
        cur.close()
        con.close()

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
                previousAvailablePowerRange = chargemanagercommon.getPowerRange(temprow1)
            else:
                # newer data
                currentAvailablePower = temprow0
                newAvailablePowerRange = chargemanagercommon.getPowerRange(temprow1)
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

    # check if weather is cloudy
    cloudyConditions = checkCloudyConditions()
    # avoid unnecessary writes
    if (chargemanagercommon.getCloudy != cloudyConditions):
        chargemanagercommon.setCloudy(cloudyConditions)
    # due to cloudy conditions we want to charge with low rates to increase stability
    
    minCharge = 0
    # get min charge threshold based on PHASES configuration from properties file
    phases = chargemanagercommon.getPhases()
    if (phases == 1):
        minCharge = 1400
    elif (phases == 2):
        minCharge = 2800
    elif (phases == 3):
        minCharge = 4500

    if ((cloudyConditions == 1) and newAvailablePowerRange >= minCharge):
        # reduce power in steps, if its cloudy to avoid to low charging values...
        if (newAvailablePowerRange > (minCharge + 2500)):
            newAvailablePowerRange = minCharge + 2000
        elif (newAvailablePowerRange > (minCharge + 1500)):
            newAvailablePowerRange = minCharge + 1000
        else:
            newAvailablePowerRange = minCharge

    # enable charging when battery soc is high enougth and useful power is existing
    # soc == 0 means house-battery is disabled / not available
    if ((int(soc) >= house_battery_soc_threshold_start_charging or int(soc) == 0) and currentAvailablePower >= minCharge):
        chargingPossible = 1
        # allow to get 5% out of house-battery for stabel charging conditions
        house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc')) - 5
    elif (currentBatteryPower > int(config.get('Chargemanager', 'battery.max_input'))):
        # in this case we have quite enought power and battery cannot get more because limit is at 4900
        chargingPossible = 1
        # we need to set threshold to a low value to avoid to stop after the next round
        house_battery_soc_threshold_start_charging = int(soc) - 5
    else:
        chargingPossible = 0
        house_battery_soc_threshold_start_charging = int(config.get('Chargemanager', 'battery.start_soc'))

    # automatically switch from SLOW to TRACKED charge mode if CHARGEMODE_AUTO is enabled 
    # and toggleToTrackedMode == True which is used to only change chargemode once in one charging-session
    if (toggleToTrackedMode == True and CHARGEMODE_AUTO == 1 and chargingPossible == 1 and cloudyConditions == 0 and chargemanagercommon.getChargemode() != 0):
        logging.info("Auto switch to tracked mode! currentBatteryPower: " + str(currentBatteryPower) + " soc: " + str(soc) + " currentAvailablePower: " + str(currentAvailablePower))
        if (chargemanagercommon.getChargemode() == 2):
            # set to TRACKED mode
            chargemanagercommon.setChargemode(3)
            # toggle to avoid multi toggle in a charging-session / reset toggle is done below if charinging is stopped
            toggleToTrackedMode = False

    # 5 minutes / 300 seconds
    changeTimeSec = 300

    logging.debug("Current (set) available power: " + str(currentAvailablePower) + " previous range:" + str(previousAvailablePowerRange) + " new range:" + str(newAvailablePowerRange) + " availablePowerRange:" + str(availablePowerRange) + " minCharge: " + str(minCharge) + " phase: " + str(chargemanagercommon.getPhases()))
    logging.debug("powerChangeCount: " + str(powerChangeCount) + " changeTimeSec:" + str(changeTimeSec) + " cloudy: " + str(cloudyConditions) + " currentBatteryPower: " + str(currentBatteryPower) + " chargingPossible: " + str(chargingPossible) + " soc: " + str(soc))

    # check if battery consumption is very high (attention: currentBatteryPower has - sign during consumption and + sign during loading)
    if (currentBatteryPower < (int(config.get('Chargemanager', 'battery.max_consumption')) * -1) and chargingPossible == 1):
        batteryProtectionCounter += 5
        if (batteryProtectionCounter >= 120):
            batteryProtectionCounter = 120
    else:
        # decrease slower than increase...
        batteryProtectionCounter -= 1
        if (batteryProtectionCounter <= 0):
            batteryProtectionCounter = 0

    # if battery-consumption is very high, stop charging as soon as possible / 2 minutes or break stable power gurantee to recalculate power values
    # activation after 60 = 2minutes (120sec/10sec_interval * 5 = 60),
    # deactvation after min. +10 minutes when upper battery consumption check is no longer true (60*10sec_interval * 1) = 600sec = 10min)
    if (batteryProtectionCounter > 60):
        if (batteryProtectionEnabled == False):
            batteryProtectionCounter = 120
            batteryProtectionEnabled = True
        # break waiting for recalculation
        powerChangeCount = 10000
        
        # stop charging only if sun is really left (under min charge, otherwise powerChangeCount = 10000 breaks halt lower timer to allow a power recalculation)
        if (currentAvailablePower < minCharge):
            chargingPossible = 0
            logging.info("Battery protection activated, stop charging now! Battery-protection-counter: " + str(batteryProtectionCounter) + " currentBatteryPower: " + str(currentBatteryPower))
    else:
        batteryProtectionEnabled = False

    # guarantee stable power for at least 5 minutes and also avoid to start / stop charging to much
    if ((powerChangeCount >= (changeTimeSec / READ_INTERVAL_SEC))):
        availablePowerRange = newAvailablePowerRange
        powerChangeCount = 0

        con = sqlite3.connect('/data/chargemanager_db.sqlite3')
        cur = con.cursor()
        try:
            # reset toggle
            if (chargingPossible == 0):      
                toggleToTrackedMode = True
            cur.execute("UPDATE controls set availablePowerRange = " + str(availablePowerRange) + ", chargingPossible=" + str(chargingPossible))
            con.commit()
        except:
            logging.error(traceback.format_exc()) 
        cur.close()
        con.close()

        logging.info("Current available power range changed to: " + str(newAvailablePowerRange) + " last available power range was:" + str(availablePowerRange) + " chargingPossible: " + str(chargingPossible))

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
    chargemanagercommon.init() 
    
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
    


