"""City of Lacombe online services (Vadim / DotNetNuke): water, sewer, garbage.

The Utility Billing page loads its data from a JSON web service. Opening the
Transactions tab triggers UbGetTransactions, which lists every bill line
(TranSrcCode "BIL") and payment ("APP"). A month's bill is the sum of its BIL
lines, dated the last day of the month, which is what the sheet records.

Usage (m3) comes from the meter readings: on the My Account Info tab, clicking
the "Water Consumption" service row (table vdmUbServicesInfoTbl) fills table
vdmUbEnterMeterTbl with the last ~6 reads: date, reading, consumption ("17.44 CM").
Each read date is the bill date, so consumption is matched to the bill by date.

For older months not in that table, usage falls back to the wastewater treatment
charge / SEWER_RATE (billed per m3; $3.00 in 2026). When both are available and
they disagree, the log warns, which usually means the sewer rate changed.
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

        try:
            meter = self._read_meter(page)
        except Exception as e:
            log.warning("lacombe: couldn't read meter readings (%s); using sewer charge instead", e)
            meter = {}

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
        for b in bills:
            m3 = meter.get(b.bill_date)
            if m3 is None:
                continue
            if b.usage is not None and abs(b.usage - m3) > 0.05:
                log.warning("lacombe: %s meter says %.2f m3 but sewer charge / %.2f gives %.2f; "
                            "the sewer rate may have changed (SEWER_RATE)", b.bill_date, m3, rate, b.usage)
            b.usage = m3
        log.info("lacombe: %d water bills from %d transaction lines, %d with meter readings",
                 len(bills), len(lines), sum(b.bill_date in meter for b in bills))
        return {"water": bills}

    def _read_meter(self, page: Page) -> dict:
        """Click the Water Consumption service row and read the meter-reading table."""
        row = page.locator("#vdmUbServicesInfoTbl tbody tr").filter(has_text="Water Consumption").first
        row.wait_for(state="visible", timeout=30_000)
        row.click()
        page.locator("#vdmUbEnterMeterTbl tbody tr td").first.wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(1000)
        rows = page.eval_on_selector_all(
            "#vdmUbEnterMeterTbl tbody tr",
            "trs => trs.map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))")
        readings = parse_meter_rows(rows)
        log.info("lacombe: %d meter readings (%s)", len(readings),
                 ", ".join(f"{d:%b %d} {v} m3" for d, v in sorted(readings.items())))
        try:   # back to the services list so the tabs are in their normal state
            page.locator("text=Back To List").first.click(timeout=5000)
        except Exception:
            pass
        return readings


def parse_meter_rows(rows: list[list[str]]) -> dict:
    """Rows look like ['10/31/2026', 'N', '2098.03', '17.44 CM', '31', "'"]."""
    out = {}
    for cells in rows:
        if len(cells) < 4:
            continue
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", cells[0])
        c = re.match(r"\s*(-?[\d.]+)", cells[3])
        if m and c:
            out[datetime(int(m[3]), int(m[1]), int(m[2])).date()] = float(c[1])
    return out


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
