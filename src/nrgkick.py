#!/usr/bin/python3
#
import requests
import sqlite3

import pytz, os
from datetime import datetime, timezone

import time
import traceback
from chargemanagercommon import initDatabase
from chargemanagercommon import getCurrent
from chargemanagercommon import setPhases
from chargemanagercommon import setChargemode
import logging
import configparser

# --------------------------------------------------------------------------- #
# This python script reads every 15 seconds values from NRGKICK charger and 
# writes them to SQLLite database and activates/deactivates charging on given charging strategy.
# Script was tested with 11KW version of first NRGKICK version (from production-year 2020)
# --------------------------------------------------------------------------- #

config = configparser.RawConfigParser()
config.read('chargemanager.properties')

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/nrgkick.log', filemode='w', level=logging.INFO)
log = logging.getLogger()

NRGKICK_MEASUREMENTS_URL = config.get('Nrgkick', 'measurements.url')
NRGKICK_SETTINGS_URL = config.get('Nrgkick', 'settings.url')

# IMPORTANT: please check the dependencies on this value if you change it 
READ_WRITE_INTERVAL_SEC = 15

retryCountStartCharging = 0
retryDisconnectCount = 0
readChargeStatusFromNRGKick = 0
readChargeValueFromNRGKick = 0

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
        logging.error("Current value out of range: " + str(currentValue))
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
        "Password": """ + config.get('Nrgkick', 'charger.password')+  """
        }
    }
    }
    """
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.put(url=NRGKICK_SETTINGS_URL, data=json_current_value, headers=headers)
        logging.debug("Response start/stop charging: " + str(resp.status_code) + " " + str(json_current_value))
        http_status = resp.status_code
        resp.close()
        return http_status 
    except:
        logging.error(traceback.format_exc()) 
        return -1
#
# Read data from NRGKICK and update database
# returns -1 if fails
# returns actual nrgkick-power 
#
def readAndUpdate():
    global readChargeStatusFromNRGKick, readChargeValueFromNRGKick, retryCountStartCharging
    chargingpower = 0
    try:
        try:
            resp = requests.get(url=NRGKICK_MEASUREMENTS_URL)
        except:
            logging.debug("Could not connect to nrg kick data")
            return -1
        general = resp.json()
        resp.status_code
        resp.close()

        try:
            if (general['Message'] == 'No content found for this request'):
                logging.debug("No NRG connected...")
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

        logging.debug(timestamp)
        logging.debug(chargingpower)
        logging.debug(temperature)
        logging.debug(phase1)
        logging.debug(phase2)
        logging.debug(phase3)

        totalVoltage = int(phase1) + int(phase2) + int(phase3)

        if (totalVoltage > 600):
            setPhases(3)
        elif (totalVoltage > 400):
            setPhases(2)
        elif (totalVoltage > 200):
            setPhases(1)

        try:
            resp = requests.get(url=NRGKICK_SETTINGS_URL)
        except:
            logging.debug("Could not connect to nrg kick settings")
            return -1
        settings = resp.json()
        resp.status_code
        resp.close()

        try:
            errorcode = settings['Info']['ErrorCodes'][0]
            isConnected = boolToInt(settings['Info']['Connected'])
            ischarging = boolToInt(settings['Values']['ChargingStatus']['Charging'])
            readChargeStatusFromNRGKick = ischarging

            chargingcurrent = settings['Values']['ChargingCurrent']['Value']
            readChargeValueFromNRGKick = chargingcurrent
            chargingcurrentmin =settings['Values']['ChargingCurrent']['Min']
            chargingcurrentmax =settings['Values']['ChargingCurrent']['Max']
        except:
            logging.error("Problems reading data from nrgkick!")
            logging.error(traceback.format_exc())
            return -1
        
        logging.debug(errorcode)
        logging.debug(ischarging)
        logging.debug(chargingcurrent)
        logging.debug(chargingcurrentmin)
        logging.debug(chargingcurrentmax)

        con = sqlite3.connect('/data/chargemanager_db.sqlite3')
        cur = con.cursor()
        try:
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
            logging.debug(nrg_update_sql)
            cur.execute(nrg_update_sql)
            con.commit()
        except:
            logging.error(traceback.format_exc()) 
        cur.close()
        con.close() 
    except:
        logging.error(traceback.format_exc())  

    if (isConnected == 0):
        return -1   

    return chargingpower

def setNrgkickDisconnected():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE nrgkick SET connected = 0")
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
    tz = pytz.timezone('Europe/Berlin')
    time.tzset()
    try:
        initDatabase()
        kickWasStartedNow = False 

        while True:
            chargemode = 0
            chargingPossible = 0
            availablePowerRange = 0
            
            actualPower = readAndUpdate()
            # check if nrgkick is available / -1 indicates that nrgkick is offline
            if (actualPower >= 0):
                # if kick was enabled currently, there is a high propability user want to start charging (set it to slow)
                if (kickWasStartedNow == False):
                    setChargemode(2)
                    kickWasStartedNow = True

                con = sqlite3.connect('/data/chargemanager_db.sqlite3')
                cur = con.cursor()
                try:
                    cur.execute("SELECT availablePowerRange,chargingPossible,chargemode FROM controls")
                    data = cur.fetchone()
                    availablePowerRange = data[0]
                    chargingPossible = data[1]
                    chargemode = data[2]
                except:
                    logging.error(traceback.format_exc()) 
                cur.close()
                con.close()

                # calc charge power / min = 6 (default)
                chargePowerValue = 6

                if (chargemode == 0):
                    # disabled mode
                    chargePowerValue = 6
                    chargingPossible = 0
                elif (chargemode == 1):
                    # fast mode
                    chargePowerValue = 15
                    chargingPossible = 1
                elif (chargemode == 2):
                    # slow mode
                    chargePowerValue = 6
                    chargingPossible = 1
                else:
                    # efficient mode
                    chargePowerValue = getCurrent(availablePowerRange)
                
                succesful = False

                # check if NRG Kick status differs from target status
                if (readChargeValueFromNRGKick != chargePowerValue or readChargeStatusFromNRGKick != chargingPossible):
                    for x in range(3):
                        if (chargingPossible == 1):
                            setChargingCurrent(chargePowerValue,True)
                        else:
                            setChargingCurrent(chargePowerValue,False)
                        logging.info("Try to set start charging to: " + str(chargingPossible) + " and charge power value to: " + str(chargePowerValue) + " (A) Retry-Count: " + str(x))
                        
                        # wait for nrg and car sync... this could take a while
                        time.sleep(18)
                        actualPower = readAndUpdate()
                        logging.info("Read actual charging power: " + str(actualPower) + " chargingPossible:" + str(chargingPossible))

                        if ((actualPower > 0 and chargingPossible == 1) or (actualPower == 0 and chargingPossible == 0)): 
                            succesful = True
                            logging.info("Set start charging to: " + str(chargingPossible) + " and charge power to: " + str(actualPower) + " (watt) was sucessful! Retry-Count: " + str(x) )
                            break
                    if (succesful == False):
                        # if it was not succesful to start charging disable charging
                        logging.info("DISABLED CHARGING because set start charging to: " + str(chargingPossible) + " and charge power to: " + str(chargePowerValue) + " (watt) failed! Retry-Count: " + str(x) + " readChargeStatusFromNRGKick: " + str(readChargeStatusFromNRGKick) + " readChargeValueFromNRGKick: " + str(readChargeValueFromNRGKick) + " chargePowerValue: " + str(chargePowerValue) + " availablePowerRange: " + str(availablePowerRange))
                        setChargemode(0)
                # write into charging log
                con = sqlite3.connect('/data/chargemanager_db.sqlite3')
                cur = con.cursor()
                try:
                    tz = pytz.timezone('Europe/Berlin')
                    timestamp = datetime.now(tz)
                    # TO-DO REFACTORING: 
                    # chargingPossible is a problem in this condition if car is full and sun is shining / need to think about a better way for this tracking
                    cur.execute("INSERT INTO 'chargelog' (timestamp,currentChargingPower,chargingPossible) VALUES ('"+ str(timestamp) + "',"  + str(actualPower) + "," + str(chargingPossible) + ")")
                    con.commit()
                except:
                    logging.error(traceback.format_exc()) 
                cur.close()
                con.close()
                retryDisconnectCount = 0
            else:
                # count retries and only disable after 3 times unavailable to avoid short network interrupts
                retryDisconnectCount += 1
                if (retryDisconnectCount == 3):
                        setNrgkickDisconnected()
                        kickWasStartedNow = False
                        logging.info("Could not reach NRGKICK, set it now to disconnect status!")
                elif (retryCountStartCharging > 3):
                        # wait 30 seconds after try to reconnect, to reduce heavy reconnect try if it seems to be disconnected
                        time.sleep(30)
                        # avoid overloading counter
                        retryCountStartCharging = 4
            time.sleep(READ_WRITE_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    


