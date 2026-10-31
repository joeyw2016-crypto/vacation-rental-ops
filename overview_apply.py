"""overview_apply.py - Apply edits made in the overview workbook back to CSV.

The overview workbook (vacation_rental_overview.xlsx) is normally generated
FROM the CSVs (see overview_sync.py). This script lets you edit the workbook
directly and push those edits back to the CSV data files, so the Telegram bot
picks them up on the next message (CSVs are re-read live, no restart needed).

Supported edits (other columns are ignored):
  - 预订(Bookings) sheet: change `status` between `confirmed` and `cancelled`.
    * confirmed -> cancelled: booking released, 1 unit returns to inventory.
    * cancelled -> confirmed: re-occupies 1 unit (fails when fully booked).
  - 房源(Properties) sheet: change `available_units` (must stay between 0 and
    total_units) or `status` (e.g. available / occupied / maintenance).

After applying edits the workbook is regenerated so it always matches the
CSVs. Run it after every manual edit of the workbook:

    python3 overview_apply.py [--excel path]

NOTE: the bot regenerates the workbook whenever data changes, so do NOT leave
the workbook half-edited while the bot is busy; edit then run this script
immediately.
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EXCEL = os.path.join(BASE_DIR, "vacation_rental_overview.xlsx")

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None

import property_store


def _find_sheet(wb, *candidates):
    """Return the first sheet whose title contains one of the candidates."""
    for ws in wb.worksheets:
        title = ws.title or ""
        if any(c.lower() in title.lower() for c in candidates):
            return ws
    return None


def _header_index(ws):
    """Map header labels (lowercased) to column indices (0-based)."""
    idx = {}
    for cell in list(ws[1]):
        if cell.value is None:
            continue
        idx[str(cell.value).strip().lower()] = cell.column - 1
    return idx


def _cell(ws, row_idx, col_idx):
    if col_idx is None:
        return None
    v = ws.cell(row=row_idx, column=col_idx + 1).value
    return v


def apply_bookings(wb, report):
    """Push booking status edits from the Bookings sheet back to CSV.

    Returns the set of property_ids whose inventory was touched by a status
    change (upper-cased) so the properties pass can skip those rows: for a
    property with a booking-status change the inventory is driven by that
    change, not by the workbook's (now stale) inventory cell.
    """
    ws = _find_sheet(wb, "预订", "booking")
    affected = set()
    if ws is None:
        report.append("skip: no Bookings sheet found")
        return affected
    idx = _header_index(ws)
    id_col = idx.get("booking_id")
    st_col = idx.get("status")
    if id_col is None or st_col is None:
        report.append("skip: Bookings sheet missing booking_id/status columns")
        return affected
    applied = skipped = 0
    for r in range(2, ws.max_row + 1):
        bid = _cell(ws, r, id_col)
        st = _cell(ws, r, st_col)
        if bid is None or str(bid).strip() == "":
            continue
        status = str(st or "").strip().lower()
        if status not in ("confirmed", "cancelled"):
            if str(st or "").strip():
                report.append(f"skip: {bid} status '{st}' is not confirmed/cancelled")
                skipped += 1
            continue
        res = property_store.update_booking_status(str(bid).strip(), status)
        if res.get("ok"):
            report.append(
                f"booking {bid}: {res['old_status']} -> {status} "
                f"({res.get('property_id', '')})"
            )
            affected.add(str(res.get("property_id", "") or "").upper())
            applied += 1
        elif res.get("reason") == "no_change":
            pass  # already in sync, not worth reporting
        else:
            report.append(f"FAIL booking {bid}: {res.get('reason')}")
            skipped += 1
    if applied:
        report.append(f"bookings applied: {applied}, skipped: {skipped}")
    return affected


def apply_properties(wb, report, skip_avail_for=frozenset()):
    """Push inventory/status edits from the Properties sheet back to CSV.

    skip_avail_for: set of upper-cased property_ids whose inventory cell is
    driven by a booking status change in the same run; for those rows the
    available_units cell is ignored (status edits still apply).
    """
    ws = _find_sheet(wb, "房源", "propert")
    if ws is None:
        report.append("skip: no Properties sheet found")
        return
    idx = _header_index(ws)
    id_col = idx.get("property_id")
    avail_col = idx.get("available_units")
    status_col = idx.get("status")
    if id_col is None:
        report.append("skip: Properties sheet missing property_id column")
        return
    applied = skipped = 0
    for r in range(2, ws.max_row + 1):
        pid = _cell(ws, r, id_col)
        if pid is None or str(pid).strip() == "":
            continue
        prop_id = str(pid).strip()
        avail = _cell(ws, r, avail_col) if avail_col is not None else None
        status = _cell(ws, r, status_col) if status_col is not None else None
        if prop_id.upper() in skip_avail_for:
            # Inventory already moved with the booking status change; the
            # workbook cell is stale by definition.
            avail = None
        if avail is None and (status is None or str(status).strip() == ""):
            continue
        res = property_store.update_property_inventory(
            prop_id,
            available_units=(str(avail).strip() if avail is not None and str(avail).strip() != "" else None),
            status=(str(status).strip() if status is not None and str(status).strip() != "" else None),
        )
        if res.get("ok"):
            p = res.get("prop", {})
            report.append(
                f"property {prop_id}: available_units={p.get('available_units')} "
                f"status={p.get('status')}"
            )
            applied += 1
        elif res.get("reason") == "no_change":
            pass
        else:
            report.append(f"FAIL property {prop_id}: {res.get('reason')}")
            skipped += 1
    if applied:
        report.append(f"properties applied: {applied}, skipped: {skipped}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Apply overview workbook edits back to the CSV data files"
    )
    parser.add_argument(
        "--excel", default=DEFAULT_EXCEL,
        help="Overview workbook path (default: vacation_rental_overview.xlsx)"
    )
    args = parser.parse_args(argv)

    excel = os.path.abspath(args.excel)
    if load_workbook is None:
        print("overview_apply: openpyxl is not installed. Run: pip install openpyxl", file=sys.stderr)
        return 1
    if not os.path.isfile(excel):
        print(f"overview_apply: workbook not found: {excel}", file=sys.stderr)
        return 1

    wb = load_workbook(excel, data_only=True)
    report = []
    affected = apply_bookings(wb, report)
    apply_properties(wb, report, skip_avail_for=affected)
    wb.close()

    if not report:
        print("overview_apply: no edits found")
        return 0

    for line in report:
        print(f"overview_apply: {line}")

    # Regenerate the workbook so it reflects the just-applied CSV state.
    try:
        from overview_sync import sync_overview
        info = sync_overview(excel_path=excel)
        print(f"overview_apply: overview refreshed ({info['excel']}, total {info['total']} rows)")
    except Exception as e:
        print(f"overview_apply: WARNING overview refresh failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
