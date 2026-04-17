#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Module reads every 15 seconds values from Solaredge inverter and writes them to SQLLite database
# Optimized for Pymodbus 3.x and high stability.
# --------------------------------------------------------------------------- #
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.client import ModbusTcpClient as ModbusClient
import math
import ctypes
import sqlite3
import logging
import pytz, os
from datetime import datetime
import time
import traceback
import signal
import sys
import chargemanagercommon

# Logging Setup
log = logging.getLogger(__name__)

# Global Variables
SOLAREDGE_INVERTER_IP = None
SOLAREDGE_MODBUS_PORT = 0
READ_INTERVAL_SEC = 12
keep_running = True

def handle_exit(signum, frame):
    """ Handles external signals like SIGTERM from pkill or reboot """
    global keep_running
    log.info(f"Signal {signum} received. Initiating graceful shutdown...")
    keep_running = False

# Register signals for clean exit
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

def readSettings():
    global SOLAREDGE_INVERTER_IP, SOLAREDGE_MODBUS_PORT
    if chargemanagercommon.SOLAREDGE_SETTINGS_DIRTY or SOLAREDGE_INVERTER_IP is None:
        new_ip = chargemanagercommon.getSetting(chargemanagercommon.SEIP)
        new_port = chargemanagercommon.getSetting(chargemanagercommon.SEPORT)           
        SOLAREDGE_INVERTER_IP = new_ip
        SOLAREDGE_MODBUS_PORT = new_port
        chargemanagercommon.SOLAREDGE_SETTINGS_DIRTY = False

def readData(client, address, size, typ):
    try:
        request = client.read_holding_registers(address, count=size, slave=1)
    
        if request.isError():
            log.error(f"Modbus error at address {address}: {request}")
            raise IOError(f"Modbus isError() at address {address}")
        
        if not hasattr(request, 'registers'):
            log.error(f"No registers in response for address {address}")
            raise IOError(f"No registers in response at address {address}")

        if typ == "int16" or typ == "uint16":
            decoder = BinaryPayloadDecoder.fromRegisters(request.registers, byteorder=Endian.BIG)
        if typ in ["uint32", "float32", "int64", "int32"]:
            decoder = BinaryPayloadDecoder.fromRegisters(request.registers, byteorder=Endian.BIG, wordorder=Endian.LITTLE)
        
        if typ == "int16": return decoder.decode_16bit_int()
        if typ == "int32": return decoder.decode_32bit_int()
        if typ == "int64": return decoder.decode_64bit_int()
        if typ == "uint16": return decoder.decode_16bit_uint()
        if typ == "uint32": return decoder.decode_32bit_uint()
        if typ == "float32": return decoder.decode_32bit_float()
        if typ == "raw": return request
        
    except Exception:
        log.error(f"Error in readData at {address}: {traceback.format_exc()}")
        raise

def cleanupData():
    log.info("Starting cleanup of old data (older than 72h)...")
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM modbus WHERE timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("VACUUM")
        con.commit()
        cur.close()
        log.info("Cleanup successful.")
    except Exception:
        log.error(f"Cleanup failed: {traceback.format_exc()}") 
    finally:
        con.close()

def readModbus(client):
    log.debug("--- Modbus Read Cycle Start ---")
    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)
    
    # Collect data from inverter
    ac_one_operation = readData(client, 40083, 2, "int32")
    ac = ctypes.c_int16(ac_one_operation & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_one_operation >> 16) & 0xffff).value
    ac_power = int(ac * math.pow(10, ac_scale_factor))

    ac_to_from_grid_raw = readData(client, 40206, 5, "raw")
    if not hasattr(ac_to_from_grid_raw, 'registers') or len(ac_to_from_grid_raw.registers) < 5:
        raise IOError("Could not read grid data (no registers), skipping this cycle.")

    ac_to_from_grid = ctypes.c_int16(ac_to_from_grid_raw.registers[0] & 0xffff).value
    ac_grid_scale_factor = ctypes.c_int16(ac_to_from_grid_raw.registers[4] & 0xffff).value
    ac_power_to_from_grid = int(ac_to_from_grid * math.pow(10, ac_grid_scale_factor))

    dc_one_operation = readData(client, 40100, 2, "int32")
    dc = ctypes.c_int16(dc_one_operation & 0xffff).value 
    dc_scale_factor = ctypes.c_int16((dc_one_operation >> 16) & 0xffff).value
    dc_power = dc * math.pow(10, dc_scale_factor)
    
    temp = readData(client, 40103, 1, "int16")
    status = readData(client, 40107, 1, "uint16")
    battery_power = readData(client, 62836, 2, "float32")
    battery_status = readData(client, 62854, 2, "uint32")
    soc = readData(client, 62852, 2, "float32")
    soh = readData(client, 62850, 2, "float32")
    
    # Calculations
    house_consumption = ac_power - ac_power_to_from_grid
    pv_prod = max(0, ac_power + battery_power) if (ac_power + battery_power) < 50 else (ac_power + battery_power)
    available_power = ac_power_to_from_grid + battery_power
    availablepowerrange = chargemanagercommon.getPowerRange(available_power)

    # Database operations
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute("SELECT sum(chargingpower) FROM wallboxes")
        row = cur.fetchone()
        wallboxes_power = int(row[0]) if row and row[0] is not None else 0
        
        if house_consumption >= wallboxes_power:
            availablepower_withoutcharging = available_power + wallboxes_power 
        else:              
            availablepower_withoutcharging = available_power           

        sql = """INSERT INTO 'modbus' (timestamp,pvprod,houseconsumption,acpower,acpowertofromgrid,dcpower,
                    availablepower_withoutcharging,availablepowerrange,temperature,status,batterypower,
                    batterystatus,soc,soh) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        
        cur.execute(sql, (str(timestamp), pv_prod, house_consumption, ac_power, ac_power_to_from_grid, 
                            dc_power, availablepower_withoutcharging, availablepowerrange, temp/100, 
                            status, battery_power, battery_status, soc, soh))
        con.commit()
        cur.close()
    except Exception as db_err:
        log.error(f"Database Error: {db_err}")
        raise
    finally:
        con.close()

def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    log.info(f"Module {__name__} started...")

    client = None
    last_used_ip = None
    last_used_port = None

    while keep_running:
        try:
            readSettings()

            # 1. INIT BLOCK
            # gen new obj if someting changed
            if SOLAREDGE_INVERTER_IP != last_used_ip or SOLAREDGE_MODBUS_PORT != last_used_port:
                if client: 
                    try: client.close()
                    except: pass
                
                if SOLAREDGE_INVERTER_IP and SOLAREDGE_INVERTER_IP not in [0, "0.0.0.0"]:
                    log.info(f"Initializing Modbus client for {SOLAREDGE_INVERTER_IP}:{SOLAREDGE_MODBUS_PORT}")
                    client = ModbusClient(str(SOLAREDGE_INVERTER_IP), port=int(SOLAREDGE_MODBUS_PORT), timeout=3)
                    last_used_ip = SOLAREDGE_INVERTER_IP
                    last_used_port = SOLAREDGE_MODBUS_PORT
                else:
                    log.warning("Invalid IP configuration. Waiting...")
                    time.sleep(10)
                    continue

            # 2. COM BLOCK
            if client:
                try:
                    # try to connect
                    if client.connect():
                        # if scuessful read
                        readModbus(client)
                        # close after sucessful read
                        client.close()
                    else:
                        # if solaredge sleeps
                        log.warning(f"Could not connect to Inverter at {SOLAREDGE_INVERTER_IP}. (Standby?)")
                
                except Exception:
                    # catch readModbus errors(like IndexError)
                    log.error(f"Error during Modbus cycle: {traceback.format_exc()}")
                    if client:
                        try: client.close()
                        except: pass
            
            # 3. NIGHTLY CLEANUP
            dt = datetime.now()
            if dt.hour == 0 and dt.minute == 1 and dt.second < READ_INTERVAL_SEC:
                cleanupData()

        except Exception:
            # Gglobal protection
            log.error(f"Critical Main Loop Error: {traceback.format_exc()}")
            time.sleep(5) 

        # 4. SLEEP LOGIC
        for _ in range(READ_INTERVAL_SEC):
            if not keep_running: 
                break
            time.sleep(1)

    # FINAL EXIT
    log.info("Cleanup before script exit...")
    if client:
        try:
            client.close()
            log.info("Modbus connection closed.")
        except:
            pass
    log.info("Script exit.")

if __name__ == "__main__":
    main()