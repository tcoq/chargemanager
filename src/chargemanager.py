#!/usr/bin/python3
# --------------------------------------------------------------------------- #
# Chargemanager is responsible for calculating the right charge strategy based
# on PV values
# --------------------------------------------------------------------------- #
import os
import time
import traceback
import logging
from datetime import datetime

import chargemanagercommon

log = logging.getLogger(__name__)

# IMPORTANT: if you want to change this interval please recalculate checkCloudyConditions!
READ_INTERVAL_SEC  = 10
POWER_STABLE_SEC   = 300   # min. time before a new power level takes effect

# runtime state
availablePowerRange = 0
powerChangeCount    = 10000  # init with high number to enable charging directly after startup
batteryProtCounter  = 0
batteryProtActive   = False
cloudyCounter       = 0
cloudyModeActive    = False
canSwitchToTracked  = True   # one-time flag per charging session: SLOW → TRACKED


def readSettings():
    global HOUSE_BAT_SOC_START, BATTERY_MAX_CONSUMPTION, STD_DEV_THRESHOLD, CHARGEMODE_AUTO
    if not chargemanagercommon.CHARGEMANAGER_SETTINGS_DIRTY:
        return
    HOUSE_BAT_SOC_START     = int(chargemanagercommon.getSetting(chargemanagercommon.BATTERYSTARTSOC))
    BATTERY_MAX_CONSUMPTION = int(chargemanagercommon.getSetting(chargemanagercommon.BATTERYMAXCONSUMPTION))
    # calculate threshold depending on peak performance of total solar-power,
    # tested on 9400 watt system with std_dev_threshold of 585, which results in divisor of 16
    STD_DEV_THRESHOLD       = int(chargemanagercommon.getSetting(chargemanagercommon.PVPEAKPOWER)) / 16
    CHARGEMODE_AUTO         = int(chargemanagercommon.getSetting(chargemanagercommon.CHARGEMODEAUTO))
    chargemanagercommon.CHARGEMANAGER_SETTINGS_DIRTY = False


#
# Checks the standard deviation of solar production over the last 15 minutes
# returns: True = cloudy
#
def _isCloudyCondition():
    global cloudyCounter, cloudyModeActive

    con = chargemanagercommon.getDBConnection()
    stdDev = 0
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT pvprod FROM modbus
            WHERE timestamp BETWEEN datetime('now','-15 minute','localtime')
                              AND datetime('now','localtime')
            ORDER BY timestamp ASC
        """)
        rows = cur.fetchall()
        cur.close()

        if len(rows) <= 1:
            return cloudyModeActive

        values = [r[0] for r in rows]
        # calculate trend: if trend[0] is negative it is a negative trend, otherwise positive
        trend = [b - a for a, b in zip(values, values[1:])]

        # we only want stddev calcs at negative trends
        if trend[0] <= 0:
            cur = con.cursor()
            con.create_aggregate("stdev", 1, chargemanagercommon.StdevFunc)
            cur.execute("""
                SELECT stdev(pvprod) FROM modbus
                WHERE timestamp BETWEEN datetime('now','-15 minute','localtime')
                                  AND datetime('now','localtime')
                  AND pvprod > 10
            """)
            result = cur.fetchone()[0]
            cur.close()
            if result is not None:
                stdDev = int(result)
    except Exception:
        log.error(traceback.format_exc())
    finally:
        con.close()

    # increase faster than decrease to avoid flickering
    if stdDev > STD_DEV_THRESHOLD:
        cloudyCounter = min(cloudyCounter + 2, 70)
    else:
        cloudyCounter = max(cloudyCounter - 1, 0)

    if cloudyCounter > 30:
        if not cloudyModeActive:
            cloudyModeActive = True
            cloudyCounter    = 70
    else:
        cloudyModeActive = False

    log.debug(f"Stdev: {stdDev}, cloudy: {cloudyModeActive}, counter: {cloudyCounter}")
    return cloudyModeActive


#
# Returns throttled power range under cloudy conditions to avoid too-low charging values
# returns: (throttled power range, badTrackingCondition)
#
def _applyCloudyThrottle(powerRange, minCharge):
    if powerRange > minCharge + 2500:
        return chargemanagercommon.getPowerRange(minCharge + 2000), False
    if powerRange > minCharge + 1500:
        return chargemanagercommon.getPowerRange(minCharge + 1000), True
    if powerRange > minCharge + 1000:
        return chargemanagercommon.getPowerRange(minCharge + 700),  True
    return minCharge, True


#
# Battery protection: stop charging if battery consumption is very high
# attention: currentBatteryPower has - sign during consumption and + sign during loading
#
def _updateBatteryProtection(currentBatteryPower, chargingPossible, minCharge):
    global batteryProtCounter, batteryProtActive, powerChangeCount

    if currentBatteryPower < (BATTERY_MAX_CONSUMPTION * -1) and chargingPossible:
        batteryProtCounter = min(batteryProtCounter + 5, 120)
    else:
        # decrease slower than increase
        batteryProtCounter = max(batteryProtCounter - 1, 0)

    # activation after 2 min (120sec / 10sec_interval * 5 = 60 counts),
    # deactivation after min. 10 min when battery consumption is back to normal (60 * 10sec = 600sec)
    if batteryProtCounter > 60:
        if not batteryProtActive:
            batteryProtCounter = 120
            batteryProtActive  = True

        # break waiting for stable power to force immediate recalculation
        powerChangeCount = 10000

        # stop charging only if sun is really gone and mode is not already FAST or SLOW
        currentMode = chargemanagercommon.getChargemode()
        if (not chargingPossible
                and currentMode not in (chargemanagercommon.FAST_MODE, chargemanagercommon.SLOW_MODE)):
            log.info(f"Battery protection activated, switch to slow mode! counter={batteryProtCounter}, batPower={currentBatteryPower}")
            chargemanagercommon.setChargemode(chargemanagercommon.SLOW_MODE)
    else:
        batteryProtActive = False


#
# Reads averaged power and battery values from the last 8 minutes (two 4-minute windows)
# returns: (newPowerRange, previousPowerRange, soc, batteryPower)
#
def _readPowerData():
    con = chargemanagercommon.getDBConnection()
    newRange  = 0
    prevRange = 0
    soc       = 0
    batPower  = 0
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT avg(availablepower_withoutcharging), max(soc), min(batterypower)
            FROM modbus
            WHERE timestamp BETWEEN datetime('now','-4 minute','localtime')
                              AND datetime('now','localtime')
            UNION ALL
            SELECT avg(availablepower_withoutcharging), max(soc), min(batterypower)
            FROM modbus
            WHERE timestamp BETWEEN datetime('now','-8 minute','localtime')
                              AND datetime('now','-4 minute','localtime')
        """)
        rows = cur.fetchall()
        cur.close()

        # first row = newer data (0-4 min), second row = older data (4-8 min)
        if len(rows) >= 1 and rows[0][0] is not None:
            newRange = chargemanagercommon.getPowerRange(rows[0][0])
            soc      = rows[0][1] or 0
            batPower = rows[0][2] or 0
        if len(rows) >= 2 and rows[1][0] is not None:
            prevRange = chargemanagercommon.getPowerRange(rows[1][0])

    except Exception:
        log.error(traceback.format_exc())
    finally:
        con.close()

    return newRange, prevRange, soc, batPower


#
# Calculates the efficient charging strategy
#
def calcEfficientChargingStrategy():
    global availablePowerRange, powerChangeCount, canSwitchToTracked

    newRange, prevRange, soc, batPower = _readPowerData()

    phases    = chargemanagercommon.getPhases(chargemanagercommon.getActiveWallboxId())
    minCharge = {1: 1400, 2: 2800, 3: 4500}.get(phases, 1400)

    # check if weather is cloudy and reduce power in steps to avoid too-low charging values
    cloudy               = _isCloudyCondition()
    badTrackingCondition = False
    if cloudy and newRange >= minCharge:
        newRange, badTrackingCondition = _applyCloudyThrottle(newRange, minCharge)

    # avoid unnecessary writes
    if cloudy != chargemanagercommon.getCloudy():
        chargemanagercommon.setCloudy(cloudy)

    chargingPossible = newRange >= minCharge

    # if conditions are bad, disable one-time switch to tracked for this session
    if cloudy or badTrackingCondition:
        canSwitchToTracked = False

    _updateBatteryProtection(batPower, chargingPossible, minCharge)

    # GUARANTEE stable power for at least POWER_STABLE_SEC and avoid too much start/stop
    stableIntervals = POWER_STABLE_SEC / READ_INTERVAL_SEC
    if powerChangeCount < stableIntervals:
        if availablePowerRange != newRange:
            powerChangeCount += 1
        else:
            powerChangeCount = 0
        return

    # stable power confirmed — update strategy
    availablePowerRange = newRange
    powerChangeCount    = 0
    now                 = datetime.now()
    currentMode         = chargemanagercommon.getChargemode()

    # automatically switch from SLOW to TRACKED if CHARGEMODE_AUTO is enabled,
    # canSwitchToTracked ensures this only happens once per charging session
    # use minCharge + 400 to avoid immediately falling back to slow charging
    if (CHARGEMODE_AUTO == 1
            and canSwitchToTracked
            and chargingPossible
            and newRange >= minCharge + 400
            and int(soc) > HOUSE_BAT_SOC_START
            and currentMode == chargemanagercommon.SLOW_MODE):
        chargemanagercommon.setChargemode(chargemanagercommon.TRACKED_MODE)
        canSwitchToTracked = False
        log.info(f"Auto switch to tracked mode! soc={soc}, power={newRange}")

    # in case it is cloudy, TRACKED_MODE is on and sun was available but suddenly gone:
    # switch to slow mode and charge with battery support until conditions improve
    elif (not chargingPossible
            and 8 < now.hour < 16
            and currentMode == chargemanagercommon.TRACKED_MODE):
        chargemanagercommon.setChargemode(chargemanagercommon.SLOW_MODE)
        canSwitchToTracked = True  # allow switching back to tracked when conditions improve
        log.info(f"Auto switch from tracked to slow mode! hour={now.hour}")

    # write available power to DB
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute(
            "UPDATE controls SET availablePowerRange=?, chargingPossible=?",
            (availablePowerRange, int(chargingPossible))
        )
        con.commit()
        cur.close()
    except Exception:
        log.error(traceback.format_exc())
    finally:
        con.close()

    log.debug(f"Power={newRange}, prev={prevRange}, possible={chargingPossible}, "
              f"phases={phases}, cloudy={cloudy}, minCharge={minCharge}, soc={soc}")


#
# Delete data older than 72h
#
def cleanupData():
    con = chargemanagercommon.getDBConnection()
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM chargelog WHERE timestamp < datetime('now','-72 hour','localtime')")
        con.commit()
        cur.execute("VACUUM")
        con.commit()
        cur.close()
    except Exception:
        log.error(traceback.format_exc())
    finally:
        con.close()


#
# Main, init and repeat reading
#
def main():
    global canSwitchToTracked
    os.environ['TZ'] = 'Europe/Berlin'
    time.tzset()
    log.info(f"Module {__name__} started.")
    last_cleanup_day = None

    try:
        while True:
            readSettings()
            time.sleep(READ_INTERVAL_SEC)
            log.debug(f"sleeped {READ_INTERVAL_SEC} seconds")

            try:
                if (chargemanagercommon.isAnyWallboxConnected() == 1
                        and chargemanagercommon.getChargemode() != chargemanagercommon.DISABLED_MODE):
                    calcEfficientChargingStrategy()
                else:
                    # reset flag if charging stopped so next session can switch to tracked again
                    canSwitchToTracked = True

                now = datetime.now()
                # clean data at 00:00:<19
                if now.hour == 0 and last_cleanup_day != now.day:
                    start = time.perf_counter()
                    cleanupData()
                    last_cleanup_day = now.day
                    duration = time.perf_counter() - start
                    log.info(f"cleanupData duration: {duration:.3f}s")

            except Exception:
                log.error(traceback.format_exc())

    except KeyboardInterrupt:
        pass