#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Module reads every 15 seconds values from Solaredge inverter and writes them to SQLLite database
# Optimized for Pymodbus 3.15.x and high stability.
# --------------------------------------------------------------------------- #
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
# Nach einem fehlgeschlagenen Zyklus (Timeout/Modbus-Fehler) länger pausieren
# als im Normalbetrieb, damit die interne TCP->RS485-Bridge des Wechselrichters
# sich erholen kann, bevor der nächste Versuch startet.
ERROR_BACKOFF_SEC = 32
# Kurze Pause zwischen einzelnen Modbus-Transaktionen innerhalb eines
# Lesezyklus, um die interne RS485-Bridge nicht mit Requests ohne Pause zu fluten.
INTER_REQUEST_DELAY_SEC = 0.08
keep_running = True

# pymodbus >= 3.9 removed BinaryPayloadDecoder; convert_from_registers() is the
# replacement. Word order "little" reproduces the old wordorder=Endian.LITTLE
# behaviour for multi-register values; byte order within a word is always big
# per Modbus spec (that's why there's no separate byteorder param anymore).
DATATYPE_MAP = {
    "int16": ModbusClient.DATATYPE.INT16,
    "uint16": ModbusClient.DATATYPE.UINT16,
    "int32": ModbusClient.DATATYPE.INT32,
    "uint32": ModbusClient.DATATYPE.UINT32,
    "float32": ModbusClient.DATATYPE.FLOAT32,
    "int64": ModbusClient.DATATYPE.INT64,
}
WORD_ORDER_LITTLE_TYPES = ("uint32", "float32", "int64", "int32")

def handle_exit(signum, frame):
    """ Handles external signals like SIGTERM from pkill or reboot """
    global keep_running
    log.info(f"Signal {signum} received. Initiating graceful shutdown...")
    keep_running = False

# Register signals for clean exit
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

def interruptible_sleep(seconds):
    """Sleeps in 1-second steps so a pending shutdown (keep_running=False)
    is picked up immediately instead of after the full sleep duration."""
    for _ in range(seconds):
        if not keep_running:
            break
        time.sleep(1)

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
        request = client.read_holding_registers(address, count=size, device_id=1)
    
        if request.isError():
            log.error(f"Modbus error at address {address}: {request}")
            raise IOError(f"Modbus isError() at address {address}")
        
        if not hasattr(request, 'registers'):
            log.error(f"No registers in response for address {address}")
            raise IOError(f"No registers in response at address {address}")

        if typ == "raw":
            return request

        word_order = "little" if typ in WORD_ORDER_LITTLE_TYPES else "big"
        return client.convert_from_registers(request.registers, DATATYPE_MAP[typ], word_order=word_order)
        
    except Exception:
        log.error(f"Error in readData at {address}: {traceback.format_exc()}")
        raise

def readBlock(client, address, count):
    """Reads a contiguous span of holding registers in a single Modbus
    transaction. Use this instead of several readData() calls whenever the
    needed registers lie next to each other - fewer transactions per cycle
    means less load on the inverter's internal TCP->RS485 bridge."""
    try:
        request = client.read_holding_registers(address, count=count, device_id=1)

        if request.isError():
            log.error(f"Modbus error at address {address} (count={count}): {request}")
            raise IOError(f"Modbus isError() at address {address}")

        if not hasattr(request, 'registers') or len(request.registers) < count:
            log.error(f"Incomplete registers in response for address {address} (count={count})")
            raise IOError(f"Incomplete registers at address {address}")

        return request.registers

    except Exception:
        log.error(f"Error in readBlock at {address} (count={count}): {traceback.format_exc()}")
        raise

def decodeValue(client, registers, offset, typ):
    """Decodes a single value of type `typ` starting at register `offset`
    within a register list already fetched via readBlock()."""
    size = 2 if typ in WORD_ORDER_LITTLE_TYPES else 1
    word_order = "little" if typ in WORD_ORDER_LITTLE_TYPES else "big"
    chunk = registers[offset:offset + size]
    return client.convert_from_registers(chunk, DATATYPE_MAP[typ], word_order=word_order)

def cleanupData():
    log.info("Starting cleanup of old data (older than 72h)...")
    con = chargemanagercommon.getDBConnection()
    start_time = time.perf_counter()
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM modbus WHERE timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("VACUUM")
        con.commit()
        cur.close()
        duration = time.perf_counter() - start_time
        log.info(f"Cleanup successful. Duration: {duration:.3f}s")
    except Exception:
        log.error(f"Cleanup failed: {traceback.format_exc()}") 
    finally:
        con.close()

def readModbus(client):
    log.debug("--- Modbus Read Cycle Start ---")
    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)
    
    # Collect data from inverter.
    # Registers that lie next to each other are fetched with a single
    # readBlock() call instead of one readData() per value, and a short
    # pause follows each transaction - both reduce the load on the
    # inverter's internal TCP->RS485 bridge, which some SolarEdge units
    # struggle with under back-to-back requests.
    ac_one_operation = readData(client, 40083, 2, "int32")
    ac = ctypes.c_int16(ac_one_operation & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_one_operation >> 16) & 0xffff).value
    ac_power = int(ac * math.pow(10, ac_scale_factor))
    time.sleep(INTER_REQUEST_DELAY_SEC)

    ac_to_from_grid_raw = readData(client, 40206, 5, "raw")
    if not hasattr(ac_to_from_grid_raw, 'registers') or len(ac_to_from_grid_raw.registers) < 5:
        raise IOError("Could not read grid data (no registers), skipping this cycle.")

    ac_to_from_grid = ctypes.c_int16(ac_to_from_grid_raw.registers[0] & 0xffff).value
    ac_grid_scale_factor = ctypes.c_int16(ac_to_from_grid_raw.registers[4] & 0xffff).value
    ac_power_to_from_grid = int(ac_to_from_grid * math.pow(10, ac_grid_scale_factor))
    time.sleep(INTER_REQUEST_DELAY_SEC)

    # 40100-40107 in one block: dc_power (int32 @ offset 0), temperature
    # (int16 @ offset 3), status (uint16 @ offset 7) - was 3 separate reads.
    block_dc = readBlock(client, 40100, 8)
    dc_one_operation = decodeValue(client, block_dc, 0, "int32")
    dc = ctypes.c_int16(dc_one_operation & 0xffff).value
    dc_scale_factor = ctypes.c_int16((dc_one_operation >> 16) & 0xffff).value
    dc_power = dc * math.pow(10, dc_scale_factor)
    temp = decodeValue(client, block_dc, 3, "int16")
    status = decodeValue(client, block_dc, 7, "uint16")
    time.sleep(INTER_REQUEST_DELAY_SEC)

    battery_power = readData(client, 62836, 2, "float32")
    time.sleep(INTER_REQUEST_DELAY_SEC)

    # 62850-62855 in one block: soh (float32 @ offset 0), soc (float32 @
    # offset 2), battery_status (uint32 @ offset 4) - was 3 separate reads.
    block_battery = readBlock(client, 62850, 6)
    soh = decodeValue(client, block_battery, 0, "float32")
    soc = decodeValue(client, block_battery, 2, "float32")
    battery_status = decodeValue(client, block_battery, 4, "uint32")
    
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
    last_cleanup_day = None

    while keep_running:
        cycle_failed = False
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
                    client = ModbusClient(str(SOLAREDGE_INVERTER_IP), port=int(SOLAREDGE_MODBUS_PORT), timeout=5, retries=1)
                    last_used_ip = SOLAREDGE_INVERTER_IP
                    last_used_port = SOLAREDGE_MODBUS_PORT
                else:
                    log.warning("Invalid IP configuration. Waiting...")
                    interruptible_sleep(10)
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
                    cycle_failed = True
            
            # 3. NIGHTLY CLEANUP
            dt = datetime.now()
            if dt.hour == 0 and dt.minute == 1 and last_cleanup_day != dt.day:
                cleanupData()
                last_cleanup_day = dt.day

        except Exception:
            # Gglobal protection
            log.error(f"Critical Main Loop Error: {traceback.format_exc()}")
            cycle_failed = True

        # 4. SLEEP LOGIC
        # After a failed cycle, back off longer than the normal read interval
        # so the inverter's Modbus interface gets a chance to recover before
        # the next attempt, instead of being hit again after just 12s.
        if cycle_failed:
            log.warning(f"Cycle failed, backing off for {ERROR_BACKOFF_SEC}s before retrying.")
            interruptible_sleep(ERROR_BACKOFF_SEC)
        else:
            interruptible_sleep(READ_INTERVAL_SEC)

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