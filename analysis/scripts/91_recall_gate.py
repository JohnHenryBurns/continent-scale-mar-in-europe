"""91_recall_gate.py — known MAR sites must light up in the suitability raster.

Every validation site tagged with the active AOI must score at or above
`RECALL_MIN_PERCENTILE` (70th, i.e. the top 30% of cells) in
``data/outputs/<aoi>/suitability_score_0to1.tif``.

    python 91_recall_gate.py --aoi dti

If the model does not light up sites that really exist, the weights are wrong:
fix the model. Never relax this threshold and never edit known_sites.csv to
make it pass (CLAUDE.md).

While no suitability raster exists this exits 0 with a skip message. Pass
--require-raster (milestone-1 task 8) to make a missing raster a failure.

Screening-level check: percentile rank against a coarse public-data model, not
site verification.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths  # noqa: E402
from config.grid import CRS, RECALL_MIN_PERCENTILE, aoi_names, grid_for  # noqa: E402

SITES_CSV = Path(__file__).resolve().parents[1] / "validation" / "known_sites.csv"
SITES_CRS = "EPSG:4326"  # known_sites.csv carries lat/lon


def load_sites(aoi: str) -> list[dict]:
    with SITES_CSV.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["aoi"].strip() == aoi]
    rows.sort(key=lambda r: r["name"])  # sorted: determinism
    for r in rows:
        r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
    return rows


def score_sites(raster: Path, sites: list[dict]) -> list[dict]:
    """Attach score + percentile rank (of valid cells) to each site."""
    import numpy as np
    import rasterio
    from pyproj import Transformer

    to_grid = Transformer.from_crs(SITES_CRS, CRS, always_xy=True)
    with rasterio.open(raster) as src:
        band = src.read(1, masked=True)
        valid = band.compressed()
        n_valid = valid.size
        for s in sites:
            x, y = to_grid.transform(s["lon"], s["lat"])
            s["x_m"], s["y_m"] = x, y
            row, col = src.index(x, y)
            if not (0 <= row < src.height and 0 <= col < src.width):
                s["score"], s["percentile"] = None, None
                s["problem"] = "outside the AOI raster"
                continue
            if band.mask.ndim and band.mask[row, col]:
                s["score"], s["percentile"] = None, None
                s["problem"] = "lands on a nodata cell"
                continue
            v = float(band[row, col])
            # Strict "<" -> ties count against the site: the stricter reading.
            s["score"] = v
            s["percentile"] = 100.0 * np.count_nonzero(valid < v) / n_valid
            s["problem"] = None
    return sites


def write_quicklook(raster: Path, sites: list[dict], aoi: str) -> Path | None:
    """Suitability raster with the validation sites plotted on top."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import rasterio
        from rasterio.plot import plotting_extent
    except ImportError:
        return None

    out = paths.quicklook(aoi, "recall_gate")
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster) as src:
        band = src.read(1, masked=True)
        extent = plotting_extent(src)
    fig, ax = plt.subplots(figsize=(6, 6), dpi=110)
    im = ax.imshow(band, extent=extent, cmap="viridis", interpolation="nearest")
    for s in sites:
        if s.get("x_m") is None:
            continue
        ok = s["percentile"] is not None and s["percentile"] >= RECALL_MIN_PERCENTILE
        ax.plot(s["x_m"], s["y_m"], marker="o", markersize=8, markeredgewidth=1.6,
                markerfacecolor="none", markeredgecolor="white" if ok else "red")
        ax.annotate(s["name"], (s["x_m"], s["y_m"]), fontsize=6, color="white",
                    xytext=(6, 4), textcoords="offset points")
    ax.set_title(f"{aoi}: screening-level suitability vs known sites\n"
                 f"(not site-verified)", fontsize=9)
    ax.set_xlabel(f"easting (m, {CRS})", fontsize=7)
    ax.set_ylabel(f"northing (m, {CRS})", fontsize=7)
    ax.tick_params(labelsize=6)
    fig.colorbar(im, ax=ax, shrink=0.7, label="suitability score (0-1)")
    fig.tight_layout()
    fig.savefig(out, metadata={"Software": None})  # no timestamp: determinism
    plt.close(fig)
    return out


def main(aoi: str, require_raster: bool) -> int:
    grid_for(aoi)  # validates the AOI definition
    raster = paths.suitability_raster(aoi)
    rel = raster.relative_to(paths.REPO)

    sites = load_sites(aoi)
    if not sites:
        print(f"  no validation sites tagged aoi={aoi} in "
              f"{SITES_CSV.relative_to(paths.REPO)} - nothing to check")
        return 1 if require_raster else 0

    if not raster.exists():
        msg = f"  no suitability raster at {rel}"
        if require_raster:
            print(f"{msg} - required (--require-raster)")
            return 1
        print(f"{msg} yet - skipped ({len(sites)} site(s) waiting)")
        return 0

    sites = score_sites(raster, sites)
    failures = 0
    for s in sites:
        if s["problem"]:
            failures += 1
            print(f"  FAIL {s['name']}: {s['problem']}")
            continue
        ok = s["percentile"] >= RECALL_MIN_PERCENTILE
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {s['name']}: score {s['score']:.3f}, "
              f"p{s['percentile']:.1f} (need p{RECALL_MIN_PERCENTILE:g}+)")

    ql = write_quicklook(raster, sites, aoi)
    if ql:
        print(f"  quicklook: {ql.relative_to(paths.REPO)}")

    print(f"  {len(sites) - failures}/{len(sites)} known sites in the top "
          f"{100 - RECALL_MIN_PERCENTILE:g}% of cells")
    if failures:
        print("  the model misses sites that really exist - fix the weights/layers, "
              "not this gate")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", default="dti", choices=aoi_names())
    ap.add_argument("--require-raster", action="store_true",
                    help="fail instead of skipping when no suitability raster exists")
    a = ap.parse_args()
    sys.exit(main(a.aoi, a.require_raster))
