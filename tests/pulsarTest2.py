import paho.mqtt.client as mqtt

# topics auf nano anschauen
# mosquitto_sub -h localhost -t "#" -v

# Callback wenn Verbindung hergestellt wird
def on_connect(client, userdata, flags, rc):
    print("Verbunden mit Code:", rc)
    # Zwei Topics abonnieren
    client.subscribe("wallbox_96287/availability")
    client.subscribe("wallbox_96287/charging_enable/state")
    client.subscribe("wallbox_96287/cable_connected/state")
    client.subscribe("wallbox_96287/charging_power/state")
    client.subscribe("wallbox_96287/charging/state")
    client.subscribe("wallbox_96287/max_charging_current/state")
    client.subscribe("wallbox_96287/status/state")
    #client.publish("wallbox_96287/max_charging_current/set", "6")
    client.publish("wallbox_96287/charging_enable/set", "1")



# Callback wenn eine Nachricht empfangen wird
def on_message(client, userdata, msg):
    print(f"Empfangen von {msg.topic}: {msg.payload.decode()}")

# MQTT Client konfigurieren
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# Verbindung zum Broker herstellen
client.connect("xx.xx.xx.xx", 1883, 60)

# Endlosschleife starten
client.loop_forever()