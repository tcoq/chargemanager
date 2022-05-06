#!/usr/bin/python3
#
from urllib import response
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
import math
import ctypes
import sqlite3
import logging
import pytz, os
from datetime import datetime, timezone
import time
import traceback
import chargemanagercommon
import configparser

# --------------------------------------------------------------------------- #
# This python script reads every 30 seconds values from Solaredge inverter and writes them to SQLLite database
# Script was tested with Solaredge Storedge SE10K-RWS and BYD LVS 8.0
# IMPORTANT: other Solaredge inversters might have different modbus register adresses!
# --------------------------------------------------------------------------- #

#logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/solaredge.log', filemode='w', level=logging.INFO)
#log = logging.getLogger()

READ_INTERVAL_SEC = 15
logCount = 1

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
    logging.debug("Try connecting sqllite...")
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    try:
        cur = con.cursor()
        cur.execute("delete from modbus where timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("vacuum")
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close() 

#
#	Read data from modbus and store them in SQLLite
#
def readModbus(client):
    global logCount

    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)
    # read two register in one operation to avoid that sf and value does not fit together
    ac_one_operation = readData(client,40083,2,"int32")
    ac = ctypes.c_int16(ac_one_operation & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_one_operation >> 16) & 0xffff).value
    ac_power = ac * math.pow(10, ac_scale_factor)
    
    ac_to_from_grid = readData(client,40206,1,"int16")
    ac_grid_scale_factor = readData(client,40210,1,"int16")
    ac_power_to_from_grid  = ac_to_from_grid * math.pow(10, ac_grid_scale_factor)

    ac_to_from_grid_one_operation = readData(client,40206,5,"raw")
    ac_to_from_grid2 = ctypes.c_int16(ac_to_from_grid_one_operation.registers[0] & 0xffff).value
    ac_grid_scale_factor2 = ctypes.c_int16(ac_to_from_grid_one_operation.registers[4] & 0xffff).value
    ac_power_to_from_grid2  = ac_to_from_grid2 * math.pow(10, ac_grid_scale_factor2)


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
    pv_prod = house_consumption + ac_power_to_from_grid + battery_power
    # calc available (free) power (overproduction)
    available_power = ac_to_from_grid+battery_power

    # if after the first calc pv_prod is very small we have to add negativ battery-power
    if (pv_prod < 50):
        pv_prod = ac_power + battery_power
        if (pv_prod < 0):
            pv_prod = 0

    nrgkick = None
    nrgkick_power = 0
    availablepowerrange = 0
    availablepower_withoutcharging = 0


    print("AC: " + str(ac) + " AC sf: " + str(ac_scale_factor) + " AC power: " + str(ac_power) + " AC to/from grid: " + str(ac_to_from_grid) + " / " + str(ac_to_from_grid2) + " AC grid scale factor: " + str(ac_grid_scale_factor) + " / " + str(ac_grid_scale_factor2) + " AC power to/from grid: " + str(ac_power_to_from_grid))
    print("House: " + str(house_consumption) + " DC: " + str(dc) + " DC scale factor: " + str(dc_scale_factor) + " DC power: " + str(dc_power) + " Temp: " + str(temp/100))
    print("Battery status: " + str(battery_status) + " Battery power: " + str(battery_power) + " SOC: " + str(soc) + " SOH:" + str(soh))
    print("PV production: " + str(pv_prod) + " available power: " + str(available_power) + " available power without battery / range: " + str(availablepower_withoutcharging) + "/" +  str(availablepowerrange) + " nrgkick power: " + str(nrgkick_power) + " inverterstatus:" + str(status))

try:

    client = ModbusClient("192.168.178.40", 1502)
    readModbus(client)
    client.close()

except:
    logging.error(traceback.format_exc())  



