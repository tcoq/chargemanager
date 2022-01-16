#!/usr/bin/python3
#
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
import ctypes
import math
import sqlite3
import logging
import pytz, os
from datetime import datetime, timezone
import time
import traceback
#from chargemanagercommon import initDatabase
#from chargemanagercommon import getPowerRange
import configparser

# --------------------------------------------------------------------------- #
# This python script reads every 30 seconds values from Solaredge inverter and writes them to SQLLite database
# Script was tested with Solaredge Storedge SE10K-RWS and BYD LVS 8.0
# IMPORTANT: other Solaredge inversters might have different modbus register adresses!
# --------------------------------------------------------------------------- #

config = configparser.RawConfigParser()
config.read('chargemanager.properties')

#logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/solaredge.log', filemode='w', level=logging.INFO)
#log = logging.getLogger()

SOLAREDGE_INVERTER_IP = '192.168.178.32'
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

#
#	Read data from modbus and store them in SQLLite
#
def readModbus(client):
    global logCount

    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)

    ac_all = readData(client,40083,2,"int32")
    ac = ctypes.c_int16(ac_all & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_all >> 16) & 0xffff).value

    ac_power = ac * math.pow(10, ac_scale_factor)
    ac_to_from_grid = readData(client,40206,1,"int16")
    ac_grid_scale_factor = readData(client,40210,1,"int16")

    print('ac_to_from_grid:' + str(ac_to_from_grid))
    print('ac_grid_scale_factor:' + str(ac_grid_scale_factor))
    ac_grid_scale_factor_all = readData(client,40206,4,"int64")
    print('ac grid_all:' + str(ac_grid_scale_factor_all))
    print('ac grid_shift:' + str(ctypes.c_int16(ac_grid_scale_factor_all & 0xffff).value))
    print('ac sf_grid_shift:' + str(ctypes.c_int16((ac_grid_scale_factor_all >> 48) & 0xffff).value))


    ac_power_to_from_grid  = ac_to_from_grid * math.pow(10, ac_grid_scale_factor)
    dc = readData(client,40100,1,"int16") 
    dc_scale_factor = readData(client,40101,1,"int16")
    dc_power = dc * math.pow(10, dc_scale_factor)
    temp = readData(client,40103,1,"int16")
    status = readData(client,40107,1,"uint16")
    battery_power =  readData(client,62836,2,"float32")
    battery_status =  readData(client,62854,2,"uint32")
    soc = readData(client,62852,2,"float32")
    soh =  readData(client,62850,2,"float32")
    
    # calculation of current pv production from solar panels
    pv_prod = ac_power + ac_power_to_from_grid + battery_power
    # calc available (free) power (overproduction)
    available_power = ac_to_from_grid+battery_power
    # calc house consumption
    house_consumption = ac_power - ac_power_to_from_grid

    # if after the first calc pv_prod is very small we have to add negativ battery-power
    if (pv_prod < 50):
        pv_prod = ac_power + battery_power
        if (pv_prod < 0):
            pv_prod = 0

    nrgkick = None
    nrgkick_power = 0
    availablepowerrange = 0
    availablepower_withoutcharging = 0

    print(str(timestamp) + "',"  + str(pv_prod) + "," + str(house_consumption) + "," + str(ac_power) + "," + str(ac_to_from_grid) + "," + str(dc_power) + "," + str(availablepower_withoutcharging) + "," + str(availablepowerrange) + "," + str(temp/100) + "," + str(status) + "," + str(battery_power) + "," + str(battery_status) + "," + str(soc) + "," + str(soh))


#
#	Main, init and repeat reading
#
if __name__ == "__main__":

    try:

        client = ModbusClient(SOLAREDGE_INVERTER_IP, 1502)
        readModbus(client)
        client.close()

    except KeyboardInterrupt:
        pass
    


