"""test_ingest.py — exercise 01_ingest.py against synthetic inputs.

    python analysis/tests/test_ingest.py

The real inputs are large and sit behind registration, so none of them are in
the repo and CI cannot download them. This builds tiny stand-ins with the same
shape as the real thing — wrong CRS, wrong resolution, tiled coverage,
categorical codes, features outside the AOI — runs the actual stage against a
throwaway MAR_DATA_ROOT, and checks the promises the stage makes:

  * output rasters land on the AOI grid exactly (CRS, transform, shape)
  * categorical layers keep their class codes (nearest, never bilinear)
  * vectors come out in EPSG:3035, clipped to the AOI bounds
  * a multi-file source stacks to one band per file, in sorted order
  * the preferred DEM source wins over the fallback when both are present
  * re-running is a no-op, --force re-runs, and both are byte-identical
  * a quicklook exists for every ingested layer

Exits 0 when every check passes.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYSIS))

from config.grid import grid_for  # noqa: E402

AOI = "dti"
GRID = grid_for(AOI)
XMIN, YMIN, XMAX, YMAX = GRID["bounds"]
CORINE_CLASSES = [111, 211, 212, 231, 311, 411, 512]

RESULTS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- fixture builders ------------------------------------------------------

def wgs84_window():
    """AOI bounds in lat/lon, padded, so fixtures fully cover the grid."""
    from pyproj import Transformer
    back = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    xs, ys = [], []
    for x in (XMIN, XMAX):
        for y in (YMIN, YMAX):
            lon, lat = back.transform(x, y)
            xs.append(lon)
            ys.append(lat)
    return min(xs) - 0.2, min(ys) - 0.2, max(xs) + 0.2, max(ys) + 0.2


def write_raster(path, arr, bounds, crs, dtype, nodata=None):
    import rasterio
    from rasterio.transform import from_bounds
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = arr.shape
    with rasterio.open(
        path, "w", driver="GTiff", width=w, height=h, count=1, dtype=dtype,
        crs=crs, transform=from_bounds(*bounds, w, h), nodata=nodata,
    ) as dst:
        dst.write(arr.astype(dtype), 1)


def write_vector(path, geoms, attrs, crs="EPSG:4326"):
    import geopandas as gpd
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(attrs, geometry=geoms, crs=crs).to_file(path)


def build_fixtures(raw: Path) -> None:
    import numpy as np
    from shapely.geometry import LineString, Polygon

    lon0, lat0, lon1, lat1 = wgs84_window()
    midlon = (lon0 + lon1) / 2

    # DEM: two lat/lon tiles, west and east, so the mosaic path is exercised.
    for i, (a, b) in enumerate([(lon0, midlon), (midlon, lon1)]):
        yy, xx = np.mgrid[0:120, 0:120]
        write_raster(raw / "copernicus_dem" / f"glo30_tile{i}.tif",
                     (80 + 0.4 * xx + 0.25 * yy + 30 * i).astype("float32"),
                     (a, lat0, b, lat1), "EPSG:4326", "float32", nodata=-32767.0)

    # Fallback DEM, deliberately a different value range: if it leaks into the
    # output we will see it. copernicus_dem must win.
    write_raster(raw / "hydrosheds_dem" / "eu_con_3s.tif",
                 np.full((60, 60), 5000.0, "float32"),
                 (lon0, lat0, lon1, lat1), "EPSG:4326", "float32", nodata=-9999.0)

    # CORINE: already EPSG:3035 but on a 100 m grid offset from ours, with
    # class codes that bilinear resampling would smear into nonsense.
    n = 400
    codes = np.array(CORINE_CLASSES, dtype="int16")
    blocks = np.repeat(np.repeat(
        codes[(np.arange(n // 40)[:, None] + np.arange(n // 40)) % len(codes)],
        40, axis=0), 40, axis=1)[:n, :n]
    write_raster(raw / "corine2018" / "clc2018.tif", blocks,
                 (XMIN - 3300, YMIN - 3300, XMIN - 3300 + n * 100,
                  YMIN - 3300 + n * 100), "EPSG:3035", "int16", nodata=-32768)

    # ESDAC: two files -> two bands, sorted by name (clay before sand).
    for name, base in (("topsoil_clay", 20.0), ("topsoil_sand", 60.0)):
        yy, xx = np.mgrid[0:100, 0:100]
        write_raster(raw / "esdac_texture" / f"{name}.tif",
                     (base + 0.1 * xx).astype("float32"),
                     (lon0, lat0, lon1, lat1), "EPSG:4326", "float32", nodata=-9999.0)

    # Rivers: two inside the AOI, one far outside that must be clipped away.
    inside_a = LineString([(midlon - 0.3, lat0 + 0.3), (midlon - 0.3, lat1 - 0.3)])
    inside_b = LineString([(midlon + 0.2, lat0 + 0.4), (midlon + 0.4, lat1 - 0.4)])
    outside = LineString([(lon1 + 6.0, lat0), (lon1 + 6.5, lat1)])
    write_vector(raw / "hydrorivers" / "HydroRIVERS_v10_eu.shp",
                 [inside_a, inside_b, outside],
                 {"ORD_STRA": [7, 6, 8], "HYRIV_ID": [1, 2, 3]})

    def rect(a, b, c, d):
        return Polygon([(a, b), (c, b), (c, d), (a, d)])

    write_vector(raw / "hydrobasins" / "hybas_eu_lev06_v1c.shp",
                 [rect(lon0 + 0.1, lat0 + 0.1, midlon, lat1 - 0.1),
                  rect(lon1 + 5, lat0, lon1 + 6, lat1)],
                 {"HYBAS_ID": [601, 602]})
    write_vector(raw / "ihme1500" / "ihme1500_v12.shp",
                 [rect(lon0, lat0, midlon, lat1), rect(midlon, lat0, lon1, lat1)],
                 {"AQUIF_TYPE": ["porous", "karst"]})
    write_vector(raw / "wise_wfd" / "gwbodies.shp",
                 [rect(lon0 + 0.2, lat0 + 0.2, lon1 - 0.2, lat1 - 0.2)],
                 {"QUANT_STAT": ["poor"]})


# --- the run ---------------------------------------------------------------

def run_ingest(data_root: Path, *extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, MAR_DATA_ROOT=str(data_root))
    return subprocess.run(
        [sys.executable, "scripts/01_ingest.py", "--aoi", AOI, *extra],
        cwd=ANALYSIS, capture_output=True, text=True, env=env,
    )


def main() -> int:
    import numpy as np
    import geopandas as gpd
    import rasterio
    from rasterio import Affine

    tmp = Path(tempfile.mkdtemp())
    data = tmp / "data"
    try:
        build_fixtures(data / "raw")
        first = run_ingest(data)
        check("stage exits 0", first.returncode == 0,
              first.stdout[-1500:] + first.stderr[-1500:])
        if first.returncode != 0:
            raise SystemExit(report())

        interim = data / "interim" / AOI
        want_t = Affine(*GRID["transform"])

        # every raster on the grid, exactly
        for layer in ("elevation_m", "landcover_corine_class", "topsoil_texture_pct"):
            tif = interim / f"{layer}.tif"
            if not tif.exists():
                check(f"{layer} written", False, "missing")
                continue
            with rasterio.open(tif) as src:
                aligned = (src.crs.to_string() == "EPSG:3035"
                           and (src.width, src.height) == (GRID["width"], GRID["height"])
                           and all(abs(a - b) < 1e-6
                                   for a, b in zip(src.transform, want_t)))
                check(f"{layer} on the AOI grid", aligned,
                      f"{src.crs} {src.width}x{src.height} {tuple(src.transform)[:6]}")
                if layer == "landcover_corine_class":
                    vals = set(np.unique(src.read(1, masked=True).compressed()).tolist())
                    check("corine keeps its class codes (nearest)",
                          vals and vals <= set(CORINE_CLASSES),
                          f"unexpected: {sorted(vals - set(CORINE_CLASSES))}")
                if layer == "topsoil_texture_pct":
                    check("esdac stacks one band per file", src.count == 2,
                          f"count={src.count}")
                    check("esdac bands named in sorted order",
                          list(src.descriptions) == ["topsoil_clay", "topsoil_sand"],
                          str(src.descriptions))
                if layer == "elevation_m":
                    band = src.read(1, masked=True)
                    check("preferred DEM used, not the fallback",
                          band.count() > 0 and float(band.max()) < 1000,
                          f"max={float(band.max()) if band.count() else 'empty'}")
                    # No tolerance here: the fixture tiles abut exactly, so a
                    # single nodata cell means a seam along the tile join, and
                    # a seam reads as a barrier in the L2 cost-distance.
                    check("DEM mosaic has no seam (100% valid)",
                          band.count() == band.size,
                          f"{band.size - band.count()} nodata cell(s) of {band.size}")

        # vectors: reprojected, clipped, non-empty
        for layer, expect in (("rivers_hydrorivers", 2), ("basins_hydrobasins", 1),
                              ("hydrogeology_ihme", 2), ("gwbodies_wise", 1)):
            gpkg = interim / f"{layer}.gpkg"
            if not gpkg.exists():
                check(f"{layer} written", False, "missing")
                continue
            gdf = gpd.read_file(gpkg)
            check(f"{layer} in EPSG:3035", gdf.crs.to_string() == "EPSG:3035",
                  str(gdf.crs))
            check(f"{layer} clipped to AOI ({expect} feature(s))", len(gdf) == expect,
                  f"got {len(gdf)}")
            if len(gdf):
                b = gdf.total_bounds
                check(f"{layer} inside AOI bounds",
                      b[0] >= XMIN - 1 and b[1] >= YMIN - 1
                      and b[2] <= XMAX + 1 and b[3] <= YMAX + 1, str(b))

        # quicklook per layer
        qls = sorted((data / "outputs" / "quicklooks").glob(f"{AOI}_*.png"))
        check("quicklook per ingested layer", len(qls) == 7,
              f"{len(qls)}: {[p.name for p in qls]}")

        # idempotency + determinism
        before = {p.name: sha256(p) for p in sorted(interim.iterdir()) if p.is_file()}
        second = run_ingest(data)
        check("re-run skips unchanged layers",
              second.returncode == 0 and second.stdout.count("[skip]") == 7,
              second.stdout[-800:])
        forced = run_ingest(data, "--force")
        after = {p.name: sha256(p) for p in sorted(interim.iterdir()) if p.is_file()}
        differ = sorted(k for k in before if before[k] != after.get(k))
        check("--force re-runs every layer",
              forced.returncode == 0 and forced.stdout.count("[work]") == 7,
              forced.stdout[-800:])
        check("outputs byte-identical across runs", not differ,
              f"changed: {differ}")

        # a changed input must invalidate the fingerprint
        (data / "raw" / "wise_wfd" / "extra.shp").unlink(missing_ok=True)
        shutil.copy(data / "raw" / "wise_wfd" / "gwbodies.shp",
                    data / "raw" / "wise_wfd" / "gwbodies.shp.bak")
        with open(data / "raw" / "wise_wfd" / "gwbodies.shp", "ab") as fh:
            fh.write(b"\0")
        touched = run_ingest(data)
        check("changed input re-ingests that layer",
              "[work] gwbodies_wise" in touched.stdout, touched.stdout[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report()


def report() -> int:
    bad = 0
    for ok, name, detail in RESULTS:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            bad += 1
            for line in (detail or "").splitlines():
                print(f"         {line}")
    print(f"  {len(RESULTS) - bad}/{len(RESULTS)} ingest checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
