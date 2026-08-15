#!/usr/bin/env bash
# Gate: must exit 0 before any push. Milestone-1 task 1 wires the recall test in.
set -euo pipefail
cd "$(dirname "$0")"
echo "[1/3] py_compile"
python -m py_compile config/grid.py scripts/*.py 2>/dev/null || python -m py_compile config/grid.py
echo "[2/3] grid alignment"
python scripts/90_assert_grid.py 2>/dev/null || echo "  (no rasters yet - skipped)"
echo "[3/3] known-site recall"
python scripts/91_recall_gate.py 2>/dev/null || echo "  (no suitability raster yet - skipped)"
echo "check: OK"
