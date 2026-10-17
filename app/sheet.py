"""Writes bills into the Lacombe Utilities Google Sheet.

Each tab is newest-first with Date in column A. Columns E:I hold summary
formulas in rows 2-3, so new bills are inserted by shifting only A:D down
(never whole rows), and the pinned 12-month formulas in I2/I3 are restored
afterwards so they keep pointing at rows 2-13.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import gspread

log = logging.getLogger(__name__)
EPOCH = date(1899, 12, 30)  # Google Sheets serial-date epoch
MATCH_WINDOW_DAYS = 6       # a bill within this many days of an existing row is the same bill


@dataclass
class Bill:
    bill_date: date
    amount: float
    usage: float | None = None


@dataclass
class TabSpec:
    title: str
    usage_col: int          # 0-based column index
    amount_col: int
    price_formula: str      # uses {r} for the row number
    date_pattern: str
    amount_format: dict | None = None
    price_format: dict | None = None


TABS = {
    "electricity": TabSpec(
        title="Echo Electricity.power", usage_col=1, amount_col=2,
        price_formula='=IF(B{r}="","",C{r}/B{r}*100)', date_pattern="yyyy/m/d"),
    "gas": TabSpec(
        title="Echo Gas", usage_col=1, amount_col=2,
        price_formula='=IF(B{r}="","",C{r}/B{r})', date_pattern="yyyy/mm/dd",
        amount_format={"type": "CURRENCY", "pattern": '"$"#,##0.00'}),
    "water": TabSpec(
        title="Lacombe Utilities", usage_col=2, amount_col=1,
        price_formula='=IF(C{r}="","",B{r}/C{r})', date_pattern="mm/dd/yyyy",
        amount_format={"type": "CURRENCY", "pattern": "[$$]#,##0.00"},
        price_format={"type": "CURRENCY", "pattern": "[$$]#,##0.00"}),
}


def to_serial(d: date) -> int:
    return (d - EPOCH).days


def from_serial(v) -> date | None:
    try:
        return EPOCH + timedelta(days=int(float(v)))
    except (TypeError, ValueError):
        return None


class UtilitySheet:
    def __init__(self, creds_file: str, spreadsheet_id: str, dry_run: bool = False):
        self.book = gspread.service_account(filename=creds_file).open_by_key(spreadsheet_id)
        self.dry_run = dry_run

    def sync(self, kind: str, bills: list[Bill]) -> None:
        spec = TABS[kind]
        for bill in sorted(bills, key=lambda b: b.bill_date):
            self._upsert(spec, bill)

    # --- internals -------------------------------------------------------
    def _rows(self, ws):
        return ws.get("A2:D", value_render_option="UNFORMATTED_VALUE")

    def _upsert(self, spec: TabSpec, bill: Bill) -> None:
        ws = self.book.worksheet(spec.title)
        rows = self._rows(ws)

        insert_at = len(rows) + 2
        for i, row in enumerate(rows):
            r = i + 2
            d = from_serial(row[0]) if row else None
            if d is None:
                continue
            if abs((d - bill.bill_date).days) <= MATCH_WINDOW_DAYS:
                self._fill_missing_usage(ws, spec, r, row, bill)
                return
            if d < bill.bill_date and insert_at > r:
                insert_at = r
                break

        log.info("%s: adding %s  $%.2f  usage=%s at row %d",
                 spec.title, bill.bill_date, bill.amount, bill.usage, insert_at)
        if not self.dry_run:
            self._insert(ws, spec, insert_at, bill)

    def _fill_missing_usage(self, ws, spec, r, row, bill):
        current = row[spec.usage_col] if len(row) > spec.usage_col else ""
        if current not in ("", None) or bill.usage is None:
            return
        log.info("%s: filling usage %s for row %d", spec.title, bill.usage, r)
        if not self.dry_run:
            ws.update_cell(r, spec.usage_col + 1, bill.usage)
            ws.update_cell(r, 4, spec.price_formula.format(r=r))

    def _insert(self, ws, spec: TabSpec, r: int, bill: Bill) -> None:
        pinned = ws.get("I2:I3", value_render_option="FORMULA")

        cells = [{} for _ in range(4)]
        cells[0] = {"userEnteredValue": {"numberValue": to_serial(bill.bill_date)},
                    "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": spec.date_pattern}}}
        cells[spec.amount_col] = {"userEnteredValue": {"numberValue": round(bill.amount, 2)}}
        if spec.amount_format:
            cells[spec.amount_col]["userEnteredFormat"] = {"numberFormat": spec.amount_format}
        if bill.usage is not None:
            cells[spec.usage_col] = {"userEnteredValue": {"numberValue": bill.usage}}
        cells[3] = {"userEnteredValue": {"formulaValue": spec.price_formula.format(r=r)},
                    "userEnteredFormat": {"numberFormat": spec.price_format
                                          or {"type": "NUMBER", "pattern": "0.00"}}}

        rng = {"sheetId": ws.id, "startRowIndex": r - 1, "endRowIndex": r,
               "startColumnIndex": 0, "endColumnIndex": 4}
        requests = [
            {"insertRange": {"range": rng, "shiftDimension": "ROWS"}},
            {"updateCells": {"start": {"sheetId": ws.id, "rowIndex": r - 1, "columnIndex": 0},
                             "rows": [{"values": cells}],
                             "fields": "userEnteredValue,userEnteredFormat.numberFormat"}},
        ]
        if pinned:
            requests.append({"updateCells": {
                "start": {"sheetId": ws.id, "rowIndex": 1, "columnIndex": 8},
                "rows": [{"values": [{"userEnteredValue": {"formulaValue": str(v[0])}}]}
                         for v in pinned if v],
                "fields": "userEnteredValue"}})
        self.book.batch_update({"requests": requests})
