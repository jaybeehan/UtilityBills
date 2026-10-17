"""Echo Energy (UTILITYnet) portal: electricity and natural gas.

After login the account page has an Electricity tab and a Gas tab. Each shows a
"Monthly Invoices" table: invoice date (YYYY/MM/DD), usage (kWh or GJ), amount.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from playwright.sync_api import Page

from portal import Portal
from sheet import Bill

log = logging.getLogger(__name__)

TABS = {"electricity": "Electricity", "gas": "Gas"}

# Returns the rows of the visible table whose header mentions "Used" (kWh Used / GJ Used).
READ_TABLE_JS = """
() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  for (const t of document.querySelectorAll('table')) {
    const head = [...t.querySelectorAll('thead th')].map(th => th.innerText.trim());
    if (!head.some(h => /used/i.test(h)) || !head.some(h => /amount/i.test(h))) continue;
    if (!visible(t)) continue;
    const rows = [...t.querySelectorAll('tbody tr')].map(
      tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()));
    return {head, rows};
  }
  return null;
}
"""
DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _num(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-]", "", text or "")
    try:
        return float(cleaned)
    except ValueError:
        return None


class EchoPortal(Portal):
    name = "echo"
    env_prefix = "ECHO"
    login_url = "https://www.echoenergy.ca/myretailer/portal/index.html"
    # From the captured login page (GWT app; the button is a plain "Go" button).
    user_sel = "#userName"
    pass_sel = "#password"
    submit_sel = "button.gapps-loginButton"

    def read_bills(self, page: Page) -> dict:
        out = {}
        for kind, tab in TABS.items():
            out[kind] = self._read_tab(page, kind, tab)
        return out

    def _read_tab(self, page: Page, kind: str, tab: str) -> list[Bill]:
        try:
            page.locator("[role=tab]").filter(has_text=re.compile(rf"^\s*{tab}\s*$")).first.click(timeout=15_000)
        except Exception:
            log.warning("echo: couldn't open the %s tab", tab)
            return []
        table = None
        for _ in range(20):                  # GWT fills the table a moment after the click
            page.wait_for_timeout(1000)
            table = page.evaluate(READ_TABLE_JS)
            if table and table["rows"] and DATE_RE.search(table["rows"][0][0] if table["rows"][0] else ""):
                break
        if not table:
            log.warning("echo: no Monthly Invoices table on the %s tab", tab)
            return []

        head = [h.lower() for h in table["head"]]
        i_use = next(i for i, h in enumerate(head) if "used" in h)
        i_amt = next(i for i, h in enumerate(head) if "amount" in h)
        bills = []
        for row in table["rows"]:
            m = DATE_RE.search(" ".join(row))
            if not m or len(row) <= max(i_use, i_amt):
                continue
            usage, amount = _num(row[i_use]), _num(row[i_amt])
            if amount is None:
                continue
            d = datetime(int(m[1]), int(m[2]), int(m[3])).date()
            bills.append(Bill(d, amount, usage))
        log.info("echo: %s tab shows %d invoices (%s)", tab, len(bills), table["head"])
        return bills
