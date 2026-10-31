#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_number_pick_fix.py - Regression for the numbered-pick fix.

Bug: after the bot pushes the numbered available-property list, a digit reply
(1/2/3...) was not recognized; pending.result.intent stayed e.g. "booking",
so the digit fell into the generic menu (1 = Book) and the bot re-listed the
catalog forever. Only typing the property ID manually could book.

Fix: _push_available_properties re-arms context.chat_data["pending"] to an
availability state before showing the list, so ANY path that lists rooms
(Book without ID, sold out, short units, ID not in catalog, occupied) is
followed by a digit pick that routes to availability_confirm.

These tests drive the REAL handle_message / handle_menu_choice flow with
mocked classify / reply / store writes. Real CSVs are never mutated (the
auto write-back hook is stubbed; store writes are mocked; read paths only).
"""

import asyncio
import sys
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, "/Users/joeyweng/Desktop/vacation_rental_ops")
import bot

# The auto write-back hook is covered by test_auto_sync_hook.py (sandbox);
# stub it here so this suite stays read-only against real data.
bot.back_sync = lambda: None

RESULTS = []


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


def _booking_pending(prop_id=None, raw="我要订房"):
    return {
        "result": {
            "intent": "booking",
            "property_id": prop_id,
            "raw_message": raw,
            "needs_human": False,
            "priority": "low",
        },
        "original_text": raw,
        "lang": "zh",
    }


def _calls_with(reply, key):
    out = []
    for c in reply.call_args_list:
        kw = c.kwargs
        if kw.get("key") == key or (len(c.args) > 2 and c.args[2] == key):
            out.append(c)
    return out


def _record(reply):
    return [c.kwargs.get("key") or (c.args[2] if len(c.args) > 2 else None)
            for c in reply.call_args_list]


async def _full_book_then_pick_chain():
    """Booking request -> menu 1 -> no-ID fallback list -> digit 1 -> confirm."""
    ctx = _ctx(pending=None)
    fake_cls = {"intent": "booking", "property_id": None,
                "raw_message": "我要订房", "needs_human": False, "priority": "low"}
    with patch.object(bot, "classify", return_value=fake_cls), \
         patch.object(bot, "_match_property", return_value=None), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        # Round 1: booking request -> generic menu shown (pending cached)
        await bot.handle_message(_FakeUpdate("我要订房"), ctx)
        keys1 = _record(reply)
        assert "menu" in keys1, f"round 1 should show menu, got {keys1}"
        # Round 2: digit 1 -> Book branch -> no property ID -> numbered list
        reply.reset_mock()
        await bot.handle_message(_FakeUpdate("1"), ctx)
        keys2 = _record(reply)
        assert "push_available" in keys2, f"round 2 should push numbered list, got {keys2}"
        assert "availability_confirm" not in keys2, f"round 2 should NOT confirm yet, got {keys2}"
        pending = ctx.chat_data.get("pending", {})
        assert pending.get("result", {}).get("intent") == "availability", \
            f"pending must be re-armed to availability, got {pending}"
        # Round 3: digit 1 -> now routes to availability_confirm (no re-list)
        reply.reset_mock()
        await bot.handle_message(_FakeUpdate("1"), ctx)
        keys3 = _record(reply)
        assert "availability_confirm" in keys3, \
            f"round 3 should confirm room 1, got {keys3}"
        assert "push_available" not in keys3, \
            f"round 3 must NOT re-list the catalog, got {keys3}"
        assert "menu" not in keys3, f"round 3 must NOT fall into generic menu, got {keys3}"


async def _digits_pick_after_each_fallback(reason, add_result):
    """After each numbered-list fallback (sold_out/short/not-found), digit picks."""
    # The guest is in menu state with a booking intent for AD-101.
    ctx = _ctx(pending=_booking_pending(prop_id="AD-101", raw="订AD-101"))
    with patch.object(bot, "store_add_booking", return_value=add_result), \
         patch.object(bot, "sync_overview", return_value=None), \
         patch.object(bot, "_finalize", new=Mock()), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        # Round 1: digit 1 -> Book branch -> fallback list
        await bot.handle_message(_FakeUpdate("1"), ctx)
        keys1 = _record(reply)
        assert "push_available" in keys1, f"[{reason}] digit 1 should list rooms, got {keys1}"
        pending = ctx.chat_data.get("pending", {})
        assert pending.get("result", {}).get("intent") == "availability", \
            f"[{reason}] pending must be re-armed, got {pending}"
        # Round 2: digit 1 -> availability_confirm, no re-list
        reply.reset_mock()
        await bot.handle_message(_FakeUpdate("1"), ctx)
        keys2 = _record(reply)
        assert "availability_confirm" in keys2, \
            f"[{reason}] digit after list should confirm room, got {keys2}"
        assert "push_available" not in keys2, \
            f"[{reason}] must not re-list after pick, got {keys2}"


async def _availability_not_found_pick():
    """Availability query with an ID not in catalog -> list -> digit picks."""
    ctx = _ctx(pending={
        "result": {"intent": "availability", "property_id": "AD-999",
                   "raw_message": "AD-999有房吗", "needs_human": False, "priority": "low"},
        "original_text": "AD-999有房吗",
        "lang": "zh",
    })
    with patch.object(bot, "store_get_property", return_value=None), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        # Round 1: AD-999 is not in catalog -> numbered list
        await bot.handle_message(_FakeUpdate("AD-999"), ctx)
        keys1 = _record(reply)
        assert "push_available" in keys1, f"not-found should list rooms, got {keys1}"
        pending = ctx.chat_data.get("pending", {})
        assert pending.get("result", {}).get("intent") == "availability", \
            f"pending must be re-armed, got {pending}"
        # Round 2: digit 1 -> availability_confirm
        reply.reset_mock()
        await bot.handle_message(_FakeUpdate("1"), ctx)
        keys2 = _record(reply)
        assert "availability_confirm" in keys2, \
            f"digit after not-found list should confirm room, got {keys2}"
        assert "push_available" not in keys2, f"must not re-list, got {keys2}"


async def main():
    await _full_book_then_pick_chain()
    print("PASS 1: booking request -> menu 1 -> no-ID list -> digit 1 -> confirm (no loop)")

    await _digits_pick_after_each_fallback("sold_out",
                                           {"error": "sold_out"})
    print("PASS 2: sold_out list -> digit 1 -> confirm")

    await _digits_pick_after_each_fallback("short",
                                           {"error": "short", "available": 1, "need": 3})
    print("PASS 3: short-units list -> digit 1 -> confirm")

    await _digits_pick_after_each_fallback("book-not-found", None)
    print("PASS 4: book-not-found list -> digit 1 -> confirm")

    await _availability_not_found_pick()
    print("PASS 5: availability not-in-catalog list -> digit 1 -> confirm")

    print("\nALL PASSED (5/5)")


if __name__ == "__main__":
    asyncio.run(main())
