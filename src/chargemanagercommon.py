#!/usr/bin/python3
#
# --------------------------------------------------------------------------- #
# Chargemanagercommon is a module for shared resource access like
# database access or project initialization
# --------------------------------------------------------------------------- #
from pickle import FALSE
from telnetlib import AUTHENTICATION
import threading
import logging
import sqlite3 
import math
import traceback

log = logging.getLogger(__name__)

phases = 0

SEIP = 'seip' 
SEPORT = 'seport'  
PVPEAKPOWER = 'pvpeakpower'
BATTERYSTARTSOC ='batterystartsoc' 
BATTERYMAXCONSUMPTION = 'batterymaxconsumption' 
BATTERYMAXINPUT = 'batterymaxinput' 
CHARGEMODEAUTO = 'chargemodeauto' 
MEASUREMENTURL ='measurementsurl' 
SETTINGSURL ='settingsurl'
CHARGERPASSWORD = 'chargerpassword' 
PULSARWALLBOXTOPICNAME ='pulsarwallboxtopicname'
MQTTIP = 'mqttip'
CHARGINGPHASES = 'chargingphases' 
WEBPORT = 'webport'
SECRETKEY = 'secretkey' 
AUTHENTICATIONENABLED = 'authenticationenabled' 
PLUGIP = 'plugip' 
PLUGONPOWER = 'plugonpower'  
PVPLUGSTARTFROM ='pvPlugstartFrom'
PVPLUGSTARTTO ='pvPlugstartTo'
ALWAYSPLUGSTARTFROM ='alwaysPlugstartFrom'
ALWAYSPLUGSTARTTO ='alwaysPlugstartTo'
PLUGSTARTFROMSOC ='plugstartFromSOC'
PLUGENABLED ='plugEnabled'
ALLOWPLUGUSEHOUSEBATTERY ='allowPlugUseBattery'

SOLAREDGE_SETTINGS_DIRTY = True
WALLBOXES_SETTINGS_DIRTY = True
SMARTPLUG_SETTINGS_DIRTY = True
FRONTEND_SETTINGS_DIRTY = True
CHARGEMANAGER_SETTINGS_DIRTY = True

TRACKED_MODE = 3
FAST_MODE = 1
SLOW_MODE = 2
DISABLED_MODE = 0

def init():
    global databaseInitialized, sem
    sem = threading.Semaphore()
    databaseInitialized = False
    sem.acquire()
    if (databaseInitialized == False):
        initModbusTable()
        initControlsTable()
        initWallboxestable()
        initChargelogTable()
        initSettingsTable()
        databaseInitialized == True
    sem.release()

def getSetting(key):
    return getSettings()[key]

def getDBConnection():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3',timeout=7)
    con.execute('PRAGMA synchronous = off')
    con.execute('PRAGMA journal_mode = off')
    con.execute('pragma temp_store = memory')
    con.execute('pragma mmap_size = 30000000000')
    return con

def getSettings():
    con = getDBConnection()

    try:
        cur = con.cursor()
        cur.execute("SELECT * FROM settings")
        settings = cur.fetchone()
        data = {}
        for idx, col in enumerate(cur.description):
            data[col[0]] = settings[idx]
        cur.close() 
        return data 
    except:
        log.error(traceback.format_exc()) 
        return {}
    finally:
        con.close()

def saveSettings(data):
    con = getDBConnection()
    
    try:
        cur = con.cursor()
        query = f"UPDATE settings SET " + ', '.join(
        "{}=?".format(k) for k in data.keys())
        # for debugging
        # print(query, list(data.values())) 
        cur.execute(query, list(data.values()))
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

#
# Returns the current number of available phases by the charger based on wallbox id
# 
# Returns: 1-3 or -1 for errors
#
def getPhases(id):
    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("SELECT phases FROM wallboxes where id = " + str(id))
        chargemode = cur.fetchone()
        cur.close()
    except:
        con.close()
        return -1
    finally:
        con.close()

    if (chargemode is None or len(chargemode) == 0):
        return -1
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
def getCurrent(availablePowerRange,id):
    chargePowerValue = 6
    if (getPhases(id) == 1):
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
    if (getPhases(id) == 2):
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
    elif (getPhases(id) == 3):
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
    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("SELECT chargemode FROM controls")
        chargemode = cur.fetchone()
        cur.close()
    except:
        con.close()
        return -1
    finally:
        con.close()
    return int(chargemode[0])

#
# Set the actual set chargemode based on wallbox id
# 0 = disabled
# 1 = fast
# 2 = slow
# 3 = tracked
#
def setChargemode(chargemode):

    if (chargemode < 0 or chargemode > 3):
        log.error("Invaild chargemode: " + str(chargemode))
        return

    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("UPDATE controls SET chargemode = " + str(chargemode))
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

def setWallboxDisconnected(id):
    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("UPDATE wallboxes SET connected = 0, chargingpower = 0 where id = " + str(id))
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

#
# Returns connected status based on wallbox id
# 1 = wallbox is connected
# 0 = wallbox is not connected
def isAnyWallboxConnected():
    con = getDBConnection()
    
    status = 0
    try:
        cur = con.cursor()
        cur.execute("SELECT max(connected) FROM wallboxes")
        val = cur.fetchone()
        cur.close()
        status = int((val[0]))
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

    if (status == 1):
        return 1
    else:
        return 0

#
# Returns charging status based on wallbox id
# 1> = Current NRGKick power in watt
# 0 = NRGKick is not charging
def isWallboxCharging(id):
    con = getDBConnection()
    
    chargingpower = 0
    try:
        cur = con.cursor()
        cur.execute("SELECT chargingpower FROM wallboxes where id = " + str(id))
        chargingpower = cur.fetchone()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()
        
    if (int(chargingpower[0]) > 0):
        return int(chargingpower[0])
    else:
        return 0

#
# Returns smart plug status
# 0 = off
# 1 = on
# -1 = error
def getSmartPlugStatus():
    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("SELECT smartPlugStatus FROM controls")
        smartPlugStatus = cur.fetchone()
        cur.close()
    except:
        con.close()
        return -1
    finally:
        con.close()
        
    return int(smartPlugStatus[0])

#
# Set the status of the smart plug
# 0 = deactivated
# 1 = activated
def setSmartPlugStatus(smartPlugStatus):
    if (smartPlugStatus < 0 or smartPlugStatus > 1):
        log.error("Invaild smartPlugStatus: " + str(smartPlugStatus))
        return

    con = getDBConnection()
    
    try:
        cur = con.cursor()
        cur.execute("UPDATE controls SET smartPlugStatus = " + str(smartPlugStatus))
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

#
# Returns cloudy status
# 0 = not cloudy
# 1 = cloudy
# -1 = error
def getCloudy():
    con = getDBConnection()

    try:
        cur = con.cursor()
        cur.execute("SELECT cloudy FROM controls")
        cloudy = cur.fetchone()
        cur.close()
    except:
        con.close()
        return -1
    finally:
        con.close()
        
    return int(cloudy[0])

#
# Set the if it is cloudy
# 0 = not cloudy
# 1 = cloudy
#
def setCloudy(cloudy):
    if (cloudy < 0 or cloudy > 1):
        log.error("Invaild cloudy pareameter: " + str(cloudy))
        return

    con = getDBConnection()

    try:
        cur = con.cursor()
        cur.execute("UPDATE controls SET cloudy = " + str(cloudy))
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()


def initModbusTable():
    con = getDBConnection()

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
        cur = con.cursor()
        cur.execute(modbus_sql)
        cur.execute("CREATE INDEX IF NOT EXISTS index_modbus ON modbus (timestamp)")
        con.commit()
        cur.close()
    except:
            log.error(traceback.format_exc()) 
    finally:
        con.close()

def initWallboxestable():
    con = getDBConnection()

    wallboxes_sql = """
    CREATE TABLE IF NOT EXISTS wallboxes (
    id integer NOT NULL,
    type integer NOT NULL,
    timestamp TEXT NOT NULL,
    chargingpower integer NOT NULL,
    temperature REAL NOT NULL,
    errorcode integer NOT NULL,
    connected integer NOT NULL,
    ischarging integer NOT NULL,
    chargingcurrent REAL NOT NULL,
    phases integer NOT NULL)"""
    try:
        cur = con.cursor()
        cur.execute(wallboxes_sql)
        con.commit()
        cur.close()
        cur = con.cursor()
        # check if there is already data
        cur.execute("SELECT * FROM wallboxes")
        wallboxes = cur.fetchone()

        if wallboxes == None:
            wallboxes_insert_sql = """
            INSERT INTO 'wallboxes' (
            id,
            type,
            timestamp,
            chargingpower,
            temperature,
            errorcode,
            connected,
            ischarging,
            chargingcurrent,
            phases) VALUES (1,1,0,0,0,0,0,0,0,1),(2,2,0,0,0,0,0,0,0,1)
            """
            cur = con.cursor()
            cur.execute(wallboxes_insert_sql)
            con.commit()
            cur.close()
            log.debug(wallboxes_insert_sql)
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

def initChargelogTable():
    con = getDBConnection()

    chargelog_sql = """
    CREATE TABLE IF NOT EXISTS chargelog (
    timestamp TEXT NOT NULL,
    currentChargingPower integer NOT NULL,
    chargingPossible integer NOT NULL)"""
    try:
        cur = con.cursor()
        cur.execute(chargelog_sql)
        cur.execute("CREATE INDEX IF NOT EXISTS index_chargelog ON chargelog (timestamp)")
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()


def initControlsTable():
    con = getDBConnection()

    chargemode = None
    try:
        chargemode 
        controls_sql = """
        CREATE TABLE IF NOT EXISTS controls (
        chargemode integer NOT NULL,
        availablePowerRange integer NOT NULL,
        chargingPossible integer NOT NULL,
        cloudy integer NOT NULL,
        smartPlugStatus integer NOT NULL
        )"""
        cur = con.cursor()
        cur.execute(controls_sql)
        cur.close()
        cur = con.cursor()
        cur.execute("SELECT chargemode FROM controls")
        chargemode = cur.fetchone()
        cur.close()
        # check if there are data otherwise init
        if (chargemode == None):
            # default = 0 (disabled)
            cur = con.cursor()
            cur.execute("INSERT INTO 'controls' (chargemode,availablePowerRange,chargingPossible,cloudy,smartPlugStatus) VALUES (0,0,0,0,0)")
            con.commit()
            cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
        con.close()

def initSettingsTable():
    con = getDBConnection()
    settings = None
    try:
        settings_sql = """
        CREATE TABLE IF NOT EXISTS settings (
        seip TEXT NOT NULL,
        seport integer NOT NULL,
        pvpeakpower integer NOT NULL,
        batterystartsoc integer NOT NULL,
        batterymaxconsumption integer NOT NULL,
        batterymaxinput integer NOT NULL,
        chargemodeauto integer NOT NULL,
        measurementsurl TEXT NOT NULL,
        settingsurl TEXT NOT NULL,
        chargerpassword TEXT NOT NULL,
        pulsarwallboxtopicname TEXT NOT NULL,
        mqttip TEXT NOT NULL,
        chargingphases integer NOT NULL,
        webport integer NOT NULL,
        secretkey TEXT NOT NULL,
        authenticationenabled integer NOT NULL,
        plugip TEXT NOT NULL,
        plugonpower integer NOT NULL,
        pvPlugstartFrom TEXT NOT NULL,
        pvPlugstartTo TEXT NOT NULL,
        alwaysPlugstartFrom TEXT NOT NULL,
        alwaysPlugstartTo TEXT NOT NULL,
        plugstartFromSOC integer NOT NULL,
        plugEnabled integer NOT NULL,
        allowPlugUseBattery integer NOT NULL
        )"""
        cur = con.cursor()
        cur.execute(settings_sql)
        cur.close()
        cur = con.cursor()
        cur.execute("SELECT seip FROM settings")
        settings = cur.fetchone()
        cur.close()
        # check if there are data otherwise init
        if (settings == None):
            # default = 0 (disabled)
            cur = con.cursor()
            insert_sql = """
            INSERT INTO settings (
            seip,
            seport,
            pvpeakpower,
            batterystartsoc,
            batterymaxconsumption,
            batterymaxinput,
            chargemodeauto,
            measurementsurl,
            settingsurl,
            chargerpassword,
            pulsarwallboxtopicname,
            mqttip,
            chargingphases,
            webport,
            secretkey,
            authenticationenabled,
            plugip,
            plugonpower,
            pvPlugstartFrom,
            pvPlugstartTo,
            alwaysPlugstartFrom,
            alwaysPlugstartTo,
            plugstartFromSOC,
            plugEnabled,
            allowPlugUseBattery) 
            VALUES (
            '192.168.178.xx',
            1502,
            9400,
            60,
            2600,
            4950,
            1,
            'http://192.168.178.xx/api/measurements/04:91:62:76:xx:xx',
            'http://192.168.178.xx/api/settings/04:91:62:76:xx:xx',
            '1234',
            'wallbox_xxxxx',
            '192.168.178.xx',
            2,
            5000,
            '11111',
            0,
            '192.168.178.xx',
            2100,
            '13:55',
            '16:15',
            '13:50',
            '16:15',
            70,
            0,
            1
            )
            """
            cur.execute(insert_sql)
        
            con.commit()
            cur.close()
    except:
        log.error(traceback.format_exc()) 
    finally:
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