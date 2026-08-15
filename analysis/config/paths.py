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
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# MAR_DATA_ROOT redirects the whole data tree, so a stage can be run against
# fixtures without touching the real one. Unset in normal use.
DATA = Path(os.environ.get("MAR_DATA_ROOT") or (REPO / "data")).resolve()
RAW = DATA / "raw"
INTERIM = DATA / "interim"
OUTPUTS = DATA / "outputs"
QUICKLOOKS = OUTPUTS / "quicklooks"

# The combined weighted-overlay raster (06_combine.py writes it, the recall
# gate reads it). Dimensionless 0-1, hence the "0to1" unit tag.
SUITABILITY_BASENAME = "suitability_score_0to1.tif"


def rel(path: Path) -> str:
    """Repo-relative path for printing; absolute when it lies outside the repo
    (which it does when MAR_DATA_ROOT points elsewhere)."""
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


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
    """Which AOI a raster belongs to, or None if unclear.

    Recognised under data/outputs and data/interim alike:
    ``<root>/<aoi>/...`` and ``<root>/<aoi>_<name>.tif``.
    """
    resolved = Path(tif).resolve()
    for root in (OUTPUTS, INTERIM):
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > 1 and rel.parts[0] in aoi_names:
            return rel.parts[0]
        for name in sorted(aoi_names):
            if rel.name.startswith(f"{name}_"):
                return name
    return None
