# -*- coding: utf-8 -*-
"""End-to-end regression for the vacation rental bot core flows.

Uses the REAL catalog data for reads; all write paths (booking save) are
mocked so running this suite never mutates bookings.csv / properties.csv.

Covers:
- availability list is numbered 1/2/3...
- availability -> pick a room by number -> confirm menu
- confirm booking path (store save mocked)
- invalid room number hint
- guest menu 4 = human agent
- property-ID direct availability query stays intact
- language stays zh/en per conversation
"""
import asyncio
import sys
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, "/Users/joeyweng/Desktop/vacation_rental_ops")
import bot

# Hook isolation: bot.handle_message now auto-runs back_sync() first. This
# regression suite is read-only against the real catalog (write paths mocked),
# so the auto write-back hook is stubbed here; the hook itself is covered by
# test_auto_sync_hook.py against a sandbox copy.
bot.back_sync = lambda: None


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


def _ctx(lang="zh", pending=None, **extra):
    class Ctx:
        pass
    c = Ctx()
    c.chat_data = {"lang": lang}
    c.chat_data.update(extra)
    if pending is not None:
        c.chat_data["pending"] = pending
    return c


def _avail_pending(lang="zh", raw="有房吗"):
    return {
        "result": {"intent": "availability", "raw_message": raw},
        "lang": lang,
        "original_text": raw,
    }


def _call(reply_mock, key):
    for c in reply_mock.call_args_list:
        if c.kwargs.get("key") == key or (len(c.args) > 2 and c.args[2] == key):
            return c
    return None


async def main():
    # 1. Numbered lines built from REAL catalog (>= 11 bookable rooms)
    lines = bot._available_lines("zh")
    assert lines and lines[0].startswith("1) AD-101"), f"unexpected first line {lines[0] if lines else None!r}"
    assert len(lines) >= 11, f"expected >=11 bookable rooms, got {len(lines)}"
    print(f"PASS 1: availability list numbered, {len(lines)} bookable rooms")

    # 2. availability request -> summary template with numbered body
    ctx = _ctx(pending=_avail_pending())
    with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("有房吗"), ctx)
    c = _call(reply, "available_summary")
    assert c is not None, "expected available_summary"
    body = c.kwargs.get("body") or (c.args[6] if len(c.args) > 6 else "")
    assert body.startswith("1) AD-101"), f"body should be numbered, got {body[:40]!r}"
    print("PASS 2: availability summary numbered")

    # 3. pick room by number -> availability_confirm with correct property
    ctx = _ctx(pending=_avail_pending())
    with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("2"), ctx)
    c = _call(reply, "availability_confirm")
    assert c is not None and c.kwargs.get("prop") == "AD-1475", \
        f"digit 2 should map to AD-1475 (2nd bookable), got {c.kwargs.get('prop') if c else None!r}"
    print("PASS 3: digit 2 -> availability_confirm AD-1475")

    # 4. confirm booking -> _do_booking (store save mocked, pending cleared)
    ctx = _ctx(pending={
        "availability_confirm": True,
        "property_id": "AD-301",
        "name": "Garden Cottage 花园小屋",
        "original_text": "2",
        "lang": "zh",
        "result": {"intent": "availability", "raw_message": "有房吗"},
    })
    with patch.object(bot, "store_add_booking", return_value={"booking_id": "BK-TEST"}) as add, \
         patch.object(bot, "_finalize", new=Mock()) as fin, \
         patch.object(bot, "sync_overview", return_value=None), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("1"), ctx)
    assert add.call_count == 1, "confirm should trigger store_add_booking"
    assert add.call_args.args[0] == "AD-301", f"booking must use AD-301, got {add.call_args.args[0]!r}"
    assert ctx.chat_data.get("pending") is None, "pending must be cleared after confirm"
    print("PASS 4: confirm 1 -> store_add_booking(AD-301), pending cleared")

    # 5. room digit beyond list (99) -> invalid_room_number
    ctx = _ctx(pending=_avail_pending())
    with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("99"), ctx)
    c = _call(reply, "invalid_room_number")
    assert c is not None, "expected invalid_room_number for 99"
    print("PASS 5: digit 99 -> invalid_room_number")

    # 6. menu 4 -> human agent escalation (from the confirm menu state)
    ctx = _ctx(pending={
        "availability_confirm": True,
        "property_id": "AD-301",
        "name": "Garden Cottage 花园小屋",
        "original_text": "2",
        "lang": "zh",
        "result": {"intent": "availability", "raw_message": "有房吗"},
    })
    with patch.object(bot, "_forward_to_admin", new=AsyncMock()) as fwd, \
         patch.object(bot, "_finalize", new=Mock()), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("4"), ctx)
    assert fwd.call_count == 1, "menu 4 should forward to human agent"
    print("PASS 6: menu 4 -> human agent")

    # 7. property ID availability query still intact (AD-101)
    ctx = _ctx(pending=_avail_pending())
    with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("AD-101"), ctx)
    c = _call(reply, "available_single") or _call(reply, "availability") or _call(reply, "availability_confirm")
    assert c is not None or reply.call_count > 0, "AD-101 query should produce a reply"
    print("PASS 7: property-ID availability query replies")

    # 8. English conversation keeps en for numbered picks
    ctx = _ctx(lang="en", pending=_avail_pending(lang="en", raw="any rooms?"))
    with patch.object(bot, "_reply_text", new=AsyncMock()) as reply:
        await bot.handle_message(_FakeUpdate("3"), ctx)
    c = _call(reply, "availability_confirm")
    assert c is not None and c.kwargs.get("prop") == "AD-203", \
        f"digit 3 in en should map to AD-203, got {c.kwargs.get('prop') if c else None!r}"
    lang = c.kwargs.get("lang") or (c.args[3] if len(c.args) > 3 else None)
    assert lang == "en", f"expected en, got {lang!r}"
    print("PASS 8: English session keeps en, digit 3 -> AD-203")

    print("\nALL PASSED (8/8)")


if __name__ == "__main__":
    asyncio.run(main())
