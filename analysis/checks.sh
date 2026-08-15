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

echo "[1/4] py_compile"
python -m py_compile config/*.py scripts/*.py tests/*.py

echo "[2/4] grid alignment"
python scripts/90_assert_grid.py --aoi "$AOI"

echo "[3/4] known-site recall"
python scripts/91_recall_gate.py --aoi "$AOI"

# The real inputs are gated behind registration and cannot be downloaded in
# CI, so the ingest stage is exercised against synthetic stand-ins instead.
# Skipped when the geo stack is not installed; nothing else here needs it.
echo "[4/4] ingest (synthetic fixtures)"
if python -c "import rasterio, geopandas" 2>/dev/null; then
  python tests/test_ingest.py
else
  echo "  rasterio/geopandas not installed - skipped"
fi

echo "check: OK"
