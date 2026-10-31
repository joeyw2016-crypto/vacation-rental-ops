# Vacation Rental Ops Assistant (Telegram → ClickUp)

An AI-assisted operations bot for vacation rental hosts: guests message a Telegram bot in natural language, the bot classifies the request internally, shows a bilingual service menu (1 = Book / 2 = Check availability / 3 = Modify booking / 4 = Human agent), then processes the guest's choice against their original message, persists every ticket to CSV, and auto-creates ClickUp tasks for follow-up. The configured host additionally sees **5 = Add property / 6 = Remove property** for self-service catalog management, with per-unit inventory (total/available units) tracked atomically to prevent overselling.

Built as a capstone project ("Course 1 & 2: Telegram Vacation Rental Ops Assistant") to demonstrate a production-ready human-in-the-loop automation pipeline.

---

## Architecture

```
Telegram message
      │
      ▼
bot.py (handle_message)
      │
      ├─ classify.py ──► structured JSON (internal, cached)
      │                   { intent, property_id, priority, needs_human, raw_message }
      │
      └─ reply: bilingual service menu
                (1 = Book / 2 = Check availability / 3 = Modify booking / 4 = Human agent)

Guest replies 1 / 2 / 3 / 4  (handle_menu_choice — runs against the cached original description)
      │
      ├─ 1 Book         : with AD-xxx → decrement available_units (atomically, under a write lock), write bookings.csv; without → ask for AD-xxx
      ├─ 2 Availability : with AD-xxx → real property info incl. remaining units;   without → available summary
      ├─ 3 Modify       : book_modify/book_cancel → record + release units on cancel; complaint → prioritize;
      │                   other → hand to ops team
      └─ 4 Human agent  : record with status=escalated, confirm a human will contact

      ▼
_finalize()
      ├─ storage.append_ticket() ──► tickets.csv (idempotent by chat_id + msg hash)
      └─ clickup_client.create_task() ──► ClickUp List (if CLICKUP_ENABLED)

Host (ADMIN_CHAT_ID only) additionally sees 5 / 6 in the menu:
      ├─ 5 Add property : guided input `ID|name|desc|price|units` → validated → append row to properties.csv
      └─ 6 Remove property : input ID → confirm (Y/N) → delete row (historical bookings in bookings.csv are kept)
```

> Internal fields (intent / property / priority) are **never echoed back to the guest** — the bot replies with the service menu first, then handles the branch using the guest's original description.

## Interaction flow (service menu)

Every new guest message goes through the same two-step interaction:

1. **First message** — the bot classifies it internally (`classify()`), caches `{result, original_text, lang}` in `chat_data.pending`, and replies with a **bilingual service menu**:
   - 中文：`请选择服务：1 = 预定 / 2 = 查询房源 / 3 = 修改房源 / 4 = 人工处理`
   - English：`Please choose: 1 = Book / 2 = Check availability / 3 = Modify booking / 4 = Human agent`
   - If the sender is the configured host (`ADMIN_CHAT_ID` in `.env`), the menu additionally shows `5 = 添加房源 / 6 = 删除房源` (Add / Remove property).
2. **Second message** — the guest replies `1`/`2`/`3`/`4`; `handle_menu_choice()` runs the matching branch using the cached **original description** (so the reply always responds to what the guest actually asked):
   - **1 预定 (Book)**: with a property ID → check remaining units (reject with "已订满" when `available_units == 0`), decrement `available_units` (optionally by the units parsed from the guest message, default 1), and create a booking row in `bookings.csv` (all writes under a lock + atomic `os.replace`); without one → ask for an `AD-xxx` ID.
   - **2 查询房源 (Availability)**: with a property ID → read the real record from `property_store` (price / capacity / status / **remaining units**); without one → summarize currently available properties (only those with `available_units > 0`, showing remaining units) and invite the guest to reply 1 to book.
   - **3 修改房源 (Modify)**: `book_modify` / `book_cancel` → record and confirm; on `book_cancel` the booked units are **released back** to `available_units` (capped at `total_units`); `complaint` → record and confirm it will be prioritized; anything else → record and say it will be handed to the ops team.
   - **4 人工处理 (Human agent)**: record the ticket with `status=escalated` and confirm a human will contact them.
3. Any other digit while a menu is pending → `invalid_menu_choice` (请回复 1、2、3 或 4 / Please reply 1, 2, 3, or 4). A non-digit message while a menu is pending is treated as a **new request** (stale pending is cleared).

> Host self-service branches:
> - **5 添加房源 (Add property)**: the bot asks for `房源ID|名称|描述|价格|总间数` (5 fields, `|`-separated). It validates that the ID is non-empty and unique, price is a positive number, total units is an integer ≥ 1, and all 5 fields are present. On success the row is appended to `properties.csv` and a property card is echoed; on a format error the bot shows an example and asks to retry (the conversation is not interrupted; reply `取消` to abort).
> - **6 删除房源 (Remove property)**: the bot asks for a property ID, echoes the current record, then requires an explicit confirmation (`Y` to confirm, `N` to cancel; anything else re-prompts Y/N). On confirmation the row is deleted from `properties.csv`; **historical bookings for that property remain in `bookings.csv` untouched**.
> - **Permission gate**: both branches are reachable only when `ADMIN_CHAT_ID` is configured and matches the sender; otherwise the bot replies `仅房东可操作该功能` and points the user back to the customer menu.

> The availability branch (choice `2`) is a pure query: it **keeps** the pending menu so the guest can still reply `1` (book), `3` (modify) or `4` (human agent) afterwards. Terminal branches (`1`/`3`/`4`) consume the pending menu.

### Reply language (`_effective_lang`)

The reply language is chosen by `detect_lang` + `_effective_lang` in `bot.py`:

- Text containing CJK characters → **Chinese**.
- Text containing Latin letters → **English**.
- Text with **no Latin letters** (digits, punctuation, emoji, symbols) → **keep the conversation's previous language** (`chat_data["lang"]`, default `en` for a brand-new chat). This is what prevents a Chinese conversation from flipping to English when the guest replies `1/2/3/4` — a pure digit contains no CJK characters, so a naive `detect_lang` call would mis-detect it as English.

`handle_message` stores the effective language back into `chat_data["lang"]` on every message. The language is therefore stable across menu choices, while a real English sentence still switches the conversation to English (and a Chinese sentence switches it back). Menu branches (`handle_menu_choice`) reply using the cached `pending["lang"]` from the guest's original message, so the branch replies always match the language the guest started in.

The old approval-menu semantics (1 = confirm / 2 = re-describe / 3 = escalate) have been **removed** and replaced by the service menu above.

### Modules

| Module | Responsibility |
|---|---|
| `bot.py` | Telegram entry point: command handlers (`/start`, `/summary`, `/list_properties`), message handler with the service-menu state machine (menu → branch 1/2/3/4, plus host-only 5/6), availability replies from the property catalog, host add/remove-property flows with permission gating (`ADMIN_CHAT_ID`), finalization (CSV + ClickUp) |
| `classify.py` | Rule-based classifier: keyword intent detection (loaded from `keywords.json`, falls back to built-in defaults) + regex property-ID extraction (`AD-1475` / `AD1475` / `ad 1475`), priority mapping, `needs_human` decision |
| `property_store.py` | Property catalog + bookings access: reads `properties.csv` live on every query (no cache) with `properties.json` fallback; parses `total_units` / `available_units` with defensive correction of illegal values (clamped to `[0, total_units]`); exposes `get_property` / `list_properties` / `is_available` / `add_booking` / `list_bookings` / `release_booking_units` / `add_property` / `remove_property`; all CSV writes go through a module-level `threading.Lock` + atomic `os.replace`, so concurrent bookings cannot oversell |
| `storage.py` | CSV persistence (`tickets.csv`), idempotency check, `/summary` aggregation |
| `clickup_client.py` | ClickUp API v2 client: creates tasks under a configured List; degrades gracefully to CSV-only when not configured |

Data files: `properties.csv` (property catalog — edit it in Excel, saved changes are live on the next query), `bookings.csv` (booking records, written by the bot and editable by hand), and `properties.json` (legacy fallback when `properties.csv` is missing). Config: `keywords.json` (intent keywords, editable without code changes).

### Ticket record (`tickets.csv`)

`timestamp, chat_id, intent, property_id, priority, needs_human, status, id_key, raw_message`

- `id_key = chat_id + md5(raw_message)` → duplicate messages are rejected ("already processed").
- `status`: `done` (recorded via a menu branch) or `escalated` (branch 4 — handed to a human).

---

## Deployment

### 1. Prerequisites

- Python 3.9+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A ClickUp List ID (from any List's URL: `https://app.clickup.com/.../list/901422719848`)

### 2. Install dependencies

```bash
cd vacation_rental_ops
pip install -r requirements.txt
```

Dependencies: `python-telegram-bot`, `requests`, `openpyxl` (see `requirements.txt`).

### 3. Configure credentials

All credentials live in `.env` (excluded by `.gitignore`) and are read from the environment at runtime — no secrets are hard-coded in source files.

```bash
cp .env.example .env
# edit .env and fill in real values
```

| Credential | `.env` key | How to get |
|---|---|---|
| Telegram bot token | `TELEGRAM_TOKEN` | `/newbot` in @BotFather |
| Admin chat ID (host menu 5/6) | `ADMIN_CHAT_ID` | your Telegram numeric ID |
| ClickUp API token | `CLICKUP_TOKEN` | ClickUp Settings → Apps → API token |
| ClickUp List ID | `CLICKUP_LIST_ID` | List URL suffix |
| LLM API key | `LLM_API_KEY` | optional; enables AI-powered replies |

> **Security note:** `.env` is excluded by `.gitignore`, so real tokens/keys are never pushed. `bot.py`, `clickup_client.py` and `llm_reply.py` read credentials only from `.env`/environment with empty or placeholder defaults — safe to publish. ClickUp and LLM are optional: without their credentials the bot gracefully degrades to CSV-only recording and template replies.

### 4. Run

```bash
python3 bot.py
```

The bot prints `Bot 已启动，正在监听消息...` and starts polling.

### 5. Verify end-to-end

1. Send `/start` to the bot → welcome message.
2. Send `现在还有没有房间` → the bot replies with the service menu (`请选择服务：1 = 预定 / 2 = 查询房源 / 3 = 修改房源 / 4 = 人工处理`) — internal fields (类型/房源/优先级) are never echoed.
3. Reply `2` → available-properties summary from the catalog (price / capacity / status).
4. Send `我要改 AD-1475 的预订` → service menu; reply `3` → modification recorded (`book_modify`). Send the same request again and reply `4` instead → escalated (`status=escalated`).
5. Send `/summary` → ticket counts by intent.
6. Open the ClickUp List → a task like `[book_modify] AD-1475` appears with the full JSON in the description.

---

## Classification & LLM Interface

### Configurable keywords (`keywords.json`)

The classifier's intent keywords are **not hard-coded** in `classify.py`. On startup `classify.py` loads them from `keywords.json` (same directory, same structure: intent → keyword list). This lets you add new question patterns **without touching any code**.

- **Edit `keywords.json`** to add keywords for an existing intent. Example: to make `退房` trigger `book_cancel`, add it to that intent's list:

```json
{
  "book_cancel": ["取消", "退订", "退房", "cancel", "refund", "cancellation"]
}
```

- **Add a brand-new intent**: add a new key with its keyword list, then (optionally) add a label for it in `bot.py`'s `INTENT_LABEL` and a priority in `classify.py`'s `PRIORITY` table. Keywords alone work immediately.
- **Fallback**: if `keywords.json` is missing, unreadable, or contains invalid JSON, `classify.py` logs a message and falls back to the built-in default keyword table (identical to what was previously hard-coded), so the bot still runs out of the box.

### Current state: rule-based classifier

`classify.py` uses keyword lists (`改/取消/漏水/投诉/什么时候/...`) + a regex for property IDs + a priority table. Deterministic, zero-cost, offline — good for demos and fixed vocabulary.

### Interface contract (this is what makes LLM swap easy)

Any replacement classifier must expose the same signature and return shape:

```python
def classify(text: str) -> dict:
    # must return:
    # {
    #   "intent":       "book_modify" | "book_cancel" | "booking" | "complaint" | "status_query" | "availability" | "other",
    #   "property_id":  "AD-1475" | None,
    #   "priority":     "high" | "medium" | "low",
    #   "needs_human":  bool,
    #   "raw_message":  text,
    # }
```

Because `bot.py` only depends on this contract, swapping classifiers requires **zero changes** in `bot.py`.

### Option A — plug-in module (recommended)

Create `llm_classify.py` with the same `classify(text)` function, then switch by env var:

```python
# bot.py
import os
from classify import classify as _rule_classify
try:
    if os.environ.get("CLASSIFIER", "rule") == "llm":
        from llm_classify import classify
    else:
        raise ImportError
except ImportError:
    classify = _rule_classify
```

### Option B — replace logic inside classify.py

Keep the signature, swap the body for an LLM call:

```python
import os, json, re
import openai  # or anthropic

def classify(text: str) -> dict:
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    schema = {
        "intent": "book_modify | book_cancel | booking | complaint | status_query | availability | other",
        "property_id": "str or null (e.g. AD-1475)",
        "priority": "high | medium | low",
        "needs_human": "bool",
    }
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Classify vacation rental guest messages. "
                                          "Return ONLY valid JSON matching this schema: " + json.dumps(schema)},
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    # normalize & guarantee contract fields
    result["raw_message"] = text
    result.setdefault("needs_human", result["intent"] in ("other", "complaint") or not result.get("property_id"))
    return result
```

For Claude (Anthropic), swap the client and use `anthropic.Anthropic(api_key=...)` + `client.messages.create(model="claude-3-5-haiku-latest", ...)` with the same JSON-schema prompt.

### What LLM classification unlocks

- Multi-language guests (English/Spanish/French...) without more keyword tables.
- Fuzzy/long natural language, paraphrases, typos.
- Free-form entity extraction (guest name, dates, unit number) beyond `AD-xxxx`.

### Keep in production

- **Fallback chain:** if the LLM call fails or returns non-JSON, fall back to the rule classifier rather than dropping the ticket.
- **Cost/latency:** route simple queries (`status_query`) through rules; use LLM only for ambiguous intents — saves money and keeps the bot snappy.
- **Validation:** re-assert the contract fields and clamp `intent` to the allowed enum after LLM output.

---

## AI-Powered Replies (LLM)

By default the bot replies with the built-in bilingual templates. To enable natural, LLM-generated replies (including graceful answers for unrecognized messages), configure an OpenAI-compatible API:

| Variable | Example | Description |
|---|---|---|
| `LLM_API_KEY` | `sk-...` | Required to enable LLM replies; when unset `LLM_ENABLED=False` and the bot stays on templates |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` or `https://api.openai.com/v1` | Base URL of an OpenAI-compatible API |
| `LLM_MODEL` | `deepseek-chat` or `gpt-4o-mini` | Model name |

Enable it (DeepSeek example):

```bash
export LLM_API_KEY="your_deepseek_key"
export LLM_BASE_URL="https://api.deepseek.com/v1"
export LLM_MODEL="deepseek-chat"
python3 bot.py
```

How it works:

- `llm_reply.py` calls `/chat/completions` with the guest message, an internal classification context (intent / property / priority) and a language hint.
- Replies follow the guest's language (Chinese or English) — `_effective_lang` keeps the language stable for pure-digit replies such as the service menu options 1/2/3/4 — and key details from the templates (service menu options 1/2/3/4, property ID, escalation notice) are preserved.
- Each call has a 15-second timeout. On any error, the bot logs the failure and automatically falls back to the bilingual template — the ticket pipeline (classify → CSV → ClickUp) never depends on the LLM.
- With no `LLM_API_KEY`, the bot behaves exactly as before: template-only, fully offline.

---

## Property Catalog & Bookings (CSV, no code needed)

The bot answers availability questions (`intent == "availability"`) from a real property catalog instead of canned text. The catalog is a plain **CSV table** (`properties.csv`, UTF-8 with BOM so Excel opens it without garbled characters) that you edit in any spreadsheet app — **save the file and the next query already sees the new data** (the store re-reads the CSV on every request; there is no cache).

### File format (`properties.csv`)

Each row is one property; the header row is the field name:

| Column | Type | Meaning |
|---|---|---|
| `property_id` | string | Unique ID, e.g. `AD-101`. Classifier extracts `AD-xxx` from messages; lookup is case-insensitive |
| `name` | string | Display name shown to guests |
| `address` | string | Physical address (informational) |
| `price_per_night` | number | Price per night, rendered as `¥{price}/晚` in replies |
| `bedrooms` | number | Number of bedrooms |
| `max_guests` | number | Maximum number of guests |
| `amenities` | semicolon-separated string | Facility list (informational), e.g. `WiFi;空调;阳台` |
| `status` | string | `available` or `occupied` — drives the "可入住 / 已入住" reply |
| `total_units` | number | Total number of units in this property type (≥ 1). Missing/legacy rows default to `1` |
| `available_units` | number | Currently bookable units (`0`..`total_units`). Decremented on each booking, released back on cancellation. Illegal values (negative or > total) are clamped with a warning |

Example rows (as they look in Excel; 13 demo properties shipped with the repo):

| property_id | name | address | price_per_night | bedrooms | max_guests | amenities | total_units | available_units | status |
|---|---|---|---|---|---|---|---|---|---|
| AD-101 | Seaview Apartment 海景公寓 | 12 Marina Road, Beach Town | 1280 | 2 | 4 | WiFi;Air conditioning;Balcony;Ocean view | 1 | 1 | available |
| AD-1475 | Sunny Villa 阳光别墅 | 88 Hillcrest Ave, Hillside | 2300 | 3 | 6 | WiFi;Private pool;BBQ;Parking | 1 | 1 | available |
| AD-203 | Cozy Studio 温馨单间 | 3 Lantern Lane, Old Town | 680 | 1 | 2 | WiFi;Kitchenette | 1 | 1 | occupied |
| AD-301 | Garden Cottage 花园小屋 | 45 Orchard Lane, Riverside | 980 | 2 | 3 | WiFi;Garden view;Fireplace | 2 | 2 | available |
| AD-302 | Penthouse Suite 顶层套房 | 200 Sky Tower, Downtown | 3200 | 3 | 6 | WiFi;Rooftop terrace;Jacuzzi;City view | 1 | 1 | available |
| AD-303 | Lakeview Cabin 湖景木屋 | 7 Lake Shore Drive, Pine Valley | 1450 | 2 | 4 | WiFi;Lake view;Kayak;BBQ | 3 | 3 | available |
| AD-304 | Modern Loft 现代Loft | 56 Factory Street, Arts District | 1100 | 1 | 2 | WiFi;Smart TV;Gym access | 2 | 1 | available |
| AD-305 | Beachfront Bungalow 海滨平房 | 2 Palm Beach Road, Coastline | 1850 | 2 | 4 | WiFi;Beach access;Surfboard;Balcony | 2 | 2 | available |
| AD-306 | Mountain Retreat 山间度假屋 | 12 Summit Trail, Alpine | 1680 | 3 | 6 | WiFi;Hot tub;Mountain view;Hiking gear | 2 | 2 | available |
| AD-307 | City Studio 城市单间 | 88 Metro Plaza, CBD | 750 | 1 | 2 | WiFi;Washing machine;Near subway | 4 | 4 | available |
| AD-308 | Family Villa 家庭别墅 | 25 Green Park Road, Suburb | 2600 | 4 | 8 | WiFi;Private garden;Kids playground;Parking | 1 | 1 | available |
| AD-309 | Harbor View House 港景之家 | 16 Pier Street, Harbor | 1550 | 3 | 5 | WiFi;Harbor view;Balcony;Parking | 2 | 2 | available |
| AD-310 | Boutique Room 精品客房 | 9 Silk Lane, Heritage Quarter | 820 | 1 | 2 | WiFi;Minibar;Heritage decor | 3 | 3 | available |

### How to add a property (Excel, no code)

1. Open `properties.csv` in Excel / Numbers / WPS.
2. Add a new row with the columns above (set `total_units` and `available_units` — e.g. `3` / `3` for a 3-unit type).
3. **Save the file.** No restart and no code changes needed — the next guest query reflects your edit immediately.

To take a property off the market, set `available_units` to `0` (guests then see "该房型已订满") and/or set `status` to `occupied`; to remove it, delete the row and save. You can also adjust `available_units` directly in Excel — saved changes are live on the next booking/query.

### Booking records (`bookings.csv`)

`bookings.csv` stores one booking per row: `booking_id, property_id, guest_name, check_in, check_out, status, created_at`. It is written by the bot when a guest books through menu branch 1 — `property_store.add_booking()` checks the remaining units, appends the booking row, and **atomically decrements `available_units`** in `properties.csv` (a module-level lock + `os.replace` prevents two concurrent bookings from overselling the last unit). Cancelling through branch 3 calls `release_booking_units()` to put the units back, capped at `total_units`. You can also edit `bookings.csv` by hand (e.g. to adjust dates or add a past booking); note that manual edits do not re-sync inventory by themselves.

### Legacy fallback

`property_store.py` exposes `get_property(property_id)`, `list_properties()`, `is_available(property_id)`, `add_booking(property_id, guest_name=..., units=1)`, `list_bookings()`, `release_booking_units(property_id, units=1)`, `add_property(...)` and `remove_property(property_id)`. If `properties.csv` is missing, it falls back to the legacy `properties.json`; if both are unavailable it returns empty/`None` values and the bot keeps running. Legacy CSV rows without inventory columns are read as `total_units=1, available_units=1` and keep working.

### Bot integration

- `/list_properties` lists all properties with availability status and remaining units (bilingual).
- In service-menu branch 2, a recognized property ID replies with real price/capacity/status/**remaining units**, e.g. `AD-101 剩余 3 间，¥1280/晚，可住4人`; when `available_units == 0` the property is shown as 已订满.
- In service-menu branch 2 without a property ID, the bot summarizes currently available properties (only those with remaining units > 0) and invites the guest to reply 1 to book.
- In service-menu branch 1 (Book), the bot checks remaining units, decrements `available_units` atomically, creates the booking, replies with the order number, and shows the new remaining count. If no units remain it replies `该房型已订满` and refuses the booking (no overselling); if the guest asked for more units than remain it shows the shortfall.
- Host branches 5/6 (Add/Remove property) are gated by `ADMIN_CHAT_ID` — non-hosts see neither menu items nor the management flows.

---

## Production Hardening Checklist

| Area | Recommendation |
|---|---|
| **Human notification** | Escalation (`status=escalated`) currently replies in-chat only. Push to a Slack channel / email / Telegram admin group so a human is actually paged. |
| **Multi-language** | Either via LLM classifier or an i18n reply layer (`bot.py` reply strings → `gettext`/dict). |
| **Auth / allowlist** | Host-only management (menu 5/6, add/remove property) is gated by `ADMIN_CHAT_ID`. For guest traffic, gate the bot to known `chat_id`s (host + staff) to prevent strangers from creating tasks; protect `/summary` and admin commands with role checks. |
| **Logging & monitoring** | `bot.log` today only captures ClickUp task results. Add structured logging (intent, latency, errors), error alerts, and a simple metrics endpoint (tickets/day, intent distribution). |
| **Credential security** | Move the Telegram token out of `bot.py` into env vars / `.env` (already gitignored). Rotate any token that was committed. |
| **Storage upgrade** | CSV is fine for a demo; move to SQLite/Postgres when volume grows. |
| **ClickUp resilience** | `create_task` already has try/except (CSV still wins if ClickUp fails). Add retry with backoff and idempotency (task keyed by `id_key`) to avoid duplicate tasks on retry. |
| **Deployment mode** | Switch from long-polling to webhook (`app.run_webhook()`) behind a reverse proxy; run under systemd/Docker with a process manager. |

---

## Roadmap

- [x] Rule-based classification (Course 1)
- [x] CSV persistence + idempotency + `/summary` (Course 1)
- [x] Human approval flow (Course 1) — replaced by the service-menu flow (1/2/3/4), see "Interaction flow (service menu)"
- [x] ClickUp integration (Course 2)
- [x] Per-unit inventory (`total_units` / `available_units`) with atomic booking decrement + cancel release (no overselling)
- [x] Host self-service add/remove property, gated by `ADMIN_CHAT_ID`
- [ ] LLM classifier (Claude / OpenAI) behind the same contract
- [ ] Slack/email escalation notifications
- [ ] Multi-language replies
- [ ] Webhook deployment + Docker
