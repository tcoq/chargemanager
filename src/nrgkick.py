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

log = logging.getLogger(__name__)

NRGKICK_MEASUREMENTS_URL = 0
NRGKICK_SETTINGS_URL = 0
NRGKICK_PASSWORD = 0
MAX_PHASES = 0

# IMPORTANT: please check the dependencies on this value if you change it 
READ_WRITE_INTERVAL_SEC = 10

retryDisconnectCount = 0
readChargeStatusFromNRGKick = 0
readChargeValueFromNRGKick = 0

def readSettings():
    global NRGKICK_MEASUREMENTS_URL,NRGKICK_SETTINGS_URL,NRGKICK_PASSWORD,MAX_PHASES
    if (chargemanagercommon.NRGKICK_SETTINGS_DIRTY == True):
        NRGKICK_MEASUREMENTS_URL = chargemanagercommon.getSetting(chargemanagercommon.MEASUREMENTURL)
        NRGKICK_SETTINGS_URL = chargemanagercommon.getSetting(chargemanagercommon.SETTINGSURL)
        NRGKICK_PASSWORD = chargemanagercommon.getSetting(chargemanagercommon.CHARGERPASSWORD)
        MAX_PHASES = chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES)
        chargemanagercommon.NRGKICK_SETTINGS_DIRTY = False

def boolToInt(input):
    if str(input).casefold() == 'true':
        return 1
    return 0
#
# Set charging current
# valid range from 6- 16
# returns -1 if fails
# returns http-status code if success
#
def setChargingCurrent(currentValue,startCharging):
    chargemode = "true"
    if startCharging == False:
        chargemode = "false"

    if currentValue < 6 or currentValue > 16:
        log.error("Current value out of range: " + str(currentValue))
        return -1

    json_current_value = """
    {
    "Values": {
        "ChargingStatus": {
        "Charging": """ + str(chargemode) + " " + """
        },
        "ChargingCurrent": {
        "Value": """ + str(currentValue) + ", " + """
        "Min": """ + str(currentValue) + ", " + """
        "Max": """ + str(currentValue) + " " + """
        },
        "DeviceMetadata": {
        "Password": """ + str(NRGKICK_PASSWORD) +  """
        }
    }
    }
    """
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.put(url=NRGKICK_SETTINGS_URL, data=json_current_value, headers=headers)
        log.debug("Response start/stop charging: " + str(resp.status_code) + " " + str(json_current_value))
        http_status = resp.status_code
        resp.close()
        return http_status 
    except:
        log.error(traceback.format_exc()) 
        return -1
#
# Read data from NRGKICK and update database
# returns -1 if fails, -2 if Kick is available but not plugged in
# returns actual nrgkick-power 
#
def readAndUpdate():
    global readChargeStatusFromNRGKick, readChargeValueFromNRGKick, retryDisconnectCount
    chargingpower = 0
    isConnected = -1
    try:
        try:
            resp = requests.get(url=NRGKICK_MEASUREMENTS_URL)
        except:
            log.debug("Could not connect to nrg kick data")
            return -1
        general = resp.json()
        resp.status_code
        resp.close()

        try:
            if (general['Message'] == 'No content found for this request'):
                log.debug("No NRG connected...")
                return -1
        except:
            # nrgkick is not connected but bluetooth device is available
            pass

        timestamp = general['Timestamp']
        # convert value from kilowatt to watt
        chargingpower = int(float(general['ChargingPower']) * 1000)
        temperature = general['TemperatureMainUnit']

        phase1 = general['VoltagePhase'][0]
        phase2 = general['VoltagePhase'][1]
        phase3 = general['VoltagePhase'][2]

        log.debug(timestamp)
        log.debug(chargingpower)
        log.debug(temperature)
        log.debug(phase1)
        log.debug(phase2)
        log.debug(phase3)

        totalVoltage = int(phase1) + int(phase2) + int(phase3)
        # read phases to avoid unnecessary writes
        phases = chargemanagercommon.getPhases()
        phasesNew = 0
        
        if (totalVoltage > 600 and MAX_PHASES == 3):
            phasesNew = 3
        elif (totalVoltage > 400):
            phasesNew = 2
        elif (totalVoltage > 200):
            phasesNew = 1

        if (phases != phasesNew):
            try:
                chargemanagercommon.setPhases(phasesNew)
            except:
                 pass   
            
        try:
            resp = requests.get(url=NRGKICK_SETTINGS_URL)
        except:
            log.debug("Could not connect to nrg kick settings")
            return -1
        settings = resp.json()
        resp.status_code
        resp.close()
        
        try:
            errorcode = settings['Info']['ErrorCodes'][0]
            isConnected = boolToInt(settings['Info']['Connected'])
            ischarging = boolToInt(settings['Values']['ChargingStatus']['Charging'])
            readChargeStatusFromNRGKick = int(ischarging)

            chargingcurrent = settings['Values']['ChargingCurrent']['Value']
            readChargeValueFromNRGKick = int(chargingcurrent)
            chargingcurrentmin =settings['Values']['ChargingCurrent']['Min']
            chargingcurrentmax =settings['Values']['ChargingCurrent']['Max']
        except:
            log.error("Problems reading data from nrgkick!")
            log.error(traceback.format_exc())
            return -1
        
        log.debug(errorcode)
        log.debug(ischarging)
        log.debug(chargingcurrent)
        log.debug(chargingcurrentmin)
        log.debug(chargingcurrentmax)

        con = chargemanagercommon.getDBConnection()
        
        # sometimes NRGKick delivers incorrect data from the second URL... 
        # chargingpower is the stronger signal so set isConnected and isCharging to true
        if (chargingpower > 1):
            isConnected = 1
            ischarging = 1
            
        try:
            cur = con.cursor()
            nrg_update_sql = """
            UPDATE 'nrgkick' SET 
            timestamp = """ + str(timestamp) + "," + """
            chargingpower = """ + str(chargingpower) + "," + """
            temperature  = """ + str(temperature) + "," + """
            errorcode = """ + str(errorcode) + "," + """
            connected = """ + str(isConnected) + "," + """
            ischarging = """ + str(ischarging) + "," + """
            chargingcurrent = """ + str(chargingcurrent) + "," + """
            chargingcurrentmin = """ + str(chargingcurrentmin) + "," + """
            chargingcurrentmax = """ + str(chargingcurrentmax) + """
            """
            log.debug(nrg_update_sql)
            cur.execute(nrg_update_sql)
            con.commit()
            cur.close()
        except:
            log.error(traceback.format_exc()) 
        finally:
            con.close()
    except:
        log.error(traceback.format_exc())  

    if (isConnected == 0):
        return -2   

    return chargingpower

#
#   Main, init and repeat reading
#
def main():
    global retryDisconnectCount, readChargeStatusFromNRGKick,readChargeValueFromNRGKick

    os.environ['TZ'] = 'Europe/Berlin'
    tz = pytz.timezone('Europe/Berlin')
    time.tzset()

    activeCharingSession = 0

    log.info("Module " + str(__name__) + " started...")


    while True:
        try:
            readSettings()

            chargemode = chargemanagercommon.getChargemode()
            chargingPossible = 0
            availablePowerRange = 0
            
            actualPower = readAndUpdate()

            # check if nrgkick is available / -1 indicates that nrgkick is offline
            if (actualPower >= 0):
                
                # NRGKick pluged in currently, there was no charge-session before...
                if (chargemode == chargemanagercommon.DISABLED_MODE and (actualPower > 1 or readChargeStatusFromNRGKick == 1) and activeCharingSession == 0):
                    chargemode = chargemanagercommon.SLOW_MODE
                    chargemanagercommon.setChargemode(chargemode)
                    activeCharingSession = 1
                
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
                    chargePowerValue = readChargeValueFromNRGKick
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
                    chargePowerValue = chargemanagercommon.getCurrent(availablePowerRange)
                    # always charge in tracked mode (at least with minCharge)
                    chargingPossible = 1
                
                succesful = False

                # check if NRG Kick status differs from target status
                if (readChargeValueFromNRGKick != chargePowerValue or readChargeStatusFromNRGKick != chargingPossible):
                    #log.info("DEBUG: actualPower:" + str(actualPower) + ",  retryDisconnectCount: " + str(retryDisconnectCount) + ",  readChargeStatusFromNRGKick: " + str(readChargeStatusFromNRGKick) + ",  readChargeValueFromNRGKick: " + str(readChargeValueFromNRGKick) + ", chargemode: " + str(chargemode) + ", chargingPossible: " + str(chargingPossible) + ", chargePowerValue:" + str(chargePowerValue) + ", activeCharingSession:" + str(activeCharingSession))
                    
                    for x in range(3):
                        if (chargingPossible == 1):
                            setChargingCurrent(chargePowerValue,True)
                        else:
                            setChargingCurrent(chargePowerValue,False)
                        log.debug("Try to set start charging to: " + str(chargingPossible) + " and charge power value to: " + str(chargePowerValue) + " (A) Retry-Count: " + str(x))
                        
                        # wait for nrg and car sync... this could take a while
                        time.sleep(12)
                        actualPower = readAndUpdate()
                        log.debug("Read actual charging power: " + str(actualPower) + " chargingPossible:" + str(chargingPossible))

                        if ((actualPower > 0 and chargingPossible == 1) or (actualPower == 0 and chargingPossible == 0)): 
                            succesful = True
                            # reset chargingSession
                            if (chargingPossible == 1):
                                log.info("Set charge power to: " + str(actualPower) + " (watt) Retry-Count: " + str(x))
                                activeCharingSession = 1
                            else:
                                log.info("Stop charging now... Retry-Count: " + str(x))
                                activeCharingSession = 0
                            break
                    if (succesful == False):
                        # if it was not succesful to start charging disable charging
                        log.info("Disabled charging. Car might be full")
                        log.debug("Set start charging to: " + str(chargingPossible) + " and charge power to: " + str(chargePowerValue) + " (watt) failed! Retry-Count: " + str(x) + " readChargeStatusFromNRGKick: " + str(readChargeStatusFromNRGKick) + " readChargeValueFromNRGKick: " + str(readChargeValueFromNRGKick) + " chargePowerValue: " + str(chargePowerValue) + " availablePowerRange: " + str(availablePowerRange) + " actualPower:" + str(actualPower))
                        if (chargemode != chargemanagercommon.DISABLED_MODE):
                            chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                            setChargingCurrent(chargePowerValue,False)
                            activeCharingSession = 0
                            # wait 10 seconds to give kick a chance to switch to new instruction
                            time.sleep(10)
                # write into charging log
                con = chargemanagercommon.getDBConnection()
                
                try:
                    cur = con.cursor()
                    tz = pytz.timezone('Europe/Berlin')
                    timestamp = datetime.now(tz)
                    # TO-DO REFACTORING: 
                    # chargingPossible is a problem in this condition if car is full and sun is shining / need to think about a better way for this tracking
                    cur.execute("INSERT INTO 'chargelog' (timestamp,currentChargingPower,chargingPossible) VALUES ('"+ str(timestamp) + "',"  + str(actualPower) + "," + str(chargingPossible) + ")")
                    con.commit()
                    cur.close()
                except:
                    log.error(traceback.format_exc()) 
                finally:
                    con.close()
                retryDisconnectCount = 0
            else:
                # count retries and only disable after 3 times unavailable to avoid short network interrupts
                retryDisconnectCount += 1
                
                if (retryDisconnectCount == 3):
                        chargemanagercommon.setNrgkickDisconnected()
                        chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                        activeCharingSession = 0
                        log.info("Could not reach NRGKICK, set it now to disconnect status and reset chargemode to disabled! ActualPower: " + str(actualPower) + ",retryDisconnectCount:" +  str(retryDisconnectCount))
                        #log.info("_DEBUG: actualPower:" + str(actualPower) + ",  retryDisconnectCount: " + str(retryDisconnectCount) + ",  readChargeStatusFromNRGKick: " + str(readChargeStatusFromNRGKick) + ",  readChargeValueFromNRGKick: " + str(readChargeValueFromNRGKick) + ", chargemode: " + str(chargemode) + ", chargingPossible: " + str(chargingPossible) + ", chargePowerValue:" + str(chargePowerValue) + ", activeCharingSession:" + str(activeCharingSession))
                elif (retryDisconnectCount > 3):
                        # wait 5 extra seconds after try to reconnect, to reduce heavy reconnect try if it seems to be disconnected
                        time.sleep(5)
                        # avoid overloading counter
                        retryDisconnectCount = 4                
            time.sleep(READ_WRITE_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            break
        except:
            log.error("Some error happens, try to repeat: " + traceback.format_exc())
   
