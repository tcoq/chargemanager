#!/bin/bash
echo 'Starting python scripts...'
exec python3 solaredge.py &
exec python3 nrgkick.py &
exec python3 chargemanager.py &
exec python3 frontend.py
 