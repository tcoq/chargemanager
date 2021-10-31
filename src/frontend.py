# flask_web/frontend.py

from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import traceback
import time
import pytz, os
import json
import logging
import configparser
from chargemanagercommon import initDatabase

config = configparser.RawConfigParser()
config.read('chargemanager.properties')

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', filename='/data/frontend.log', filemode='w', level=logging.INFO)
server = Flask(__name__)

#
# Returns the actual set chargemode
# 0 = disabled
# 1 = fast
# 2 = slow
# 3 = tracked
#
def getChargemode():
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT chargemode FROM controls")
        chargemode = cur.fetchone()
    except:
        chargemode = None
    cur.close()
    con.close()
    return chargemode

#
# JSON data for GoogleChart input
#
def getJSONForSolaredgeData():
    with sqlite3.connect('/data/chargemanager_db.sqlite3') as con:
        cur = con.cursor()
        title = "Solaredge"
        # build 5 minute intervals of data
        sql = """
        select interval,pvprod,availablepowerrange,chargerange,chargingpossible from ( 
        select datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch','localtime') interval, CAST(avg(pvprod) as INTEGER) as pvprod, avg(availablepowerrange) as availablepowerrange from modbus WHERE timestamp > datetime('now','-12 hour','localtime') group by interval)
        LEFT JOIN (
        select datetime((strftime('%s', timestamp) / 300) * 300, 'unixepoch','localtime') interval, avg(currentChargingPower) as chargerange, max(chargingPossible) as chargingpossible from chargelog WHERE timestamp > datetime('now','-12 hour','localtime') group by interval) USING (interval)"""
        cur.execute(sql)
        data = cur.fetchall()
        return json.dumps(data)
#
# Render index html
#
@server.route("/")
def renderPage():
    row = None 
    nrgkick = None 
    controls = None
    
    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("SELECT timestamp,pvprod,houseconsumption,acpowertofromgrid,batterypower,temperature,soc,status FROM modbus order by timestamp desc LIMIT 1")
        row = cur.fetchone()

        cur.execute("SELECT connected,chargingpower,ischarging FROM nrgkick")
        nrgkick = cur.fetchone()

        cur.execute("SELECT chargemode,availablePowerRange,chargingPossible FROM controls")
        controls = cur.fetchone()
    except:
        logging.error(traceback.format_exc())  
    cur.close()
    con.close()
    if row == None or nrgkick == None or controls == None:
        return "No data" 

    chargemode = getChargemode()
    trackedcharging = ""
    fastcharging = ""
    slowcharging = ""
    disabledcharging = ""

    if (chargemode[0] == 0):
        disabledcharging = "checked"
    elif (chargemode[0] == 1):
        fastcharging = "checked"
    elif (chargemode[0] == 2):
        slowcharging = "checked"
    elif (chargemode[0] == 3):
        trackedcharging = "checked"        

    return render_template('index.html', row = row, trackedcharging = trackedcharging , fastcharging = fastcharging, slowcharging=slowcharging, controls=controls, nrgkick=nrgkick, disabledcharging=disabledcharging, tempdata=getJSONForSolaredgeData())
               
@server.route("/chargemode", methods=['POST', 'GET'])
def setChargemode():   
    chargemode = request.form["chargemode"]

    con = sqlite3.connect('/data/chargemanager_db.sqlite3')
    cur = con.cursor()
    try:
        cur.execute("UPDATE controls set chargemode = " + chargemode)
        con.commit()
    except:
        logging.error(traceback.format_exc()) 

    cur.close()
    con.close()
    return redirect(url_for('renderPage'))

if __name__ == "__main__":
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    try:
        initDatabase()
        server.run(host='0.0.0.0', port=config.get('Webinterface', 'web.port'))
    except KeyboardInterrupt:
        pass