import logging
import socket
import time
import chargemanagercommon
from wallbox.base import WallboxBase
from pymodbus.client import ModbusTcpClient

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
        self._last_is_charging = True
        self.last_data = self._get_empty_data()
        self.low_power_count = 0
        self.last_valid_power = 0
        self._charging_requested = False
        self._session_active = False
        self.readSettings()

    def readSettings(self):
        if chargemanagercommon.KEBAP30_SETTINGS_DIRTY:
            self.ip_address = chargemanagercommon.getSetting(chargemanagercommon.KEBAP30IP)
            self.max_phases = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGINGPHASES))
            chargemanagercommon.KEBAP30_SETTINGS_DIRTY = False

        if not self.ip_address or self.ip_address == "0.0.0.0":
            self.ip_address = "192.168.178.153"

    def _smooth_power(self, new_raw_watt):
        alpha = 0.3

        diff = abs(new_raw_watt - self.last_valid_power)

        if diff > 800:
            alpha = 0.8

        if self.last_valid_power == 0 and new_raw_watt > 0:
            return int(round(new_raw_watt / 100.0) * 100)

        smoothed = (alpha * new_raw_watt) + ((1 - alpha) * self.last_valid_power)
        return int(round(smoothed / 100.0) * 100)

    def _handle_offline(self):
        """Reset internal state when connection is lost. Cable is considered pulled."""
        self.available = 0
        self._session_active = False
        self._charging_requested = False
        self.last_data.update({
            "isconnected": 0, "ischarging": 0, "chargingpower": 0
        })

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

        try:
            if client.connect():
                self.available = 1
                self.last_data["isconnected"] = 1

                # Fetch Charge State (Register 1001).
                # Individual try blocks are used because certain firmware versions
                # or lack of RFID auth can cause register read errors.
                try:
                    res_s = client.read_holding_registers(1001, count=1, slave=self.UNIT_ID)
                    time.sleep(0.1)
                    if res_s and not res_s.isError():
                        keba_state = res_s.registers[0]
                except Exception:
                    log.debug("KEBA: Status register 1001 inaccessible (possibly locked by RFID)")

                # Fetch Active Power (Register 1020, 32-bit value in mW).
                try:
                    res_p = client.read_holding_registers(1020, count=2, slave=self.UNIT_ID)
                    time.sleep(0.1)
                    if res_p and not res_p.isError():
                        power_mw = (res_p.registers[0] << 16) | res_p.registers[1]
                        raw_watt = int(power_mw / 1000)
                        self.last_valid_power = self._smooth_power(raw_watt)
                except Exception:
                    log.debug("KEBA: Power register 1020 inaccessible")

                real_power = self.last_valid_power

                # Plausibility check with debounce.
                # If real power is flowing we trust that over any status register.
                # This bypasses laggy status register updates or RFID-locked status bits.
                if real_power > 500:
                    self.low_power_count = 0
                    self._last_is_charging = True
                else:
                    self.low_power_count += 1
                    if self.low_power_count >= 2:
                        if keba_state == 3:
                            # Box reports active charging state
                            self._last_is_charging = True
                        elif keba_state == 2 and (self.activeChargingSession or self._charging_requested):
                            # Handshake or ramp-up phase during an active control request
                            self._last_is_charging = True
                        else:
                            # State 1 (not connected) or state 2 with no active request
                            self._last_is_charging = False
                            # Cable has been physically removed while box stayed online
                            if keba_state == 1:
                                self._session_active = False
                                self._charging_requested = False
                    else:
                        self._last_is_charging = True

                # Robust phase detection.
                # Guard against division by zero: skip calculation if no current is set.
                detected_phases = 1
                if self._last_is_charging and self.last_set_limit_a >= 6:
                    # Power / (Voltage * Amps). Using 225V as a slightly lower base
                    # makes detection more robust against under-voltage.
                    calc_phases = real_power / (225 * self.last_set_limit_a)
                    detected_phases = int(round(calc_phases))
                    detected_phases = max(1, min(self.max_phases, detected_phases))

                self.last_data.update({
                    "chargingpower": max(0, real_power),
                    "phases": int(detected_phases),
                    "ischarging": 1 if self._last_is_charging else 0,
                    "chargingcurrent": int(self.last_set_limit_a),
                    "temperature": 0,
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

    def setCharging(self, currentValue, startCharging):
        """
        Sends control commands via UDP (Port 7090).
        UDP is generally faster and often accepted even if Modbus is currently locked.

        Important: ena 0 terminates the RFID transaction on the wallbox side, so it is
        only sent when there is genuinely no active session (cable pulled or first-time
        shutdown). While a session is open and the manager only wants to pause, curr 0
        is sent instead — this throttles the current to zero without closing the
        transaction, allowing the session to resume without a new RFID tap.
        """
        if not self.isAvailable():
            return {"errorcode": 1}

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        try:
            target_a = int(round(float(currentValue)))
            target_a = max(6, min(32, target_a))

            if startCharging:
                sock.sendto(f"curr {target_a * 1000}".encode(), (self.ip_address, self.UDP_PORT))
                time.sleep(0.8)
                # ena 1 is safe to send even if a session is already open
                sock.sendto(b"ena 1", (self.ip_address, self.UDP_PORT))
                self.last_set_limit_a = target_a
                self._charging_requested = True
                self._session_active = True
                log.info(f"KEBA ID 3: Start Command ({target_a}A) sent via UDP.")

            else:
                if self._session_active:
                    # Cable is still connected: throttle to zero but keep the RFID
                    # transaction open so charging can resume without a new card tap.
                    # Do NOT send ena 0 here — it would terminate the transaction.
                    sock.sendto(b"curr 0", (self.ip_address, self.UDP_PORT))
                    # last_set_limit_a is intentionally kept at its previous value
                    # to prevent division by zero in phase detection during the pause.
                    self._charging_requested = False
                    log.info("KEBA ID 3: Pause via curr 0 (session kept open).")
                else:
                    # No active session (cable pulled or clean shutdown):
                    # ramp down current first, then disable output cleanly.
                    sock.sendto(b"curr 0", (self.ip_address, self.UDP_PORT))
                    time.sleep(0.1)
                    sock.sendto(b"ena 0", (self.ip_address, self.UDP_PORT))
                    self.last_set_limit_a = 0
                    self._charging_requested = False
                    self._session_active = False
                    log.info("KEBA ID 3: Stop Command sent via UDP (session closed).")

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

    # Framework interface methods
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