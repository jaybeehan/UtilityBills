"""utility-sync: pull Echo Energy and City of Lacombe bills into Google Sheets.

MODE=capture  log in to each portal once and save pages for parser development
MODE=sync     fetch bills and add any missing ones to the sheet (repeats daily)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from echo import EchoPortal
from lacombe import LacombePortal
from sheet import UtilitySheet

DATA = Path(os.getenv("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(DATA / "utility-sync.log")])
log = logging.getLogger("utility-sync")


def portals():
    out = []
    if os.getenv("ECHO_USERNAME"):
        out.append(EchoPortal(DATA))
    if os.getenv("LACOMBE_USERNAME"):
        out.append(LacombePortal(DATA))
    if not out:
        sys.exit("No portal credentials found in .env")
    return out


def capture():
    for p in portals():
        try:
            p.capture()
        except Exception:
            log.exception("%s: capture failed", p.name)


def sync_once():
    sheet = UtilitySheet(str(DATA / "service-account.json"), os.environ["SHEET_ID"],
                         dry_run=os.getenv("DRY_RUN", "false").lower() == "true")
    for p in portals():
        try:
            for kind, bills in p.fetch_bills().items():
                log.info("%s: found %d %s bills", p.name, len(bills), kind)
                sheet.sync(kind, bills)
        except Exception:
            log.exception("%s: sync failed", p.name)


def sync_forever():
    hour = int(os.getenv("RUN_HOUR", "7"))
    while True:
        sync_once()
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        log.info("next run %s", nxt)
        time.sleep((nxt - now).total_seconds())


if __name__ == "__main__":
    mode = os.getenv("MODE", "sync")
    if mode == "capture":
        capture()
    elif mode == "once":
        sync_once()
    else:
        sync_forever()
