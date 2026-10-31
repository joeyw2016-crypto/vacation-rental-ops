#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_auto_sync_hook.py - Minimal tests for the auto write-back hook.

Verifies that bot.handle_message now runs sync_back.back_sync() up front:
  1. Editing the overview xlsx then sending any message propagates the edit
     into properties.csv automatically (the hook fires).
  2. A failing back_sync never blocks the normal message flow.
  3. The manual CLI entry point (python3 sync_back.py) is still intact.

Everything runs against an isolated sandbox copy - the real bookings.csv /
properties.csv / tickets.csv / xlsx are never touched.
"""

import asyncio
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from openpyxl import load_workbook

PROJECT = "/Users/joeyweng/Desktop/vacation_rental_ops"

SRC_FILES = [
    "bot.py", "classify.py", "storage.py", "clickup_client.py",
    "llm_reply.py", "property_store.py", "overview_sync.py", "sync_back.py",
]
CSV_FILES = ["properties.csv", "bookings.csv", "tickets.csv"]
XLSX_NAME = "vacation_rental_overview.xlsx"
SHEET_P = "房源(Properties)"


def make_sandbox(tag):
    d = tempfile.mkdtemp(prefix=f"auto_hook_{tag}_")
    for name in SRC_FILES + CSV_FILES:
        shutil.copy(os.path.join(PROJECT, name), os.path.join(d, name))
    return d


def load_sandbox_bot(d):
    """Load the sandbox copy of bot (never the project one)."""
    for name in ("bot", "sync_back", "overview_sync", "property_store",
                 "classify", "storage", "clickup_client", "llm_reply"):
        sys.modules.pop(name, None)
    sys.path.insert(0, d)
    try:
        import bot  # noqa: F401
    finally:
        sys.path.pop(0)
    return sys.modules["bot"]


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def set_cell(wb_path, sheet, row_idx, col_name, value):
    wb = load_workbook(wb_path)
    ws = wb[sheet]
    header = [c.value for c in ws[1]]
    col = header.index(col_name) + 1
    ws.cell(row=row_idx, column=col).value = value
    wb.save(wb_path)


class _FakeChat:
    id = 100000000


class _FakeEff:
    id = 100000000
    chat = _FakeChat()


class _FakeUser:
    full_name = "Joe Joe"
    first_name = "Joe"
    language_code = "zh-CN"


class _FakeMsg:
    def __init__(self, text):
        self.text = text


class _FakeUpdate:
    def __init__(self, text):
        self.message = _FakeMsg(text)
        self.effective_chat = _FakeEff()
        self.effective_user = _FakeUser()


def _ctx(pending):
    class Ctx:
        pass
    c = Ctx()
    c.chat_data = {"lang": "zh"}
    if pending is not None:
        c.chat_data["pending"] = pending
    return c


def _avail_pending():
    return {
        "result": {"intent": "availability", "raw_message": "有房吗"},
        "lang": "zh",
        "original_text": "有房吗",
    }


class AutoSyncHookTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = make_sandbox(self._testMethodName)
        # Build the initial overview workbook inside the sandbox.
        _, overview_sync = self._load_pair()
        overview_sync.sync_overview()

    def _load_pair(self):
        for name in ("sync_back", "overview_sync"):
            sys.modules.pop(name, None)
        sys.path.insert(0, self.sandbox)
        try:
            import sync_back  # noqa: F401
            import overview_sync  # noqa: F401
        finally:
            sys.path.pop(0)
        return sys.modules["sync_back"], sys.modules["overview_sync"]

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def test_edit_xlsx_then_message_auto_syncs_csv(self):
        """User edits the xlsx; the next message propagates the edit to CSV."""
        bot = load_sandbox_bot(self.sandbox)
        xlsx = os.path.join(self.sandbox, XLSX_NAME)

        # Operator edits AD-101's nightly price inside the xlsx.
        set_cell(xlsx, SHEET_P, 2, "price_per_night", 9999)

        ctx = _ctx(pending=_avail_pending())
        with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
            asyncio.run(bot.handle_message(_FakeUpdate("有房吗"), ctx))

        props = read_csv(os.path.join(self.sandbox, "properties.csv"))
        row = next(p for p in props if p["property_id"] == "AD-101")
        self.assertEqual(row["price_per_night"], "9999",
                         "xlsx edit should be auto-written back to properties.csv")
        # And the message flow itself was not blocked.
        self.assertGreater(reply.call_count, 0)

    def test_hook_failure_does_not_block_message(self):
        """A failing back_sync is logged and never blocks normal handling."""
        bot = load_sandbox_bot(self.sandbox)
        original = bot.back_sync

        def boom():
            raise RuntimeError("simulated back_sync failure")

        bot.back_sync = boom
        ctx = _ctx(pending=_avail_pending())
        try:
            with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
                asyncio.run(bot.handle_message(_FakeUpdate("有房吗"), ctx))
            self.assertGreater(reply.call_count, 0,
                               "message handling must continue after hook failure")
        finally:
            bot.back_sync = original

    def test_manual_cli_still_available(self):
        """python3 sync_back.py --excel ... remains a valid manual entry."""
        xlsx = os.path.join(self.sandbox, XLSX_NAME)
        proc = subprocess.run(
            [sys.executable, os.path.join(self.sandbox, "sync_back.py"),
             "--excel", xlsx],
            capture_output=True, text=True, timeout=60,
            cwd=self.sandbox,
        )
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
