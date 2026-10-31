
import csv
import os
from datetime import datetime

# Absolute path based on this file's location: tickets.csv always lives in
# the project root, no matter what the current working directory is.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_BASE_DIR, "tickets.csv")
FIELDS = [
    "timestamp", "chat_id", "intent", "property_id", "priority",
    "needs_human", "status", "id_key", "raw_message",
]


def _ensure_file():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def _is_valid_ticket(row) -> bool:
    """A valid ticket row must carry a non-blank id_key and at least one other
    non-blank field.

    This filters out blank lines, all-empty-field rows (e.g. ",,,,,,,," left
    by manual CSV editing) and rows whose id_key is empty, so /summary and
    idempotency checks never count garbage rows.
    """
    if not isinstance(row, dict) or not row:
        return False
    if not str(row.get("id_key") or "").strip():
        return False
    for k in FIELDS:
        if k == "id_key":
            continue
        if str(row.get(k) or "").strip():
            return True
    return False


def is_duplicate(id_key: str) -> bool:
    """Idempotency check: return True if id_key already exists."""
    if not os.path.exists(CSV_PATH):
        return False
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not _is_valid_ticket(row):
                continue
            if row.get("id_key") == id_key:
                return True
    return False


def append_ticket(id_key: str, record: dict) -> bool:
    """Append one ticket record to the CSV.

    Returns True when the row was written. When id_key is blank (e.g. the
    caller has no meaningful message to dedupe against), nothing is written:
    writing garbage rows is exactly what makes /summary and idempotency
    checks drift upward.
    """
    _ensure_file()
    if not (id_key or "").strip():
        return False
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": record.get("chat_id", ""),
        "intent": record.get("intent", ""),
        "property_id": record.get("property_id", ""),
        "priority": record.get("priority", ""),
        "needs_human": record.get("needs_human", ""),
        "status": record.get("status", ""),
        "id_key": id_key,
        "raw_message": record.get("raw_message", ""),
    }
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(row)
    return True


def summary_text(lang: str = "en") -> str:
    """/summary output: total tickets + distribution by intent (bilingual)."""
    if not os.path.exists(CSV_PATH):
        return "No tickets yet." if lang == "en" else "暂无工单记录。"
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Only count valid tickets: blank lines / all-empty rows / empty id_key
    # are ignored so hand-edited CSVs never inflate the statistics.
    valid_rows = [r for r in rows if _is_valid_ticket(r)]
    total = len(valid_rows)
    by_intent = {}
    for r in valid_rows:
        k = r.get("intent", "unknown") or "unknown"
        by_intent[k] = by_intent.get(k, 0) + 1
    lines = [f"Total tickets: {total}" if lang == "en" else f"工单总数：{total}"]
    for k, v in sorted(by_intent.items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
