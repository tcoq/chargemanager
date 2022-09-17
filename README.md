# CHARGEMANAGER PROJECT 
## Introduction
Welcome to the chargemanager project, which implements a electric car charging manager via software that controls a NRGKICK charger to make optimal use of the charging power according to the available excess production of a Solaredge solar system without drawing energy from the grid. If not charing this software can also activate a TP-Link smart plug to control additional devices like a e-heating rod.

The advantages of this charging manager are as follows:

* Free photovoltaics-power tracked charging considering house consumption
* No extra hardware necessary (only a small linux server in local network)
* Web interface with controls for 3 different charging strategies (slow, fast and tracked)
* Automatic stop when the vehicle is fully charged
* Automatic cloud detection (if weather is cloudy, charge-power is reduced in tracked mode to avoid receiving power from grid)
* Near realtime charging chart
* Near realtime Solaredge inverter data
* Possibility to choose between 1, 2 or 3 phase charging
* Auto detection for disabling phases via fuses
* Token authentification for public deployments with brute force protection available
* All values of the Solaredge inverter and the NRGKICK are stored in a SQLite database and are available for other evaluations
* **NEW!**: TP-Link smart plug support (HS110 / HS100) 
* **NEW!**: Settings web form 

![picture alt](https://github.com/tcoq/chargemanager/blob/main/chargemanager.jpg?raw=true "Main screen")

![picture alt](https://github.com/tcoq/chargemanager/blob/main/settings.jpg?raw=true "Seccings screen")

## Requirements
The chargemanger was tested with Storedge SE10K-RWS and BYD LVS 8.0 (production year 2020) and NRGKICK + Connect (1st version, production year 2020, Connect is a extra bluetooth hardware) and VW ID.4 (2 phase charging). Other Solaredge inverters may have differences in the modbus protocol, which are not covered here. Individual modbus adjustments must be made by yourself. To use the chargemanger you only need a small linux server like raspberry or jetson nano with network access to Solaredge inverter and NRGKICK.

## Installation

The project is packaged in a configured docker container. You only need to check out the project and bulid the container like this way:

1. Clone the project git clone:
  https://github.com/tcoq/chargemanager.git

2. Move to the root folder of the project (where DOCKERFILE is located)
3. Create the image:
  "docker build -t chargemanagerimage ."
4. Start the container 
  "docker run --network="host" --volume /your/path/to/chargemanager/data:/data chargemanagerimage" 
(please notice that docker container need to have access to the network of the host to connect to Solaredge and NRGKICK)
5. If everything is ok, you should see the webinterface when you type this into your browser: http://192.xxx.xxx.xxx:5000 (if authentification is activated the secret.key is necessary like this http://192.xxx.xxx.xxx:5000?secret=YOURTOKEN)

Important: "Watch out to mount data directory correctly to make database and logs available form host (outside docker client)

Recommendation: 
Please ensure that the Docker container is automatically restarted after system boot.

## Settings

Please go after you run the application to and edit the default values to your environment:

http://192.xxx.xxx.xxx:5000/settings

###### **PV TRACKING / Auto on [0|1]**
If set to 1 (default) chargestratgy is automatically switched from "SLOW" to "TRACKED" if battery is charged enought and if it is not cloudy, 0 means disabled.
###### **PV TRACKING / On at SOC [%]**
Min SOC of house-battery when swtiching to "TRACKED".
###### **HOUSE BATTERY / PV TRACKING / Max consumption [W]**
Max allowed battery consumption during charing for compensation of short-term load peaks default is 2600 (best practice) Your can set it lower, but be careful to increase it to avoid charging from your house battery to much. 
###### **HOUSE BATTERY / PV TRACKING / Max charging [W]**
Max power input into the battery (depending on individual battery-hardware) 4950 is default for BYD LVS 8.0. If PV reaches more available power than battery can consume beyond this value, charging will start to avoid to feed free-energy into grid.
###### **CAR / Max phases [n]**
Number of phases which your car max allows to load or are max available, for calculating the right charge power (e.g. most small battery VW only allow 2 phases) 
If your NRGKICK has deactived phases (e.g. 1 of 3) the lower value will be used instead.
###### **TP-LINK SMART PLUG / IP**
IP of HS100 or HS110 smart plug.	
###### **TP-LINK SMART PLUG / Enabled [0|1]**	
Turn it on (1) or deactivate (0).
###### **TP-LINK SMART PLUG / Allow battery [0|1]**	
Turn it on (1) if you want to allow house battery support if pv power is shortly gone in cloudy conditions. Battery power is only used if SOC > 94% and 55% of given "On at [W]" free pv power is left.
###### **TP-LINK SMART PLUG / On at [W]**	
Available "free" PV power threshold on which smart plug should switch on [Watt]
###### **TP-LINK SMART PLUG / On at SOC [%]**	
Min SOC of house-battery when swtiching smart plug on. 
###### **TP-LINK SMART PLUG / 1st on [hh:mm]**
First interval where plug should turned on. (set start and end to the same value if you want to disable)
###### **TP-LINK SMART PLUG / 2nd on [hh:mm]**
Second interval where plug should turned on. (set start and end to the same value if you want to disable)
###### **TP-LINK SMART PLUG / Start hour [h]**
Earliest full hour from which smart plug should be turned on. (24h format, e.g. 13,14 or 15)

###### **SOLAREDGE / IP**	
Ip address of solaredge inverter.
###### **SOLAREDGE / Modbus port [n]**	
Solaredge modbus port (modbus is by default deactivated in Solaredge inverters, use Solaredge-SetApp for activation)
###### **SOLAREDGE / PV peak power [W]**
Specifiy the peak power of your PV modules in watt e.g. 9400 (this value is necessary for some calculations like cloud-detection)

###### **NRGKICK / Measurements URL**	
Data url of nrgkick in this format http://192.168.178.xx/api/measurements/04:91:62:76:XX:XX
###### **NRGKICK / Settings URL**	
Settings url of nrgkick in this format http://192.168.178.xx/api/settings/04:91:62:76:XX:XX
###### **NRGKICK / Password**
NRGKICK password (default 0000)

###### **WEB / UI port**	
Port on which UI should start
###### **WEB / Secret**	
Key for URL authentication example http://localhost:5000?secret=VSSDCX34FVAY50
###### **WEB / Secret enabled [0|1]**
Specifiy if URL authentication is enabled or not (1=enabled, 0=disabled)

(Note: Changes in "WEB" section requires a server reboot)

## Documentation
There are three different charge strategies:

1. **Disabled / Offline**<br/>
  Charging is disabled if button is blue. If button is red and text is "Offline" NRGKICK is not available by the network.
3. **Slow**<br/>
  The car is charged immediately with low charge power, if chargemode.auto set to 1 (see settings) mode is switched automatically to tracked if pv production is high and battery is charged enought  (1380 watt 1 phase, 2760 watt 2 phases or 4140 watt 3 phases) until car is full. (this strategy ignores Solar production) 
5. **Fast**<br/>
  The car is charged immediately with high charge power (3450 watt 1 phase, 6900 watt, 2 phases or 10350 watt 3 phases) until car is full. (this strategy ignores also Solar production) 
7. **Tracked**<br/>
  Chargemanager tries to follow the maximum free available PV power (considering the current house-consumption). Charging is started only if minimum house battery SOC threshold is reached and is done until car is full or free available power is no longer available. (you can configure thresholds in settings)
  
The green color of the button indicates charging is currently active:

![picture alt](https://github.com/tcoq/chargemanager/blob/main/green.jpg?raw=true "Screenshot")

The charge manager is currently optimized for 2 phase (16A) charging on private PV installation with 8,5-10 KW peak. 3 phase charging (16A) is also possible but your PV should have minimum 12KW peak, otherwise minimum charging is to high to get most out of your PV. Please note that chargemanger always charges a little bit lower than maximum per phase in TRACKED and FAST mode to have more safety for your electric home-infrastructure. (overload, heat, etc.)

## Caution 
The use of this software is at your own risk. In my environment chargemanger charges my VW ID.4 many times without any problems, but in worst cases (like other combinations of e.g. cars) bugs can occur, so please be careful and take a look into the logfiles in /data folder and webinterface.

## Security
There is token authentification feature implemented. Please go to settings to enable it and set your individual token. (e.g. http://192.xxx.xxx.xxx:5000?secret=YOURTOKEN)
