"""Single source of truth for on-disk locations and output naming.

The gate scripts and the pipeline stages must agree on where things live, so
the conventions are stated once, here.

Layout per AOI::

    data/raw/<source>/                     never committed
    data/interim/<aoi>/<layer>.tif         never committed
    data/outputs/<aoi>/<layer>.tif         never committed (.gitignore: *.tif)
    data/outputs/<aoi>_candidates.geojson  committed
    data/outputs/quicklooks/<aoi>_*.png    committed
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUTPUTS = DATA / "outputs"
QUICKLOOKS = OUTPUTS / "quicklooks"

# The combined weighted-overlay raster (06_combine.py writes it, the recall
# gate reads it). Dimensionless 0-1, hence the "0to1" unit tag.
SUITABILITY_BASENAME = "suitability_score_0to1.tif"


def interim_dir(aoi: str) -> Path:
    return INTERIM / aoi


def outputs_dir(aoi: str) -> Path:
    return OUTPUTS / aoi


def suitability_raster(aoi: str) -> Path:
    return outputs_dir(aoi) / SUITABILITY_BASENAME


def candidates_geojson(aoi: str) -> Path:
    return OUTPUTS / f"{aoi}_candidates.geojson"


def quicklook(aoi: str, name: str) -> Path:
    """Quicklook PNG path, e.g. quicklook("dti", "recall_gate")."""
    return QUICKLOOKS / f"{aoi}_{name}.png"


def owning_aoi(tif: Path, aoi_names) -> str | None:
    """Which AOI a raster under data/outputs belongs to, or None if unclear.

    Recognised: ``data/outputs/<aoi>/...`` and ``data/outputs/<aoi>_<name>.tif``.
    """
    try:
        rel = tif.resolve().relative_to(OUTPUTS)
    except ValueError:
        return None
    if len(rel.parts) > 1 and rel.parts[0] in aoi_names:
        return rel.parts[0]
    for name in sorted(aoi_names):
        if rel.name.startswith(f"{name}_"):
            return name
    return None
