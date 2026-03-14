#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Module reads every 15 seconds values from NRGKICK charger and 
# writes them to SQLLite database and activates/deactivates charging on given charging strategy.
# Script was tested with 11KW version of first NRGKICK version (from production-year 2020)
# --------------------------------------------------------------------------- #

import requests
import sqlite3

import pytz, os
from datetime import datetime

import time
import traceback
import chargemanagercommon
import logging
from wallbox import nrgkickcontroller
from wallbox import pulsarwallboxcontroller
from wallbox import kebap30controller

log = logging.getLogger(__name__)
os.environ['TZ'] = 'Europe/Berlin'
tz = pytz.timezone('Europe/Berlin')
time.tzset()

NRGKICK_MEASUREMENTS_URL = 0
NRGKICK_SETTINGS_URL = 0
NRGKICK_PASSWORD = 0
MAX_PHASES = 0
 
READ_WRITE_INTERVAL_SEC = 4

# save date to wallbox table in database
def saveWallboxData(deviceDict, deviceID):
    con = chargemanagercommon.getDBConnection()
    timestamp = datetime.now(tz)

    try:
        cur = con.cursor()
        update_sql = """
        UPDATE wallboxes SET 
            timestamp = ?, 
            chargingpower = ?, 
            temperature = ?, 
            phases = ?, 
            errorcode = ?, 
            connected = ?, 
            ischarging = ?, 
            chargingcurrent = ?
        WHERE id = """ + str(deviceID) + """
        """
        values = (
            str(timestamp),
            int(deviceDict['chargingpower']),
            int(deviceDict['temperature']),
            int(deviceDict['phases']),
            int(deviceDict['errorcode']),  
            int(deviceDict['isconnected']),
            int(deviceDict['ischarging']),
            int(deviceDict['chargingcurrent'])
        )

        log.debug(update_sql)
        cur.execute(update_sql, values)
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()


#
#   Main, init and repeat reading
#
def main():
    log.info("Module " + str(__name__) + " started...")

    nrgkick = nrgkickcontroller.NrgkickController()
    pulsar = pulsarwallboxcontroller.PulsarWallboxController()
    kebap30 = kebap30controller.Kebap30Controller()

    devices = [nrgkick, pulsar, kebap30]

    while True:
        try:
            chargemode = chargemanagercommon.getChargemode()
            chargingPossible = 0
            availablePowerRange = 0
            
            for device in devices:

                deviceDict = device.readData()
                saveWallboxData(deviceDict,device.getID())

                # if a wallbox is charging lock others for to avoid conflicts during control (only controll one by time)....
                if (device.isCharging()):
                    for lockeddevices in devices:
                        if lockeddevices.getID() != device.getID():
                            lockeddevices.set_locked(True)
                        else:
                            lockeddevices.set_locked(False)
                #log.info(str(device.getID()) + " " + str(device.isAvailable()) + " " + str(device.isCharging()) + " " + str(device.isActiveChargingSession()) + " " + str(device.is_locked()))

                # check if wallbox is available and not locked
                if (device.isAvailable() and device.is_locked() == False):
                                       
                    # log.info("Wallbox ID " + str(device.getID()) + ": " + str(actualPower) + " (Watt), chargingPossible:" + str(chargingPossible) + " isavailable: " + str(device.isAvailable()) + " activeSession:" + str(device.isActiveChargingSession()))
                    # wallbox pluged in currently, there was no charge-session before...
                    if (chargemode == chargemanagercommon.DISABLED_MODE and device.isCharging() and device.isActiveChargingSession() == False):
                        chargemode = chargemanagercommon.SLOW_MODE
                        chargemanagercommon.setChargemode(chargemode)
                        device.setActiveChargingSession(True)
                    
                    con = chargemanagercommon.getDBConnection()              
                    
                    try:
                        cur = con.cursor()
                        cur.execute("SELECT availablePowerRange,chargingPossible FROM controls")
                        data = cur.fetchone()
                        cur.close()
                        availablePowerRange = data[0]
                        chargingPossible = data[1]
                        
                    except:
                        log.error(traceback.format_exc()) 
                        con.close()
                        continue # ignore the rest of code an retry until we get database back because we do not have plausible values
                    finally:
                        con.close()

                    # calc charge power / min = 6 (default)
                    chargePowerValue = 6

                    if (chargemode == chargemanagercommon.DISABLED_MODE):
                        # disabled mode
                        # set to current value to avoid to send a change event to nrgkick
                        chargePowerValue = device.getChargingLevel()
                        chargingPossible = 0
                    if (chargemode == chargemanagercommon.FAST_MODE):
                        # fast mode
                        chargePowerValue = 15
                        chargingPossible = 1
                    elif (chargemode == chargemanagercommon.SLOW_MODE):
                        # slow mode
                        chargePowerValue = 6
                        chargingPossible = 1
                    else:
                        # tracked mode
                        chargePowerValue = chargemanagercommon.getCurrent(availablePowerRange,device.getID())
                    
                    succesful = False

                    # check if NRG Kick status differs from target status
                    if (device.getChargingLevel() != chargePowerValue or device.isCharging() != chargingPossible):
                        log.info("cloudy:" + str(chargemanagercommon.getCloudy()) + " availablePowerRange:" + str(availablePowerRange) +  ", chargemode: " + str(chargemode) + ", chargingPossible: " + str(chargingPossible) + ", chargePowerValue:" + str(chargePowerValue))
                        
                        for x in range(3):
                            if (chargingPossible == 1):
                                device.setCharging(chargePowerValue,True)
                            else:
                                device.setCharging(chargePowerValue,False)
                            log.info("Try to set start charging to: " + str(chargingPossible) + " and charge power value to: " + str(chargePowerValue) + " (A) Retry-Count: " + str(x) + " wallboxid:" + str(device.getID()))
                            
                            # wait for nrg and car sync... this could take a while  
                            time.sleep(13)

                            deviceDict = device.readData()
                            saveWallboxData(deviceDict,device.getID())
                            
                            log.info("Read actual charging power for Wallbox ID " + str(device.getID()) + ": " + str(int(deviceDict['chargingpower'])) + " (Watt), chargingPossible:" + str(chargingPossible) + " isCharging:" + str(device.isCharging()))

                            if ((device.isCharging() and chargingPossible == 1) or (device.isCharging() == False and chargingPossible == 0)): 
                                succesful = True
                                # reset chargingSession
                                if (chargingPossible == 1):
                                    log.info("Set charge power to: " + str(int(deviceDict['chargingpower'])) + " (watt), Wallbox ID: " + str(device.getID()) + ", Retry-Count: " + str(x))
                                    device.setActiveChargingSession(True)
                                else:
                                    log.info("Stop charging now. Wallbox ID: " + str(device.getID()) + ", Retry-Count: " + str(x))
                                    device.setActiveChargingSession(False)
                                break
                        if (succesful == False):

                            # check if any other wallbox is charging
                            overallStatus = False
                            for deviceSecond in devices:
                                if (deviceSecond.isCharging()):
                                    overallStatus = True
                            # do not disable if any other wallbox is charging
                            if (overallStatus == False):
                                # if it was not succesful to start charging disable charging
                                log.info("Disabled charging. Wallbox: " + str(device.getID()) + " Car might be full")
                                log.debug("Set start charging to: " + str(chargingPossible) + " and charge power to: " + str(chargePowerValue) + " (watt) failed! Retry-Count: " + str(x) + " device.isCharging(): " + str(device.isCharging()) + " device.getChargingLevel(): " + str(device.getChargingLevel()) + " chargePowerValue: " + str(chargePowerValue) + " availablePowerRange: " + str(availablePowerRange) + " actualPower:" + str(int(deviceDict['chargingpower'])))
                                if (chargemode != chargemanagercommon.DISABLED_MODE):
                                    chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                                    nrgkick.setCharging(chargePowerValue,False)
                                    device.setActiveChargingSession(False)
                                    # wait 10 seconds to give kick a chance to switch to new instruction
                                    time.sleep(10)
                    # write into charging log
                    con = chargemanagercommon.getDBConnection()
                    
                    try:
                        cur = con.cursor()
                        timestamp = datetime.now(tz)
                        # TO-DO REFACTORING: 
                        # chargingPossible is a problem in this condition if car is full and sun is shining / need to think about a better way for this tracking
                        cur.execute("INSERT INTO 'chargelog' (timestamp,currentChargingPower,chargingPossible) VALUES ('"+ str(timestamp) + "',"  + str(int(deviceDict['chargingpower'])) + "," + str(chargingPossible) + ")")
                        con.commit()
                        cur.close()
                    except:
                        log.error(traceback.format_exc()) 
                    finally:
                        con.close()
                    device.setRetryCount(0)
                else:
                    # count retries and only disable after 2 times unavailable to avoid short network interrupts
                    count = device.getRetryCount()
                    count += 1
                    device.setRetryCount(count)
                    
                    if (device.getRetryCount() == 3):
                            device.setActiveChargingSession(False)
                            # check if any other wallbox is charging
                            overallStatus = False
                            for deviceSecond in devices:
                                if (deviceSecond.isCharging()):
                                    overallStatus = True

                            if (overallStatus == False):
                                # all boxes are not charging                               
                                if (chargemanagercommon.getChargemode() != chargemanagercommon.DISABLED_MODE):
                                    chargemanagercommon.setWallboxDisconnected(device.getID())

                                    chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                                    # unlock all devices
                                    for lockeddevices in devices:
                                        device.set_locked(False)
                                    # all wallboxes are not charging...wait extra times to reduce network traffic
                                    time.sleep(4)
                                    log.info("No wallbox is charging any more, set it to disabled! ActualPower: " + str(int(deviceDict['chargingpower'])) + ",retryDisconnectCount:" +  str(device.getRetryCount()))
                            else:
                                # repeate until all wallboxes are offline
                                device.setRetryCount(2) # old value + increment

                    elif (device.getRetryCount() > 3):
                            # do not repeate disable mode again and again... 
                            device.setRetryCount(4) # avoid overloading counter and 
                            time.sleep(2)
                            #log.info("_DEBUG: actualPower:" + str(actualPower) + ",  retryDisconnectCount: " + str(retryDisconnectCount) + ",  readChargeStatusFromNRGKick: " + str(readChargeStatusFromNRGKick) + ",  readChargeValueFromNRGKick: " + str(readChargeValueFromNRGKick) + ", chargemode: " + str(chargemode) + ", chargingPossible: " + str(chargingPossible) + ", chargePowerValue:" + str(chargePowerValue) + ", activeChargingSession:" + str(activeChargingSession))               
                time.sleep(READ_WRITE_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            break
        except:
            log.error("Some error happens, try to repeat: " + traceback.format_exc())
   
