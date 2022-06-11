#!/usr/bin/python3
#
import threading
import logging
import sqlite3 
import math
import traceback

phases = 0

def init():
    global databaseInitialized, sem
    sem = threading.Semaphore()
    databaseInitialized = False
    sem.acquire()
    if (databaseInitialized == False):
        initModbusTable()
        initControlsTable()
        initNrgkicktable()
        initChargelogTable()
        databaseInitialized == True
    sem.release()

#
# Sets the current number of available phases at the charger
# Possible values 1-3
#
def setPhases(value):
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE nrgkick SET phases = " + str(value))
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()

#
# Returns the current number of available phases by the charger
# 
# Returns: 1-3 or -1 for errors
#
def getPhases():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT phases FROM nrgkick")
        chargemode = cur.fetchone()
    except:
        cur.close()
        con.close()
        return -1
    cur.close()
    con.close()
    return int(chargemode[0])
#
# Calculating the right power range for a given power-value
#
def getPowerRange(currentAvailablePower):
    new_availablePowerRange = 0

    if (currentAvailablePower <= 500):
        new_availablePowerRange = 0
    if (currentAvailablePower > 500 and currentAvailablePower <= 800):
        new_availablePowerRange = 500 
    if (currentAvailablePower > 800 and currentAvailablePower <= 1100):
        new_availablePowerRange = 800 
    if (currentAvailablePower > 1100 and currentAvailablePower <= 1500):
        new_availablePowerRange = 1100             
    if (currentAvailablePower > 1500 and currentAvailablePower <= 1700):
        new_availablePowerRange = 1400 # here we can start charging 1 phase
    if (currentAvailablePower > 1700 and currentAvailablePower <= 1900):
        new_availablePowerRange = 1700
    if (currentAvailablePower > 1900 and currentAvailablePower <= 2100):
        new_availablePowerRange = 1900
    if (currentAvailablePower > 2100 and currentAvailablePower <= 2350):
        new_availablePowerRange = 2100
    if (currentAvailablePower > 2350 and currentAvailablePower <= 2600):
        new_availablePowerRange = 2350
    if (currentAvailablePower > 2600 and currentAvailablePower <= 2800):
        new_availablePowerRange = 2600
    if (currentAvailablePower > 2800 and currentAvailablePower <= 3050):
        new_availablePowerRange = 2800 # here we can start charging 2 phase
    if (currentAvailablePower > 3050 and currentAvailablePower <= 3300):
        new_availablePowerRange = 3050
    if (currentAvailablePower > 3300 and currentAvailablePower <= 3500):
        new_availablePowerRange = 3300
    if (currentAvailablePower > 3500 and currentAvailablePower <= 3800):
        new_availablePowerRange = 3500
    if (currentAvailablePower > 3800 and currentAvailablePower <= 4200):
        new_availablePowerRange = 3800
    if (currentAvailablePower > 4200 and currentAvailablePower <= 4650):
        new_availablePowerRange = 4200
    if (currentAvailablePower > 4650 and currentAvailablePower <= 5100):
        new_availablePowerRange = 4650 # here we can start charging 3 phase
    if (currentAvailablePower > 5100 and currentAvailablePower <= 5600):
        new_availablePowerRange = 5100
    if (currentAvailablePower > 5600 and currentAvailablePower <= 6050):
        new_availablePowerRange = 5600
    if (currentAvailablePower > 6050 and currentAvailablePower <= 6500):
        new_availablePowerRange = 6050
    if (currentAvailablePower > 6500 and currentAvailablePower <= 6950):
        new_availablePowerRange = 6500
    if (currentAvailablePower > 6950 and currentAvailablePower <= 7600):
        new_availablePowerRange = 6950
    if (currentAvailablePower > 7600 and currentAvailablePower <= 8300):
        new_availablePowerRange = 7500 
    if (currentAvailablePower > 8300 and currentAvailablePower <= 9000):
        new_availablePowerRange = 8000 
    if (currentAvailablePower > 9000 and currentAvailablePower <= 9700):
        new_availablePowerRange = 9000
    if (currentAvailablePower > 9700 and currentAvailablePower <= 10400):
        new_availablePowerRange = 9500 
    if (currentAvailablePower > 10400):
        new_availablePowerRange = 10000
    return new_availablePowerRange
#
# Calculating the right power current for a given powerrange
#
def getCurrent(availablePowerRange):
    chargePowerValue = 6
    if (getPhases() == 1):
        if (availablePowerRange == 1400):
            chargePowerValue = 6 # 1380 watt
        elif (availablePowerRange == 1700):
            chargePowerValue = 7 # 1610 watt
        elif (availablePowerRange == 1900):
            chargePowerValue = 8 # 1840 watt
        elif (availablePowerRange == 2100):
            chargePowerValue = 9 # 2070 watt
        elif (availablePowerRange == 2350):
            chargePowerValue = 10 # 2300 watt
        elif (availablePowerRange == 2600):
            chargePowerValue = 11 # 2530 watt
        elif (availablePowerRange == 2800): 
            chargePowerValue = 12 # 2760 watt
        elif (availablePowerRange == 3050): 
            chargePowerValue = 13 # 2990 watt
        elif (availablePowerRange == 3300): 
            chargePowerValue = 14 # 3220 watt
        elif (availablePowerRange >= 3500): 
            chargePowerValue = 15 # 3450 watt
    if (getPhases() == 2):
        if (availablePowerRange == 2800):
            chargePowerValue = 6 # 2760 watt
        elif (availablePowerRange == 3300):
            chargePowerValue = 7 # 3220 watt
        elif (availablePowerRange == 3800):
            chargePowerValue = 8 # 3680 watt
        elif (availablePowerRange == 4200):
            chargePowerValue = 9 # 4140 watt
        elif (availablePowerRange == 4650):
            chargePowerValue = 10 # 4600 watt
        elif (availablePowerRange == 5100): 
            chargePowerValue = 11 # 5060 watt
        elif (availablePowerRange == 5600): 
            chargePowerValue = 12 # 5520 watt
        elif (availablePowerRange == 6050): 
            chargePowerValue = 13 # 5980 watt
        elif (availablePowerRange == 6500): 
            chargePowerValue = 14 # 6440 watt
        elif (availablePowerRange >= 6950): 
            chargePowerValue = 15 # 6900 watt
    elif (getPhases() == 3):
        if (availablePowerRange == 4500):
            chargePowerValue = 6 # 4140 watt
        elif (availablePowerRange == 5000):
            chargePowerValue = 7 # 4830 watt
        elif (availablePowerRange == 5500):
            chargePowerValue = 8 # 5520 watt
        elif (availablePowerRange == 6000):
            chargePowerValue = 9 # 6210 watt
        elif (availablePowerRange == 7000): 
            chargePowerValue = 10 # 6900 watt
        elif (availablePowerRange == 7500): 
            chargePowerValue = 11 # 7590 watt
        elif (availablePowerRange == 8000): 
            chargePowerValue = 12 # 8280 watt
        elif (availablePowerRange == 9000): 
            chargePowerValue = 13 # 8970 watt
        elif (availablePowerRange == 9500): 
            chargePowerValue = 14 # 9660 watt
        elif (availablePowerRange == 10000): 
            chargePowerValue = 15 # 10350 watt
    return chargePowerValue

#
# Returns the actual set chargemode
# 0 = disabled
# 1 = fast
# 2 = slow
# 3 = tracked
#-1 = error
def getChargemode():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT chargemode FROM controls")
        chargemode = cur.fetchone()
    except:
        cur.close()
        con.close()
        return -1
    cur.close()
    con.close()
    return int(chargemode[0])

#
# Set the actual set chargemode
# 0 = disabled
# 1 = fast
# 2 = slow
# 3 = tracked
#
def setChargemode(chargemode):

    if (chargemode < 0 or chargemode > 3):
        logging.error("Invaild chargemode: " + str(chargemode))
        return

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE controls SET chargemode = " + str(chargemode))
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()

#
# Returns cloudy status
# 0 = not cloudy
# 1 = cloudy
# -1 = error
def getCloudy():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT cloudy FROM controls")
        cloudy = cur.fetchone()
    except:
        cur.close()
        con.close()
        return -1
    cur.close()
    con.close()
    return int(cloudy[0])

#
# Set the if it is cloudy
# 0 = not cloudy
# 1 = cloudy
#
def setCloudy(cloudy):
    if (cloudy < 0 or cloudy > 1):
        logging.error("Invaild cloudy pareameter: " + str(cloudy))
        return

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE controls SET cloudy = " + str(cloudy))
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()


def initModbusTable():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()

    modbus_sql = """
    CREATE TABLE IF NOT EXISTS modbus (
    timestamp TEXT NOT NULL,
    pvprod integer NOT NULL,
    houseconsumption integer NOT NULL,
    acpower integer NOT NULL,
    acpowertofromgrid integer NOT NULL,
    dcpower integer NOT NULL,
    availablepower_withoutcharging integer NOT NULL,
    availablepowerrange integer NOT NULL,
    temperature integer NOT NULL,
    status integer NOT NULL,
    batterypower integer NOT NULL,
    batterystatus REAL NOT NULL,
    soc REAL NOT NULL,
    soh REAL NOT NULL)"""
    try:
        cur.execute(modbus_sql)
        con.commit()
    except:
            logging.error(traceback.format_exc()) 
    cur.close()
    con.close()

def initNrgkicktable():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()

    nrgkick_sql = """
    CREATE TABLE IF NOT EXISTS nrgkick (
    timestamp TEXT NOT NULL,
    chargingpower integer NOT NULL,
    temperature REAL NOT NULL,
    errorcode integer NOT NULL,
    connected integer NOT NULL,
    ischarging integer NOT NULL,
    chargingcurrent REAL NOT NULL,
    chargingcurrentmin REAL NOT NULL,
    chargingcurrentmax REAL NOT NULL,
    phases integer NOT NULL)"""
    try:
        cur.execute(nrgkick_sql)
        con.commit()

        # check if there is already data
        cur.execute("SELECT * FROM nrgkick")
        nrgkick = cur.fetchone()

        if nrgkick == None:
            nrg_insert_sql = """
            INSERT INTO 'nrgkick' (
            timestamp,
            chargingpower,
            temperature,
            errorcode,
            connected,
            ischarging,
            chargingcurrent,
            chargingcurrentmin,
            chargingcurrentmax,
            phases) VALUES (0,0,0,0,0,0,0,0,0,1)
            """
            cur.execute(nrg_insert_sql)
            con.commit()
            logging.debug(nrg_insert_sql)
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()

def initChargelogTable():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()

    chargelog_sql = """
    CREATE TABLE IF NOT EXISTS chargelog (
    timestamp TEXT NOT NULL,
    currentChargingPower integer NOT NULL,
    chargingPossible integer NOT NULL)"""
    try:
        cur.execute(chargelog_sql)
        con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()


def initControlsTable():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()

    chargemode = None
    try:
        chargemode 
        controls_sql = """
        CREATE TABLE IF NOT EXISTS controls (
        chargemode integer NOT NULL,
        availablePowerRange integer NOT NULL,
        chargingPossible integer NOT NULL,
        cloudy integer NOT NULL
        )"""
        cur.execute(controls_sql)

        cur.execute("SELECT chargemode FROM controls")
        chargemode = cur.fetchone()

        # check if there are data otherwise init
        if (chargemode == None):
            # default = 0 (disabled)
            cur.execute("INSERT INTO 'controls' (chargemode,availablePowerRange,chargingPossible,cloudy) VALUES (0,0,0,0)")
            con.commit()
    except:
        logging.error(traceback.format_exc()) 
    cur.close()
    con.close()

class StdevFunc:
    def __init__(self):
        self.M = 0.0
        self.S = 0.0
        self.k = 1

    def step(self, value):
        if value is None:
            return
        tM = self.M
        self.M += (value - tM) / self.k
        self.S += (value - tM) * (value - self.M)
        self.k += 1

    def finalize(self):
        if self.k < 3:
            return None
        return math.sqrt(self.S / (self.k-2))