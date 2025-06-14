#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Moduel reads every 15 seconds values from Solaredge inverter and writes them to SQLLite database
# Module was tested with Solaredge Storedge SE10K-RWS and BYD LVS 8.0
# IMPORTANT: other Solaredge inversters might have different modbus register adresses!
# --------------------------------------------------------------------------- #
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
import math
import ctypes
import sqlite3
import logging
import pytz, os
from datetime import datetime
import time
import traceback
import chargemanagercommon

log = logging.getLogger(__name__)

SOLAREDGE_INVERTER_IP = 0
SOLAREDGE_MODBUS_PORT = 0
READ_INTERVAL_SEC = 12

def readSettings():
    global SOLAREDGE_INVERTER_IP,SOLAREDGE_MODBUS_PORT
    if (chargemanagercommon.SOLAREDGE_SETTINGS_DIRTY == True):
        SOLAREDGE_INVERTER_IP = chargemanagercommon.getSetting(chargemanagercommon.SEIP)
        SOLAREDGE_MODBUS_PORT = chargemanagercommon.getSetting(chargemanagercommon.SEPORT)
        chargemanagercommon.SOLAREDGE_SETTINGS_DIRTY == False 

# Reading & decoding data from modbus

# adress = modbus registers
# size = amount for registers to read
# typ =  int16 | uint16 | uint32 | float32
def readData(client,address,size,typ):
    #logging.debug("client" + str(client))
    request = client.read_holding_registers(address,size,unit=1)
    if (typ == "int16" or typ == "uint16"):
        decoder = BinaryPayloadDecoder.fromRegisters(request.registers,byteorder=Endian.Big)
    if (typ == "uint32" or typ == "float32" or typ == "int64" or typ == "int32"):
        decoder = BinaryPayloadDecoder.fromRegisters(request.registers,Endian.Big,wordorder=Endian.Little)
    if (typ == "int16"):
        return decoder.decode_16bit_int()
    if (typ == "int32"):
        return decoder.decode_32bit_int()
    if (typ == "int64"):
        return decoder.decode_64bit_int()
    if (typ == "uint16"):
        return decoder.decode_16bit_uint()
    if (typ == "uint32"):
        return decoder.decode_32bit_uint()
    if (typ == "float32"):
        return decoder.decode_32bit_float()
    if (typ == "raw"):
        return request
#
#	Delete data older 72 h
#
def cleanupData():
    log.debug("Try connecting sqllite...")
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute("delete from modbus where timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("vacuum")
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

#
#	Read data from modbus and store them in SQLLite
#
def readModbus(client):

    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)
    # read two register in one operation to avoid that sf and value does not fit together
    ac_one_operation = readData(client,40083,2,"int32")
    ac = ctypes.c_int16(ac_one_operation & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_one_operation >> 16) & 0xffff).value
    ac_power = int(ac * math.pow(10, ac_scale_factor))

    ac_to_from_grid_one_operation = readData(client,40206,5,"raw")
    ac_to_from_grid = ctypes.c_int16(ac_to_from_grid_one_operation.registers[0] & 0xffff).value
    ac_grid_scale_factor = ctypes.c_int16(ac_to_from_grid_one_operation.registers[4] & 0xffff).value
    ac_power_to_from_grid  = int(ac_to_from_grid * math.pow(10, ac_grid_scale_factor))

    dc_one_operation = readData(client,40100,2,"int32")
    dc = ctypes.c_int16(dc_one_operation & 0xffff).value 
    dc_scale_factor = ctypes.c_int16((dc_one_operation >> 16) & 0xffff).value
    dc_power = dc * math.pow(10, dc_scale_factor)
    temp = readData(client,40103,1,"int16")
    status = readData(client,40107,1,"uint16")
    battery_power =  readData(client,62836,2,"float32")
    battery_status =  readData(client,62854,2,"uint32")
    soc = readData(client,62852,2,"float32")
    soh =  readData(client,62850,2,"float32")
    
    # calc house consumption
    house_consumption = ac_power - ac_power_to_from_grid
    # calculation of current pv production from solar panels
    pv_prod = ac_power + battery_power
    # calc available (free) power (overproduction)
    available_power = ac_power_to_from_grid + battery_power
    availablepowerrange = 0
    availablepowerrange = chargemanagercommon.getPowerRange(available_power)

    # if after the first calc pv_prod is very small we have to add negativ battery-power
    if (pv_prod < 50):
        pv_prod = ac_power + battery_power
        if (pv_prod < 0):
            pv_prod = 0

    nrgkick = None
    nrgkick_power = 0

    con = chargemanagercommon.getDBConnection()

    try:
        cur = con.cursor()
        cur.execute("SELECT sum(chargingpower) FROM wallboxes")
        wallboxes = cur.fetchone()
        cur.close()
        if wallboxes == None:
            log.error("Wallboxes table is empty!")
        else:
            wallboxes_power = int(wallboxes[0])

            # plausibility check: due to async read data nrg-kick can be read before house
            if (house_consumption >= wallboxes_power):
                availablepower_withoutcharging = available_power + wallboxes_power    
            else:             
                availablepower_withoutcharging = available_power           
            cur = con.cursor()
            data_sql = "INSERT INTO 'modbus' (timestamp,pvprod,houseconsumption,acpower,acpowertofromgrid,dcpower,availablepower_withoutcharging,availablepowerrange,temperature,status,batterypower,batterystatus,soc,soh) VALUES ('"+ str(timestamp) + "',"  + str(pv_prod) + "," + str(house_consumption) + "," + str(ac_power) + "," + str(ac_power_to_from_grid) + "," + str(dc_power) + "," + str(availablepower_withoutcharging) + "," + str(availablepowerrange) + "," + str(temp/100) + "," + str(status) + "," + str(battery_power) + "," + str(battery_status) + "," + str(soc) + "," + str(soh) + ")"
            log.debug(data_sql)
            cur.execute(data_sql)
            con.commit()
            cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

    # for debugging
    if (False):
        log.info("AC: " + str(ac) + " AC sf: " + str(ac_scale_factor) + " AC power: " + str(ac_power) + " AC to/from grid: " + str(ac_to_from_grid) + " AC grid scale factor: " + str(ac_grid_scale_factor) + " AC power to/from grid: " + str(ac_power_to_from_grid))
        log.info("House: " + str(house_consumption) + " DC: " + str(dc) + " DC scale factor: " + str(dc_scale_factor) + " DC power: " + str(dc_power) + " Temp: " + str(temp/100))
        log.info("Battery status: " + str(battery_status) + " Battery power: " + str(battery_power) + " SOC: " + str(soc) + " SOH:" + str(soh))
        log.info("PV production: " + str(pv_prod) + " available power: " + str(available_power) + " available power without battery / range: " + str(availablepower_withoutcharging) + "/" +  str(availablepowerrange) + " nrgkick power: " + str(nrgkick_power) + " inverterstatus:" + str(status))


#
#	Main, init and repeat reading
#
def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()

    log.info("Module " + str(__name__) + " started...")
    try:
        while True:
            try:
                readSettings()

                client = ModbusClient(SOLAREDGE_INVERTER_IP, port=SOLAREDGE_MODBUS_PORT)
                readModbus(client)
                client.close()
                
                dt = datetime.now()
                # clean data 00:00:<31
                if (dt.hour == 0 and dt.minute == 1 and dt.second < 29):
                    start = time.process_time()
                    cleanupData()
                    log.info("cleanupData duration: " + str(time.process_time() - start))
            except:
                log.error(traceback.format_exc())  
        
            time.sleep(READ_INTERVAL_SEC)
            log.debug("sleeped " + str(READ_INTERVAL_SEC) + " seconds")
    except KeyboardInterrupt:
        pass
    


