"""sync_back.py - Single-table maintenance entry (xlsx -> CSV back-sync).

vacation_rental_overview.xlsx is the single source of truth for daily edits.
Edits are written back to the CSV master files, then the overview workbook is
rebuilt so everything stays consistent:

- 房源(Properties) sheet -> properties.csv (full overwrite; the
  available_units column is IGNORED and recomputed from confirmed bookings)
- 预订(Bookings) sheet -> bookings.csv (full overwrite; rows are validated:
  booking_id / property_id required, status in {confirmed, cancelled}; invalid
  rows are skipped and reported)
- 工单(Tickets) sheet is READ-ONLY (tickets.csv is maintained by the bot)

CLI: python3 sync_back.py [--excel PATH]
"""

import argparse
import sys

from openpyxl import load_workbook

from property_store import (
    _atomic_write_properties,
    _write_bookings_rows,
)
from overview_sync import sync_overview, DEFAULT_EXCEL

SHEET_PROPERTIES = "房源(Properties)"
SHEET_BOOKINGS = "预订(Bookings)"
SHEET_TICKETS = "工单(Tickets)"

ALLOWED_STATUSES = ("confirmed", "cancelled")


def _to_int(value, default=None):
    """Coerce int-like values (int / float / numeric string) to int."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else default
    try:
        return int(str(value).strip())
    except ValueError:
        try:
            return int(float(str(value).strip()))
        except Exception:
            return default


def _sheet_rows(wb, sheet_name):
    """Read one sheet into header-keyed dicts, skipping fully-empty rows."""
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for r in rows[1:]:
        vals = ["" if v is None else str(v).strip() for v in r]
        if not any(vals):
            continue
        out.append(
            {header[i]: vals[i] if i < len(vals) else "" for i in range(len(header))}
        )
    return out


def _parse_bookings(rows):
    """Validate booking rows; returns (valid_rows, errors)."""
    valid, errors = [], []
    for i, row in enumerate(rows, start=2):  # Excel row 1 is the header
        booking_id = str(row.get("booking_id", "") or "").strip()
        prop_id = str(row.get("property_id", "") or "").strip()
        status = str(row.get("status", "") or "").strip()
        if not booking_id:
            errors.append(f"预订 Sheet 第 {i} 行：booking_id 为空，已跳过")
            continue
        if not prop_id:
            errors.append(f"预订 Sheet 第 {i} 行：property_id 为空，已跳过")
            continue
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"预订 Sheet 第 {i} 行：status={status!r} 非法"
                "（仅允许 confirmed/cancelled），已跳过"
            )
            continue
        valid.append({
            "booking_id": booking_id,
            "property_id": prop_id,
            "guest_name": str(row.get("guest_name", "") or "").strip(),
            "chat_id": str(row.get("chat_id", "") or "").strip(),
            "check_in": str(row.get("check_in", "") or "").strip(),
            "check_out": str(row.get("check_out", "") or "").strip(),
            "status": status,
            "created_at": str(row.get("created_at", "") or "").strip(),
        })
    return valid, errors


def _parse_properties(rows):
    """Validate property rows; returns (valid_rows, errors)."""
    valid, errors = [], []
    for i, row in enumerate(rows, start=2):
        prop_id = str(row.get("property_id", "") or "").strip()
        if not prop_id:
            errors.append(f"房源 Sheet 第 {i} 行：property_id 为空，已跳过")
            continue
        total_units = _to_int(row.get("total_units"))
        if total_units is None or total_units < 1:
            errors.append(
                f"房源 Sheet 第 {i} 行：total_units={row.get('total_units')!r}"
                " 非正整数，已跳过"
            )
            continue
        amenities_raw = str(row.get("amenities", "") or "").strip()
        amenities = [a.strip() for a in amenities_raw.split(";") if a.strip()]
        valid.append({
            "property_id": prop_id,
            "name": str(row.get("name", "") or "").strip(),
            "address": str(row.get("address", "") or "").strip(),
            "price_per_night": _to_int(row.get("price_per_night"), 0),
            "bedrooms": _to_int(row.get("bedrooms"), 0),
            "max_guests": _to_int(row.get("max_guests"), 0),
            "amenities": amenities,
            "total_units": total_units,
            # available_units is recomputed below from confirmed bookings.
            "available_units": total_units,
            "status": str(row.get("status", "") or "").strip(),
        })
    return valid, errors


def _recompute_available(properties, bookings):
    """available_units = total_units - confirmed bookings, floored at 0."""
    confirmed = {}
    for b in bookings:
        if b["status"] == "confirmed":
            key = str(b["property_id"]).strip().upper()
            confirmed[key] = confirmed.get(key, 0) + 1
    for p in properties:
        key = str(p["property_id"]).strip().upper()
        total = int(p.get("total_units", 1) or 1)
        used = confirmed.get(key, 0)
        p["available_units"] = max(0, total - used)


def back_sync(excel_path=None):
    """Back-sync xlsx -> CSVs, then rebuild the overview workbook.

    Returns a report dict:
      {"excel": path, "bookings_written": N, "properties_written": N,
       "inventory": {prop_id: {"total": N, "available": M}},
       "errors": [...]}
    Raises on fatal errors (missing sheet / CSV write failure).
    """
    path = excel_path or DEFAULT_EXCEL
    wb = load_workbook(path)

    bookings, booking_errors = _parse_bookings(_sheet_rows(wb, SHEET_BOOKINGS))
    properties, prop_errors = _parse_properties(_sheet_rows(wb, SHEET_PROPERTIES))
    errors = booking_errors + prop_errors

    _recompute_available(properties, bookings)

    # 工单(Tickets) is read-only: tickets.csv stays owned by the bot.
    if not _write_bookings_rows(bookings):
        raise RuntimeError("failed to write bookings.csv")
    if not _atomic_write_properties(properties):
        raise RuntimeError("failed to write properties.csv")

    # Rebuild the overview workbook so xlsx matches the CSVs again
    # (available_units now shows the recomputed values).
    info = sync_overview(excel_path=path)

    inventory = {
        p["property_id"]: {
            "total": p["total_units"],
            "available": p["available_units"],
        }
        for p in properties
    }
    return {
        "excel": info["excel"],
        "bookings_written": len(bookings),
        "properties_written": len(properties),
        "inventory": inventory,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Back-sync vacation_rental_overview.xlsx to the CSV master "
        "files, then rebuild the overview workbook"
    )
    parser.add_argument(
        "--excel", default=DEFAULT_EXCEL,
        help="Input overview Excel path (default: vacation_rental_overview.xlsx)"
    )
    args = parser.parse_args(argv)
    try:
        report = back_sync(excel_path=args.excel)
    except Exception as e:
        print(f"sync_back: FAILED: {e}", file=sys.stderr)
        return 1
    print(f"sync_back: 写入预订 {report['bookings_written']} 行 | "
          f"写入房源 {report['properties_written']} 行")
    for pid, inv in report["inventory"].items():
        print(f"  inventory {pid}: total={inv['total']} available={inv['available']}")
    if report["errors"]:
        for e in report["errors"]:
            print(f"  [跳过] {e}")
    print(f"sync_back: 总览已重建 -> {report['excel']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
