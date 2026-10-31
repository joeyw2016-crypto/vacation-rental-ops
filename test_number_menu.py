# -*- coding: utf-8 -*-
"""Unit tests for the numbered room-selection menu (1/2/3...).

Covers:
- _available_lines emits numbered lines starting at 1
- availability state: digit within list picks that room -> availability_confirm
- availability state: digit beyond list (> list size and > 4) -> invalid_room_number
- availability state: digit 1-4 beyond list (fewer rooms) -> falls through to guest menu
- language stays as session language for pure-number replies
"""
import asyncio
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/Users/joeyweng/Desktop/vacation_rental_ops")
import bot


def _fake_prop(pid, name, price=100, guests=2, units=1):
    return {
        "property_id": pid,
        "name": name,
        "price_per_night": price,
        "max_guests": guests,
        "available_units": units,
        "status": "available",
    }


FAKE_PROPS = [
    _fake_prop("AD-101", "Cozy Cabin", 120, 2, 1),
    _fake_prop("AD-102", "Garden Cottage", 150, 3, 1),
    _fake_prop("AD-103", "Lake House", 200, 4, 1),
    _fake_prop("AD-104", "Mountain Lodge", 260, 5, 1),
]


class _FakeChat:
    id = 1001


class _FakeEff:
    chat = _FakeChat()


class _FakeMsg:
    def __init__(self, text):
        self.text = text


class _FakeUpdate:
    def __init__(self, text):
        self.message = _FakeMsg(text)
        self.effective_chat = _FakeEff()


def _make_context():
    class Ctx:
        chat_data = {
            "lang": "zh",
            "pending": {
                "result": {"intent": "availability", "raw_message": "有房吗"},
                "lang": "zh",
                "original_text": "有房吗",
            }
        }
    return Ctx()


async def _run(text, avail_props=FAKE_PROPS):
    ctx = _make_context()
    with patch.object(bot, "store_list_properties", return_value=avail_props), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply, \
         patch.object(bot, "handle_menu_choice", new=AsyncMock()) as menu:
        await bot.handle_message(_FakeUpdate(text), ctx)
    return ctx, reply, menu


def _call(reply_mock, key):
    for c in reply_mock.call_args_list:
        kw = c.kwargs.get("key")
        arg_key = c.args[2] if len(c.args) > 2 else None
        if kw == key or arg_key == key:
            return c
    return None


def _call_lang(call):
    """Reply language: _reply_text(update, context, key, lang, ...) passes it
    positionally (4th arg) in bot code, but tests may also receive kwargs."""
    if call.kwargs.get("lang") is not None:
        return call.kwargs["lang"]
    return call.args[3] if len(call.args) > 3 else None


async def main():
    # 1. Numbered lines start at 1
    with patch.object(bot, "store_list_properties", return_value=FAKE_PROPS):
        lines = bot._available_lines("zh")
    assert lines[0].startswith("1) AD-101"), f"first line should be numbered 1, got {lines[0]!r}"
    assert lines[3].startswith("4) AD-104"), f"4th line should be numbered 4, got {lines[3]!r}"
    print("PASS 1: _available_lines numbered 1..4")

    # 2. Digit within list picks that room -> availability_confirm
    ctx, reply, _ = await _run("2")
    c = _call(reply, "availability_confirm")
    assert c is not None, "expected availability_confirm reply, got none"
    assert c.kwargs.get("prop") == "AD-102", f"expected AD-102, got {c.kwargs.get('prop')!r}"
    assert _call_lang(c) == "zh", "number reply should keep session language zh"
    assert ctx.chat_data["pending"].get("availability_confirm") is True
    print("PASS 2: digit 2 -> availability_confirm AD-102, lang zh")

    # 3. Digit beyond list and beyond menu -> invalid_room_number with max
    ctx, reply, _ = await _run("5")
    c = _call(reply, "invalid_room_number")
    assert c is not None, "expected invalid_room_number reply, got none"
    assert c.kwargs.get("max") == 4, f"expected max=4, got {c.kwargs.get('max')!r}"
    print("PASS 3: digit 5 -> invalid_room_number max=4")

    # 4. Digit 4 within list (4 rooms) picks room 4, NOT the guest menu
    ctx, reply, menu = await _run("4")
    c = _call(reply, "availability_confirm")
    assert c is not None and c.kwargs.get("prop") == "AD-104", \
        "expected availability_confirm AD-104 for digit 4 with 4 rooms"
    assert menu.call_count == 0, "menu should not fire when digit picks a room"
    print("PASS 4: digit 4 with 4 rooms -> availability_confirm AD-104, no menu")

    # 5. Digit 4 with only 3 rooms -> falls through to guest menu (human)
    three = FAKE_PROPS[:3]
    ctx, reply, menu = await _run("4", avail_props=three)
    c = _call(reply, "availability_confirm")
    assert c is None, "no confirm expected when digit 4 exceeds a 3-room list"
    assert menu.call_count == 1 and menu.call_args.args[-1] == "4", \
        f"expected menu routing for 4=human, got {menu.call_args_list!r}"
    print("PASS 5: digit 4 with 3 rooms -> menu 4=human")

    # 6. English session keeps en
    ctx = _make_context()
    ctx.chat_data["lang"] = "en"
    ctx.chat_data["pending"] = {
        "result": {"intent": "availability", "raw_message": "any rooms?"},
        "lang": "en",
        "original_text": "any rooms?",
    }
    with patch.object(bot, "store_list_properties", return_value=FAKE_PROPS), \
         patch.object(bot, "_reply_text", new=AsyncMock()) as reply, \
         patch.object(bot, "handle_menu_choice", new=AsyncMock()) as menu:
        await bot.handle_message(_FakeUpdate("2"), ctx)
    c = _call(reply, "availability_confirm")
    assert c is not None and c.kwargs.get("prop") == "AD-102", "en flow should pick AD-102"
    assert _call_lang(c) == "en", f"expected en, got {_call_lang(c)!r}"
    print("PASS 6: English session digit 2 -> availability_confirm AD-102, lang en")

    print("\nALL PASSED (6/6)")


if __name__ == "__main__":
    asyncio.run(main())
