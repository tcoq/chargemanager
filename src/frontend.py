# flask_web/frontend.py
#
# --------------------------------------------------------------------------- #
# Module for building and controlling the web frontend
# --------------------------------------------------------------------------- #
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import traceback
import time
import os
import json
import logging
import chargemanagercommon 

AUTHENTICATION_ENABLED = 0
SECRET_KEY = 0
WEBPORT = 0

log = logging.getLogger(__name__)

# reduce flask-server general log spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

server = Flask(__name__)

def readSettings():
    global AUTHENTICATION_ENABLED, SECRET_KEY,WEBPORT
    if (chargemanagercommon.FRONTEND_SETTINGS_DIRTY == True):
        AUTHENTICATION_ENABLED = chargemanagercommon.getSetting(chargemanagercommon.AUTHENTICATIONENABLED)
        SECRET_KEY = chargemanagercommon.getSetting(chargemanagercommon.SECRETKEY)
        WEBPORT = chargemanagercommon.getSetting(chargemanagercommon.WEBPORT)
        chargemanagercommon.FRONTEND_SETTINGS_DIRTY = False

#
# Method checks correct auth
# returns:
# 0 = disabled authentication
# -1 = forbidden because request-secret information are invailid
#
def checkAuth(request):
    if (int(AUTHENTICATION_ENABLED) == 1):
        key = request.args.get("secret")
        if (key == None or key != SECRET_KEY):
            # brute force protection
            time.sleep(10)
            return -1
    else:
       return 0


#
# JSON data for GoogleChart input
#
def getJSONForSolaredgeData():
        con = sqlite3.connect('/data/chargemanager_db.sqlite3')
        cur = con.cursor()
        try:
            title = "Solaredge"
            # build 5 minute intervals of data
            sql = """
            select interval,pvprod,houseconsumption,chargerange,chargingpossible from ( 
            select datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch','localtime') interval, CAST(avg(pvprod) as INTEGER) as pvprod, avg(houseconsumption) as houseconsumption from modbus WHERE timestamp > datetime('now','-12 hour','localtime') group by interval)
            LEFT JOIN (
            select datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch','localtime') interval, avg(currentChargingPower) as chargerange, max(chargingPossible) as chargingpossible from chargelog WHERE timestamp > datetime('now','-12 hour','localtime') group by interval) USING (interval)"""
            cur.execute(sql)
            data = cur.fetchall()
            cur.close()
        except:
            log.error(traceback.format_exc())
        con.close()
        return json.dumps(data)
#
# Render index html
#
@server.route("/")
def renderPage():
    row = None 
    nrgkick = None 
    controls = None
    secret = SECRET_KEY

    status = checkAuth(request)
    if (status == -1):
        return "FORBIDDEN"
    elif (status == 0):
        secret = 0

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT timestamp,pvprod,houseconsumption,acpowertofromgrid,batterypower,temperature,soc,soh,status FROM modbus order by timestamp desc LIMIT 1")
        row = cur.fetchone()

        cur.execute("SELECT connected,chargingpower,ischarging FROM nrgkick")
        nrgkick = cur.fetchone()

        cur.execute("SELECT chargemode,availablePowerRange,chargingPossible,cloudy,smartPlugStatus FROM controls")
        controls = cur.fetchone()
        cur.close()
    except:
        log.error(traceback.format_exc())  
    con.close()

    if row == None or nrgkick == None or controls == None:
        return "No data" 

    chargemode = chargemanagercommon.getChargemode()
    trackedcharging = ""
    fastcharging = ""
    slowcharging = ""
    disabledcharging = ""

    if (chargemode == 0):
        disabledcharging = "checked"
    elif (chargemode == 1):
        fastcharging = "checked"
    elif (chargemode == 2):
        slowcharging = "checked"
    elif (chargemode == 3):
        trackedcharging = "checked"        

    return render_template('index.html', row = row, trackedcharging = trackedcharging , fastcharging = fastcharging, slowcharging=slowcharging, controls=controls, nrgkick=nrgkick, disabledcharging=disabledcharging, secret=secret, tempdata=getJSONForSolaredgeData())
               
@server.route("/chargemode", methods=['POST', 'GET'])
def setChargemode():   

    status = checkAuth(request)
    if (status == -1):
        return "FORBIDDEN"

    chargemode = request.form["chargemode"]

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE controls set chargemode = " + chargemode)
        con.commit()
        cur.close()
    except:
        log.error(traceback.format_exc()) 
    con.close()
    
    if (int(AUTHENTICATION_ENABLED) == 1):
        return redirect(url_for('renderPage', secret = SECRET_KEY))
    else:
        return redirect(url_for('renderPage'))

@server.route('/settings', methods=['GET'])
def renderForm():
    status = checkAuth(request)
    if (status == -1):
        return "FORBIDDEN"
    else:
        with open("/data/logs.log", "r") as f: 
            logfilecontent = f.read() 
        return render_template('settings.html', settings = chargemanagercommon.getSettings(), secret=SECRET_KEY, logfile=logfilecontent)

@server.route('/settings', methods=['POST'])
def saveForm():
    try:
        status = checkAuth(request)
        if (status == -1):
            return "FORBIDDEN"

        data = {}
        data[chargemanagercommon.SEIP ] = request.form[chargemanagercommon.SEIP ]
        data[chargemanagercommon.SEPORT]  = request.form[chargemanagercommon.SEPORT]
        data[chargemanagercommon.PVPEAKPOWER]  = request.form[chargemanagercommon.PVPEAKPOWER]
        data[chargemanagercommon.BATTERYSTARTSOC]  = request.form[chargemanagercommon.BATTERYSTARTSOC]
        data[chargemanagercommon.BATTERYMAXCONSUMPTION]  = request.form[chargemanagercommon.BATTERYMAXCONSUMPTION]
        data[chargemanagercommon.BATTERYMAXINPUT]  = request.form[chargemanagercommon.BATTERYMAXINPUT]
        data[chargemanagercommon.CHARGEMODEAUTO]  = request.form[chargemanagercommon.CHARGEMODEAUTO]
        data[chargemanagercommon.MEASUREMENTURL]  = request.form[chargemanagercommon.MEASUREMENTURL]
        data[chargemanagercommon.SETTINGSURL]  = request.form[chargemanagercommon.SETTINGSURL]
        data[chargemanagercommon.CHARGERPASSWORD]  = request.form[chargemanagercommon.CHARGERPASSWORD]
        data[chargemanagercommon.CHARGINGPHASES]  = request.form[chargemanagercommon.CHARGINGPHASES]
        data[chargemanagercommon.WEBPORT]  = request.form[chargemanagercommon.WEBPORT]
        data[chargemanagercommon.SECRETKEY]  = request.form[chargemanagercommon.SECRETKEY]
        data[chargemanagercommon.AUTHENTICATIONENABLED]  = request.form[chargemanagercommon.AUTHENTICATIONENABLED]
        data[chargemanagercommon.PLUGIP]  = request.form[chargemanagercommon.PLUGIP]
        data[chargemanagercommon.PLUGONPOWER ]  = request.form[chargemanagercommon.PLUGONPOWER ]
        data[chargemanagercommon.PVPLUGSTARTFROM]  = request.form[chargemanagercommon.PVPLUGSTARTFROM]
        data[chargemanagercommon.PVPLUGSTARTTO]  = request.form[chargemanagercommon.PVPLUGSTARTTO]
        data[chargemanagercommon.ALWAYSPLUGSTARTFROM]  = request.form[chargemanagercommon.ALWAYSPLUGSTARTFROM]
        data[chargemanagercommon.ALWAYSPLUGSTARTTO]  = request.form[chargemanagercommon.ALWAYSPLUGSTARTTO]
        data[chargemanagercommon.PLUGSTARTFROMSOC]  = request.form[chargemanagercommon.PLUGSTARTFROMSOC]
        data[chargemanagercommon.PLUGENABLED]  = request.form[chargemanagercommon.PLUGENABLED]
        data[chargemanagercommon.ALLOWPLUGUSEHOUSEBATTERY]  = request.form[chargemanagercommon.ALLOWPLUGUSEHOUSEBATTERY]

        chargemanagercommon.saveSettings(data)

        # force to reload setting in all modules
        chargemanagercommon.SOLAREDGE_SETTINGS_DIRTY == True
        chargemanagercommon.NRGKICK_SETTINGS_DIRTY == True
        chargemanagercommon.SMARTPLUG_SETTINGS_DIRTY == True
        chargemanagercommon.FRONTEND_SETTINGS_DIRTY == True
        chargemanagercommon.CHARGEMANAGER_SETTINGS_DIRTY == True
    except:
        log.error(traceback.format_exc()) 

    return render_template('settings.html', settings = chargemanagercommon.getSettings(), notice = "Settings saved! (NOTE: Server restart for WEB changes necessary!)", secret=SECRET_KEY)


def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    try:
        readSettings()
        log.info("Module " + str(__name__) + " started...")

        server.run(host='::', port=WEBPORT)
    except KeyboardInterrupt:
        pass