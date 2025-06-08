import paho.mqtt.client as mqtt
import time
import traceback
import chargemanagercommon
import logging
from wallbox.base import WallboxBase

log = logging.getLogger(__name__)

class PulsarWallboxController(WallboxBase):

    ID = 2
    lastCharingLevel = 6
    chargingStatus = False
    available = False
    retryCount = 4
    activeChargingSession = False
    topicname = ""
    mqttip = ""
    l1 = 0
    l2 = 0
    l3 = 0

    received_values = {
    "chargingpower": 0,
    "temperature": 0,
    "phases": 0,
    "errorcode": 1,
    "isconnected": 0,
    "ischarging": 0,
    "chargingcurrent": 0
    }

    def __init__(self):
        self.measurements_url = None
        self.settings_url = None
        self.password = None
        self.max_phases = None
        self.readSettings()
        self.read_charge_status = 0
        self.read_charge_value = 0

    def readSettings(self):
        if (chargemanagercommon.WALLBOXES_SETTINGS_DIRTY):
           self.mqttip = str(chargemanagercommon.getSetting(chargemanagercommon.MQTTIP))
           self.topicname = str(chargemanagercommon.getSetting(chargemanagercommon.PULSARWALLBOXTOPICNAME))
           self.max_phases = chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES)
           chargemanagercommon.WALLBOXES_SETTINGS_DIRTY = False

    def setCharging(self, currentValue, startCharging):
        if currentValue < 6 or currentValue > 16:
            log.error("Current value out of range: " + str(currentValue))
            return {"errorcode": 1}
        try:

            client = mqtt.Client()  # Für neue paho-mqtt-Versionen
            client.connect(self.mqttip, 1883, 60)
            
            # log.info("Publish new charge values: " + str(chargemode) + " " +  str(currentValue))
            client.publish(self.topicname + "/charging_enable/set", str(startCharging))
            client.publish(self.topicname + "/max_charging_current/set", str(currentValue))

            client.loop_start()
            
            # we need to wait a while until we get the messages...
            timeout = 2
            start = time.time()
            while time.time() - start < timeout:
                time.sleep(0.1)

            client.loop_stop()

            client.disconnect()

        except:
            log.error(traceback.format_exc()) 
            return {"errorcode": 2}

    def getID(self):
        return self.ID

    def isCharging(self):
        return self.chargingStatus

    def getCharingLevel(self):
        return self.lastCharingLevel

    def getRetryCount(self):
        return self.retryCount

    def setRetryCount(self, count: int): 
        self.retryCount = count

    def isActiveCharingSession(self):
        return self.activeChargingSession

    def setActiveCharingSession(self, status: bool): 
        self.activeChargingSession = status

    def readData(self):
        return self.read_wallbox_status()

    def isAvailable(self):
        return self.available

    def read_wallbox_status(self):
        try:
            def on_connect(client, userdata, flags, rc):
                if rc != 0:
                    log.error(f"MQTT-Verbindung fehlgeschlagen mit Code {rc}")

            def on_message(client, userdata, msg):
                topic = msg.topic
                payload = msg.payload.decode()
                log.debug(msg.topic + " > "+ payload)

                if topic == self.topicname + "/charging_power/state":
                    chargingpower = int(float(payload))
                    self.received_values["chargingpower"] = chargingpower
                    self.chargingStatus = True if chargingpower > 0 else False
                    self.received_values["ischarging"] = 1 if chargingpower > 0 else 0
                    #log.info(str(chargingpower) + " " + str(self.chargingStatus))
                elif topic == self.topicname + "/availability":
                    if (payload == 'offline'):
                        self.received_values["isconnected"] = 0
                        self.available = False
                    else:
                        self.received_values["isconnected"] = 1
                        self.available = True
                elif topic == self.topicname + "/max_charging_current/state":
                    self.received_values["chargingcurrent"] = int(payload)
                    self.lastCharingLevel = int(payload)
                elif topic == self.topicname + "/charging_power_l1/state":
                    self.l1 = int(float(payload))
                    if (self.l1 > 1): self.l1 = 230
                    else: self.l1 = 0
                elif topic == self.topicname + "/charging_power_l2/state":
                    self.l2 = int(float(payload))
                    if (self.l2 > 1): self.l2 = 230
                    else: self.l2 = 0
                elif topic == self.topicname + "/charging_power_l3/state":
                    self.l3 = int(float(payload))
                    if (self.l3 > 1): self.l3 = 230 
                    else: self.l3 = 0

                self.received_values["errorcode"] = 0
                log.debug("V:"+  str(self.l1) + " " + str(self.l2) + " " + str(self.l3))
                totalVoltage = int(self.l1) + int(self.l2) + int(self.l3)
                # default
                phases = 2
                if (totalVoltage > 600 and self.max_phases == 3):
                    phases = 3
                elif (totalVoltage > 400):
                    phases = 2
                elif (totalVoltage > 200):
                    phases = 1
                self.received_values["phases"] = int(phases)

            client = mqtt.Client()  # Für neue paho-mqtt-Versionen
            client.on_message = on_message
            client.on_connect = on_connect

            client.connect(self.mqttip, 1883, 60)

            client.subscribe(str(self.topicname + "/availability"))
            client.subscribe(str(self.topicname + "/charging_power/state"))
            client.subscribe(str(self.topicname + "/max_charging_current/state"))
            client.subscribe(str(self.topicname + "/charging_power_l1/state"))
            client.subscribe(str(self.topicname + "/charging_power_l2/state"))
            client.subscribe(str(self.topicname + "/charging_power_l3/state"))

            client.loop_start()
            
            # we need to wait a while until we get the messages...
            timeout = 2
            start = time.time()
            while time.time() - start < timeout:
                time.sleep(0.1)

            client.loop_stop()
        except:
            log.error(traceback.format_exc()) 
        
        log.debug("PulsarWallbox chargingStatus: " + str(self.chargingStatus) + " isAvailable: " + str(self.available))
        return self.received_values