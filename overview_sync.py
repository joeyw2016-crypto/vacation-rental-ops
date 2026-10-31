"""Overview workbook sync script.

Reads properties.csv / bookings.csv / tickets.csv and merges them into
vacation_rental_overview.xlsx with three sheets:
    房源(Properties) / 预订(Bookings) / 工单(Tickets)

- sync_overview(excel_path=None): called by bot.py after data changes.
  It writes a temp file first, then os.replace for atomic replacement so the
  file is not corrupted while Excel has it open. Failures raise and the caller
  (bot.py) catches them so the main flow is unaffected.
- CLI entry: python overview_sync.py [--excel output_path] for a manual refresh.

Requires: openpyxl (sync_overview raises a clear ImportError if missing).
"""

import argparse
import csv
import os
import sys
import tempfile

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover - 由 sync_overview 在真正使用时给出清晰提示
    Workbook = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROPERTIES_CSV = os.path.join(BASE_DIR, "properties.csv")
BOOKINGS_CSV = os.path.join(BASE_DIR, "bookings.csv")
TICKETS_CSV = os.path.join(BASE_DIR, "tickets.csv")
DEFAULT_EXCEL = os.path.join(BASE_DIR, "vacation_rental_overview.xlsx")

# (Sheet 名, 源 CSV 路径)
SHEETS = (
    ("房源(Properties)", PROPERTIES_CSV),
    ("预订(Bookings)", BOOKINGS_CSV),
    ("工单(Tickets)", TICKETS_CSV),
)

MAX_COL_WIDTH = 60


def _read_csv_rows(csv_path):
    """读取 CSV 内容（utf-8-sig 自动剥离 BOM），返回 [表头, 数据行...]。

    数据行按表头列数对齐：超长截断、不足补空；全空行跳过。
    """
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header = rows[0]
    width = len(header)
    out = [header]
    for row in rows[1:]:
        if not row or all(not (c or "").strip() for c in row):
            continue
        aligned = list(row[:width]) + [""] * (width - len(row))
        out.append(aligned)
    return out


def _display_width(value):
    """估算单元格显示宽度：中文等宽字符按 2 计。"""
    s = str(value) if value is not None else ""
    return sum(2 if ord(ch) > 127 else 1 for ch in s)


def _write_sheet(wb, sheet_name, rows):
    ws = wb.create_sheet(title=sheet_name)
    if not rows:
        return ws, 0
    header = rows[0]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows[1:]:
        ws.append(row)
    ws.freeze_panes = "A2"
    # 列宽自适应：表头与数据共同决定
    col_widths = [0] * len(header)
    for r in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for idx, cell in enumerate(r):
            w = _display_width(cell.value)
            if idx < len(col_widths) and w > col_widths[idx]:
                col_widths[idx] = w
    for idx, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = min(w + 2, MAX_COL_WIDTH)
    return ws, ws.max_row - 1  # 数据行数（不含表头）


def sync_overview(excel_path=None):
    """Read the three CSVs and build/refresh the overview Excel, atomically.

    excel_path: output file path; defaults to
        BASE_DIR/vacation_rental_overview.xlsx.
    Returns: {"excel": path, "sheets": {sheet name: data rows}, "total": total}
    Raises on failure (missing file / openpyxl not installed / write error).
    """
    if Workbook is None:
        raise ImportError(
            "openpyxl is not installed. Run: pip install openpyxl"
        )
    target = excel_path or DEFAULT_EXCEL
    target = os.path.abspath(target)

    wb = Workbook()
    wb.remove(wb.active)  # 移除默认空 Sheet

    stats = {}
    total = 0
    for sheet_name, csv_path in SHEETS:
        rows = _read_csv_rows(csv_path)
        _, data_rows = _write_sheet(wb, sheet_name, rows)
        stats[sheet_name] = data_rows
        total += data_rows

    # 先写同目录临时文件，再 os.replace 原子替换：
    # 即使 Excel 正打开着目标文件，也不会中途写坏或报"文件占用"。
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".vacation_rental_overview.", suffix=".xlsx.tmp", dir=os.path.dirname(target)
    )
    os.close(tmp_fd)
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, target)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {"excel": target, "sheets": stats, "total": total}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Refresh the overview workbook "
        "(properties/bookings/tickets -> vacation_rental_overview.xlsx)"
    )
    parser.add_argument(
        "--excel", default=DEFAULT_EXCEL,
        help="Output Excel path (default: vacation_rental_overview.xlsx)"
    )
    args = parser.parse_args(argv)
    try:
        info = sync_overview(excel_path=args.excel)
    except Exception as e:
        print(f"overview_sync: FAILED: {e}", file=sys.stderr)
        return 1
    parts = " | ".join(f"{k}: {v} 行" for k, v in info["sheets"].items())
    print(f"overview_sync: OK -> {info['excel']} ({parts}, 合计 {info['total']} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
