#!/usr/bin/env bash
# Gate: must exit 0 before any push.  Run from anywhere:  make check
# Override the AOI under test with:  AOI=po make check
#
# Every step is a hard gate. Nothing here swallows a failure: the gate scripts
# own their own "not built yet" skip paths and exit 0 for those themselves.
set -euo pipefail
cd "$(dirname "$0")"
AOI="${AOI:-dti}"
echo "AOI: $AOI"

echo "[1/3] py_compile"
python -m py_compile config/*.py scripts/*.py

echo "[2/3] grid alignment"
python scripts/90_assert_grid.py --aoi "$AOI"

echo "[3/3] known-site recall"
python scripts/91_recall_gate.py --aoi "$AOI"

echo "check: OK"
