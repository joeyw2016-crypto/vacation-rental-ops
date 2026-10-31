#!/usr/bin/env bash
# One-click refresh of the overview workbook: re-read the three CSVs
# (properties/bookings/tickets) and atomically regenerate
# vacation_rental_overview.xlsx.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

"$PY" overview_sync.py --excel "vacation_rental_overview.xlsx"
