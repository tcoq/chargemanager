import logging
import socket
import time
import chargemanagercommon
from wallbox.base import WallboxBase
from pymodbus.client import ModbusTcpClient

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)

class Kebap30Controller(WallboxBase):
    ID = 3  
    UNIT_ID = 255 
    UDP_PORT = 7090

    def __init__(self):
        self.ip_address = None
        self.max_phases = 3
        self.retryCount = 0
        self.activeChargingSession = False
        self.locked = False
        self.last_set_limit_a = 0
        
        # WIE BEIM NRGKICK: Erstmal auf 0 (Offline), bis der erste Connect klappt
        self.available = 0 
        self._last_is_charging = False
        
        self.last_data = self._get_empty_data()
        self.readSettings()
        log.info(f"KEBA: Controller initialisiert für {self.ip_address} (Start-Status: Offline)")

    def readSettings(self):
        if chargemanagercommon.KEBAP30_SETTINGS_DIRTY:
            self.ip_address = chargemanagercommon.getSetting(chargemanagercommon.KEBAP30IP)
            self.max_phases = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES))
            chargemanagercommon.KEBAP30_SETTINGS_DIRTY = False
        if not self.ip_address or self.ip_address == "0.0.0.0":
            self.ip_address = "192.168.178.153"

    def readData(self):
        self.readSettings()
        client = ModbusTcpClient(self.ip_address, port=502, timeout=4)
        
        try:
            if client.connect():
                # Erst jetzt erlauben wir dem Manager den Zugriff
                self.available = 1
                self.last_data["isconnected"] = 1
                
                time.sleep(0.1)
                res_s = client.read_holding_registers(1001, count=1, slave=self.UNIT_ID)
                
                if res_s and not res_s.isError():
                    keba_state = res_s.registers[0]
                    res_p = client.read_holding_registers(1020, count=2, slave=self.UNIT_ID)
                    
                    real_power = 0
                    if res_p and not res_p.isError():
                        power_mw = (res_p.registers[0] << 16) | res_p.registers[1]
                        real_power = int(power_mw / 1000)

                    self._last_is_charging = (keba_state == 3)
                    
                    self.last_data.update({
                        "chargingpower": max(0, real_power),
                        "phases": self.max_phases if real_power > 1000 else 1,
                        "ischarging": 1 if self._last_is_charging else 0,
                        "chargingcurrent": int(self.last_set_limit_a),
                        "errorcode": 0
                    })
                
                # WIE BEIM NRGKICK: Wenn wir Leistung sehen, ist sie definitiv verfügbar
                if (real_power > 1):
                    self.available = 1

            else:
                self._handle_disconnect()

        except Exception as e:
            log.debug(f"KEBA Modbus Read failed: {e}")
            self._handle_offline()
        finally:
            client.close()
            
        return self.last_data

    def _handle_offline(self):
        self.available = 0
        self.last_data.update({
            "isconnected": 0, "ischarging": 0, "chargingpower": 0
        })

    def setCharging(self, currentValue, startCharging):
        # WICHTIG: Wenn die Box offline ist, blockieren wir den Befehl sofort
        # Das verhindert die "Geister-Befehle" im Log
        if not self.isAvailable():
            return {"errorcode": 1}

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        try:
            target_a = int(round(float(currentValue)))
            target_a = max(6, min(32, target_a))

            if startCharging:
                log.info(f"KEBA UDP: Start {target_a}A")
                sock.sendto(b"ena 1", (self.ip_address, self.UDP_PORT))
                time.sleep(0.2)
                sock.sendto(f"curr {target_a * 1000}".encode(), (self.ip_address, self.UDP_PORT))
                self.last_set_limit_a = target_a
            else:
                log.info("KEBA UDP: Stop")
                sock.sendto(b"curr 0", (self.ip_address, self.UDP_PORT))
                time.sleep(0.2)
                sock.sendto(b"ena 0", (self.ip_address, self.UDP_PORT))
                self.last_set_limit_a = 0
            
            return {"errorcode": 0}
        except Exception:
            return {"errorcode": 2}
        finally:
            sock.close()

    def _get_empty_data(self):
        return {
            "chargingpower": 0, "phases": 1, "errorcode": 0, 
            "isconnected": 0, "ischarging": 0, "chargingcurrent": 0, "temperature": 0
        }

    # Framework Methoden
    def getID(self): return self.ID
    def isCharging(self): return self._last_is_charging
    def getChargingLevel(self): return self.last_set_limit_a
    
    # Exakt wie beim NRGkick: 
    def isAvailable(self): 
        return self.available > 0
    
    def getRetryCount(self): return self.retryCount
    def setRetryCount(self, count): self.retryCount = count
    def isActiveChargingSession(self): return self.activeChargingSession
    def setActiveChargingSession(self, status: bool): self.activeChargingSession = status
    def is_locked(self): return self.locked
    def set_locked(self, status: bool): self.locked = status