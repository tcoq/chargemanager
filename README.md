# CHARGEMANAGER PROJECT 
## Introduction
Welcome to the chargemanager project, which implements a electric car charging manager via software that controls a NRGKICK charger to make optimal use of the charging power according to the available excess production of a Solaredge solar system without drawing energy from the grid.

The advantages of this charging manager are as follows:

* Free photovoltaics-power tracked charging considering house consumption
* Web interface with controls for 3 different charging strategies (slow, fast and tracked)
* Automatic stop when the vehicle is fully charged
* Automatic cloud detection (if weather is cloudy, charge-power is reduced in tracked mode to avoid receiving power from grid)
* Near realtime charging chart
* Near realtime Solaredge inverter data
* Possibility to choose between 1, 2 or 3 phase charging
* Auto detection for disabling phases via fuses
* All values of the Solaredge inverter and the NRGKICK are stored in a SQLite database and are available for other evaluations

![picture alt](https://github.com/tcoq/chargemanager/blob/main/chargemanager.jpg?raw=true "Screenshot")

## Requirements
The chargemanger was tested with Storedge SE10K-RWS and BYD LVS 8.0 (production year 2020) and NRGKICK + Connect (1st version, production year 2020, Connect is a extra bluetooth hardware) and VW ID.4 (2 phase charging). Other Solaredge inverters may have differences in the modbus protocol, which are not covered here. Individual modbus adjustments must be made by yourself. To use the chargemanger you only need a small linux server like raspberry or jetson nano with network access to Solaredge inverter and NRGKICK.

## Installation

The project is packaged in a configured docker container. You only need to check out the project and bulid the container like this way:

1. Clone the project git clone:
  https://github.com/tcoq/chargemanager.git

2. **IMPORTANT:** Check and edit /src/chargemanager.properties to configure your devices (IP adresses, ports, etc.) 
3. Move to the root folder of the project (where DOCKERFILE is located)
4. Create the image:
  "docker build -t chargemanagerimage ."
5. Start the container 
  "docker run --network="host" --volume /your/path/to/chargemanager/data:/data chargemanagerimage" 
(please notice that docker container need to have access to the network of the host to connect to Solaredge and NRGKICK)
6. If everything is ok, you should see the webinterface when you type this into your browser: http://192.xxx.xxx.xxx:5000 (if authentification is activated the secret.key is necessary like this http://192.xxx.xxx.xxx:5000?secret=YOURTOKEN)

Important: "Watch out to mount data directory correctly to make database and logs available form host (outside docker client)

Recommendation: 
Please ensure that the Docker container is automatically restarted after system boot.

## Documentation
There are three different charge strategies:

1. **Disabled / Offline**<br/>
  Charging is disabled if button is blue. If button is red and text is "Offline" NRGKICK is not available by the network.
3. **Slow**<br/>
  The car is charged immediately with low charge power, if chargemode.auto set to 1 (see properties) mode is switched automatically to tracked if pv production is high and battery is charged enought  (1380 watt 1 phase, 2760 watt 2 phases or 4140 watt 3 phases) until car is full. (this strategy ignores Solar production) 
5. **Fast**<br/>
  The car is charged immediately with high charge power (3450 watt 1 phase, 6900 watt, 2 phases or 10350 watt 3 phases) until car is full. (this strategy ignores also Solar production) 
7. **Tracked**<br/>
  Chargemanager tries to follow the maximum free available PV power (considering the current house-consumption). Charging is started only if minimum house battery SOC threshold is reached and is done until car is full or free available power is no longer available. (you can configure thresholds in chargemanager.properties)
  
The green color of the button indicates charging is currently active:

![picture alt](https://github.com/tcoq/chargemanager/blob/main/green.jpg?raw=true "Screenshot")

The charge manager is currently optimized for 2 phase (16A) charging on private PV installation with 8,5-10 KW peak. 3 phase charging (16A) is also possible but your PV should have minimum 12KW peak, otherwise minimum charging is to high to get most out of your PV. 

## Caution 
The use of this software is at your own risk. In my environment chargemanger charges my VW ID.4 many times without any problems, but in worst cases (like other combinations of e.g. cars) bugs can occur, so please be careful and take a look into the logfiles in /data folder and webinterface.

## Security
There is token authentification feature implemented. Please set authentication.enabled=1 in properties to enable it and edit set your individual token. (e.g. http://192.xxx.xxx.xxx:5000?secret=YOURTOKEN)
