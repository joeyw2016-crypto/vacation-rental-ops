# -*- coding: utf-8 -*-
"""Language-follow regression: "发中文回中文、发英文回英文".

Guards the fix for the bug where an English message got a Chinese reply.
Root cause: _effective_lang treated any letters/digits/space-only string
(e.g. "Hello", "I want to book a room") as a technical token and returned
the previous conversation language (zh), so an English sentence sent in a
Chinese conversation was answered in Chinese.

Now only code-like single tokens (property ID AD-101, URL, path, compact
ID) keep the conversation language; real Latin sentences are English.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, "/Users/joeyweng/Desktop/vacation_rental_ops")
import bot

# Hook isolation: same pattern as the other suites.
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


def _eff(text, prev="zh"):
    return bot._effective_lang(text, _ctx(lang=prev))


# ---- _effective_lang unit branches ---------------------------------------

def test_cjk_always_zh():
    assert _eff("还有房间吗") == "zh"
    assert _eff("我要预订 AD-1475") == "zh"   # CJK wins even with Latin
    assert _eff("你好 Hello") == "zh"


def test_english_sentence_in_zh_conversation_is_en():
    # The actual bug: prev=zh must NOT leak into an English reply.
    assert _eff("I want to book a room", prev="zh") == "en"
    assert _eff("Hello", prev="zh") == "en"
    assert _eff("How much for AD-101?", prev="zh") == "en"
    assert _eff("book the seaview apartment please", prev="zh") == "en"
    assert _eff("Are there any rooms tonight?", prev="zh") == "en"


def test_english_sentence_fresh_chat():
    assert _eff("I want to book a room", prev=None) == "en"
    assert _eff("Hello", prev=None) == "en"


def test_technical_tokens_keep_conversation_lang():
    assert _eff("AD-101", prev="zh") == "zh"
    assert _eff("AD-1475", prev="zh") == "zh"
    assert _eff("AD-1475", prev="en") == "en"
    assert _eff("https://example.com/floorplan", prev="zh") == "zh"
    assert _eff("www.example.com", prev="zh") == "zh"
    assert _eff("docs/floorplan.png", prev="zh") == "zh"
    assert _eff("A1B2", prev="zh") == "zh"


def test_digits_and_no_latin_keep_conversation_lang():
    assert _eff("1", prev="zh") == "zh"
    assert _eff("123", prev="en") == "en"
    assert _eff("！！！", prev="zh") == "zh"
    assert _eff("", prev="zh") == "zh"
    assert _eff("", prev=None) == "en"


# ---- end-to-end: handle_message picks the right lang ---------------------

async def _run(text, prev="zh", pending=None):
    update = _FakeUpdate(text)
    ctx = _ctx(lang=prev, pending=pending)
    with patch.object(bot, "_reply_text", new=AsyncMock()) as rt:
        await bot.handle_message(update, ctx)
        assert ctx.chat_data.get("lang") is not None
        return rt, ctx


def test_en_message_in_zh_chat_replies_en():
    async def case():
        rt, ctx = await _run("I want to book a room", prev="zh")
        assert ctx.chat_data["lang"] == "en"
        assert rt.await_count == 1
        # _reply_text(update, context, key, lang, ...)
        assert rt.await_args.args[3] == "en"
    asyncio.run(case())


def test_zh_message_replies_zh():
    async def case():
        rt, ctx = await _run("还有房间吗", prev="zh")
        assert ctx.chat_data["lang"] == "zh"
        assert rt.await_args.args[3] == "zh"
    asyncio.run(case())


def test_technical_token_keeps_zh_in_zh_chat():
    async def case():
        rt, ctx = await _run("AD-101", prev="zh")
        assert ctx.chat_data["lang"] == "zh"
        assert rt.await_args.args[3] == "zh"
    asyncio.run(case())


def test_en_message_fresh_chat_replies_en():
    async def case():
        rt, ctx = await _run("Hello", prev=None)
        assert ctx.chat_data["lang"] == "en"
        assert rt.await_args.args[3] == "en"
    asyncio.run(case())


def test_menu_choice_keeps_pending_lang():
    # Guest sent Chinese originally, then picks 1: menu branch keeps zh.
    async def case():
        update = _FakeUpdate("1")
        ctx = _ctx(lang="zh", pending={
            "result": {"intent": "booking", "property_id": "AD-1475"},
            "original_text": "还有房间吗",
            "lang": "zh",
        })
        with patch.object(bot, "_reply_text", new=AsyncMock()) as rt, \
                patch.object(bot, "_do_booking", new=AsyncMock()) as db:
            await bot.handle_message(update, ctx)
            assert db.await_count == 1
            assert db.await_args.args[4] == "zh"  # lang passed to _do_booking
            assert rt.await_count == 0  # booking branch replies via _do_booking
    asyncio.run(case())


def test_menu_choice_english_pending_stays_en():
    async def case():
        update = _FakeUpdate("1")
        ctx = _ctx(lang="en", pending={
            "result": {"intent": "booking", "property_id": "AD-1475"},
            "original_text": "I want to book a room",
            "lang": "en",
        })
        with patch.object(bot, "_reply_text", new=AsyncMock()) as rt, \
                patch.object(bot, "_do_booking", new=AsyncMock()) as db:
            await bot.handle_message(update, ctx)
            assert db.await_args.args[4] == "en"
            assert rt.await_count == 0
    asyncio.run(case())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
