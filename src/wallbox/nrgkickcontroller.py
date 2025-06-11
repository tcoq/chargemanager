# wallbox/nrgkick_wallbox.py

import requests
import traceback
import chargemanagercommon
import logging
from wallbox.base import WallboxBase

log = logging.getLogger(__name__)

class NrgkickController(WallboxBase):

    ID = 1
    charingLevel = 6
    chargingStatus = False
    retryCount = 4
    activeChargingSession = False
    available = -1

    def __init__(self):
        self.measurements_url = None
        self.settings_url = None
        self.password = None
        self.max_phases = None
        self.readSettings()

        self.read_charge_status = 0
        self.read_charge_value = 0

    def readSettings(self):
        if chargemanagercommon.NRGKICK_SETTINGS_DIRTY:
            self.measurements_url = chargemanagercommon.getSetting(chargemanagercommon.MEASUREMENTURL)
            self.settings_url = chargemanagercommon.getSetting(chargemanagercommon.SETTINGSURL)
            self.password = chargemanagercommon.getSetting(chargemanagercommon.CHARGERPASSWORD)
            self.max_phases = chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES)
            chargemanagercommon.NRGKICK_SETTINGS_DIRTY = False

    def setCharging(self, currentValue, startCharging):
        
        chargemode = "true"
        if startCharging == False:
            chargemode = "false"


        if currentValue < 6 or currentValue > 16:
            log.error("Current value out of range: " + str(currentValue))
            return {
                    "errorcode": 1
            } 

        json_current_value = """
        {
        "Values": {
            "ChargingStatus": {
            "Charging": """ + str(chargemode) + " " + """
            },
            "ChargingCurrent": {
            "Value": """ + str(currentValue) + ", " + """
            "Min": """ + str(currentValue) + ", " + """
            "Max": """ + str(currentValue) + " " + """
            },
            "DeviceMetadata": {
            "Password": """ + str(self.password) +  """
            }
        }
        }
        """
        headers = {"Content-Type": "application/json"}
        try:
            resp = requests.put(url=self.settings_url, data=json_current_value, headers=headers)
            log.debug("Response start/stop charging: " + str(resp.status_code) + " " + str(json_current_value))
            http_status = resp.status_code
            resp.close()
            # success case
            return {
                    "errorcode": 0
            } 
        except:
            #log.error(traceback.format_exc()) 
            return {
                    "errorcode": 2
            } 

    def getID(self):
        return self.ID

    def isCharging(self):
        return self.chargingStatus

    def getCharingLevel(self):
        return self.charingLevel

    def getRetryCount(self):
        return self.retryCount

    def setRetryCount(self, count): 
        self.retryCount = count

    def isActiveCharingSession(self):
        return self.activeChargingSession

    def setActiveCharingSession(self, status: bool): 
        self.activeChargingSession = status

    def readData(self):
        chargingpower = 0
        self.available = -1
        try:
            try:
                resp = requests.get(url=self.measurements_url)
            except:
                log.debug("Could not connect to nrg kick data")

                return {
                    "chargingpower": -1,
                    "temperature": 0,
                    "phases": 0,
                    "errorcode": 1,
                    "isconnected": self.available,
                    "ischarging": 0,
                    "chargingcurrent": 0
                }   
            general = resp.json()
            resp.status_code
            resp.close()

            try:
                if (general['Message'] == 'No content found for this request'):
                    log.debug("No NRG connected...")
                    return {
                        "chargingpower": -1,
                        "temperature": 0,
                        "phases": 0,
                        "errorcode": 2,
                        "isconnected": self.available,
                        "ischarging": 0,
                        "chargingcurrent": 0
                    } 
            except:
                # nrgkick is not connected but bluetooth device is available
                pass

            timestamp = general['Timestamp']
            # convert value from kilowatt to watt
            chargingpower = int(float(general['ChargingPower']) * 1000)
            temperature = general['TemperatureMainUnit']

            phase1 = general['VoltagePhase'][0]
            phase2 = general['VoltagePhase'][1]
            phase3 = general['VoltagePhase'][2]

            log.debug(timestamp)
            log.debug(chargingpower)
            log.debug(temperature)
            log.debug(phase1)
            log.debug(phase2)
            log.debug(phase3)

            totalVoltage = int(phase1) + int(phase2) + int(phase3)
            
            # default
            phases = 2
            if (totalVoltage > 600 and self.max_phases == 3):
                phases = 3
            elif (totalVoltage > 400):
                phases = 2
            elif (totalVoltage > 200):
                phases = 1

            try:
                resp = requests.get(url=self.settings_url)
            except:
                log.debug("Could not connect to nrg kick settings")
                return {
                    "chargingpower": -1,
                    "temperature": 0,
                    "phases": 0,
                    "errorcode": 31,
                    "isconnected": self.available,
                    "ischarging": 0,
                    "chargingcurrent": 0
                } 
            settings = resp.json()
            resp.status_code
            resp.close()
            
            try:
                errorcode = settings['Info']['ErrorCodes'][0]
                self.available = chargemanagercommon.boolToInt(settings['Info']['Connected'])
                ischarging = chargemanagercommon.boolToInt(settings['Values']['ChargingStatus']['Charging'])
                self.charingLevel = int(settings['Values']['ChargingCurrent']['Value'])

            except:
                log.error("Problems reading data from nrgkick!")
                log.error(traceback.format_exc())
                
                return {
                    "chargingpower": -1,
                    "temperature": 0,
                    "phases": 0,
                    "errorcode": 4,
                    "isconnected": self.available,
                    "ischarging": 0,
                    "chargingcurrent": 0
                } 
            
            log.debug(errorcode)
            log.debug(ischarging)
            log.debug(self.charingLevel)

            con = chargemanagercommon.getDBConnection()
            
            # sometimes NRGKick delivers incorrect data from the second URL... 
            # chargingpower is the stronger signal so set isConnected and isCharging to true
            if (chargingpower > 1):
                self.available = 1
                ischarging = 1

            if (int(ischarging) == 1):
                self.chargingStatus= True
            else:
                self.chargingStatus = False

        except:
            log.error(traceback.format_exc())      

        return {
            "chargingpower": chargingpower,
            "temperature": temperature,
            "phases": phases,
            "errorcode": 0,
            "isconnected": self.available,
            "ischarging": ischarging,
            "chargingcurrent": self.charingLevel
        }   

    def isAvailable(self):
        if (self.available > 0):
            return True
        else:
            return False