
import asyncio
import hashlib
import json
import os
import re


def _load_dotenv(path=".env"):
    """Minimal .env loader: fills os.environ without overriding existing vars."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as e:
        print(f"bot: failed to load .env: {e}")


_load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from classify import classify
from storage import append_ticket, is_duplicate, summary_text
from clickup_client import CLICKUP_ENABLED, create_task
from llm_reply import LLM_ENABLED, llm_reply
from overview_sync import sync_overview
from sync_back import back_sync
from property_store import (
    get_property as store_get_property,
    list_properties as store_list_properties,
    is_available as store_is_available,
    add_booking as store_add_booking,
    list_bookings as store_list_bookings,
    release_booking_units as store_release_booking_units,
    parse_property_line as store_parse_property_line,
    add_property as store_add_property,
    remove_property as store_remove_property,
)

# Telegram bot token comes from .env / environment only. NEVER hard-code it:
# a leaked token lets anyone control the bot.
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# Admin notification: ADMIN_CHAT_ID comes from .env / environment only.
# Empty by default -> forwarding is disabled; guests just get the normal reply.
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()


# Bilingual labels for intents and priorities (English enum keys stay as-is)
INTENT_LABEL = {
    "book_modify":  {"zh": "修改预订", "en": "Modify Booking"},
    "book_cancel":  {"zh": "取消预订", "en": "Cancel Booking"},
    "complaint":    {"zh": "投诉/问题", "en": "Complaint / Issue"},
    "status_query": {"zh": "进度查询", "en": "Status Query"},
    "availability": {"zh": "查房态", "en": "Availability"},
    "booking":      {"zh": "预定", "en": "Booking"},
    "other":        {"zh": "其他", "en": "Other"},
}

PRIORITY_LABEL = {
    "high":   {"zh": "高", "en": "High"},
    "medium": {"zh": "中", "en": "Medium"},
    "low":    {"zh": "低", "en": "Low"},
}

# Bilingual reply templates, rendered with str.format()
REPLIES = {
    "welcome": {
        "zh": ("欢迎！我是度假租赁客服机器人。\n"
               "直接发消息描述你的问题即可，例如：\n"
               "· 我要改 AD-1475 的预订\n"
               "· 房间漏水了\n"
               "· 我的预订什么时候开始\n"
               "发送 /summary 可查看已记录工单统计，发送 /list_properties 可查看房源列表。"),
        "en": ("Welcome! I'm your vacation rental support bot.\n"
               "Just send a message describing your request, e.g.:\n"
               "· I want to change my booking at AD-1475\n"
               "· There's a water leak\n"
               "· When does my booking start?\n"
               "Send /summary to see recorded ticket stats, or /list_properties to see our properties."),
    },
    "menu": {
        "zh": ("请选择服务：\n"
               "1 = 预定\n"
               "2 = 查询房源\n"
               "3 = 修改房源\n"
               "4 = 人工处理\n\n"
               "请回复数字，我会根据您刚才的描述继续处理。"),
        "en": ("Please choose a service:\n"
               "1 = Book\n"
               "2 = Check availability\n"
               "3 = Modify booking\n"
               "4 = Human agent\n\n"
               "Reply with a number; I'll continue using your last message."),
    },
    "menu_admin": {
        "zh": ("请选择服务：\n"
               "1 = 预定\n"
               "2 = 查询房源\n"
               "3 = 修改房源\n"
               "4 = 人工处理\n"
               "5 = 添加房源\n"
               "6 = 删除房源\n\n"
               "请回复数字，我会根据您刚才的描述继续处理。"),
        "en": ("Please choose a service:\n"
               "1 = Book\n"
               "2 = Check availability\n"
               "3 = Modify booking\n"
               "4 = Human agent\n"
               "5 = Add property\n"
               "6 = Remove property\n\n"
               "Reply with a number; I'll continue using your last message."),
    },
    "invalid_menu_choice": {
        "zh": "请回复 {valid}。",
        "en": "Please reply {valid}.",
    },
    "admin_only": {
        "zh": "仅房东可操作该功能。请回复 1、2、3 或 4 使用客户服务菜单。",
        "en": "This function is for the host only. Please reply 1, 2, 3 or 4 to use the guest service menu.",
    },
    "admin_add_prompt": {
        "zh": ("请按以下格式输入新房源（用 | 分隔 5 项）：\n"
               "房源ID|名称|描述|价格|总间数\n"
               "例如：AD-999|海景豪华房|带阳台海景|1500|3\n\n"
               "价格与总间数需为正数，总间数至少为 1。输入\"取消\"可退出添加。"),
        "en": ("Send the new property in this format (5 fields separated by |):\n"
               "PropertyID|Name|Description|Price|TotalUnits\n"
               "Example: AD-999|Deluxe Sea View Room|Balcony, ocean view|1500|3\n\n"
               "Price and total units must be positive; total units must be >= 1. Send \"cancel\" to abort."),
    },
    "admin_add_fail_format": {
        "zh": "格式不正确：{reason}\n\n请重新发送，格式为：\n房源ID|名称|描述|价格|总间数\n例如：AD-999|海景豪华房|带阳台海景|1500|3",
        "en": "Invalid format: {reason}\n\nPlease resend in this format:\nPropertyID|Name|Description|Price|TotalUnits\nExample: AD-999|Deluxe Sea View Room|Balcony, ocean view|1500|3",
    },
    "admin_add_dup": {
        "zh": "房源 ID {prop} 已存在，请使用其他 ID 重新发送，或发送\"取消\"退出。",
        "en": "Property ID {prop} already exists. Use a different ID and resend, or send \"cancel\" to abort.",
    },
    "admin_add_ok": {
        "zh": ("房源已添加：\n"
               "{name}（{prop}）\n"
               "描述：{desc}\n"
               "价格：¥{price}/晚\n"
               "总间数：{total} 间，可订 {avail} 间\n"
               "状态：可订"),
        "en": ("Property added:\n"
               "{name} ({prop})\n"
               "Description: {desc}\n"
               "Price: ¥{price}/night\n"
               "Total units: {total}, available: {avail}\n"
               "Status: available"),
    },
    "admin_add_abort": {
        "zh": "已取消添加房源。",
        "en": "Add-property aborted.",
    },
    "admin_del_prompt": {
        "zh": "请输入要删除的房源 ID（如 AD-203）。发送\"取消\"可退出。",
        "en": "Send the property ID to remove (e.g. AD-203). Send \"cancel\" to abort.",
    },
    "admin_del_not_found": {
        "zh": "未找到房源 {prop}。请重新输入房源 ID，或发送\"取消\"退出。",
        "en": "Property {prop} not found. Send the ID again, or \"cancel\" to abort.",
    },
    "admin_del_confirm": {
        "zh": ("即将删除房源：\n"
               "{name}（{prop}）· ¥{price}/晚 · 总 {total} 间 · 剩余 {avail} 间\n\n"
               "确认删除请回复 Y；取消请回复 N。\n"
               "（该房源关联的历史预订记录保留在 bookings.csv，不会被删除）"),
        "en": ("About to remove property:\n"
               "{name} ({prop}) · ¥{price}/night · {total} unit(s) · {avail} available\n\n"
               "Reply Y to confirm removal, N to cancel.\n"
               "(Historical bookings for this property stay in bookings.csv; they are not deleted)"),
    },
    "admin_del_ok": {
        "zh": "房源 {prop}（{name}）已删除。历史预订记录仍保留在 bookings.csv。",
        "en": "Property {prop} ({name}) removed. Historical bookings remain in bookings.csv.",
    },
    "admin_del_cancel": {
        "zh": "已取消删除。",
        "en": "Removal cancelled.",
    },
    "admin_del_invalid": {
        "zh": "请输入 Y 确认删除，或 N 取消。",
        "en": "Reply Y to confirm removal, or N to cancel.",
    },
    "booking_sold_out": {
        "zh": "抱歉，{prop}（{name}）已订满，暂时无法预订。可回复 2 查看其他可订房源。",
        "en": "Sorry, {prop} ({name}) is fully booked. Reply 2 to see other available properties.",
    },
    "booking_units_short": {
        "zh": "抱歉，{prop}（{name}）当前仅剩 {avail} 间，无法满足 {need} 间。可减少间数后重试，或回复 2 查看其他可订房源。",
        "en": "Sorry, {prop} ({name}) has only {avail} unit(s) left; can't book {need}. Try fewer units or reply 2 for other options.",
    },
    "cancel_refunded": {
        "zh": "已为您取消预订，库存已回补。",
        "en": "Your booking was cancelled; the unit has been released back to inventory.",
    },
    "booking_intent": {
        "zh": "已为您预订 {prop}（订单号 {booking}，{units} 间），剩余 {avail} 间。客服会尽快与您确认。",
        "en": "Booked {prop} (booking {booking}, {units} unit(s)). {avail} unit(s) left. A human agent will contact you to confirm.",
    },
    "booking_not_found": {
        "zh": "未在房源库中找到 {prop}，无法预订，请确认编号后重试。",
        "en": "Could not find {prop} in the property catalog, so the booking was not created. Please double-check the ID.",
    },
    "booking_ask_id": {
        "zh": "预定需要房源编号，请提供 AD-xxx 编号（如 AD-101）。",
        "en": "To book, please provide a property ID like AD-101.",
    },
    "available_summary": {
        "zh": "当前可入住房源：\n{body}\n\n回复编号（1/2/3…）选择房源，我会为您确认预订。",
        "en": "Available properties:\n{body}\n\nReply with a number (1/2/3...) to pick a room and I will confirm the booking.",
    },
    "push_available": {
        "zh": "当前可入住房源：\n{body}\n\n回复编号（1/2/3…）选择房源，我会为您确认预订。",
        "en": "Available properties:\n{body}\n\nReply with a number (1/2/3...) to pick a room and I will confirm the booking.",
    },
    "invalid_room_number": {
        "zh": "请从上方列表选择 1-{max} 的编号，或回复 3 修改预订、4 联系人工。",
        "en": "Please pick a number from 1-{max} in the list above, or reply 3 to modify a booking or 4 for a human agent.",
    },
    "no_available": {
        "zh": "抱歉，当前没有可入住房源。",
        "en": "Sorry, no properties are available right now.",
    },
    "modify_recorded": {
        "zh": "已记录您的{type}请求，我们会尽快处理。",
        "en": "Your {type} request has been recorded; we'll handle it soon.",
    },
    "complaint_recorded": {
        "zh": "已记录您的投诉，我们会优先处理，给您带来不便深表歉意。",
        "en": "Your complaint has been recorded and will be prioritized. We apologize for the inconvenience.",
    },
    "handover_recorded": {
        "zh": "已记录您的请求，将转给运营跟进。",
        "en": "Your request has been recorded; our ops team will follow up.",
    },
    "escalated":      {"zh": "已转人工处理，客服会尽快联系您。", "en": "Escalated to a human agent; they will contact you shortly."},
    "duplicate":      {"zh": "这条消息刚才已处理过，无需重复发送。", "en": "This message was already processed; no need to resend it."},
    "property_list": {
        "zh": "房源列表：\n{body}",
        "en": "Properties:\n{body}",
    },
    "no_properties":  {"zh": "房源库为空，暂无房源信息。", "en": "No properties registered yet."},
    "availability_found": {
        "zh": "{name}（{prop}）：{status_text}，¥{price}/晚，可住 {guests} 人，{bedrooms} 间卧室，剩余 {units_avail} 间。",
        "en": "{name} ({prop}): {status_text}, ¥{price}/night, up to {guests} guests, {bedrooms} bedroom(s), {units_avail} unit(s) left.",
    },
    "availability_occupied": {
        "zh": "{name}（{prop}）当前已入住，暂无空房。",
        "en": "{name} ({prop}) is currently occupied, no vacancy.",
    },
    "availability_not_found": {
        "zh": "未在房源库中找到 {prop}，请确认编号后重试。",
        "en": "Could not find {prop} in the property catalog. Please double-check the ID.",
    },
    "availability_ask_id": {
        "zh": "请提供房源编号（如 AD-101），我来帮您查询房态。",
        "en": "Please provide a property ID (e.g. AD-101) so I can check availability.",
    },
    "availability_confirm": {
        "zh": "您要预订 {name}（{prop}）吗？请回复：\n1 = 是，确认预订\n2 = 查询其他房源\n3 = 修改预订\n4 = 联系人工",
        "en": "Would you like to book {name} ({prop})? Please reply:\n1 = Yes, confirm the booking\n2 = Check other available properties\n3 = Modify an existing booking\n4 = Contact a human agent",
    },
    "availability_confirm_no": {
        "zh": "抱歉，我没看懂您的回复。请回复：\n1 = 确认预订 {name}（{prop}）\n2 = 查询其他房源\n3 = 修改预订\n4 = 联系人工",
        "en": "Sorry, I didn't understand that. Please reply:\n1 = Confirm booking {name} ({prop})\n2 = Check other available properties\n3 = Modify an existing booking\n4 = Contact a human agent",
    },
    "no_booking": {
        "zh": "您目前没有预订记录。如需预订请回复 1，或回复 2 查看可订房源。",
        "en": "You have no bookings on record yet. Reply 1 to book a property, or reply 2 to see available properties.",
    },
    "my_bookings": {
        "zh": "您有 {count} 笔确认预订：\n{body}\n如需取消或修改，请直接说明需求（例如“取消 BK-xxx”），或回复 4 联系人工。",
        "en": "You have {count} confirmed booking(s):\n{body}\nTo cancel or modify one, tell me the need directly (e.g. \"cancel BK-xxx\"), or reply 4 for a human agent.",
    },
}

# Host self-service: reason codes from property_store.parse_property_line()
REASON_LABEL = {
    "need_5_fields":        {"zh": "需要 5 个字段并用 | 分隔", "en": "expected 5 fields separated by |"},
    "empty_id":             {"zh": "房源 ID 不能为空", "en": "property ID must not be empty"},
    "price_not_number":     {"zh": "价格必须是数字", "en": "price must be a number"},
    "price_not_positive":   {"zh": "价格必须为正数", "en": "price must be positive"},
    "units_not_integer":    {"zh": "总间数必须是整数", "en": "total units must be an integer"},
    "units_too_small":      {"zh": "总间数至少为 1", "en": "total units must be >= 1"},
    "duplicate":            {"zh": "该房源 ID 已存在", "en": "that property ID already exists"},
    "write_failed":         {"zh": "写入文件失败，请稍后重试", "en": "failed to write file, please retry later"},
    "not_found":            {"zh": "未找到该房源", "en": "property not found"},
}


def _is_admin_chat_id(chat_id) -> bool:
    """True only when ADMIN_CHAT_ID is configured and matches this chat."""
    if not ADMIN_CHAT_ID:
        return False
    try:
        return str(int(chat_id)) == str(int(ADMIN_CHAT_ID))
    except Exception:
        return False


def _parse_units(text: str) -> int:
    """Guess how many units the guest wants to book (default 1).

    Recognizes patterns like '2间', '3 rooms', 'two rooms' and 'x2'. Unknown
    patterns default to a single unit.
    """
    if not text:
        return 1
    m = re.search(r"(\d+)\s*(?:间|rooms?|units?)\b", text, re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            return 1
    if re.search(r"[两2]\s*间", text):
        return 2
    m = re.search(r"\b[x×]\s*(\d+)", text, re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            return 1
    return 1


# CJK range: any Chinese character means the reply should be in Chinese
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


_LATIN_RE = re.compile(r"[a-zA-Z]")


def detect_lang(text: str) -> str:
    """Return 'zh' if the text contains CJK characters, otherwise 'en'."""
    return "zh" if _CJK_RE.search(text) else "en"


def _effective_lang(text: str, context) -> str:
    """Pick the reply language for a message while keeping the conversation stable.

    - Text contains CJK characters                 -> Chinese
    - No Latin letters (digits / punctuation)      -> keep conversation language
    - Latin letters that are only a technical token (property ID like AD-101,
      a code, a URL, a path, a compact ID)         -> keep conversation language,
      so replying "AD-101" in a Chinese conversation never flips to English
    - Real Latin words / sentences                 -> English
    """
    prev = context.chat_data.get("lang")
    t = text.strip()
    if not t:
        return prev or "en"
    if _CJK_RE.search(t):
        return "zh"
    if not _LATIN_RE.search(t):
        return prev or "en"
    # Latin letters present: distinguish natural language from technical
    # tokens (property IDs, codes, URLs, paths) that should not flip the
    # language. A technical token is a single space-free code-like string
    # with digits or URL/path structure; any real Latin sentence ("Hello",
    # "I want to book a room") is English even if it is letters-only.
    if _is_technical_token(t):
        return prev or "en"
    return "en"


def _is_technical_token(t: str) -> bool:
    """True when t is a code-like token (property ID, URL, path, compact ID).

    Multi-word text is natural language. Single tokens with digits, URL or
    path structure are technical and must keep the conversation language.
    """
    if " " in t:
        return False
    if re.search(r"://", t) or t.startswith(("www.", "http", "ftp")):
        return True
    if re.fullmatch(r"[A-Za-z]+-\d+", t):  # AD-101, PL-42
        return True
    if "/" in t or "\\" in t or re.fullmatch(r"[A-Za-z0-9]+(\.[A-Za-z0-9]+)+", t):
        return True  # path / filename like a.png
    if re.fullmatch(r"[A-Za-z0-9]+", t) and re.search(r"\d", t) and len(t) <= 12:
        return True  # compact code like A1B2
    return False


def _user_lang(update: Update) -> str:
    """Best-effort language from the Telegram user profile (for commands with no text)."""
    code = getattr(update.effective_user, "language_code", None) or ""
    return "zh" if code.lower().startswith("zh") else "en"


def _t(key: str, lang: str, **kwargs) -> str:
    """Pick the reply template for the detected language and format it."""
    return REPLIES[key][lang].format(**kwargs)


def _lang_matches(text: str, lang: str) -> bool:
    """True when the generated text matches the requested reply language."""
    if lang == "zh":
        return bool(_CJK_RE.search(text))
    return bool(_LATIN_RE.search(text))


async def _reply_text(update: Update, context, key: str, lang: str,
                      user_message: str = "", extra_context: str = "", **kwargs):
    """Send a reply: LLM-generated natural text when available, template otherwise.

    Falls back to the bilingual template if the LLM is not configured or fails.
    The LLM output is also language-checked: a reply that is not in the
    requested language (e.g. DeepSeek answering English for a Chinese
    conversation on a digit-only message like '1') falls back to the template
    so the guest never receives a wrongly-languaged answer.
    """
    if LLM_ENABLED:
        try:
            generated = await asyncio.to_thread(llm_reply, user_message, extra_context, lang)
            if generated and _lang_matches(generated, lang):
                await update.message.reply_text(generated)
                return
            if generated:
                print(f"LLM reply language mismatch (expected {lang}), falling back to template")
        except Exception as e:
            print(f"LLM reply failed, falling back to template: {e}")
    await update.message.reply_text(_t(key, lang, **kwargs))


def _id_key(update: Update, text: str) -> str:
    """Idempotency key: chat_id + hash of the message text."""
    msg_hash = hashlib.md5(text.encode()).hexdigest()
    return f"{update.effective_chat.id}:{msg_hash}"


def _finalize(update: Update, result: dict, status: str = "done"):
    """Log the ticket to CSV and push it to ClickUp."""
    result["status"] = status
    append_ticket(_id_key(update, result["raw_message"]), result)
    # Auto-refresh the overview workbook after a ticket is logged;
    # failures are logged only.
    try:
        sync_overview()
    except Exception as e:
        print(f"overview_sync: failed to refresh overview after ticket: {e}")
    if CLICKUP_ENABLED:
        try:
            task = create_task(
                title=f"[{result['intent']}] {result.get('property_id') or 'unknown property'}",
                description=json.dumps(result, ensure_ascii=False, indent=2),
            )
            print(f"ClickUp task created: {task.get('id')}")
        except Exception as e:
            print(f"Failed to create ClickUp task: {e}")


async def _forward_to_admin(update: Update, context, result: dict, note: str = ""):
    """Forward the guest message and brief context to the configured admin.

    Reads ADMIN_CHAT_ID from .env / environment. When it is empty the call is
    a no-op (guests still get the normal reply). Any send failure is logged
    but never breaks the main flow.
    """
    if not ADMIN_CHAT_ID:
        return
    try:
        user = update.effective_user
        guest = ""
        if user is not None:
            guest = (getattr(user, "username", None)
                     or getattr(user, "first_name", "")
                     or getattr(user, "full_name", "")
                     or "")
        chat_id = update.effective_chat.id if update.effective_chat else "?"
        text = (
            "客户请求转发（人工处理）\n"
            f"客户: {guest or '(无用户名)'}\n"
            f"chat_id: {chat_id}\n"
            f"消息: {result.get('raw_message') or ''}\n"
            f"意图: {result.get('intent') or ''}\n"
            f"房源: {result.get('property_id') or '-'}\n"
            f"备注: {note}"
        )
        await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text)
    except Exception as e:
        print(f"Forward to admin failed (non-fatal): {e}")


async def start(update: Update, context):
    """/start command: greet the user."""
    lang = _user_lang(update)
    context.chat_data["lang"] = lang
    await update.message.reply_text(_t("welcome", lang))


async def summary(update: Update, context):
    """/summary command: show ticket statistics in the chat language."""
    lang = context.chat_data.get("lang") or _user_lang(update)
    await update.message.reply_text(summary_text(lang))


async def list_properties_command(update: Update, context):
    """/list_properties command: show the property catalog in the chat language."""
    lang = context.chat_data.get("lang") or _user_lang(update)
    props = store_list_properties()
    if not props:
        await update.message.reply_text(_t("no_properties", lang))
        return
    lines = []
    for p in props:
        pid = p.get("property_id", "?")
        name = p.get("name", "")
        if p.get("status") == "available":
            status = "可入住" if lang == "zh" else "available"
        else:
            status = "已入住" if lang == "zh" else "occupied"
        lines.append(f"{pid} · {name} · {status}")
    await update.message.reply_text(_t("property_list", lang, body="\n".join(lines)))


def _name_tokens(name: str) -> list:
    """Split a bilingual property name like 'Garden Cottage 花园小屋' into
    searchable tokens: each English word and each CJK phrase separately."""
    tokens = []
    for part in re.split(r"[\s/|,，、]+", name.lower().strip()):
        part = part.strip(".,-:;()[]'\"")
        if not part:
            continue
        if re.fullmatch(r"[a-z0-9]+", part):
            tokens.append(part)
        else:
            tokens.append(part)
    return tokens


def _match_property(text: str):
    """Return a property dict when text refers to a property by ID or name.

    - Tries the AD-xxx / ADxxx / ad 1475 ID pattern first.
    - Falls back to a case-insensitive match against the full bilingual name
      or any single token of it, e.g. "Seaview Apartment", "海景公寓",
      "Garden Cottage", "花园小屋", or even "garden".
    Returns None when no property is referenced.
    """
    t = text.lower().strip()
    m = re.search(r"(?:AD|ad)[- ]?(\d{3,4})", t)
    if m:
        pid = f"AD-{m.group(1)}"
        prop = store_get_property(pid)
        if prop is not None:
            return prop
    for p in store_list_properties():
        name = (p.get("name") or "").strip()
        if not name:
            continue
        nl = name.lower()
        if nl in t or t in nl:
            return p
        for tok in _name_tokens(name):
            if len(tok) >= 2 and (tok in t or t in tok):
                return p
    return None


def _available_props() -> list:
    """Currently bookable properties (status available and units > 0)."""
    return [p for p in store_list_properties()
            if p.get("status") == "available" and int(p.get("available_units", 0) or 0) > 0]


def _available_lines(lang: str) -> list:
    """Return numbered display lines for currently available properties.

    Lines are numbered 1/2/3... so the guest can reply with a number to
    pick a room (number routing is implemented in handle_message).
    """
    lines = []
    for i, p in enumerate(_available_props(), start=1):
        pid = p.get("property_id", "?")
        name = p.get("name", "")
        price = p.get("price_per_night", "?")
        guests = p.get("max_guests", "?")
        units = p.get("available_units", 0)
        if lang == "zh":
            lines.append(f"{i}) {pid} · {name} · ¥{price}/晚 · 可住 {guests} 人 · 剩余 {units} 间")
        else:
            lines.append(f"{i}) {pid} · {name} · ¥{price}/night · up to {guests} guests · {units} unit(s) left")
    return lines


async def _push_available_properties(update: Update, context, lang: str, user_message: str, reason: str):
    """Push the currently available properties as the final answer.

    Used when the guest's request cannot be fulfilled as-is (no property ID,
    property sold out, ID not found, occupied). Never asks follow-up
    questions; presents the real catalog numbered 1/2/3... and invites the
    guest to reply with a number to pick a room.
    """
    # Re-arm the numbered-pick state BEFORE showing the list: whatever path
    # led here (menu 1 Book without a property ID, sold out, short units,
    # ID not in catalog, occupied), the next digit reply must be routed to
    # the availability confirm branch. Without this, pending.result.intent
    # stays e.g. "booking" and a digit falls into the generic menu
    # (1 = Book) which re-lists the catalog forever.
    context.chat_data["pending"] = {
        "result": {
            "intent": "availability",
            "raw_message": user_message,
            "property_id": None,
            "needs_human": False,
            "priority": "low",
        },
        "original_text": user_message,
        "lang": lang,
    }
    lines = _available_lines(lang)
    if not lines:
        await _reply_text(
            update, context, "no_available", lang,
            user_message=user_message,
            extra_context=(
                f"{reason} No properties are currently available. Tell the "
                "guest politely and do not ask any follow-up questions."
            ),
        )
        return
    await _reply_text(
        update, context, "push_available", lang,
        user_message=user_message,
        extra_context=(
            f"{reason} Present the currently available properties below, each "
            "numbered 1/2/3..., and invite the guest to reply with a NUMBER to "
            "pick a room. Do NOT ask any follow-up questions; end your reply "
            "after the list.\n"
            + "\n".join(lines)
        ),
        body="\n".join(lines),
    )


async def _availability_summary(update: Update, context, lang: str, user_message: str):
    """Branch 2 without a property ID: summarize currently available properties."""
    lines = _available_lines(lang)
    if not lines:
        await _reply_text(
            update, context, "no_available", lang,
            user_message=user_message,
            extra_context="No properties are currently available. Tell the guest politely and stop.",
        )
        return
    await _reply_text(
        update, context, "available_summary", lang,
        user_message=user_message,
        extra_context=(
            "List the currently available properties with price and capacity "
            "using the REAL catalog data below. Answer the guest's availability "
            "question directly with these options; do NOT ask for extra details "
            "like guest count or area, and end your reply after the list.\n"
            + "\n".join(lines)
        ),
        body="\n".join(lines),
    )


async def _availability_reply(update: Update, context, result: dict, lang: str):
    """Branch 2 (availability): answer with real data from the property catalog.

    - Property ID recognized and found  -> show real price/capacity/status
    - Property ID recognized but absent -> ask the user to double-check
    - No property ID                    -> summarize available properties
    """
    prop_id = result.get("property_id")
    if not prop_id:
        await _availability_summary(update, context, lang, result["raw_message"])
        return
    prop = store_get_property(prop_id)
    if prop is None:
        await _push_available_properties(
            update, context, lang, result["raw_message"],
            reason=f"The guest asked about property {prop_id}, which is not in the catalog.",
        )
        return
    avail_units = int(prop.get("available_units", 0) or 0)
    if store_is_available(prop_id) and avail_units > 0:
        status_text = "今晚可入住" if lang == "zh" else "available tonight"
        await _reply_text(
            update, context, "availability_found", lang,
            user_message=result["raw_message"],
            extra_context=(
                f"Property {prop_id} ({prop.get('name', '')}) is available with "
                f"{avail_units} unit(s) left. Price ¥{prop.get('price_per_night', '?')}/night, "
                f"up to {prop.get('max_guests', '?')} guests, "
                f"{prop.get('bedrooms', '?')} bedroom(s). Answer the guest's availability question."
            ),
            name=prop.get("name", prop_id),
            prop=prop_id,
            status_text=status_text,
            price=prop.get("price_per_night", "?"),
            guests=prop.get("max_guests", "?"),
            bedrooms=prop.get("bedrooms", "?"),
            units_avail=avail_units,
        )
    else:
        await _push_available_properties(
            update, context, lang, result["raw_message"],
            reason=(
                f"Property {prop_id} ({prop.get('name', '')}) has no vacancy "
                f"(fully booked: {avail_units} unit(s) left)."
            ),
        )


async def handle_message(update: Update, context):
    """Plain text message: classify internally -> cache -> show the service menu.

    The guest then picks 1/2/3/4; handle_menu_choice runs the branch using
    the cached description of their original message. Internal fields such as
    intent/property/priority are never echoed back to the guest.
    """
    # Auto write-back hook: if the operator edited vacation_rental_overview.xlsx,
    # any inbound message triggers back_sync() (xlsx -> CSV full write-back +
    # overview rebuild, idempotent). Failures are logged and never block the
    # normal message handling flow.
    try:
        back_sync()
    except Exception as e:
        print(f"auto back_sync failed (non-fatal): {e}")

    text = update.message.text.strip()
    if not text:
        # Telegram does not normally deliver empty text messages; guard anyway
        # so a whitespace-only payload never reaches classify()/menu logic.
        return
    lang = _effective_lang(text, context)
    context.chat_data["lang"] = lang

    # 1. Menu selection pending: 1-4 route to branches; any other digit is an
    #    invalid menu choice; any non-digit text is a NEW request. Host
    #    self-service flows (add/remove property) use dedicated pending modes.
    pending = context.chat_data.get("pending")
    if pending is not None:
        if pending.get("admin_add"):
            await _admin_add_input(update, context, pending, text, lang)
            return
        if pending.get("admin_del"):
            await _admin_del_input(update, context, pending, text, lang)
            return
        if pending.get("admin_del_confirm"):
            await _admin_del_confirm_input(update, context, pending, text, lang)
            return
        if pending.get("availability_confirm"):
            # The guest picked a property after seeing availability and was
            # asked "would you like to book?"; route their confirmation
            # BEFORE the 1-4 menu check so "1" confirms the booking instead
            # of being swallowed by the generic menu dispatcher.
            await _availability_confirm_input(update, context, pending, text, lang)
            return
        # Availability follow-up: when the guest is looking at the numbered
        # list of available properties (1/2/3...), a digit picks that room
        # BEFORE the generic 1-4 menu. Digits outside the list fall through
        # to the menu (3=modify, 4=human) or get an invalid-range hint.
        if pending.get("result", {}).get("intent") == "availability":
            avail = _available_props()
            if text.isdigit() and 1 <= int(text) <= len(avail):
                prop = avail[int(text) - 1]
                pid = prop.get("property_id")
                context.chat_data["pending"] = {
                    "availability_confirm": True,
                    "property_id": pid,
                    "name": prop.get("name", pid),
                    "original_text": text,
                    "lang": lang,
                    "result": pending.get("result"),
                }
                await _reply_text(
                    update, context, "availability_confirm", lang,
                    user_message=text,
                    extra_context=(
                        f"The guest picked room #{int(text)} ({pid}, "
                        f"{prop.get('name', '')}). Ask whether they want to "
                        "book it; do NOT list all properties again."
                    ),
                    name=prop.get("name", pid),
                    prop=pid,
                )
                return
            if text.isdigit() and int(text) > len(avail) and int(text) > 4:
                # A number that matches neither the room list nor the guest
                # menu -> tell the guest the valid range instead of guessing.
                await _reply_text(
                    update, context, "invalid_room_number", lang,
                    user_message=pending.get("original_text", text),
                    extra_context=(
                        f"The guest replied {text} but the available list has "
                        f"only {len(avail)} room(s). Tell them to pick 1-{len(avail)} "
                        "from the list, or 3=modify / 4=human."
                    ),
                    max=max(1, len(avail)),
                )
                return
        if text in ("1", "2", "3", "4"):
            await handle_menu_choice(update, context, pending, text)
            return
        is_admin = _is_admin_chat_id(update.effective_chat.id)
        if text in ("5", "6"):
            if not is_admin:
                await _reply_text(
                    update, context, "admin_only", lang,
                    user_message=pending.get("original_text", text),
                    extra_context=(
                        "A non-host chat tried to use the host menu (5/6). Tell "
                        "them this is host-only and offer the guest menu 1-4."
                    ),
                )
                return
            context.chat_data.pop("pending", None)
            if text == "5":
                context.chat_data["pending"] = {"admin_add": True, "lang": lang}
                await _reply_text(
                    update, context, "admin_add_prompt", lang,
                    user_message=text,
                    extra_context=(
                        "Host chose 'Add property'. Prompt for the pipe-separated "
                        "5-field format and validate before writing."
                    ),
                )
            else:
                context.chat_data["pending"] = {"admin_del": True, "lang": lang}
                await _reply_text(
                    update, context, "admin_del_prompt", lang,
                    user_message=text,
                    extra_context=(
                        "Host chose 'Remove property'. Ask for the property ID, "
                        "show it, then require an explicit Y/N confirmation."
                    ),
                )
            return
        if text.isdigit():
            plang = pending.get("lang", lang)
            valid = "1、2、3、4、5 或 6" if _is_admin_chat_id(update.effective_chat.id) else "1、2、3 或 4"
            await _reply_text(
                update, context, "invalid_menu_choice", plang,
                user_message=pending.get("original_text", text),
                extra_context=(
                    "The guest replied with a digit that is not in the menu while "
                    "a selection is pending. Ask them to reply with a valid option."
                ),
                valid=valid,
            )
            return
        # Availability follow-up: after the guest picked 2, they may reply
        # with a specific property (by ID or by name) or with extra details.
        # A specific property starts the "book it?" confirm flow; anything
        # else is merged into the original request and re-run against the
        # real catalog (no clarifying-question loops).
        if pending.get("result", {}).get("intent") == "availability":
            matched = _match_property(text)
            if matched is not None:
                pid = matched["property_id"]
                context.chat_data["pending"] = {
                    "availability_confirm": True,
                    "property_id": pid,
                    "name": matched.get("name", pid),
                    "original_text": text,
                    "lang": lang,
                    "result": pending.get("result"),
                }
                await _reply_text(
                    update, context, "availability_confirm", lang,
                    user_message=text,
                    extra_context=(
                        f"The guest picked property {pid} ({matched.get('name', '')}). "
                        "Ask whether they want to book it; do NOT list all "
                        "properties again."
                    ),
                    name=matched.get("name", pid),
                    prop=pid,
                )
                return
            combined = f"{pending.get('original_text', '')} {text}"
            pending["original_text"] = combined
            pending["result"]["raw_message"] = combined
            await _availability_reply(update, context, pending["result"], lang)
            return
        context.chat_data.pop("pending", None)

    # 2. Idempotency: skip messages already processed
    if is_duplicate(_id_key(update, text)):
        await _reply_text(
            update, context, "duplicate", lang,
            user_message=text,
            extra_context="The user's message is a duplicate of one already processed. Tell them kindly it has already been handled.",
        )
        return

    # 3. Classify internally, cache the original description, show the menu
    result = classify(text)
    result["chat_id"] = update.effective_chat.id
    result["lang"] = lang
    context.chat_data["pending"] = {
        "result": result,
        "original_text": text,
        "lang": lang,
    }
    menu_key = "menu_admin" if _is_admin_chat_id(update.effective_chat.id) else "menu"
    await _reply_text(
        update, context, menu_key, lang,
        user_message=result["raw_message"],
        extra_context=(
            f"Classified internally: intent={result['intent']}, "
            f"property={result['property_id'] or 'unknown'}, "
            f"priority={result['priority']}, needs_human={result['needs_human']}. "
            "Do NOT reveal these internal fields. Show the service menu and ask the "
            "guest to pick 1 (Book), 2 (Check availability), 3 (Modify booking) or "
            "4 (Human agent). Keep the options exactly: 1 = Book / 2 = Check "
            "availability / 3 = Modify booking / 4 = Human agent."
        ),
    )


async def _do_booking(update: Update, context, prop_id: str, original: str, lang: str, result: dict = None):
    """Execute a real booking for prop_id and reply with the outcome.

    Shared by menu choice 1 (Book) and the availability follow-up confirm
    flow, so both paths behave identically (atomic inventory decrement,
    ticket finalize, overview refresh).
    """
    if not prop_id:
        await _push_available_properties(
            update, context, lang, original,
            reason="The guest wants to book but no property ID was found in their message.",
        )
        return
    units = _parse_units(original)
    guest_name = ""
    user = update.effective_user
    if user is not None:
        guest_name = getattr(user, "full_name", "") or getattr(user, "first_name", "") or ""
    booking = store_add_booking(
        prop_id, guest_name=guest_name,
        chat_id=update.effective_chat.id, units=units,
    )
    if booking is None:
        await _push_available_properties(
            update, context, lang, original,
            reason=f"The guest tried to book {prop_id} but it is not in the property catalog.",
        )
        return
    if booking.get("error") == "sold_out":
        await _push_available_properties(
            update, context, lang, original,
            reason=f"Booking for {prop_id} was rejected: 0 units left (fully booked).",
        )
        return
    if booking.get("error") == "short":
        await _push_available_properties(
            update, context, lang, original,
            reason=(
                f"Booking for {prop_id} rejected: only "
                f"{booking.get('available', 0)} unit(s) left but the "
                f"guest asked for {booking.get('need', units)}."
            ),
        )
        return
    remaining = 0
    fresh = store_get_property(prop_id)
    if fresh:
        remaining = int(fresh.get("available_units", 0) or 0)
    if result is None:
        result = {
            "intent": "booking",
            "property_id": prop_id,
            "raw_message": original,
            "priority": "medium",
            "needs_human": False,
            "chat_id": update.effective_chat.id,
            "lang": lang,
        }
    else:
        result["intent"] = "booking"
        result["property_id"] = prop_id
        result["raw_message"] = original
    result["booking_id"] = booking["booking_id"]
    _finalize(update, result)
    # Auto-refresh the overview workbook after a booking is saved;
    # failures are logged only.
    try:
        sync_overview()
    except Exception as e:
        print(f"overview_sync: failed to refresh overview after booking: {e}")
    await _reply_text(
        update, context, "booking_intent", lang,
        user_message=original,
        extra_context=(
            f"Booking {booking['booking_id']} for {prop_id} "
            f"({units} unit(s)) created; {remaining} unit(s) left. "
            "Confirm to the guest."
        ),
        prop=prop_id,
        booking=booking["booking_id"],
        units=units,
        avail=remaining,
    )


async def handle_menu_choice(update: Update, context, pending: dict, choice: str):
    """Service menu branch: 1=Book / 2=Availability / 3=Modify / 4=Human agent.

    Uses the cached description of the guest's original message so the reply
    always responds to what they actually asked.
    """
    result = pending["result"]
    original = pending["original_text"]
    lang = pending.get("lang", "en")

    if choice == "1":  # Book
        context.chat_data.pop("pending", None)  # menu choice consumed
        prop_id = result.get("property_id")
        if not prop_id:
            # The guest may have named a property ("Seaview Apartment")
            # without an AD-xxx ID; resolve the name to a real property.
            matched = _match_property(original)
            if matched:
                prop_id = matched["property_id"]
        await _do_booking(update, context, prop_id, original, lang, result)

    elif choice == "2":  # Check availability
        await _availability_reply(update, context, result, lang)
        # Keep the pending menu: a pure query branch does not finalize the
        # request, so the guest can still reply 1/3/4 afterwards (e.g. book
        # after seeing the availability summary).

    elif choice == "3":  # Modify / complaint / other
        context.chat_data.pop("pending", None)  # menu choice consumed
        intent = result.get("intent")
        if intent in ("book_modify", "book_cancel"):
            # Before recording a modify/cancel request, confirm this guest
            # actually HAS a booking, otherwise reply "no booking" so the
            # guest is never misled about their booking status.
            if not _my_confirmed_bookings(update.effective_chat.id):
                await _reply_text(
                    update, context, "no_booking", lang,
                    user_message=original,
                    extra_context=(
                        "The guest asked to modify/cancel a booking but has NO "
                        "confirmed booking on record. Tell them they have no "
                        "bookings and invite them to reply 1 (book) or 2 "
                        "(check availability)."
                    ),
                )
                return
            _finalize(update, result)
            if intent == "book_cancel":
                released = store_release_booking_units(prop_id)
                if released:
                    # Auto-refresh the overview workbook after units are
                    # released by a cancellation; failures are logged only.
                    try:
                        sync_overview()
                    except Exception as e:
                        print(f"overview_sync: failed to refresh overview after cancel: {e}")
                    await _reply_text(
                        update, context, "cancel_refunded", lang,
                        user_message=original,
                        extra_context=(
                            f"Cancelled the latest booking for {prop_id} and "
                            f"released {released} unit(s) back to inventory."
                        ),
                        prop=prop_id,
                    )
                    return
            await _reply_text(
                update, context, "modify_recorded", lang,
                user_message=original,
                extra_context=(
                    f"The {intent} request has been recorded. Tell the guest it is "
                    "logged and will be handled soon."
                ),
                type=INTENT_LABEL[intent][lang],
            )
        elif intent == "complaint":
            _finalize(update, result)
            await _forward_to_admin(update, context, result, note="投诉，已记录并优先处理")
            await _reply_text(
                update, context, "complaint_recorded", lang,
                user_message=original,
                extra_context=(
                    "The complaint has been recorded and will be prioritized. "
                    "Apologize briefly and thank the guest."
                ),
            )
        else:
            _finalize(update, result)
            await _forward_to_admin(update, context, result, note="其他请求，转运营团队跟进")
            await _reply_text(
                update, context, "handover_recorded", lang,
                user_message=original,
                extra_context=(
                    "The request has been recorded and will be handed to the ops "
                    "team for follow-up. Reassure the guest."
                ),
            )

    else:  # "4" Human agent
        context.chat_data.pop("pending", None)  # menu choice consumed
        _finalize(update, result, status="escalated")
        await _forward_to_admin(update, context, result, note="客户选择4-人工处理")
        await _reply_text(
            update, context, "escalated", lang,
            user_message=original,
            extra_context=(
                "The guest escalated to a human agent. Confirm that a human will "
                "contact them soon."
            ),
        )


async def _availability_confirm_input(update: Update, context, pending: dict, text: str, lang: str):
    """Handle the guest's reply to the book-confirmation menu.

    Menu shown after the guest picked a property:
        1 = confirm the booking
        2 = check other available properties
        3 = modify a booking (first check whether this guest HAS one)
        4 = contact a human agent
    Anything else repeats the explicit menu (never re-lists all properties).
    """
    prop_id = pending.get("property_id")
    name = pending.get("name") or prop_id
    original = pending.get("original_text", text)
    result = pending.get("result") or None
    t = text.strip().lower()
    confirm = t in ("1", "yes", "y", "sure", "ok", "book", "book it", "confirm") or t in (
        "确认", "预订", "预定", "好的", "要", "要的", "是的")
    if confirm:
        context.chat_data.pop("pending", None)
        await _do_booking(update, context, prop_id, original, lang, result)
        return
    if t in ("2", "no", "n", "not now", "不用", "不订", "不要", "其他房源", "看看别的", "别的", "查其他", "查询其他"):
        context.chat_data.pop("pending", None)
        await _availability_reply(update, context, result, lang)
        return
    if t in ("3", "modify", "修改", "改", "改期", "改单", "修改预订"):
        context.chat_data.pop("pending", None)
        await _modify_booking_menu(update, context, update.effective_chat.id, original, lang)
        return
    if t in ("4", "human", "人工", "客服", "人工客服", "转人工", "联系人工"):
        context.chat_data.pop("pending", None)
        if result:
            _finalize(update, result, status="escalated")
        await _forward_to_admin(update, context, result or {}, note="客户选择4-联系人工")
        await _reply_text(
            update, context, "escalated", lang,
            user_message=original,
            extra_context=(
                "The guest escalated to a human agent. Confirm that a human "
                "will contact them soon."
            ),
        )
        return
    # Unrecognized reply: repeat the explicit 1/2/3/4 menu with the property
    # name so the guest is never left guessing which options exist.
    context.chat_data.pop("pending", None)
    await _reply_text(
        update, context, "availability_confirm_no", lang,
        user_message=original,
        extra_context=(
            "The guest's reply did not match any menu option. Repeat the "
            "explicit 1/2/3/4 menu; do NOT list all properties again."
        ),
        name=name,
        prop=prop_id,
    )


def _my_confirmed_bookings(chat_id):
    """Confirmed bookings belonging to this chat (identity match on chat_id)."""
    cid = str(chat_id or "").strip()
    if cid.isdigit():
        cid = str(int(cid))
    out = []
    for b in store_list_bookings():
        if str(b.get("chat_id") or "").strip() == cid and b.get("status") == "confirmed":
            out.append(b)
    return out


async def _modify_booking_menu(update: Update, context, chat_id, original, lang):
    """Menu option 3: modify a booking.

    First check whether this guest HAS a confirmed booking, then answer
    "you have X booking(s)" with the list, or "you have no bookings yet"
    so the guest is never misled about their booking status.
    """
    mine = _my_confirmed_bookings(chat_id)
    if not mine:
        await _reply_text(
            update, context, "no_booking", lang,
            user_message=original,
            extra_context=(
                "The guest chose to modify a booking but has NO confirmed "
                "bookings on record. Tell them they have no bookings yet and "
                "invite them to reply 1 (book) or 2 (check availability)."
            ),
        )
        return
    lines = []
    for b in mine:
        pid = b.get("property_id", "?")
        status = "已确认" if lang == "zh" else "confirmed"
        lines.append(f"{b.get('booking_id', '?')} · {pid} · {status}")
    body = "\n".join(lines)
    await _reply_text(
        update, context, "my_bookings", lang,
        user_message=original,
        extra_context=(
            "The guest has confirmed bookings. Show the list below, ask which "
            "one they want to cancel or modify, and offer reply 4 for a human "
            "agent if they need hands-on help.\n" + body
        ),
        count=len(mine),
        body=body,
    )


async def _admin_add_input(update: Update, context, pending: dict, text: str, lang: str):
    """Handle host input during the add-property flow (validate -> write)."""
    if text.strip().lower() in ("cancel", "取消"):
        context.chat_data.pop("pending", None)
        await update.message.reply_text(_t("admin_add_abort", lang))
        return
    parsed = store_parse_property_line(text)
    if not parsed.get("ok"):
        reason = parsed.get("reason") or "need_5_fields"
        await _reply_text(
            update, context, "admin_add_fail_format", lang,
            user_message=text,
            extra_context=(
                f"Add-property parse failed ({reason}); keep the flow alive "
                "and show the format example."
            ),
            reason=REASON_LABEL.get(reason, {}).get(lang, reason),
        )
        return
    saved = store_add_property(parsed["prop"])
    if saved.get("ok"):
        # Auto-refresh the overview workbook after a property is added;
        # failures are logged only.
        try:
            sync_overview()
        except Exception as e:
            print(f"overview_sync: failed to refresh overview after add property: {e}")
        context.chat_data.pop("pending", None)
        p = saved.get("prop", {})
        await _reply_text(
            update, context, "admin_add_ok", lang,
            user_message=text,
            extra_context=(
                f"Host added property {p.get('property_id')} "
                f"({p.get('name')}). Confirm the card."
            ),
            name=p.get("name", ""),
            prop=p.get("property_id", ""),
            desc=p.get("address", ""),
            price=p.get("price_per_night", "?"),
            total=p.get("total_units", "?"),
            avail=p.get("available_units", "?"),
        )
        return
    reason = saved.get("reason") or "write_failed"
    if reason == "duplicate":
        await _reply_text(
            update, context, "admin_add_dup", lang,
            user_message=text,
            extra_context=(
                f"Add-property rejected ({reason}); keep the flow alive and "
                "ask for a different ID."
            ),
            prop=parsed["prop"].get("property_id", ""),
        )
    else:
        await _reply_text(
            update, context, "admin_add_fail_format", lang,
            user_message=text,
            extra_context=(
                f"Add-property rejected ({reason}); keep the flow alive and "
                "let the host retry."
            ),
            reason=REASON_LABEL.get(reason, {}).get(lang, reason),
        )


async def _admin_del_input(update: Update, context, pending: dict, text: str, lang: str):
    """Handle host input during the remove-property flow (ID collection)."""
    if text.strip().lower() in ("cancel", "取消"):
        context.chat_data.pop("pending", None)
        await update.message.reply_text(_t("admin_del_cancel", lang))
        return
    prop_id = text.strip()
    prop = store_get_property(prop_id)
    if prop is None:
        await _reply_text(
            update, context, "admin_del_not_found", lang,
            user_message=text,
            extra_context=(
                f"Host tried to remove {prop_id} but it does not exist; keep "
                "the flow alive and ask for a valid ID."
            ),
            prop=prop_id,
        )
        return
    context.chat_data["pending"] = {"admin_del_confirm": True, "lang": lang, "prop_id": prop_id}
    await _reply_text(
        update, context, "admin_del_confirm", lang,
        user_message=text,
        extra_context=(
            f"Show property {prop_id} details and ask for explicit Y/N "
            "confirmation before deleting the CSV row."
        ),
        name=prop.get("name", ""),
        prop=prop_id,
        price=prop.get("price_per_night", "?"),
        total=prop.get("total_units", "?"),
        avail=prop.get("available_units", "?"),
    )


async def _admin_del_confirm_input(update: Update, context, pending: dict, text: str, lang: str):
    """Handle host Y/N confirmation during the remove-property flow."""
    answer = text.strip().upper()
    prop_id = pending.get("prop_id")
    if answer == "Y":
        context.chat_data.pop("pending", None)
        removed = store_remove_property(prop_id)
        if removed.get("ok"):
            # Auto-refresh the overview workbook after a property is removed;
            # failures are logged only.
            try:
                sync_overview()
            except Exception as e:
                print(f"overview_sync: failed to refresh overview after remove property: {e}")
            p = removed.get("prop", {})
            await _reply_text(
                update, context, "admin_del_ok", lang,
                user_message=text,
                extra_context=(
                    f"Removed property {prop_id}; historical bookings were kept."
                ),
                prop=prop_id,
                name=p.get("name", ""),
            )
        else:
            await _reply_text(
                update, context, "admin_del_not_found", lang,
                user_message=text,
                extra_context=(
                    f"Removal of {prop_id} failed ({removed.get('reason')}); "
                    "tell the host and end the flow."
                ),
                prop=prop_id,
            )
        return
    if answer == "N":
        context.chat_data.pop("pending", None)
        await update.message.reply_text(_t("admin_del_cancel", lang))
        return
    await _reply_text(
        update, context, "admin_del_invalid", lang,
        user_message=text,
        extra_context=(
            "Host replied something other than Y/N during removal confirm; "
            "ask again for Y or N."
        ),
    )


def main():
    if not TOKEN:
        print("Bot token is missing. Set TELEGRAM_TOKEN in .env (or the environment) and retry.")
        return
    if ADMIN_CHAT_ID and not ADMIN_CHAT_ID.isdigit():
        print("WARNING: ADMIN_CHAT_ID is not a numeric chat id; admin forwarding will fail "
              "silently until fixed in .env.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("list_properties", list_properties_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started, listening for messages... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
