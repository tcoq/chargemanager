#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Wallbox Manager: Reads data from multiple wallboxes (NRGKick, Pulsar, KEBA)
# and manages charging strategies based on available solar power.
# --------------------------------------------------------------------------- #

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

# Setup logging and timezone
log = logging.getLogger(__name__)
os.environ['TZ'] = 'Europe/Berlin'
tz = pytz.timezone('Europe/Berlin')
time.tzset()

READ_WRITE_INTERVAL_SEC = 4

def saveWallboxData(deviceDict, deviceID):
    """Updates the 'wallboxes' table with current live telemetry."""
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
        WHERE id = ?
        """
        values = (
            str(timestamp),
            int(deviceDict['chargingpower']),
            int(deviceDict['temperature']),
            int(deviceDict['phases']),
            int(deviceDict['errorcode']),  
            int(deviceDict['isconnected']),
            int(deviceDict['ischarging']),
            int(deviceDict['chargingcurrent']),
            deviceID
        )
        cur.execute(update_sql, values)
        con.commit()
        cur.close()
    except:
        log.error(f"Error updating wallboxes table: {traceback.format_exc()}") 
    finally:
        con.close()

def main():
    log.info(f"Module {__name__} started...")

    # Initialize controllers
    nrgkick = nrgkickcontroller.NrgkickController()
    pulsar = pulsarwallboxcontroller.PulsarWallboxController()
    kebap30 = kebap30controller.Kebap30Controller()

    devices = [nrgkick, pulsar, kebap30]

    while True:
        try:
            chargemode = chargemanagercommon.getChargemode()
            chargingPossible_global = 0
            availablePowerRange = 0
            
            # This will hold the sum of all charging power for the current cycle
            total_cycle_charging_power = 0
            
            for device in devices:
                # 1. Read hardware telemetry
                deviceDict = device.readData()
                
                # 2. Persist live status for UI/Dashboard
                saveWallboxData(deviceDict, device.getID())

                # 3. COLLECT DATA FOR CONSOLIDATED LOG
                # Add up power, treating negative values as 0
                current_device_power = int(deviceDict.get('chargingpower', 0))
                if current_device_power > 0:
                    total_cycle_charging_power += current_device_power

                # 4. MUTUAL EXCLUSION (Only one wallbox may charge at a time)
                if (device.isCharging()):
                    for lockeddevices in devices:
                        if lockeddevices.getID() != device.getID():
                            lockeddevices.set_locked(True)
                        else:
                            lockeddevices.set_locked(False)

                # 5. CONTROL LOGIC (Only proceed if device is available and not locked)
                if (device.isAvailable() and not device.is_locked()):
                    
                    if (chargemode == chargemanagercommon.DISABLED_MODE and device.isCharging() and not device.isActiveChargingSession()):
                        log.info(f"ID {device.getID()}: Vehicle initiated charging. Auto-switching to SLOW_MODE.")
                        chargemode = chargemanagercommon.SLOW_MODE
                        chargemanagercommon.setChargemode(chargemode)
                        device.setActiveChargingSession(True)
                    
                    con = chargemanagercommon.getDBConnection()              
                    try:
                        cur = con.cursor()
                        cur.execute("SELECT availablePowerRange, chargingPossible FROM controls")
                        data = cur.fetchone()
                        cur.close()
                        availablePowerRange = data[0]
                        chargingPossible_local = data[1]
                        # Track if at least one box is allowed to charge
                        if chargingPossible_local == 1:
                            chargingPossible_global = 1
                    except:
                        log.error(f"DB Fetch error: {traceback.format_exc()}") 
                        con.close()
                        continue
                    finally:
                        con.close()

                    chargePowerValue = 6
                    if (chargemode == chargemanagercommon.DISABLED_MODE):
                        chargePowerValue = device.getChargingLevel()
                        chargingPossible_local = 0
                    elif (chargemode == chargemanagercommon.FAST_MODE):
                        chargePowerValue = 15
                        chargingPossible_local = 1
                    elif (chargemode == chargemanagercommon.SLOW_MODE):
                        chargePowerValue = 6
                        chargingPossible_local = 1
                    else:
                        chargePowerValue = chargemanagercommon.getCurrent(availablePowerRange, device.getID())
                    
                    if (device.getChargingLevel() != chargePowerValue or device.isCharging() != chargingPossible_local):
                        log.info(f"Control Trigger (ID {device.getID()}): mode={chargemode}, possible={chargingPossible_local}, target={chargePowerValue}A")
                        
                        successful = False
                        for retry in range(3):
                            device.setCharging(chargePowerValue, bool(chargingPossible_local))
                            log.info(f"Retry {retry} for ID {device.getID()}: Start={chargingPossible_local}, Current={chargePowerValue}A")
                            
                            time.sleep(13)

                            deviceDict = device.readData()
                            saveWallboxData(deviceDict, device.getID())
                            
                            if ((device.isCharging() and chargingPossible_local == 1) or (not device.isCharging() and chargingPossible_local == 0)): 
                                successful = True
                                if (chargingPossible_local == 1):
                                    log.info(f"Successfully started: {deviceDict['chargingpower']}W, ID: {device.getID()}")
                                    device.setActiveChargingSession(True)
                                else:
                                    log.info(f"Successfully stopped: ID {device.getID()}")
                                    device.setActiveChargingSession(False)
                                break
                        
                        if not successful:
                            any_box_charging = any(d.isCharging() for d in devices)
                            if not any_box_charging:
                                log.info(f"Failed to initiate charge on ID {device.getID()}. Assuming vehicle is full. Disabling.")
                                if (chargemode != chargemanagercommon.DISABLED_MODE):
                                    chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                                    device.setCharging(chargePowerValue, False)
                                    device.setActiveChargingSession(False)
                                    time.sleep(10)

                    device.setRetryCount(0)
                
                # 6. OFFLINE HANDLING
                else:
                    if not device.is_locked():
                        count = device.getRetryCount() + 1
                        device.setRetryCount(count)
                        
                        if (device.getRetryCount() == 3):
                            device.setActiveChargingSession(False)
                            any_box_charging = any(d.isCharging() for d in devices)

                            if not any_box_charging:
                                if (chargemanagercommon.getChargemode() != chargemanagercommon.DISABLED_MODE):
                                    chargemanagercommon.setWallboxDisconnected(device.getID())
                                    chargemanagercommon.setChargemode(chargemanagercommon.DISABLED_MODE)
                                    for d in devices:
                                        d.set_locked(False)
                                    time.sleep(4)
                                    log.info(f"No wallboxes active. ID {device.getID()} is offline. System DISABLED.")
                            else:
                                device.setRetryCount(2)

                    elif (device.getRetryCount() > 3):
                        device.setRetryCount(4)
                        time.sleep(2)

            # --- 7. CONSOLIDATED LOGGING (ONCE PER CYCLE) ---
            # This writes exactly one entry into chargelog representing the whole system.
            con_log = chargemanagercommon.getDBConnection()
            try:
                cur_log = con_log.cursor()
                timestamp = datetime.now(tz)
                # TO-DO REFACTORING: 
                # chargingPossible is a problem in this condition if car is full and sun is shining / need to think about a better way for this tracking
                cur_log.execute("INSERT INTO 'chargelog' (timestamp,currentChargingPower,chargingPossible) VALUES ('"+ str(timestamp) + "',"  + str(int(deviceDict['chargingpower'])) + "," + str(chargingPossible_global) + ")")

                con_log.commit()
                cur_log.close()
            except:
                log.error(f"Error writing to consolidated chargelog: {traceback.format_exc()}")
            finally:
                con_log.close()

            time.sleep(READ_WRITE_INTERVAL_SEC)
            
        except KeyboardInterrupt:
            log.info("Manager stopped by user.")
            break
        except Exception:
            log.error(f"Critical error in main loop: {traceback.format_exc()}")

if __name__ == "__main__":
    main()