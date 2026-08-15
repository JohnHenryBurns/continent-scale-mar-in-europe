"""01_ingest.py — reproject, clip and snap every raw layer onto the AOI grid.

    python 01_ingest.py --aoi dti
    python 01_ingest.py --aoi dti --layers elevation_m landcover_corine_class
    python 01_ingest.py --aoi dti --force

Rasters are warped straight onto the AOI grid from config/grid.py, so the
output transform and shape are the grid's by construction, not by luck.
Vectors are reprojected to EPSG:3035 and clipped to the AOI bounds, staying
vector — rasterising them needs the class-to-score mapping, which belongs to
the layer stages, not here.

Outputs land in data/interim/<aoi>/ with units in the filename, plus a
quicklook per layer in data/outputs/quicklooks/.

Idempotent: a layer is skipped when its output exists and the SHA-256
fingerprint of its inputs is unchanged. --force overrides.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# GDAL stamps gpkg_contents.last_change with the wall clock, which would make
# every GeoPackage write differ from the last. Pin it: identical inputs must
# produce byte-identical outputs (CLAUDE.md). Set before GDAL is imported.
os.environ.setdefault("OGR_CURRENT_DATE", "1970-01-01T00:00:00.000Z")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths  # noqa: E402
from config.grid import CRS, aoi_names, grid_for  # noqa: E402

# Layer registry. `source` keys match 00_fetch_data.py; `patterns` are globs
# under data/raw/<source>/. Continuous rasters resample bilinear, categorical
# ones nearest — resampling a land-cover code with bilinear invents classes
# that do not exist.
LAYERS = {
    "elevation_m": {
        "kind": "raster",
        "source": ["copernicus_dem", "hydrosheds_dem"],  # first present wins
        "patterns": ["**/*.tif"],
        "resampling": "bilinear",
        "dtype": "float32",
        "nodata": -9999.0,
        "desc": "Ground elevation (m). Copernicus GLO-30 preferred, HydroSHEDS fallback.",
    },
    "landcover_corine_class": {
        "kind": "raster",
        "source": ["corine2018"],
        "patterns": ["**/*.tif"],
        "resampling": "nearest",
        "dtype": "int16",
        "nodata": -32768,
        "desc": "CORINE Land Cover 2018 class code.",
    },
    "topsoil_texture_pct": {
        "kind": "raster",
        "source": ["esdac_texture"],
        "patterns": ["**/*.tif"],
        "resampling": "bilinear",
        "dtype": "float32",
        "nodata": -9999.0,
        "desc": "ESDAC topsoil texture fraction (%). Multi-file sources stack by band.",
        "stack": True,  # keep each input file as its own band, sorted by name
    },
    "rivers_hydrorivers": {
        "kind": "vector",
        "source": ["hydrorivers"],
        "patterns": ["**/HydroRIVERS_v10_eu.shp"],
        "desc": "River network; ORD_STRA carries Strahler order for L2 sources.",
    },
    "basins_hydrobasins": {
        "kind": "vector",
        "source": ["hydrobasins"],
        "patterns": ["**/hybas_eu_lev06_v1c.shp", "**/hybas_eu_lev05_v1c.shp"],
        "desc": "HydroBASINS polygons; the AOI clip polygon is selected from these.",
    },
    "hydrogeology_ihme": {
        "kind": "vector",
        "source": ["ihme1500"],
        "patterns": ["**/*.shp"],
        "desc": "IHME1500 hydrogeological units. Class-level only (1:1.5M).",
    },
    "gwbodies_wise": {
        "kind": "vector",
        "source": ["wise_wfd"],
        "patterns": ["**/*.shp", "**/*.gpkg"],
        "desc": "WISE WFD groundwater bodies; quantitative status drives L3.",
    },
}

FINGERPRINT = ".ingest_fingerprint.json"
CHUNK = 1 << 20


def resolve_inputs(layer: str) -> tuple[str | None, list[Path]]:
    """First source with matching files wins. Returns (source_key, files)."""
    spec = LAYERS[layer]
    for source in spec["source"]:
        root = paths.RAW / source
        if not root.is_dir():
            continue
        hits: set[Path] = set()
        for pattern in spec["patterns"]:
            hits.update(p for p in root.glob(pattern) if p.is_file())
        if hits:
            return source, sorted(hits)  # sorted: determinism
    return None, []


def fingerprint(source: str, files: list[Path], spec: dict) -> str:
    """Hash of the inputs *and* the settings that shape the output."""
    h = hashlib.sha256()
    h.update(json.dumps({
        "source": source,
        "resampling": spec.get("resampling"),
        "dtype": spec.get("dtype"),
        "nodata": spec.get("nodata"),
        "stack": spec.get("stack", False),
    }, sort_keys=True).encode())
    for p in files:  # already sorted
        h.update(p.name.encode())
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
    return h.hexdigest()


def load_fingerprints(aoi: str) -> dict:
    fp = paths.interim_dir(aoi) / FINGERPRINT
    if fp.is_file():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_fingerprints(aoi: str, data: dict) -> None:
    fp = paths.interim_dir(aoi) / FINGERPRINT
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --- raster path -----------------------------------------------------------

def mosaics(files: list[Path], grid: dict):
    """Mosaic `files` in their native CRS, cropped to the AOI window.

    Yields (crs, array, transform, nodata) once per distinct source CRS.

    Warping tile-by-tile and filling gaps afterwards leaves a nodata seam
    along tile joins, because a destination cell straddling the join samples
    outside both tiles. A seam through the DEM would read as a barrier in the
    L2 cost-distance, so tiles are merged *before* the warp instead.

    The crop keeps memory bounded: a continent-wide source is never read whole,
    only the AOI window plus a margin for the resampling kernel.
    """
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    by_crs: dict[str, list[Path]] = {}
    for path in files:  # sorted: determinism
        with rasterio.open(path) as src:
            if src.crs is None:
                raise RuntimeError(
                    f"{path.name} has no CRS; cannot reproject it safely"
                )
            by_crs.setdefault(src.crs.to_string(), []).append(path)

    xmin, ymin, xmax, ymax = grid["bounds"]
    pad = 4 * grid["resolution_m"]
    for crs_str in sorted(by_crs):  # sorted: determinism
        group = by_crs[crs_str]
        window = transform_bounds(CRS, crs_str,
                                  xmin - pad, ymin - pad, xmax + pad, ymax + pad)
        srcs = [rasterio.open(p) for p in group]
        try:
            overlapping = [
                s for s in srcs
                if s.bounds.left < window[2] and s.bounds.right > window[0]
                and s.bounds.bottom < window[3] and s.bounds.top > window[1]
            ]
            if not overlapping:
                continue
            array, mosaic_transform = merge(overlapping, bounds=window)
            yield crs_str, array[0], mosaic_transform, overlapping[0].nodata
        finally:
            for s in srcs:
                s.close()


def ingest_raster(layer: str, files: list[Path], out: Path, aoi: str) -> None:
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    spec = LAYERS[layer]
    grid = grid_for(aoi)
    transform = rasterio.Affine(*grid["transform"])
    height, width = grid["height"], grid["width"]
    resampling = getattr(Resampling, spec["resampling"])
    dtype, nodata = spec["dtype"], spec["nodata"]

    # One band per input file when stacking, otherwise all files mosaic into a
    # single band.
    groups = [[f] for f in files] if spec.get("stack") else [files]
    bands = []
    for group in groups:
        dest = np.full((height, width), nodata, dtype=dtype)
        for src_crs, mosaic, src_transform, src_nodata in mosaics(group, grid):
            scratch = np.full((height, width), nodata, dtype=dtype)
            reproject(
                source=mosaic,
                destination=scratch,
                src_transform=src_transform,
                src_crs=src_crs,
                src_nodata=src_nodata,
                dst_transform=transform,
                dst_crs=CRS,
                dst_nodata=nodata,
                resampling=resampling,
            )
            # Groups fill only what earlier ones left empty, so their order
            # cannot change the result.
            gap = np.isnan(dest) if np.isnan(nodata) else dest == nodata
            dest = np.where(gap, scratch, dest)
        bands.append(dest)

    out.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff", "width": width, "height": height, "count": len(bands),
        "dtype": dtype, "crs": CRS, "transform": transform, "nodata": nodata,
        "compress": "deflate", "predictor": 2, "tiled": True,
    }
    with rasterio.open(out, "w", **profile) as dst:
        for i, band in enumerate(bands, start=1):
            dst.write(band, i)
            if spec.get("stack"):
                dst.set_band_description(i, groups[i - 1][0].stem)


# --- vector path -----------------------------------------------------------

def ingest_vector(layer: str, files: list[Path], out: Path, aoi: str) -> int:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    grid = grid_for(aoi)
    clip = box(*grid["bounds"])

    frames = []
    for src_path in files:  # sorted: determinism
        gdf = gpd.read_file(src_path)
        if gdf.crs is None:
            raise RuntimeError(
                f"{src_path.name} has no CRS; cannot reproject it safely"
            )
        gdf = gdf.to_crs(CRS)
        gdf = gdf[gdf.intersects(clip)]
        if gdf.empty:
            continue
        gdf = gdf.clip(clip)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        frames.append(gdf)

    out.parent.mkdir(parents=True, exist_ok=True)
    # Overwriting a GeoPackage in place replaces the layer but reuses SQLite
    # pages, so the bytes drift run to run. Start from a fresh file.
    out.unlink(missing_ok=True)
    if not frames:
        # An empty layer is a real answer (nothing of this kind in the AOI);
        # write it so downstream stages find a file with the right schema.
        gpd.GeoDataFrame(geometry=[], crs=CRS).to_file(out, driver="GPKG")
        return 0
    merged = pd.concat(frames, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=CRS)
    # Stable row order so repeated runs write the same file.
    merged = merged.sort_values(
        by=list(merged.columns.drop("geometry")), kind="mergesort"
    ).reset_index(drop=True)
    merged.to_file(out, driver="GPKG", layer=layer)
    return len(merged)


# --- quicklook -------------------------------------------------------------

def quicklook(layer: str, out: Path, aoi: str) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    spec = LAYERS[layer]
    grid = grid_for(aoi)
    xmin, ymin, xmax, ymax = grid["bounds"]
    png = paths.quicklook(aoi, layer)
    png.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(5.5, 5.5), dpi=110)
    if spec["kind"] == "raster":
        import numpy as np
        import rasterio
        with rasterio.open(out) as src:
            band = src.read(1, masked=True)
        if band.count():
            lo, hi = (float(np.percentile(band.compressed(), p)) for p in (2, 98))
        else:
            lo, hi = 0.0, 1.0
        im = ax.imshow(band, extent=(xmin, xmax, ymin, ymax), cmap="viridis",
                       vmin=lo, vmax=hi, interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.7, label=layer)
    else:
        import geopandas as gpd
        gdf = gpd.read_file(out)
        if len(gdf):
            gdf.plot(ax=ax, linewidth=0.4, markersize=1, color="#1f77b4",
                     edgecolor="#1f77b4", facecolor="none")
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal")
        ax.text(0.02, 0.02, f"{len(gdf)} features", transform=ax.transAxes,
                fontsize=7, color="#444")

    ax.set_title(f"{aoi}: {layer}\nscreening-level input, not site-verified",
                 fontsize=9)
    ax.set_xlabel(f"easting (m, {CRS})", fontsize=7)
    ax.set_ylabel(f"northing (m, {CRS})", fontsize=7)
    ax.tick_params(labelsize=6)
    fig.tight_layout()
    fig.savefig(png, metadata={"Software": None})  # no timestamp: determinism
    plt.close(fig)
    return png


# --- driver ----------------------------------------------------------------

def main(aoi: str, only: list[str] | None, force: bool) -> int:
    grid_for(aoi)  # validates the AOI definition
    wanted = only or sorted(LAYERS)  # sorted: determinism
    unknown = [ln for ln in wanted if ln not in LAYERS]
    if unknown:
        print(f"unknown layer(s): {', '.join(unknown)}")
        print(f"known: {', '.join(sorted(LAYERS))}")
        return 2

    prints = load_fingerprints(aoi)
    interim = paths.interim_dir(aoi)
    done = skipped = missing = 0

    for layer in wanted:
        spec = LAYERS[layer]
        ext = "tif" if spec["kind"] == "raster" else "gpkg"
        out = interim / f"{layer}.{ext}"
        source, files = resolve_inputs(layer)

        if not files:
            missing += 1
            print(f"  [MISS] {layer}: no input under "
                  f"{'/'.join(spec['source'])} - run 00_fetch_data.py")
            continue

        fp = fingerprint(source, files, spec)
        if out.exists() and prints.get(layer) == fp and not force:
            skipped += 1
            print(f"  [skip] {layer}: unchanged")
            continue

        print(f"  [work] {layer}: {len(files)} file(s) from {source}")
        if spec["kind"] == "raster":
            ingest_raster(layer, files, out, aoi)
            detail = f"{grid_for(aoi)['width']}x{grid_for(aoi)['height']} on grid"
        else:
            n = ingest_vector(layer, files, out, aoi)
            detail = f"{n} feature(s) in AOI"
        png = quicklook(layer, out, aoi)
        prints[layer] = fp
        save_fingerprints(aoi, prints)
        done += 1
        print(f"  [ok  ] {layer}: {detail} -> {paths.rel(out)}")
        if png:
            print(f"         quicklook {paths.rel(png)}")

    print(f"\n{done} ingested, {skipped} unchanged, {missing} missing input")
    if missing:
        print("missing inputs are not a pipeline failure yet - fetch them and "
              "re-run; 00_fetch_data.py lists how")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", default="dti", choices=aoi_names())
    ap.add_argument("--layers", nargs="+", metavar="LAYER",
                    help=f"subset of: {', '.join(sorted(LAYERS))}")
    ap.add_argument("--force", action="store_true",
                    help="re-ingest even if inputs are unchanged")
    a = ap.parse_args()
    sys.exit(main(a.aoi, a.layers, a.force))
