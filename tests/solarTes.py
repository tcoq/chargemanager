import logging
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

# Konfiguration - Hier deine Daten eintragen
IP_ADDRESS = "192.168.178.51"
PORT = 502  # Probiere 502 oder 8502
UNIT_ID = 1 # Probiere 1 oder 126

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ModbusTest")

def run_test():
    log.info(f"Starte Test: Verbinde zu {IP_ADDRESS}:{PORT} (ID: {UNIT_ID})...")
    client = ModbusTcpClient(IP_ADDRESS, port=PORT, timeout=3)
    
    if not client.connect():
        log.error("❌ Verbindung fehlgeschlagen! Port offen? IP korrekt?")
        return

    log.info("✅ Verbindung aufgebaut. Lese Register 40004 (Modellbezeichnung)...")
    
    try:
        # 40004 ist der Start der Modellbezeichnung (C_Model)
        # Wir lesen 16 Register (32 Zeichen String)
        result = client.read_holding_registers(40004, count=16, slave=UNIT_ID)
        
        if result.isError():
            log.error(f"❌ Modbus Fehler: {result}")
        else:
            # String decodieren
            decoder = BinaryPayloadDecoder.fromRegisters(result.registers, byteorder=Endian.BIG)
            model_name = decoder.decode_string(32).decode('ascii').strip()
            log.info(f"✅ Erfolg! Gefundenes Modell: '{model_name}'")
            
    except Exception as e:
        log.error(f"💥 Crash während der Abfrage: {e}")
    finally:
        client.close()
        log.info("Verbindung geschlossen.")

if __name__ == "__main__":
    run_test()