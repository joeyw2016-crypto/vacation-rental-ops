#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_sync_back.py - Branch tests for sync_back (sandbox copies only).

Every test runs against an isolated sandbox copy of the project files, so the
real bookings.csv / properties.csv / tickets.csv are never touched.
"""

import csv
import os
import shutil
import subprocess
import sys
import unittest

from openpyxl import load_workbook

PROJECT = "/Users/joeyweng/Desktop/vacation_rental_ops"
SANDBOX_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "sync_back_sandbox")

SRC_FILES = ["property_store.py", "overview_sync.py", "sync_back.py"]
CSV_FILES = ["properties.csv", "bookings.csv", "tickets.csv"]
XLSX_NAME = "vacation_rental_overview.xlsx"

SHEET_P = "房源(Properties)"
SHEET_B = "预订(Bookings)"
SHEET_T = "工单(Tickets)"


def make_sandbox(tag):
    d = os.path.join(SANDBOX_ROOT, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    for name in SRC_FILES + CSV_FILES:
        shutil.copy(os.path.join(PROJECT, name), os.path.join(d, name))
    return d


def load_sandbox_modules(d):
    """Load the sandbox copies (never the project ones) of the 3 modules."""
    for name in ("property_store", "overview_sync", "sync_back"):
        sys.modules.pop(name, None)
    sys.path.insert(0, d)
    try:
        import property_store  # noqa: F401
        import overview_sync   # noqa: F401
        import sync_back       # noqa: F401
    finally:
        sys.path.pop(0)
    return sys.modules["sync_back"], sys.modules["overview_sync"]


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_row(wb_path, sheet, row):
    wb = load_workbook(wb_path)
    ws = wb[sheet]
    header = [c.value for c in ws[1]]
    ws.append([row.get(h, "") for h in header])
    wb.save(wb_path)


def set_cell(wb_path, sheet, row_idx, col_name, value):
    wb = load_workbook(wb_path)
    ws = wb[sheet]
    header = [c.value for c in ws[1]]
    col = header.index(col_name) + 1
    ws.cell(row=row_idx, column=col).value = value
    wb.save(wb_path)


def delete_row(wb_path, sheet, row_idx):
    wb = load_workbook(wb_path)
    ws = wb[sheet]
    ws.delete_rows(row_idx)
    wb.save(wb_path)


BOOKING_TEMPLATE = {
    "booking_id": "BK-0000", "property_id": "AD-101",
    "guest_name": "Guest", "chat_id": "u0",
    "check_in": "2026-11-01", "check_out": "2026-11-03",
    "status": "confirmed", "created_at": "2026-10-30 10:00:00",
}


class SyncBackTest(unittest.TestCase):

    def _prepare(self, tag):
        d = make_sandbox(tag)
        sb, os_mod = load_sandbox_modules(d)
        os_mod.sync_overview()  # create the initial xlsx inside the sandbox
        xlsx = os.path.join(d, XLSX_NAME)
        return d, sb, xlsx

    # -- branch 1: empty bookings -------------------------------------------
    def test_empty_bookings_keeps_available_equal_total(self):
        d, sb, xlsx = self._prepare("t_empty")
        report = sb.back_sync(excel_path=xlsx)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["bookings_written"], 0)
        self.assertEqual(report["properties_written"], 13)
        props = read_csv(os.path.join(d, "properties.csv"))
        self.assertEqual(len(props), 13)
        for p in props:
            self.assertEqual(int(p["available_units"]), int(p["total_units"]),
                             f"{p['property_id']} available != total")
        self.assertEqual(read_csv(os.path.join(d, "bookings.csv")), [])

    # -- branch 2: add confirmed booking -> inventory -1 --------------------
    def test_add_confirmed_booking_decreases_inventory(self):
        d, sb, xlsx = self._prepare("t_add_booking")
        row = dict(BOOKING_TEMPLATE, booking_id="BK-9001", property_id="AD-101")
        append_row(xlsx, SHEET_B, row)
        report = sb.back_sync(excel_path=xlsx)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["inventory"]["AD-101"],
                         {"total": 1, "available": 0})
        bookings = read_csv(os.path.join(d, "bookings.csv"))
        self.assertEqual(len(bookings), 1)
        self.assertEqual(bookings[0]["booking_id"], "BK-9001")
        self.assertEqual(bookings[0]["property_id"], "AD-101")

    # -- branch 3: delete booking -> inventory +1 ---------------------------
    def test_delete_booking_increases_inventory(self):
        d, sb, xlsx = self._prepare("t_del_booking")
        for bid in ("BK-9101", "BK-9102"):
            append_row(xlsx, SHEET_B,
                       dict(BOOKING_TEMPLATE, booking_id=bid,
                            property_id="AD-301"))
        r1 = sb.back_sync(excel_path=xlsx)
        self.assertEqual(r1["inventory"]["AD-301"],
                         {"total": 2, "available": 0})
        delete_row(xlsx, SHEET_B, 3)  # remove the 2nd booking row
        r2 = sb.back_sync(excel_path=xlsx)
        self.assertEqual(r2["inventory"]["AD-301"],
                         {"total": 2, "available": 1})
        self.assertEqual(len(read_csv(os.path.join(d, "bookings.csv"))), 1)

    # -- branch 4: confirmed -> cancelled backfills unit --------------------
    def test_status_cancelled_backfills_unit(self):
        d, sb, xlsx = self._prepare("t_cancel")
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="BK-9002",
                        property_id="AD-101"))
        r1 = sb.back_sync(excel_path=xlsx)
        self.assertEqual(r1["inventory"]["AD-101"]["available"], 0)
        set_cell(xlsx, SHEET_B, 2, "status", "cancelled")
        r2 = sb.back_sync(excel_path=xlsx)
        self.assertEqual(r2["inventory"]["AD-101"]["available"], 1)
        self.assertEqual(read_csv(os.path.join(d, "bookings.csv"))[0]["status"],
                         "cancelled")

    # -- branch 5: property add / delete / edit price / edit status ---------
    def test_property_add_edit_delete(self):
        d, sb, xlsx = self._prepare("t_property")
        # edit existing: price + status
        set_cell(xlsx, SHEET_P, 2, "price_per_night", 1500)
        set_cell(xlsx, SHEET_P, 2, "status", "maintenance")
        # add a new property (no bookings -> available == total)
        wb = load_workbook(xlsx)
        ws = wb[SHEET_P]
        header = [c.value for c in ws[1]]
        ws.append([{h: v for h, v in zip(header, [
            "AD-999", "Test House 测试房", "1 Test Rd", 999, 1, 2,
            "WiFi;Parking", 3, 3, "available",
        ])}[h] for h in header])
        wb.save(xlsx)
        # delete AD-310 (last data row, row 14)
        delete_row(xlsx, SHEET_P, 14)
        report = sb.back_sync(excel_path=xlsx)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["properties_written"], 13)
        props = {p["property_id"]: p
                 for p in read_csv(os.path.join(d, "properties.csv"))}
        self.assertNotIn("AD-310", props)
        self.assertEqual(props["AD-101"]["price_per_night"], "1500")
        self.assertEqual(props["AD-101"]["status"], "maintenance")
        self.assertEqual(props["AD-101"]["available_units"], "1")
        self.assertIn("AD-999", props)
        self.assertEqual(props["AD-999"]["total_units"], "3")
        self.assertEqual(props["AD-999"]["available_units"], "3")
        self.assertEqual(props["AD-999"]["amenities"], "WiFi;Parking")

    # -- branch 6: invalid rows are skipped and reported --------------------
    def test_invalid_rows_skipped(self):
        d, sb, xlsx = self._prepare("t_invalid")
        # one valid + two invalid booking rows
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="BK-9201",
                        property_id="AD-101"))
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="",
                        property_id="AD-101"))  # empty booking_id
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="BK-9203",
                        property_id="AD-101", status="unknown"))
        r1 = sb.back_sync(excel_path=xlsx)
        self.assertEqual(len(r1["errors"]), 2)
        bookings = read_csv(os.path.join(d, "bookings.csv"))
        self.assertEqual([b["booking_id"] for b in bookings], ["BK-9201"])
        # one invalid property row (total_units = 0)
        wb = load_workbook(xlsx)
        ws = wb[SHEET_P]
        header = [c.value for c in ws[1]]
        ws.append([{h: v for h, v in zip(header, [
            "AD-998", "Bad House", "1 Bad Rd", 100, 1, 1, "WiFi", 0, 0,
            "available",
        ])}[h] for h in header])
        wb.save(xlsx)
        r2 = sb.back_sync(excel_path=xlsx)
        self.assertTrue(any("total_units" in e for e in r2["errors"]))
        props = {p["property_id"]: p
                 for p in read_csv(os.path.join(d, "properties.csv"))}
        self.assertNotIn("AD-998", props)

    # -- branch 7: multi-unit property, 2 confirmed -> available 0 ----------
    def test_multi_unit_two_confirmed_available_zero(self):
        d, sb, xlsx = self._prepare("t_multi")
        for bid in ("BK-9301", "BK-9302"):
            append_row(xlsx, SHEET_B,
                       dict(BOOKING_TEMPLATE, booking_id=bid,
                            property_id="AD-301"))
        report = sb.back_sync(excel_path=xlsx)
        self.assertEqual(report["inventory"]["AD-301"],
                         {"total": 2, "available": 0})

    # -- branch 8: rebuilt workbook reflects edits --------------------------
    def test_rebuild_consistency(self):
        d, sb, xlsx = self._prepare("t_rebuild")
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="BK-9401",
                        property_id="AD-101"))
        sb.back_sync(excel_path=xlsx)
        wb = load_workbook(xlsx)
        b_header = [c.value for c in wb[SHEET_B][1]]
        rows = list(wb[SHEET_B].iter_rows(values_only=True))
        self.assertTrue(any(r[b_header.index("booking_id")] == "BK-9401"
                            for r in rows[1:]))
        p_header = [c.value for c in wb[SHEET_P][1]]
        avail_col = p_header.index("available_units") + 1
        for r in wb[SHEET_P].iter_rows(min_row=2, values_only=True):
            if r[0] == "AD-101":
                self.assertEqual(str(r[avail_col - 1]), "0")

    # -- branch 9: CLI output -------------------------------------------------
    def test_cli_output(self):
        d, sb, xlsx = self._prepare("t_cli")
        append_row(xlsx, SHEET_B,
                   dict(BOOKING_TEMPLATE, booking_id="BK-9501",
                        property_id="AD-101"))
        proc = subprocess.run(
            [sys.executable, "sync_back.py", "--excel", xlsx],
            cwd=d, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("写入预订 1 行", proc.stdout)
        self.assertIn("写入房源 13 行", proc.stdout)
        self.assertIn("总览已重建", proc.stdout)
        self.assertIn("inventory AD-101: total=1 available=0", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
