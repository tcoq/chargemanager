#!/usr/bin/python3
#
# copyright notice ###
# This module uses code-snippet from https://github.com/turais/tplink-smartplug which is available on Apache 2.0 licence
#
# --------------------------------------------------------------------------- #
# Module activates / deactivates TP-Link smart plug based on actual 
# PV overproduction / free PV power
# --------------------------------------------------------------------------- #

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
PLUG_ON_POWER = 0
FIRST_PLUG_START_FROM = "00:00"
FIRST_PLUG_START_TO = "00:00"
SECOND_PLUG_START_FROM = "00:00"
SECOND_PLUG_START_TO = "00:00"
PLUG_START_FROM_SOC = 0
PLUG_ALLOWED_USE_HOUSE_BATTERY = 0
PLUG_PORT = 9999

def readSettings():
    global PLUG_IP,PLUG_ON_POWER, PLUG_START_FROM_SOC, PLUG_ENABLED, FIRST_PLUG_START_FROM, FIRST_PLUG_START_TO, SECOND_PLUG_START_FROM, SECOND_PLUG_START_TO, PLUG_ALLOWED_USE_HOUSE_BATTERY
    if (chargemanagercommon.SMARTPLUG_SETTINGS_DIRTY == True):
        PLUG_IP = chargemanagercommon.getSetting(chargemanagercommon.PLUGIP)
        PLUG_ON_POWER = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGONPOWER))
        FIRST_PLUG_START_FROM = chargemanagercommon.getSetting(chargemanagercommon.FIRSTPLUGSTARTFROM)
        FIRST_PLUG_START_TO = chargemanagercommon.getSetting(chargemanagercommon.FIRSTPLUGSTARTTO)
        SECOND_PLUG_START_FROM = chargemanagercommon.getSetting(chargemanagercommon.SECONDPLUGSTARTFROM)
        SECOND_PLUG_START_TO = chargemanagercommon.getSetting(chargemanagercommon.SECONDPLUGSTARTTO)
        PLUG_START_FROM_SOC = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGSTARTFROMSOC))
        PLUG_ENABLED = int(chargemanagercommon.getSetting(chargemanagercommon.PLUGENABLED))
        PLUG_ALLOWED_USE_HOUSE_BATTERY = int(chargemanagercommon.getSetting(chargemanagercommon.ALLOWPLUGUSEHOUSEBATTERY))
        chargemanagercommon.SMARTPLUG_SETTINGS_DIRTY == False

def isNowBetweenTimes(fromTime,toTime):
    if (fromTime == toTime):
        return False

    tz = pytz.timezone('Europe/Berlin')
    nowDate = datetime.now(tz)
    fromTmpDate = nowDate.strptime(fromTime, '%H:%M')
    toTmpDate = nowDate.strptime(toTime, '%H:%M')
    fromDate = nowDate.replace(hour=fromTmpDate.hour, minute=fromTmpDate.minute, second=0, microsecond=0)
    toDate = nowDate.replace(hour=toTmpDate.hour, minute=toTmpDate.minute, second=0, microsecond=0)

    if (fromDate <= nowDate <= toDate):
        return True
    else:
        return False

def isPowerOnNowAllowed():
    if (isNowBetweenTimes(FIRST_PLUG_START_FROM,FIRST_PLUG_START_TO) == True):
        return True
    elif (isNowBetweenTimes(SECOND_PLUG_START_FROM,SECOND_PLUG_START_TO) == True):
        return True
    return False


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
    status = sendCommand('{"system":{"set_relay_state":{"state":0}}}')
    if (status != False):
        chargemanagercommon.setSmartPlugStatus(0)

def setPlugOn():
    status = sendCommand('{"system":{"set_relay_state":{"state":1}}}')
    if (status != False):
        chargemanagercommon.setSmartPlugStatus(1)

def getPower():
    relay_state = sendCommand('{"emeter":{"get_realtime":{}}}')['emeter']['get_realtime']['power']
    if (relay_state == -1):
        return 0
    return relay_state
#
#	Main, init and repeat reading
#
def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()

    log.info("Module " + str(__name__) + " started...")

    # sleep 3 minutes
    SLEEP = 180

    logPlugFound = True
    logPlugNotFound = True

    powerOn = False
    lastPowerState = True
    setFromTrackedToSlowMode = False

    while(True):
        readSettings()

        ALLOW_CHARGE_FROM_BATTERY_SOC = 99
        availablePower = 0
        actualPlugPower = 0
        nrgKickPower = 0
        chargeMode = chargemanagercommon.DISABLED_MODE

        try:
            if (isPlugAvailable() == True and PLUG_ENABLED == 1):
                if (logPlugFound):
                    log.info("SmartPlug found at " + str(PLUG_IP) + " , start control...")
                    logPlugFound = False
                    logPlugNotFound = True

                if (isPowerOnNowAllowed() == False):
                    if (lastPowerState == True):
                        log.info("SmartPlug switched off because time interval is no longer allowed")
                        setPlugOff()
                    powerOn = False
                    lastPowerState = powerOn
                    setFromTrackedToSlowMode = False
                    time.sleep(30)
                    continue
                
                actualPlugPower = int(getPower())

                nrgKickPower = chargemanagercommon.isNrgkickCharging()
                # check if NRGKick is charging the car
                if (nrgKickPower > 0):
                    chargeMode = chargemanagercommon.getChargemode() 
                    # avoid turning smart plug on in FAST charging mode
                    if (chargeMode == chargemanagercommon.FAST_MODE):
                        powerOn = False
                        lastPowerState = powerOn
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
                    # substract nrgKickPower to know the right available power
                    availablePower = int(data[0]) - nrgKickPower
                    soc = int(data[1])
                except:
                    log.error(traceback.format_exc()) 
                    con.close()
                    log.error('Problems fetching modbus data!')
                    time.sleep(10)
                    continue # ignore the rest of code an retry until we get database back because we do not have plausible values
                con.close()

                # check if nrgkick is charging
                if (nrgKickPower > 0):
                    # check if there is not enough available power during charging and TRACKED chargeMode is on
                    if (lastPowerState == False and availablePower < PLUG_ON_POWER and chargeMode == chargemanagercommon.TRACKED_MODE):
                        # set to SLOW to give smartPlug more available power
                        chargemanagercommon.setChargemode(chargemanagercommon.SLOW_MODE)
                        setFromTrackedToSlowMode = True
                    # set back to tracked mode if tracked mode was activated bevor and plug power is gone because e.g. tank is full of heat
                    if (lastPowerState == True and actualPlugPower == 0 and setFromTrackedToSlowMode == True):
                        chargemanagercommon.setChargemode(chargemanagercommon.TRACKED_MODE)

                try:
                    # we have enough free PV power... start charging based on given time-window and min SOC
                    if (soc > PLUG_START_FROM_SOC and int(availablePower + actualPlugPower) > PLUG_ON_POWER):
                        powerOn = True
                        log.info("Normal power on! availablePower:" + str(availablePower) + " plugPower: " + str(actualPlugPower))
                    # battery is full but PV power is not enought now... allow using house battery with max 55% Watt consumption and in given time windows
                    elif (int(soc) >= ALLOW_CHARGE_FROM_BATTERY_SOC and int(availablePower + actualPlugPower) > (PLUG_ON_POWER * -0.55) and PLUG_ALLOWED_USE_HOUSE_BATTERY == 1):
                        powerOn = True
                        ALLOW_CHARGE_FROM_BATTERY_SOC = 94
                        log.info("Charge from battery power on! availablePower:" + str(availablePower) + " plugPower: " + str(actualPlugPower))
                    else:
                        powerOn = False
                        ALLOW_CHARGE_FROM_BATTERY_SOC = 99
                        

                    if (powerOn == True):
                        if (lastPowerState == False):
                            setPlugOn()
                    else:
                        if (lastPowerState == True):
                            setPlugOff() 
                            log.info("SmartPlug switched off because PV power is gone! (" + str(int(availablePower)) + " Watt)")
                            # sleep double time to avoid turn on / off shortly after each other until it is cloudy
                            time.sleep(SLEEP)
                    
                    lastPowerState = powerOn
                except:
                    log.error(traceback.format_exc()) 
                    setPlugOff()
                    powerOn = False
                    lastPowerState = powerOn
            else:
                if (logPlugNotFound):
                    log.warn('TP-Link smart plug is disabled or not found!')
                    chargemanagercommon.setSmartPlugStatus(0)
                    logPlugFound = True
                    logPlugNotFound = False
                    powerOn = False
                    lastPowerState = powerOn
            time.sleep(SLEEP)

        except KeyboardInterrupt:
            setPlugOff()
            powerOn = False
            lastPowerState = powerOn
            break
        except:
            log.error("Some error happens, try to repeat: " + traceback.format_exc())
            setPlugOff()
            powerOn = False
            lastPowerState = powerOn


