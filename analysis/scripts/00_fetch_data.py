"""00_fetch_data.py — acquire and verify raw inputs for an AOI.

Scriptable sources are downloaded; gated sources (free registration) are
documented and verified-present. Run:  python 00_fetch_data.py --aoi dti

NOTE for Claude Code: this container's network may be restricted to package
registries. If downloads fail here, this script still serves as the checklist:
tell the user which files to place in data/raw/<source>/ and verify them.
"""
import argparse
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

SCRIPTABLE = {
    # source_dir: (description, url_hint)
    "hydrosheds": (
        "HydroSHEDS DEM 3s + HydroRIVERS + HydroBASINS lev05/06 (Europe)",
        "https://www.hydrosheds.org/products  (direct download links, no login)",
    ),
    "ihme1500": (
        "IHME 1500 International Hydrogeological Map of Europe v1.2 (BGR)",
        "https://www.bgr.bund.de/ihme1500  (shapefile download / WMS)",
    ),
    "esdac_texture": (
        "ESDAC topsoil physical properties (texture) 500m",
        "https://esdac.jrc.ec.europa.eu  (request form, emailed link)",
    ),
    "wise_wfd": (
        "EEA WISE WFD groundwater body status (quantitative)",
        "https://www.eea.europa.eu/data-and-maps  (WFD database download)",
    ),
}

MANUAL = {
    "copernicus_dem": (
        "Copernicus GLO-30 DEM tiles covering the AOI",
        "https://dataspace.copernicus.eu  (free account; download GLO-30 tiles)",
    ),
    "corine2018": (
        "CORINE Land Cover 2018 raster 100m (EU coverage clip is fine)",
        "https://land.copernicus.eu/en/products/corine-land-cover  (free account)",
    ),
}


def status(aoi: str) -> int:
    print(f"AOI: {aoi}\n")
    missing = 0
    for group, table in (("scriptable", SCRIPTABLE), ("manual", MANUAL)):
        print(f"-- {group} sources --")
        for d, (desc, hint) in table.items():
            p = RAW / d
            have = p.exists() and any(p.iterdir())
            print(f"[{'ok' if have else 'MISSING'}] data/raw/{d}/  {desc}")
            if not have:
                print(f"          -> {hint}")
                missing += 1
        print()
    if missing:
        print(f"{missing} source dirs missing. Scriptable ones: implement the "
              f"download in this file (allowed-domain permitting) or fetch "
              f"manually; manual ones: user downloads once, drops files in place.")
    return 1 if missing else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="dti")
    sys.exit(status(ap.parse_args().aoi))
