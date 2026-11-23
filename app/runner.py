#!/usr/bin/env python3
import os, subprocess, sys, time, signal
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    LOG_TZ=ZoneInfo(os.environ.get("RH_SYNC_TIMEZONE","Europe/Paris"))
except ZoneInfoNotFoundError:
    LOG_TZ=timezone.utc

def timestamp():
    return datetime.now(LOG_TZ).isoformat(timespec="seconds")

def say(message):
    print(f"{timestamp()} [INFO] {message}", flush=True)

INTERVAL=max(15, int(os.environ.get("SYNC_INTERVAL_SECONDS", "3600")))
STOP=False

def stop(*_):
    global STOP
    STOP=True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

say(f"RH-SYNC Docker V3.10 démarré — polling toutes les {INTERVAL}s")
while not STOP:
    started=time.time()
    p=subprocess.run([sys.executable, "/app/sync_engine.py"], text=True)
    if p.returncode == 0:
        say("Cycle RH-SYNC terminé: OK")
    elif p.returncode == 2:
        say("Cycle RH-SYNC terminé: AVEC_ERREURS (le service continue)")
    else:
        say(f"Cycle RH-SYNC terminé: ECHEC code={p.returncode} (le service continue)")
    elapsed=time.time()-started
    wait=max(1, INTERVAL-elapsed)
    end=time.time()+wait
    while not STOP and time.time()<end:
        time.sleep(min(1, end-time.time()))
say("RH-SYNC arrêté proprement.")
