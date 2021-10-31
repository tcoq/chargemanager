# CHARGEMANAGER PROJECT 
## Introduction
Welcome to the chargemanager project, which implements a charging manager via software that controls a NRGKICK charger to make optimal use of the charging power according to the available excess production of a Solaredge solar system without drawing energy from the grid.

The advantages of this charging manager are as follows:

* Free photovoltaics-power tracked charging
* Web interface with controls for 3 different charging strategies (slow, fast and tracked)
* Automatic stop when the vehicle is fully charged
* Near realtime charging chart
* Near realtime Solaredge inverter data
* Possibility to choose between 2 or 3 phase charging (1 phase is planned later)
* All values of the Solaredge inverter and the NRGKICK are stored in a SQLLite database and are available for other evaluations

![picture alt](https://github.com/tcoq/chargemanager/blob/main/chargemanager.jpg?raw=true "Screenshot")

## Requirements
The chargemanger was tested with Storedge SE10K-RWS and BYD LVS 8.0 (production year 2020) and NRGKICK + Connect (1st version, production year 2020, Connect is a extra bluetooth hardware) and VW ID.4 (2 phase charging). Other Solaredge inverters may have differences in the modbus protocol, which are not covered here. Individual modbus adjustments must be made by yourself. To use the chargemanger you only need a small linux server like raspberry or jetson nano with network access to Solaredge inverter and NRGKICK.

## Installation

The project is packaged in a configured docker container. You only need to check out the project and bulid the container like this way:

1. Check out the project
2. **IMPORTANT:** Check and edit /src/chargemanager.properties to fit to your home environment 
3. Move to the root folder of the project (where DOCKERFILE is located)
4. Type: "docker build -t chargemanagerimage" to create the image
5. Start the container like this "docker run --network="host" --volume /your/path/to/chargemanager/data:/data chargemanagerimage" (please notice that docker container need to have access to the network of the host to connect to Solaredge and NRGKICK)
6. If everything is ok, you should see the webinterface when you type this into your browser: http://192.xxx.xxx.xxx:5000

Important: "Watch out to mount data directory correctly to make database and logs available form host (outside docker client)

Recommendation: 
Please ensure that the Docker container is restarted every 24h to counteract any memory errors. The system cron is ideal for this, for example.

## Documentation
There are three different charge strategies:

1. **Disabled / Offline**<br/>
  Charging is disabled if button is blue. If button is red and text is "Offline" NRGKICK is not available by the network.
3. **Slow**<br/>
  The car is charged immediately with low charge power until car is full and ignores PV production. (2760 watt, 2 phases or 4140 watt 3 phases)
5. **Fast**<br/>
  The car is charged immediately with high available charge power until car is full and ignores PV production. (6900 watt, 2 phases or 10350 watt 3 phases)
7. **Tracked**<br/>
  Software tries to follow the maximum free available PV power (taking into account the current house-consumption). Charging is started only if minimum house battery SOC threshold is reached and is done until car is full or free available power is no longer available. (you can configure thresholds in chargemanager.properties)
  
The green color of the button indicates charging is currently active:

![picture alt](https://github.com/tcoq/chargemanager/blob/main/green.jpg?raw=true "Screenshot")

The charge manager is currently optimized for 2 phase (16A) charging on private PV installation with 8,5-10 KW peak. 3 phase charging (16A) is also possible but your PV should have minimum 12KW peak, otherwise minimum charging is to high to get most out of your PV. 

## Caution 
The use of this software is at your own risk. It cannot be guarenteed that this project is completly bug free. In my environment chargemanger charges my VW ID.4 many times without any problems, but in worst cases (like other combinations of e.g. cars) bugs can happend and may cause damages to your existing hardware.

## Security
There is no authentification feature implemented. Please make sure that the docker container is startet in a non public environment (your own network) with active firewall.
