import logging
import socket
import time
import chargemanagercommon
from wallbox.base import WallboxBase
from pymodbus.client.sync import ModbusTcpClient

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)

class Kebap30Controller(WallboxBase):
    ID = 3  
    UNIT_ID = 255 
    UDP_PORT = 7090

    def __init__(self):
        self.ip_address = None
        self.max_phases = 3
        self.last_set_limit_a = 0  # 0 bedeutet aktuell "aus" oder kein Limit gesetzt
        self.readSettings()

    def readSettings(self):
        if chargemanagercommon.KEBAP30_SETTINGS_DIRTY:
            self.ip_address = chargemanagercommon.getSetting(chargemanagercommon.KEBAP30IP)
            self.max_phases = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES))
            chargemanagercommon.KEBAP30_SETTINGS_DIRTY = False
        if not self.ip_address or self.ip_address == "0.0.0.0":
            self.ip_address = "192.168.178.153"

    def readData(self):
        self.readSettings()
        client = ModbusTcpClient(self.ip_address, port=502, timeout=1)
        data = self._get_empty_data()
        
        try:
            if client.connect():
                # 1. Wirkleistung lesen (Register 1020)
                res_p = client.read_holding_registers(1020, 2, unit=self.UNIT_ID)
                real_power = 0
                if not res_p.isError() and len(res_p.registers) >= 2:
                    power_mw = (res_p.registers[0] << 16) | res_p.registers[1]
                    real_power = int(power_mw / 1000)

                # 2. Status lesen
                keba_state = 0
                res_s = client.read_holding_registers(1001, 1, unit=self.UNIT_ID)
                if not res_s.isError():
                    keba_state = res_s.registers[0]

                # Plausibilitäts-Korrektur: Wenn Leistung fließt, lädt sie auch
                if real_power > 200 and keba_state < 3:
                    keba_state = 3

                is_charging = (keba_state == 3)
                is_connected = (keba_state in [2, 3, 5])

                data.update({
                    "chargingpower": max(0, real_power),
                    "phases": self.max_phases if real_power > 1000 else 1,
                    "isconnected": 1 if is_connected else 0,
                    "ischarging": 1 if is_charging else 0,
                    "chargingcurrent": int(self.last_set_limit_a),
                    "temperature": 0,
                    "errorcode": 0
                })
                # Log nur auf DEBUG, um das Haupt-Log sauber zu halten
                log.debug(f"KEBA: {real_power}W, State: {keba_state}, Limit: {self.last_set_limit_a}A")
        except Exception as e:
            log.error(f"KEBA Modbus Error: {e}")
        finally:
            client.close()
        return data

    def setCharging(self, currentValue, startCharging):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        try:
            # 1. Wert säubern: Sicherstellen, dass es ein Float/Int ist und runden
            # Das verhindert Updates bei winzigen Abweichungen (z.B. 6.001 auf 6.002)
            try:
                target_a = int(round(float(currentValue)))
            except (ValueError, TypeError):
                target_a = 6

            # 2. Hardware-Grenzen einhalten (KEBA P30 Minimum ist meist 6A)
            if target_a < 6: target_a = 6
            if target_a > 32: target_a = 32 # Oder 16, je nach Absicherung

            if startCharging:
                # NUR senden, wenn sich der ganzzahlige Ampere-Wert geändert hat
                # ODER wenn die Box vorher im Status "aus" (0) war
                if target_a != self.last_set_limit_a:
                    self.last_set_limit_a = target_a
                    target_ma = target_a * 1000
                    
                    # UDP Befehle: Erst einschalten, dann Strom setzen
                    sock.sendto(b"ena 1", (self.ip_address, self.UDP_PORT))
                    time.sleep(0.1) 
                    sock.sendto(f"curr {target_ma}".encode(), (self.ip_address, self.UDP_PORT))
                    
                    log.info(f"KEBA SET: {target_a}A (Wallbox ID {self.ID})")
                else:
                    log.debug(f"KEBA ID {self.ID} ist bereits auf {target_a}A. Kein UDP-Senden nötig.")
            else:
                # Stopp-Logik: Nur senden, wenn wir nicht schon auf 0 stehen
                if self.last_set_limit_a != 0:
                    self.last_set_limit_a = 0
                    sock.sendto(b"curr 0", (self.ip_address, self.UDP_PORT))
                    time.sleep(0.1)
                    sock.sendto(b"ena 0", (self.ip_address, self.UDP_PORT))
                    log.info(f"KEBA STOPP (Wallbox ID {self.ID})")
            
            return {"errorcode": 0}
        except Exception as e:
            log.error(f"KEBA UDP Error in setCharging: {e}")
            return {"errorcode": 2}
        finally:
            sock.close()

    def _get_empty_data(self):
        return {"chargingpower": 0, "phases": 1, "errorcode": 0, "isconnected": 0, "ischarging": 0, "chargingcurrent": 0, "temperature": 0}

    # --- Boilerplate Methoden ---
    def getID(self): return self.ID
    def isCharging(self): 
        return self.readData()["ischarging"]
    def getChargingLevel(self): 
        # Falls die Box aus ist, melden wir 6A als kleinstmöglichen Startwert
        return self.last_set_limit_a if self.last_set_limit_a >= 6 else 6
    def isAvailable(self): return True
    def getRetryCount(self): return 3
    def setRetryCount(self, count): pass
    def isActiveChargingSession(self): return True
    def setActiveChargingSession(self, status): pass
    def is_locked(self): return False
    def set_locked(self, status): pass