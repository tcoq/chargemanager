import logging
import socket
import time
import chargemanagercommon
from wallbox.base import WallboxBase
from pymodbus.client import ModbusTcpClient

# Suppress pymodbus internal logging noise
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)

class Kebap30Controller(WallboxBase):
    """
    Controller for KEBA P30 wallboxes using a hybrid Modbus/UDP approach.
    Modbus (TCP 502) is used for reading precise telemetry data.
    UDP (7090) is used for control commands (start/stop/current) due to lower latency.
    """
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
        self.available = 0 
        self._last_is_charging = False
        self.last_data = self._get_empty_data()
        self.readSettings()

    def readSettings(self):
        if chargemanagercommon.KEBAP30_SETTINGS_DIRTY:
            self.ip_address = chargemanagercommon.getSetting(chargemanagercommon.KEBAP30IP)
            self.max_phases = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES))
            chargemanagercommon.KEBAP30_SETTINGS_DIRTY = False
        
        # Fallback to test IP if settings are empty
        if not self.ip_address or self.ip_address == "0.0.0.0":
            self.ip_address = "192.168.178.153"

    def readData(self):
        """
        Fetches telemetry from the wallbox. 
        NOTE: Modbus registers may be locked/empty if the user has not 
        authenticated via RFID or if the vehicle is not yet handshake-ready.
        """
        self.readSettings()
        client = ModbusTcpClient(self.ip_address, port=502, timeout=3)
        
        real_power = 0
        keba_state = 0
        temperature = 0

        try:
            if client.connect():
                # Device is reachable via network
                self.available = 1
                self.last_data["isconnected"] = 1
                
                # Fetch Charge State (Register 1001)
                # We use individual try blocks because certain firmware versions 
                # or lack of RFID auth can cause register read errors.
                try:
                    res_s = client.read_holding_registers(1001, count=1, slave=self.UNIT_ID)
                    if res_s and not res_s.isError():
                        keba_state = res_s.registers[0]
                except Exception:
                    log.debug("KEBA: Status register 1001 inaccessible (possibly locked by RFID)")

                # Fetch Active Power (Register 1020, 32-bit value in mW)
                try:
                    res_p = client.read_holding_registers(1020, count=2, slave=self.UNIT_ID)
                    if res_p and not res_p.isError():
                        # High-word and low-word bit shifting for 32-bit value
                        power_mw = (res_p.registers[0] << 16) | res_p.registers[1]
                        real_power = int(power_mw / 1000) # Convert mW to W
                except Exception:
                    log.debug("KEBA: Power register 1020 inaccessible")

                # Fetch Internal Temperature (Register 1046)
                try:
                    res_t = client.read_holding_registers(1046, count=1, slave=self.UNIT_ID)
                    if res_t and not res_t.isError():
                        temperature = int(res_t.registers[0] / 10) # 0.1°C resolution
                except Exception:
                    pass

                # PLAUSIBILITY CHECK:
                # If active power exceeds 100W, we force 'ischarging' to True.
                # This bypasses laggy status register updates or RFID-locked status bits.
                if real_power > 100:
                    self._last_is_charging = True
                else:
                    self._last_is_charging = (keba_state == 3)

                self.last_data.update({
                    "chargingpower": max(0, real_power),
                    "phases": self.max_phases if real_power > 1000 else 1,
                    "ischarging": 1 if self._last_is_charging else 0,
                    "chargingcurrent": int(self.last_set_limit_a),
                    "temperature": temperature,
                    "errorcode": 0
                })
            else:
                self._handle_offline()

        except Exception as e:
            log.debug(f"KEBA Connection Error: {e}")
            self._handle_offline()
        finally:
            client.close()
            
        return self.last_data

    def _handle_offline(self):
        """Reset internal state when connection is lost."""
        self.available = 0
        self.last_data.update({
            "isconnected": 0, "ischarging": 0, "chargingpower": 0
        })

    def setCharging(self, currentValue, startCharging):
        """
        Sends control commands via UDP (Port 7090).
        UDP is generally faster and often accepted even if Modbus is currently locked.
        """
        if not self.isAvailable():
            return {"errorcode": 1}

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        try:
            target_a = int(round(float(currentValue)))
            target_a = max(6, min(32, target_a))

            if startCharging:
                # 'ena 1' enables the charging output, 'curr' sets Amps (mA format)
                sock.sendto(b"ena 1", (self.ip_address, self.UDP_PORT))
                time.sleep(0.1)
                sock.sendto(f"curr {target_a * 1000}".encode(), (self.ip_address, self.UDP_PORT))
                self.last_set_limit_a = target_a
                log.info(f"KEBA ID 3: Start Command ({target_a}A) sent via UDP.")
            else:
                # Ramping down current before disabling output
                sock.sendto(b"curr 0", (self.ip_address, self.UDP_PORT))
                time.sleep(0.1)
                sock.sendto(b"ena 0", (self.ip_address, self.UDP_PORT))
                self.last_set_limit_a = 0
                log.info("KEBA ID 3: Stop Command sent via UDP.")
            
            return {"errorcode": 0}
        except Exception as e:
            log.error(f"KEBA UDP Command failed: {e}")
            return {"errorcode": 2}
        finally:
            sock.close()

    def _get_empty_data(self):
        return {
            "chargingpower": 0, "phases": 1, "errorcode": 0, 
            "isconnected": 0, "ischarging": 0, "chargingcurrent": 0, "temperature": 0
        }

    # Framework Interface Methods
    def getID(self): return self.ID
    def isCharging(self): return self._last_is_charging
    def getChargingLevel(self): return self.last_set_limit_a
    def isAvailable(self): return self.available > 0
    def getRetryCount(self): return self.retryCount
    def setRetryCount(self, count): self.retryCount = count
    def isActiveChargingSession(self): return self.activeChargingSession
    def setActiveChargingSession(self, status: bool): self.activeChargingSession = status
    def is_locked(self): return self.locked
    def set_locked(self, status: bool): self.locked = status