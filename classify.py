
import json
import os
import re

# Default intent keyword lists (Chinese + English, matched against lowercased
# text). Used as a fallback when keywords.json is missing or cannot be parsed.
_DEFAULT_KEYWORDS = {
    "book_modify":  ["改", "修改", "变更", "reschedule", "change", "modify", "edit", "rebook"],
    "book_cancel":  ["取消", "退订", "cancel", "refund", "cancellation"],
    "booking":      ["订", "预订", "预定", "预约", "book", "reserve", "reservation", "rent"],
    "complaint":    ["投诉", "漏水", "坏了", "脏", "差评", "吵", "没热水", "broken", "leak", "complaint", "noisy", "dirty", "no hot water", "maintenance", "not working", "issue", "problem"],
    "availability": ["还有没有房间", "还有房吗", "有房吗", "空房", "有房间吗", "现在有没有房", "available", "vacancy", "availability", "any room", "rooms available", "is there a room", "do you have a room"],
    "status_query": ["进度", "什么时候", "到哪了", "开始", "status", "when", "update", "check", "where is", "arrive", "start"],
    "other":        [],
}

# Path of the external keyword file (same directory as this module).
_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.json")


def _load_keywords() -> dict:
    """Load intent keywords from keywords.json.

    The JSON uses the same structure as the default table (intent -> keyword
    list). Keys present in the file override the default keywords for that
    intent; intents not present keep their defaults. On any load/parse error
    the built-in defaults are used so the bot still works without the file.
    """
    try:
        with open(_DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("keywords.json must contain a JSON object")
        merged = {k: list(v) for k, v in _DEFAULT_KEYWORDS.items()}
        for intent, words in data.items():
            if isinstance(words, list):
                merged[intent] = [str(w) for w in words]
        return merged
    except Exception as e:
        print(f"keywords.json load failed ({e}); using built-in defaults")
        return {k: list(v) for k, v in _DEFAULT_KEYWORDS.items()}


KEYWORDS = _load_keywords()

PRIORITY = {
    "complaint":    "high",
    "book_modify":  "medium",
    "book_cancel":  "medium",
    "booking":      "medium",
    "status_query": "low",
    "availability": "low",
    "other":        "low",
}


def classify(text: str) -> dict:
    """Return a structured dict for the given message (intent/property_id/priority/needs_human)."""
    t = text.lower().strip()

    # 1. Intent detection (first matching keyword wins)
    intent = "other"
    for name, words in KEYWORDS.items():
        if any(w in t for w in words):
            intent = name
            break

    # 2. Extract property ID (AD-1475 / AD1475 / ad 1475)
    property_id = None
    m = re.search(r"(?:AD|ad)[- ]?(\d{3,4})", t)
    if m:
        property_id = f"AD-{m.group(1)}"

    # 3. Priority
    priority = PRIORITY.get(intent, "low")

    # 4. Needs human approval: other / complaint / missing property ID.
    #    Availability queries are auto-recorded even without a property ID.
    needs_human = intent in ("other", "complaint") or (property_id is None and intent != "availability")

    return {
        "intent": intent,
        "property_id": property_id,
        "priority": priority,
        "needs_human": needs_human,
        "raw_message": text,
    }
