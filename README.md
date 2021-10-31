# CHARGEMANAGER PROJECT 
## Introduction
Welcome to the chargemanager project, which implements a charging manager via software that controls an NRGKICK charger to make optimal use of the charging power according to the available excess production of a Solaredge solar system without drawing energy from the grid.

The advantages of this charging manager are as follows:

* Web interface with controls for 3 different charging strategies
* Automatic shutdown when the vehicle is fully charged
* Display of the current charging curve in a graphic
* Tabular display of the Solaredge data in near-realtime
* Possibility to distinguish between 2 or 3 phase charging
* All values of the Solaredge inverters and the NRGKICK are stored in a SQLLite database and are available there for other evaluations.
