#!/usr/bin/python3
#
import logging
import solaredge
import nrgkick
import chargemanager
import chargemanagercommon
import smartplug
import frontend
import threading
import time
import os

def main():
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()

    logging.basicConfig(format='%(asctime)s %(module)s %(levelname)s %(message)s', filename='/data/logs.log', filemode='w', level=logging.INFO)
    logging.info("Start chargemanager...")

    chargemanagercommon.init()

    solaredgeThread = threading.Thread(target=solaredge.main)
    nrgkickThread = threading.Thread(target=nrgkick.main)
    chargemanagerThread = threading.Thread(target=chargemanager.main)
    smartplugThread = threading.Thread(target=smartplug.main)
    frontendThread = threading.Thread(target=frontend.main)

    solaredgeThread.start()
    nrgkickThread.start()
    chargemanagerThread.start()
    smartplugThread.start()
    frontendThread.start()

if __name__ == '__main__':
    main()