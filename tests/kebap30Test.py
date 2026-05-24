from pymodbus.client import ModbusTcpClient
import time

IP = "192.168.178.153"
UNIT_ID = 255 # Wir testen erst 255

print(f"--- Modbus Deep Test auf ID {UNIT_ID} ---")
client = ModbusTcpClient(IP, port=502, timeout=5)

if client.connect():
    try:
        print(f"Lese Register 1212 (i2) von Slave {UNIT_ID}...")
        # Wir fragen nach 2 Registern
        res = client.read_holding_registers(1212, count=1, slave=UNIT_ID)
        
        if res is None:
            print("Ergebnis ist None (Timeout)")
        elif res.isError():
            print(f"Modbus Fehler-Objekt erhalten: {res}")
        else:
            print(f"ERFOLG! Rohdaten: {res.registers}")
            power = (res.registers[0] << 16) | res.registers[1]
            print(f"Berechnete Leistung: {power / 1000} W")
            
    except Exception as e:
        print(f"Absturz beim Lesen: {e}")
    finally:
        client.close()
else:
    print("Verbindung fehlgeschlagen.")
print("--- TEST ENDE ---")