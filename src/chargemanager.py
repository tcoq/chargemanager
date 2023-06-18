#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Chargemanager is responsible for calculating the right charge strategy based 
# PV values
# --------------------------------------------------------------------------- #
import sqlite3 

import os
from datetime import datetime

import time
import traceback
import chargemanagercommon
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# IMPORTANT: if you want to change this interval pls recalculate checkCloudyConditions!
READ_INTERVAL_SEC = 10
availablePowerRange = 0
# init value with a high number to enable charging directly after software startup
powerChangeCount = 10000
HOUSE_BAT_SOCO_START = 0
BATTERY_MAX_CONSUMPTION = 0
STD_DEV_THRESHOLD = 0
CHARGEMODE_AUTO = 0

batteryProtectionCounter = 0
batteryProtectionEnabled = False
cloudyCounter = 0
cloudyModeEnabled = False
toggleToTrackedMode = True


def readSettings():
    global HOUSE_BAT_SOCO_START,BATTERY_MAX_CONSUMPTION,STD_DEV_THRESHOLD,CHARGEMODE_AUTO
    if (chargemanagercommon.CHARGEMANAGER_SETTINGS_DIRTY == True):
        HOUSE_BAT_SOCO_START = int(chargemanagercommon.getSetting(chargemanagercommon.BATTERYSTARTSOC))
        BATTERY_MAX_CONSUMPTION = int(chargemanagercommon.getSetting(chargemanagercommon.BATTERYMAXCONSUMPTION))
        # calculate threshold depending on peak performance of total solar-power, 
        # ... tested on 9400 watt system with std_dev_threshold of 585, which results in divisor of 16
        STD_DEV_THRESHOLD = int(chargemanagercommon.getSetting(chargemanagercommon.PVPEAKPOWER)) / 16
        CHARGEMODE_AUTO = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGEMODEAUTO))
        chargemanagercommon.CHARGEMANAGER_SETTINGS_DIRTY == False
#
# Method checks the standard derivation of the solar production of the last 15 minutes
# returns :
# 0 = not cloudy
# 1 = cloudy
#
def checkCloudyConditions():
    global logCount, cloudyCounter, cloudyModeEnabled
    
    cloudy = 0
    
    con = chargemanagercommon.getDBConnection()

    stdDev = 0
    trend = None
    try:
        cur = con.cursor()
        cur.execute("select pvprod from modbus WHERE timestamp between datetime('now','-15 minute','localtime') AND datetime('now','localtime') order by timestamp asc")
        result = cur.fetchall()
        cur.close()
        if (len(result) <= 1):
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
        log.error(traceback.format_exc()) 
    finally:
        con.close()

    # check if it is cloudy
    if (stdDev > STD_DEV_THRESHOLD):
        cloudyCounter += 2
        if (cloudyCounter >= 70):
            cloudyCounter = 70
    else:
        # decrease slower than increase...
        cloudyCounter -= 1
        if (cloudyCounter <= 0):
            cloudyCounter = 0

    if (cloudyCounter > 30):
        if (cloudyModeEnabled == False):
            cloudyModeEnabled = True
            cloudyCounter = 70
        cloudy = 1
        log.debug("Stdev: " + str(stdDev) + " cloudy: " + str(cloudy) + ", trend: " + str(trend[0]) + ", cloudyCnt: " + str(cloudyCounter) + ", cloudymodeEnabled: " + str(cloudyModeEnabled))
    else:
        cloudyModeEnabled = False

    return cloudy
#
# Calculte the efficient charging strategy
#
def calcEfficientChargingStrategy():
    global availablePowerRange,powerChangeCount, batteryProtectionCounter, batteryProtectionEnabled, toggleToTrackedMode
    previousAvailablePowerRange = 0
    newAvailablePowerRange = 0
    chargingPossible = 0
    currentBatteryPower = 0
    soc = 0

    con = chargemanagercommon.getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("select avg(availablepower_withoutcharging),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-4 minute','localtime') AND datetime('now','localtime') UNION select avg(availablepower_withoutcharging),max(soc),min(batterypower) from modbus WHERE timestamp between datetime('now','-8 minute','localtime') AND datetime('now','-4 minute','localtime')")
        rows = cur.fetchall()
        cur.close()

        first = True
        index = 0
        for row in rows:
            
            temprow0 = 0
            temprow1 = 0
            temprow2 = 0

            if (row[0] != None):
                temprow0 = row[0]
            if (row[1] != None):
                temprow1 = row[1]
            if (row[2] != None):
                temprow2 = row[2]

            if (first):
                previousAvailablePowerRange = chargemanagercommon.getPowerRange(temprow0)
            else:
                # newer data
                newAvailablePowerRange = chargemanagercommon.getPowerRange(temprow0)
                currentBatteryPower = temprow2
                soc = temprow1
            if (index >= 2):
                log.error("SQL returns more than 2 rows! ") 
                break
            log.debug(str(first) + " previousAvailablePowerRange: " + str(previousAvailablePowerRange) + " newAvailablePowerRange:" + str(newAvailablePowerRange) + " soc:" + str(soc) + " currentBatteryPower:" + str(currentBatteryPower))
            index += 1
            first = False
    except:
        log.error(traceback.format_exc())  
    finally:
        con.close()
     
    # check if weather is cloudy
    cloudyConditions = checkCloudyConditions()
    # avoid unnecessary writes
    if (chargemanagercommon.getCloudy != cloudyConditions):
        chargemanagercommon.setCloudy(cloudyConditions)
    # due to cloudy conditions we want to charge with low rates to increase stability
    
    thisDayTime = datetime.now()
    minCharge = 0
    # get min charge threshold based on PHASES configuration from properties file
    phases = chargemanagercommon.getPhases()
    if (phases == 1):
        minCharge = 1400
    elif (phases == 2):
        minCharge = 2800
    elif (phases == 3):
        minCharge = 4500

    badTrackedChargingConditions = 0

    if ((cloudyConditions == 1) and newAvailablePowerRange >= minCharge):
        # reduce power in steps, if its cloudy to avoid to low charging values...
        if (newAvailablePowerRange > (minCharge + 2500)):
            newAvailablePowerRange = chargemanagercommon.getPowerRange(minCharge + 2000)
        elif (newAvailablePowerRange > (minCharge + 1500)):
            newAvailablePowerRange = chargemanagercommon.getPowerRange(minCharge + 1000)
            badTrackedChargingConditions = 1
        elif (newAvailablePowerRange > (minCharge + 1000)):
            newAvailablePowerRange = chargemanagercommon.getPowerRange(minCharge + 700)
            badTrackedChargingConditions = 1
        else:
            newAvailablePowerRange = minCharge

    # enable charging when enought PV power exist
    if (newAvailablePowerRange >= minCharge):
        chargingPossible = 1
    else:
        chargingPossible = 0

    # 5 minutes / 300 seconds
    changeTimeSec = 300

    log.debug("Current (set) available power range: " + str(newAvailablePowerRange) + " previous range:" + str(previousAvailablePowerRange) + " new range:" + str(newAvailablePowerRange) + " availablePowerRange:" + str(availablePowerRange) + " minCharge: " + str(minCharge) + " phase: " + str(chargemanagercommon.getPhases()))
    log.debug("powerChangeCount: " + str(powerChangeCount) + " changeTimeSec:" + str(changeTimeSec) + " cloudy: " + str(cloudyConditions) + " currentBatteryPower: " + str(currentBatteryPower) + " chargingPossible: " + str(chargingPossible) + " soc: " + str(soc))

    # check if battery consumption is very high (attention: currentBatteryPower has - sign during consumption and + sign during loading)
    if (currentBatteryPower < (BATTERY_MAX_CONSUMPTION * -1) and chargingPossible == 1):
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
        
        # stop charging only if sun is really left and it is out of time range (under min charge, otherwise powerChangeCount = 10000 breaks halt lower timer to allow a power recalculation)
        if (newAvailablePowerRange < minCharge and chargemanagercommon.getChargemode() != chargemanagercommon.FAST_MODE):
            log.info("Battery protection activated, stop charging now! Battery-protection-counter: " + str(batteryProtectionCounter) + " currentBatteryPower: " + str(currentBatteryPower))
            if (thisDayTime.hour < 16 and thisDayTime.hour > 8):
                chargemanagercommon.setChargemode(chargemanagercommon.SLOW_MODE) # slow
                log.info("Battery protection switch to slow mode! Hour: " + str(thisDayTime.hour))
            else:
                chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE) # disabled
                log.info("Battery protection switch to disabled mode! Hour: " + str(thisDayTime.hour))
    else:
        batteryProtectionEnabled = False

    # if tracked mode is already on toggle to tracked mode: avoid to reactivate if a manual mode switch by user
    # avoid switching to tracked mode if it is cloudy
    if (chargemanagercommon.getChargemode() == chargemanagercommon.TRACKED_MODE or badTrackedChargingConditions == 1):
        toggleToTrackedMode = False

    # GUARANTEE stable power for at least 5 minutes and also avoid to start / stop charging to much
    if ((powerChangeCount >= (changeTimeSec / READ_INTERVAL_SEC))):
        availablePowerRange = newAvailablePowerRange
        powerChangeCount = 0

        # automatically switch from SLOW to TRACKED charge mode if CHARGEMODE_AUTO is enabled 
        # and toggleToTrackedMode == True which is used to only change chargemode once in one charging-session 
        # (currentAvailablePower) >= minCharge + 400 = use a little bit more min power to avoid falling back to slow charing 
        if (toggleToTrackedMode == True and 
            CHARGEMODE_AUTO == 1 and
            chargingPossible == 1 and 
            newAvailablePowerRange >= (minCharge + 400) and 
            int(soc) > HOUSE_BAT_SOCO_START and
            chargemanagercommon.getChargemode() != chargemanagercommon.DISABLED_MODE and 
            chargemanagercommon.getChargemode() != chargemanagercommon.FAST_MODE): 
            if (chargemanagercommon.getChargemode() == chargemanagercommon.SLOW_MODE):
                # set to TRACKED mode
                chargemanagercommon.setChargemode(chargemanagercommon.TRACKED_MODE)
                # toggle to avoid multi toggle in a charging-session / reset toggle is done below if charinging is stopped
                toggleToTrackedMode = False
                log.info("Auto switch to tracked mode! currentBatteryPower: " + str(currentBatteryPower) + " soc: " + str(soc) + " newAvailablePowerRange: " + str(newAvailablePowerRange))

        # in this case it is cloudy, TRACKED MODE is on and sun was available but suddenly gone..
        # we need to avoid to start/stop charging! For this reason switch to slow mode and charge with battery support until soc is high enough
        if (chargingPossible == 0 and 
            thisDayTime.hour < 16 and 
            thisDayTime.hour > 8 and 
            chargemanagercommon.getChargemode() == chargemanagercommon.TRACKED_MODE):
            
            chargemanagercommon.setChargemode(chargemanagercommon.SLOW_MODE)
            # allow to switch back to tracked mode when conditions are getting better...
            toggleToTrackedMode = True
            log.info("Auto switch from tracked to slow mode! Hour: " + str(thisDayTime.hour))

        con = chargemanagercommon.getDBConnection()
        try:
            # reset toggle if there is no free power anymore and charging was disabled to avoid jumping back from manual mode to tracked
            cm = chargemanagercommon.getChargemode()
            if (chargingPossible == 0 and cm == chargemanagercommon.DISABLED_MODE): # 0 DISABLED     
                toggleToTrackedMode = True
            cur = con.cursor()
            cur.execute("UPDATE controls set availablePowerRange = " + str(availablePowerRange) + ", chargingPossible=" + str(chargingPossible))
            con.commit()
            cur.close()
        except:
            log.error(traceback.format_exc()) 
        finally:
            con.close()
        log.debug("Current available power range changed to: " + str(newAvailablePowerRange) + " last available power range was:" + str(availablePowerRange) + " chargingPossible: " + str(chargingPossible) + " phases: " + str(phases) + " cloudy: " + str(cloudyConditions) + " minCharge: " + str(minCharge) + " soc:" + str(soc))

    # check if power ranges changes
    if (availablePowerRange != newAvailablePowerRange):
        powerChangeCount += 1
    else:
        powerChangeCount = 0

#
#	Delete data older 72 h
#
def cleanupData():
    log.debug("Try connecting sqllite...")
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute("delete from chargelog where timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.close()
        cur = con.cursor()
        cur.execute("vacuum")
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

#
#	Main, init and repeat reading
#
def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    
    log.info("Module " + str(__name__) + " started...")

    try:
        while True:
            readSettings()

            time.sleep(READ_INTERVAL_SEC)
            log.debug("sleeped " + str(READ_INTERVAL_SEC) + " seconds")
            try:
                if (chargemanagercommon.isNrgkickConnected() == 1 and chargemanagercommon.getChargemode() != chargemanagercommon.DISABLED_MODE):
                    calcEfficientChargingStrategy()

                dt = datetime.now()
                # clean data 00:00:<31
                if (dt.hour == 0 and dt.minute == 0 and dt.second < 19):
                    start = time.process_time()
                    cleanupData()
                    log.info("cleanupData duration: " + str(time.process_time() - start))
            except:
                log.error(traceback.format_exc())
    except KeyboardInterrupt:
        pass
    


