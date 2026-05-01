#!/bin/bash
echo "Starting chargeconrtoller docker..."
cd /home/steffen/my-scripts/chargemanager
docker run --network="host" --volume /home/steffen/my-scripts/chargemanager/data:/data chargemanagerimage
echo "Chargecontroller docker stopped..."
