"""property_store.py - Property catalog + bookings stored as editable CSV tables.

Primary data source is properties.csv (UTF-8 with BOM so Excel opens it
cleanly). When properties.csv is missing or invalid the module falls back to
the legacy properties.json, so existing setups keep working.

IMPORTANT (real-time sync): the CSV files are re-read on EVERY call; there is
no in-memory cache. Edits made in a spreadsheet are reflected by the Telegram
bot on the next message without restarting the bot.
"""
import csv
import json
import os
import tempfile
import threading
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROPERTIES_CSV = os.path.join(_BASE_DIR, "properties.csv")
_LEGACY_JSON = os.path.join(_BASE_DIR, "properties.json")
_BOOKINGS_CSV = os.path.join(_BASE_DIR, "bookings.csv")

# Serializes every write to properties.csv / bookings.csv so concurrent
# bookings cannot oversell the last unit (two threads race on the same row).
_LOCK = threading.Lock()

PROPERTY_FIELDS = [
    "property_id", "name", "address", "price_per_night",
    "bedrooms", "max_guests", "amenities",
    "total_units", "available_units", "status",
]
BOOKING_FIELDS = [
    "booking_id", "property_id", "guest_name", "chat_id",
    "check_in", "check_out", "status", "created_at",
]


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------

def _read_properties_csv() -> list:
    """Read properties.csv into a list of normalized property dicts ([] on error)."""
    rows = []
    try:
        with open(_PROPERTIES_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                if not raw.get("property_id"):
                    continue
                rows.append(_normalize_property(raw))
    except Exception:
        return []
    return rows


def _normalize_property(raw: dict) -> dict:
    """Convert one CSV row to the same shape as legacy properties.json entries."""

    def to_int(value, default=0):
        try:
            return int(str(value).strip())
        except Exception:
            return default

    amenities = str(raw.get("amenities", "") or "").strip()
    amenities_list = [a.strip() for a in amenities.split(";") if a.strip()]

    # Inventory fields: total_units = number of rooms in this unit type,
    # available_units = how many are still bookable. Legacy rows without the
    # columns are treated as 1 unit / 1 available (status still gates them).
    total_units = to_int(raw.get("total_units"), 1)
    available_units = to_int(raw.get("available_units"), 1)
    if total_units < 1:
        print(f"[property_store] WARNING: {raw.get('property_id')} total_units={total_units} invalid, reset to 1")
        total_units = 1
    if available_units < 0:
        print(f"[property_store] WARNING: {raw.get('property_id')} available_units={available_units} invalid, reset to 0")
        available_units = 0
    if available_units > total_units:
        print(f"[property_store] WARNING: {raw.get('property_id')} available_units={available_units} > total_units={total_units}, capped")
        available_units = total_units

    return {
        "property_id": str(raw.get("property_id", "") or "").strip(),
        "name": str(raw.get("name", "") or "").strip(),
        "address": str(raw.get("address", "") or "").strip(),
        "price_per_night": to_int(raw.get("price_per_night"), 0),
        "bedrooms": to_int(raw.get("bedrooms"), 0),
        "max_guests": to_int(raw.get("max_guests"), 0),
        "amenities": amenities_list,
        "total_units": total_units,
        "available_units": available_units,
        "status": str(raw.get("status", "") or "").strip(),
    }


def _coerce_units(prop: dict) -> dict:
    """Backfill inventory fields for legacy JSON entries that lack them."""
    if prop.get("total_units") is None:
        prop["total_units"] = 1
    if prop.get("available_units") is None:
        prop["available_units"] = 1
    return prop


def _load_legacy_json() -> list:
    """Fallback: read the legacy properties.json format."""
    try:
        with open(_LEGACY_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get("properties", [])
    except Exception:
        pass
    return []


def _load() -> list:
    """Always re-read the current CSV (no cache) so spreadsheet edits are live.

    Falls back to properties.json only when the CSV is missing or unreadable.
    """
    props = _read_properties_csv()
    if props:
        return props
    return _load_legacy_json()


def get_property(property_id):
    """Return the property dict for an ID (case-insensitive) or None."""
    if not property_id:
        return None
    target = str(property_id).strip().upper()
    for p in _load():
        if str(p.get("property_id", "")).strip().upper() == target:
            return _coerce_units(p)
    return None


def list_properties() -> list:
    """Return a copy of the full property catalog (live from CSV)."""
    return [_coerce_units(p) for p in _load()]


def is_available(property_id) -> bool:
    """True when the property exists and its status is 'available'."""
    p = get_property(property_id)
    return bool(p and p.get("status") == "available")


def _atomic_write_properties(rows: list) -> bool:
    """Atomically rewrite properties.csv from a list of normalized dicts.

    Writes to a temp file in the same directory then os.replace()s it into
    place, so a crash mid-write can never leave a truncated properties.csv and
    concurrent readers always see either the old or the new version. Keeps the
    UTF-8 BOM so Excel still opens the file without mojibake.
    """
    try:
        fd, tmp_path = tempfile.mkstemp(dir=_BASE_DIR, prefix=".props_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROPERTY_FIELDS)
                writer.writeheader()
                for p in rows:
                    writer.writerow({
                        "property_id": p.get("property_id", ""),
                        "name": p.get("name", ""),
                        "address": p.get("address", ""),
                        "price_per_night": p.get("price_per_night", ""),
                        "bedrooms": p.get("bedrooms", ""),
                        "max_guests": p.get("max_guests", ""),
                        "amenities": ";".join(p.get("amenities", []) or []),
                        "total_units": p.get("total_units", 1),
                        "available_units": p.get("available_units", 1),
                        "status": p.get("status", ""),
                    })
            os.replace(tmp_path, _PROPERTIES_CSV)
            return True
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False


def set_property_status(property_id: str, status: str) -> bool:
    """Update the status column of one property in properties.csv.

    Returns False when properties.csv does not exist (legacy JSON mode); the
    bot keeps working with the JSON fallback in that case.
    """
    with _LOCK:
        rows = _read_properties_csv()
        if not rows:
            return False
        target = str(property_id).strip().upper()
        changed = False
        for p in rows:
            if str(p.get("property_id", "")).strip().upper() == target:
                p["status"] = status
                changed = True
        if not changed:
            return False
        return _atomic_write_properties(rows)


# --------------------------------------------------------------------------
# Bookings (bookings.csv)
# --------------------------------------------------------------------------

def _ensure_bookings_file():
    """Create bookings.csv with the current header, or upgrade an older file
    that is missing newly added columns (e.g. chat_id) without losing rows.
    """
    if not os.path.exists(_BOOKINGS_CSV):
        with open(_BOOKINGS_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BOOKING_FIELDS)
            writer.writeheader()
        return
    try:
        with open(_BOOKINGS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), None)
    except Exception:
        return
    if header == BOOKING_FIELDS:
        return
    # Header is missing columns -> rewrite preserving all existing rows.
    try:
        with open(_BOOKINGS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            rows = [
                {k: raw.get(k, "") for k in BOOKING_FIELDS}
                for raw in csv.DictReader(f)
            ]
    except Exception:
        return
    with open(_BOOKINGS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BOOKING_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def add_booking(property_id, guest_name="", chat_id="", check_in="", check_out="",
                status="confirmed", auto_occupy=True, units=1):
    """Atomically append a booking and decrement available_units.

    The whole check-then-decrement happens under _LOCK so two concurrent
    booking requests for the last unit can never both succeed (no oversell).
    properties.csv is rewritten with os.replace() for atomicity.

    Returns:
      - the created booking dict on success
      - None when the property does not exist
      - {"error": "sold_out", ...} when 0 units are left
      - {"error": "short", ...} when fewer units are left than requested
    """
    try:
        n = max(1, int(units))
    except Exception:
        n = 1
    target = str(property_id).strip().upper()
    with _LOCK:
        rows = _read_properties_csv()
        if not rows:
            return None
        prop = None
        for p in rows:
            if str(p.get("property_id", "")).strip().upper() == target:
                prop = p
                break
        if prop is None:
            return None
        prop_id = str(prop.get("property_id", "")).strip()
        name = str(prop.get("name", "") or "").strip()
        if str(prop.get("status", "") or "").strip() != "available":
            return {"error": "sold_out", "prop": prop_id, "name": name, "available": 0, "need": n}
        avail = int(prop.get("available_units", 0) or 0)
        if avail < n:
            return {
                "error": "sold_out" if avail <= 0 else "short",
                "prop": prop_id,
                "name": name,
                "available": avail,
                "need": n,
            }
        prop["available_units"] = avail - n
        if not _atomic_write_properties(rows):
            return None

        # Append the booking row; if that fails, roll the unit back.
        _ensure_bookings_file()
        booking_id = _next_booking_id()
        row = {
            "booking_id": booking_id,
            "property_id": prop_id,
            "guest_name": str(guest_name or "").strip(),
            "chat_id": str(chat_id or "").strip(),
            "check_in": str(check_in or "").strip(),
            "check_out": str(check_out or "").strip(),
            "status": status,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            with open(_BOOKINGS_CSV, "a", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=BOOKING_FIELDS).writerow(row)
        except Exception:
            rows2 = _read_properties_csv()
            for p in rows2:
                if str(p.get("property_id", "")).strip().upper() == target:
                    total = int(p.get("total_units", 1) or 1)
                    cur = int(p.get("available_units", 0) or 0)
                    p["available_units"] = min(total, cur + n)
                    break
            _atomic_write_properties(rows2)
            return None
        return row


def release_booking_units(property_id, units=1) -> bool:
    """Return booked units to available_units (booking cancel / modify backfill).

    Clamped to total_units so a release can never oversell the catalog.
    """
    try:
        n = max(1, int(units))
    except Exception:
        n = 1
    target = str(property_id).strip().upper()
    with _LOCK:
        rows = _read_properties_csv()
        if not rows:
            return False
        changed = False
        for p in rows:
            if str(p.get("property_id", "")).strip().upper() == target:
                total = int(p.get("total_units", 1) or 1)
                cur = int(p.get("available_units", 0) or 0)
                p["available_units"] = min(total, cur + n)
                changed = True
        if not changed:
            return False
        return _atomic_write_properties(rows)


def _next_booking_id() -> str:
    """Generate a short human-friendly booking id like BK-20261028-0001."""
    prefix = datetime.now().strftime("BK-%Y%m%d")
    count = 0
    try:
        with open(_BOOKINGS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                if str(raw.get("booking_id", "") or "").startswith(prefix):
                    count += 1
    except Exception:
        pass
    return f"{prefix}-{count + 1:04d}"


def list_bookings() -> list:
    """Return all bookings currently recorded in bookings.csv."""
    rows = []
    try:
        with open(_BOOKINGS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                if raw.get("booking_id") or raw.get("property_id"):
                    rows.append(dict(raw))
    except Exception:
        return []
    return rows


# --------------------------------------------------------------------------
# Host self-service: add / remove properties
# --------------------------------------------------------------------------

def parse_property_line(text: str) -> dict:
    """Parse host input 'ID|Name|Description|Price|TotalUnits'.

    Returns {"ok": True, "prop": {...}} or {"ok": False, "reason": "<key>"}
    where reason is one of: need_5_fields / empty_id / price_not_number /
    price_not_positive / units_not_integer / units_too_small.
    """
    text = (text or "").strip()
    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 5:
        return {"ok": False, "reason": "need_5_fields"}
    pid, name, desc, price_s, units_s = parts
    if not pid:
        return {"ok": False, "reason": "empty_id"}
    try:
        price = int(float(price_s))
    except Exception:
        return {"ok": False, "reason": "price_not_number"}
    if price <= 0:
        return {"ok": False, "reason": "price_not_positive"}
    try:
        total = int(units_s)
    except Exception:
        return {"ok": False, "reason": "units_not_integer"}
    if total < 1:
        return {"ok": False, "reason": "units_too_small"}
    return {
        "ok": True,
        "prop": {
            "property_id": pid.upper(),
            "name": name or pid.upper(),
            "address": desc,
            "price_per_night": price,
            "bedrooms": 1,
            "max_guests": 2,
            "amenities": [],
            "total_units": total,
            "available_units": total,
            "status": "available",
        },
    }


def add_property(prop: dict) -> dict:
    """Append a new property row (host self-service add).

    Returns {"ok": True, "prop": ...} or {"ok": False, "reason": ...} with
    reason in {"empty_id", "duplicate", "write_failed"}.
    """
    pid = str(prop.get("property_id", "") or "").strip()
    if not pid:
        return {"ok": False, "reason": "empty_id"}
    target = pid.upper()
    with _LOCK:
        rows = _read_properties_csv()
        for p in rows:
            if str(p.get("property_id", "") or "").strip().upper() == target:
                return {"ok": False, "reason": "duplicate"}
        rows.append(prop)
        if not _atomic_write_properties(rows):
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True, "prop": prop}


def remove_property(property_id) -> dict:
    """Delete a property row (host self-service remove).

    Historical bookings for that property are deliberately left untouched in
    bookings.csv.

    Returns {"ok": True, "prop": removed} or {"ok": False, "reason": ...}
    with reason in {"not_found", "write_failed"}.
    """
    target = str(property_id).strip().upper()
    with _LOCK:
        rows = _read_properties_csv()
        if not rows:
            return {"ok": False, "reason": "not_found"}
        kept = []
        removed = None
        for p in rows:
            if str(p.get("property_id", "") or "").strip().upper() == target:
                removed = p
            else:
                kept.append(p)
        if removed is None:
            return {"ok": False, "reason": "not_found"}
        if not _atomic_write_properties(kept):
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True, "prop": removed}


# --------------------------------------------------------------------------
# Overview workbook -> CSV back-sync helpers
# --------------------------------------------------------------------------

def _write_bookings_rows(rows: list) -> bool:
    """Atomically rewrite bookings.csv from a list of dicts (keeps BOM)."""
    try:
        fd, tmp_path = tempfile.mkstemp(dir=_BASE_DIR, prefix=".bk_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=BOOKING_FIELDS)
                writer.writeheader()
                for b in rows:
                    writer.writerow({k: b.get(k, "") for k in BOOKING_FIELDS})
            os.replace(tmp_path, _BOOKINGS_CSV)
            return True
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        return False


def update_booking_status(booking_id: str, status: str) -> dict:
    """Change one booking row's status and keep inventory in sync.

    Only 'confirmed' and 'cancelled' are supported:
      confirmed -> cancelled: releases 1 unit back to inventory.
      cancelled -> confirmed: re-occupies 1 unit (fails when fully booked).

    Returns {"ok": True, "booking": ..., "property_id": ..., "old_status": ...}
    or {"ok": False, "reason": ...} with reason in
    {"invalid_status", "not_found", "no_change", "property_not_found",
     "sold_out", "write_failed"}.
    """
    target = str(booking_id or "").strip()
    if status not in ("confirmed", "cancelled"):
        return {"ok": False, "reason": "invalid_status"}
    with _LOCK:
        rows = list_bookings()
        found = None
        for b in rows:
            if str(b.get("booking_id", "") or "").strip() == target:
                found = b
                break
        if found is None:
            return {"ok": False, "reason": "not_found"}
        old = str(found.get("status", "") or "").strip()
        if old == status:
            return {"ok": False, "reason": "no_change"}
        prop_id = str(found.get("property_id", "") or "").strip()
        props = _read_properties_csv()
        prop = None
        for p in props:
            if str(p.get("property_id", "") or "").strip().upper() == prop_id.upper():
                prop = p
                break
        if prop is None:
            return {"ok": False, "reason": "property_not_found"}
        total = int(prop.get("total_units", 1) or 1)
        avail = int(prop.get("available_units", 0) or 0)
        if status == "cancelled":
            prop["available_units"] = min(total, avail + 1)
        else:  # confirmed -> occupy one unit
            if avail < 1:
                return {"ok": False, "reason": "sold_out"}
            prop["available_units"] = avail - 1
        if not _atomic_write_properties(props):
            return {"ok": False, "reason": "write_failed"}
        found["status"] = status
        if not _write_bookings_rows(rows):
            # Roll the inventory change back so the two files stay consistent.
            props2 = _read_properties_csv()
            for p in props2:
                if str(p.get("property_id", "") or "").strip().upper() == prop_id.upper():
                    delta = 1 if status == "cancelled" else -1
                    p["available_units"] = int(p.get("available_units", 0) or 0) - delta
                    break
            _atomic_write_properties(props2)
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True, "booking": found, "property_id": prop_id, "old_status": old}


def update_property_inventory(property_id: str, available_units=None, status=None) -> dict:
    """Edit inventory / status fields of one property row directly.

    available_units is clamped to [0, total_units]; status is written as-is
    (typical values: available / occupied / maintenance). Only fields that
    differ from the current CSV value are applied.

    Returns {"ok": True, "prop": ...} or {"ok": False, "reason": ...} with
    reason in {"no_csv", "not_found", "invalid_units", "units_out_of_range",
    "no_change", "write_failed"}.
    """
    target = str(property_id or "").strip()
    with _LOCK:
        rows = _read_properties_csv()
        if not rows:
            return {"ok": False, "reason": "no_csv"}
        found = None
        for p in rows:
            if str(p.get("property_id", "") or "").strip().upper() == target.upper():
                found = p
                break
        if found is None:
            return {"ok": False, "reason": "not_found"}
        changed = False
        if available_units is not None:
            try:
                val = int(available_units)
            except Exception:
                return {"ok": False, "reason": "invalid_units"}
            total = int(found.get("total_units", 1) or 1)
            if val < 0 or val > total:
                return {"ok": False, "reason": "units_out_of_range"}
            if int(found.get("available_units", 0) or 0) != val:
                found["available_units"] = val
                changed = True
        if status is not None:
            st = str(status or "").strip()
            if st and st != str(found.get("status", "") or "").strip():
                found["status"] = st
                changed = True
        if not changed:
            return {"ok": False, "reason": "no_change"}
        if not _atomic_write_properties(rows):
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True, "prop": found}
