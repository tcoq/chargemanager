#!/usr/bin/python3
#
import sqlite3
import socket
import json
from struct import pack
import chargemanagercommon
import logging
import traceback
import time
import pytz, os
from datetime import datetime

log = logging.getLogger(__name__)

PLUG_IP = 0
PLUG_MAX_SECONDS = 0
PLUG_ON_POWER = 0
PLUG_START_FROM_HOUR = 0
PLUG_START_FROM_SOC = 0
PLUG_PORT = 9999

def readSettings():
    global PLUG_IP,PLUG_MAX_SECONDS,PLUG_ON_POWER,PLUG_START_FROM_HOUR, PLUG_START_FROM_SOC, PLUG_ENABLED
    if (chargemanagercommon.SMARTPLUG_SETTINGS_DIRTY == True):
        PLUG_IP = chargemanagercommon.getSetting(chargemanagercommon.PLUGIP)
        PLUG_MAX_SECONDS = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGMAXSECONDS))
        PLUG_ON_POWER = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGONPOWER))
        PLUG_START_FROM_HOUR = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGSTARTFROM))
        PLUG_START_FROM_SOC = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGSTARTFROMSOC))
        PLUG_ENABLED = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGENABLED))
        chargemanagercommon.SMARTPLUG_SETTINGS_DIRTY == False


def encrypt(string):
    key = 171
    result = pack('>I', len(string))
    for i in string:
        a = key ^ ord(i)
        key = a
        result += bytes([a])
    return result


def decrypt(string):
    key = 171
    result = ""
    for i in string:
        a = key ^ i
        key = i
        result += chr(a)
    return result

def sendCommand(command):
    try:
        sock_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_tcp.settimeout(10)
        sock_tcp.connect((PLUG_IP, PLUG_PORT))
        sock_tcp.send(encrypt(command))
        data = sock_tcp.recv(2048)
        sock_tcp.close()

        decrypted = decrypt(data[4:])
        return json.loads(decrypted)
    except:
        # log.warn("Could not sendCommand... maybe device is not available...") 
        # do nothing
        true = 1
    return -1

def isPlugAvailable():
    relay_state = sendCommand('{"system":{"get_sysinfo":{}}}')
    if (relay_state == -1):
        return False
    return True

def isPlugOn():
    relay_state = sendCommand('{"system":{"get_sysinfo":{}}}')['system']['get_sysinfo']['relay_state']
    if (relay_state == 1):
        return True
    return False

def setPlugOff():
    if (isPlugOn() == True):
        status = sendCommand('{"system":{"set_relay_state":{"state":0}}}')
        log.info("SmartPlug power off...")
        if (status != False):
            chargemanagercommon.setSmartPlugStatus(0)

def setPlugOn():
    if (isPlugOn() == False):
        log.info("SmartPlug power on...")
        status = sendCommand('{"system":{"set_relay_state":{"state":1}}}')
        if (status != False):
            chargemanagercommon.setSmartPlugStatus(1)

#
#	Main, init and repeat reading
#
def main():
    os.environ['TZ'] = 'Europe/Berlin'
    tz = pytz.timezone('Europe/Berlin')
    time.tzset()

    log.info("Module " + str(__name__) + " started...")

    # sleep 3 minutes
    SLEEP = 180

    logPlugFound = True
    logPlugNotFound = True
    logPowerLimitReached = True

    powerOn = False
    lastPowerState = False
    powerOnInSeconds = 0
    lastDay = datetime.now().day

    while(True):
        readSettings()
        thisHour = datetime.now().hour

        # reset powerOnInSeconds until the day has changed to the next day...
        if (lastDay != (datetime.now().day)):
            powerOnInSeconds = 0
            lastDay = datetime.now().day
            
        try:
            if (isPlugAvailable() == True and PLUG_ENABLED == 1):
                if (logPlugFound):
                    log.info("SmartPlug found at " + str(PLUG_IP) + " , start control...")
                    logPlugFound = False
                    logPlugNotFound = True
                
                availablePowerRange = 0

                status = chargemanagercommon.isNrgkickCharging()
                if (status == 1):
                    setPlugOff()
                    time.sleep(30)
                    continue

                con = sqlite3.connect('/data/chargemanager_db.sqlite3')
                cur = con.cursor()
                try:
                    cur = con.cursor()
                    cur.execute("select avg(availablepower_withoutcharging),max(soc) from modbus WHERE timestamp between datetime('now','-4 minute','localtime') AND datetime('now','localtime')")
                    data = cur.fetchone()
                    cur.close()
                    availablePowerRange = int(data[0])
                    soc = int(data[1])
                except:
                    log.error(traceback.format_exc()) 
                    con.close()
                    log.error('Problems fetching modbus data!')
                    time.sleep(10)
                    continue # ignore the rest of code an retry until we get database back because we do not have plausible values
                con.close()

                try:
                    cloudyOffset = 0
                    if(chargemanagercommon.getCloudy() == 1):
                        cloudyOffset = 550

                    #log.info("soc: " + str(soc) + " , availablePowerRange: " + str(availablePowerRange))  
                    if (soc > PLUG_START_FROM_SOC and thisHour >= PLUG_START_FROM_HOUR and int(availablePowerRange + cloudyOffset) > PLUG_ON_POWER and powerOnInSeconds < PLUG_MAX_SECONDS):
                        setPlugOn()
                        powerOn = True
                    else:
                        setPlugOff()
                        powerOn = False

                        # only log if last power state was "power on"
                        if (lastPowerState == True):
                            # log reason why plug is turned of only one time a day until logPowerLimitReached was reset
                            if (powerOnInSeconds >= PLUG_MAX_SECONDS):
                                log.info("SmartPlug switched off because max seconds limit ( " + str(PLUG_MAX_SECONDS) + " ) reached!")
                            else:
                                log.info("SmartPlug switched off because PV power is gone! (" + str(int(availablePowerRange + cloudyOffset)) + " Watt)")
                                # sleep double time to avoid turn on / off shortly after each other until it is cloudy
                                time.sleep(SLEEP)
                    lastPowerState = powerOn
                except:
                    log.error(traceback.format_exc()) 
            else:
                if (logPlugNotFound):
                    log.warn('No TP-Link smart plug found or plug control is disabled!')
                    chargemanagercommon.setSmartPlugStatus(0)
                    logPlugFound = True
                    logPlugNotFound = False
                    powerOn = False
            time.sleep(SLEEP)

            # track how many "sleeps" power is on... 
            if (powerOn):
                powerOnInSeconds = powerOnInSeconds + SLEEP

        except KeyboardInterrupt:
            break
        except:
            log.error("Some error happens, try to repeat: " + traceback.format_exc())


