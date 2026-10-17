"""City of Lacombe online services (Vadim / DotNetNuke): water, sewer, garbage.

The Utility Billing page loads its data from a JSON web service. Opening the
Transactions tab triggers UbGetTransactions, which lists every bill line
(TranSrcCode "BIL") and payment ("APP"). A month's bill is the sum of its BIL
lines, dated the last day of the month, which is what the sheet records.

Usage (m3) isn't listed directly. The wastewater treatment charge is billed per
cubic metre, so usage = that charge / SEWER_RATE ($3.00 in 2026, which matches
every month already in the sheet). If the city changes the rate, set SEWER_RATE.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import Page

from portal import NAV_SEL, Portal
from sheet import Bill

log = logging.getLogger(__name__)
TZ = ZoneInfo("America/Edmonton")


def _vadim_date(value: str):
    ms = int(re.search(r"-?\d+", value).group())
    return datetime.fromtimestamp(ms / 1000, TZ).date()


class LacombePortal(Portal):
    name = "lacombe"
    env_prefix = "LACOMBE"
    login_url = "https://onlineservices.lacombe.ca/login.aspx"
    # Standard DotNetNuke login control IDs (confirmed working).
    user_sel = "input[id$='txtUsername']"
    pass_sel = "input[id$='txtPassword']"
    submit_sel = "a[id$='cmdLogin'], input[id$='cmdLogin']"
    billing_url = "https://onlineservices.lacombe.ca/OnlineServices/UtilityBilling.aspx"
    start_urls = (
        "https://onlineservices.lacombe.ca/vadimopen/LinkClick.aspx?link=86&tabid=55&portalid=0&mid=421",
        billing_url,
    )

    def read_bills(self, page: Page) -> dict:
        rate = float(os.getenv("SEWER_RATE", "3.00"))
        page.goto(self.billing_url, wait_until="domcontentloaded", timeout=60_000)
        self._settle(page)

        tab = page.locator(NAV_SEL).filter(has_text=re.compile(r"^\s*Transactions\s*$"))
        with page.expect_response(lambda r: "UbGetTransactions" in r.url, timeout=45_000) as resp:
            for i in range(tab.count()):
                if tab.nth(i).is_visible():
                    tab.nth(i).click()
                    break
            else:
                raise RuntimeError("lacombe: Transactions tab not found on Utility Billing page")
        lines = json.loads(resp.value.text())["d"]
        bills = parse_transactions(lines, rate)
        log.info("lacombe: %d water bills from %d transaction lines", len(bills), len(lines))
        return {"water": bills}


def parse_transactions(lines: list[dict], rate: float) -> list[Bill]:
    months = defaultdict(lambda: {"amount": 0.0, "sewer": None})
    for t in lines:
        if t.get("TranSrcCode") != "BIL":
            continue
        m = months[_vadim_date(t["TranDate"])]
        m["amount"] += float(t["Amt"])
        if t.get("SrvcTypeCode") == "SEW" and "treatment" in t.get("Descr", "").lower():
            m["sewer"] = (m["sewer"] or 0) + float(t["Amt"])

    bills = []
    for d, m in sorted(months.items()):
        usage = round(m["sewer"] / rate, 2) if m["sewer"] is not None else None
        bills.append(Bill(d, round(m["amount"], 2), usage))
    return bills
