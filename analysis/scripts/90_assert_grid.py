"""90_assert_grid.py — assert every output raster sits on the AOI grid.

A stage that writes a misaligned raster is a bug, not a warning (CLAUDE.md), so
this is a hard gate: any CRS / transform / shape mismatch exits non-zero.

    python 90_assert_grid.py --aoi dti

Rasters are attributed to an AOI by path (``data/outputs/<aoi>/...``) or by
filename prefix (``data/outputs/<aoi>_*.tif``) and checked against that AOI's
grid. Rasters that match no known AOI are checked against --aoi and reported,
since an unattributable output is itself a naming bug.

Exits 0 with a skip message when data/outputs holds no rasters yet.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths  # noqa: E402
from config.grid import aoi_names, grid_for  # noqa: E402

# Sub-millimetre; guards against float noise in georeferencing round-trips.
TRANSFORM_TOL_M = 1e-6


def _transform_tuple(rio_transform) -> tuple:
    """rasterio Affine -> (a, b, c, d, e, f), matching config.grid."""
    t = rio_transform
    return (t.a, t.b, t.c, t.d, t.e, t.f)


def check_raster(tif: Path, aoi: str) -> list[str]:
    """Return a list of human-readable problems (empty == aligned)."""
    import rasterio  # imported lazily: no rasters, no dependency

    grid = grid_for(aoi)
    problems = []
    with rasterio.open(tif) as src:
        if src.crs is None or src.crs.to_string() != grid["crs"]:
            problems.append(
                f"CRS {src.crs.to_string() if src.crs else 'undefined'} "
                f"!= {grid['crs']}"
            )
        if (src.width, src.height) != (grid["width"], grid["height"]):
            problems.append(
                f"shape {src.width}x{src.height} "
                f"!= {grid['width']}x{grid['height']} (width x height)"
            )
        got = _transform_tuple(src.transform)
        want = grid["transform"]
        if any(abs(g - w) > TRANSFORM_TOL_M for g, w in zip(got, want)):
            problems.append(
                "transform "
                + ", ".join(f"{v:.6g}" for v in got)
                + " != "
                + ", ".join(f"{v:.6g}" for v in want)
            )
    return problems


def main(aoi: str) -> int:
    known = set(aoi_names())
    grid_for(aoi)  # validates the active AOI definition itself

    tifs = sorted(paths.OUTPUTS.rglob("*.tif"))  # sorted: determinism
    if not tifs:
        print(f"  no rasters in {paths.OUTPUTS.relative_to(paths.REPO)} yet - skipped")
        return 0

    failures = 0
    for tif in tifs:
        rel = tif.relative_to(paths.REPO)
        owner = paths.owning_aoi(tif, known)
        note = ""
        if owner is None:
            owner, note = aoi, "  (unattributable filename, checked against --aoi)"
        try:
            problems = check_raster(tif, owner)
        except Exception as exc:  # unreadable raster is also a gate failure
            problems = [f"could not open: {exc}"]
        if problems:
            failures += 1
            print(f"  FAIL {rel} [{owner}]{note}")
            for p in problems:
                print(f"         {p}")
        else:
            print(f"  ok   {rel} [{owner}]{note}")

    print(f"  {len(tifs) - failures}/{len(tifs)} rasters aligned")
    if failures:
        print(f"  {failures} misaligned raster(s) - reproject/snap in the stage "
              f"that wrote them, never here")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", default="dti", choices=aoi_names())
    sys.exit(main(ap.parse_args().aoi))
