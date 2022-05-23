#!/usr/bin/python3
#
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

config = configparser.RawConfigParser()
config.read('chargemanager.properties')

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/solaredge.log', filemode='w', level=logging.INFO)
log = logging.getLogger()

SOLAREDGE_INVERTER_IP = config.get('Solaredge', 'inverter.ip')
READ_INTERVAL_SEC = 15

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

    tz = pytz.timezone('Europe/Berlin')
    timestamp = datetime.now(tz)
    # read two register in one operation to avoid that sf and value does not fit together
    ac_one_operation = readData(client,40083,2,"int32")
    ac = ctypes.c_int16(ac_one_operation & 0xffff).value
    ac_scale_factor = ctypes.c_int16((ac_one_operation >> 16) & 0xffff).value
    ac_power = ac * math.pow(10, ac_scale_factor)

    ac_to_from_grid_one_operation = readData(client,40206,5,"raw")
    ac_to_from_grid = ctypes.c_int16(ac_to_from_grid_one_operation.registers[0] & 0xffff).value
    ac_grid_scale_factor = ctypes.c_int16(ac_to_from_grid_one_operation.registers[4] & 0xffff).value
    ac_power_to_from_grid  = ac_to_from_grid * math.pow(10, ac_grid_scale_factor)

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
    availablepowerrange = 0
    availablepowerrange = chargemanagercommon.getPowerRange(available_power)

    # if after the first calc pv_prod is very small we have to add negativ battery-power
    if (pv_prod < 50):
        pv_prod = ac_power + battery_power
        if (pv_prod < 0):
            pv_prod = 0

    nrgkick = None
    nrgkick_power = 0

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT chargingpower FROM nrgkick")
        nrgkick = cur.fetchone()
        if nrgkick == None:
            logging.error("NRGKick table is empty!")
        else:
            nrgkick_power = int(nrgkick[0])

            # plausibility check: due to async read data nrg-kick can be read before house
            if (house_consumption >= nrgkick_power):
                availablepower_withoutcharging = available_power + nrgkick_power    
            else:             
                availablepower_withoutcharging = available_power           
            
            data_sql = "INSERT INTO 'modbus' (timestamp,pvprod,houseconsumption,acpower,acpowertofromgrid,dcpower,availablepower_withoutcharging,availablepowerrange,temperature,status,batterypower,batterystatus,soc,soh) VALUES ('"+ str(timestamp) + "',"  + str(pv_prod) + "," + str(house_consumption) + "," + str(ac_power) + "," + str(ac_to_from_grid) + "," + str(dc_power) + "," + str(availablepower_withoutcharging) + "," + str(availablepowerrange) + "," + str(temp/100) + "," + str(status) + "," + str(battery_power) + "," + str(battery_status) + "," + str(soc) + "," + str(soh) + ")"
            logging.debug(data_sql)
            cur.execute(data_sql)
            con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close() 

    # logging where mybe a bug occured dureing reading modbus
    if (availablepower_withoutcharging <= 0 and pv_prod >= 2500):
        logging.info("ATTENTION: MAYBE WE READ WRONG VALUES FROM MODBUS, CHECK IF POWER VALUES ARE PLAUSIBLE:")
        logging.info("AC: " + str(ac) + " AC sf: " + str(ac_scale_factor) + " AC power: " + str(ac_power) + " AC to/from grid: " + str(ac_to_from_grid) + " AC grid scale factor: " + str(ac_grid_scale_factor) + " AC power to/from grid: " + str(ac_power_to_from_grid))
        logging.info("House: " + str(house_consumption) + " DC: " + str(dc) + " DC scale factor: " + str(dc_scale_factor) + " DC power: " + str(dc_power) + " Temp: " + str(temp/100))
        logging.info("Battery status: " + str(battery_status) + " Battery power: " + str(battery_power) + " SOC: " + str(soc) + " SOH:" + str(soh))
        logging.info("PV production: " + str(pv_prod) + " available power: " + str(available_power) + " available power without battery / range: " + str(availablepower_withoutcharging) + "/" +  str(availablepowerrange) + " nrgkick power: " + str(nrgkick_power) + " inverterstatus:" + str(status))


#
#	Main, init and repeat reading
#
if __name__ == "__main__":
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    chargemanagercommon.init()

    try:
        while True:
            try:
                client = ModbusClient(SOLAREDGE_INVERTER_IP, port=config.get('Solaredge', 'modbus.port'))
                readModbus(client)
                client.close()
                cleanupData()
            except:
                logging.error(traceback.format_exc())  
        
            time.sleep(READ_INTERVAL_SEC)
            logging.debug("sleeped " + str(READ_INTERVAL_SEC) + " seconds")
    except KeyboardInterrupt:
        pass
    


