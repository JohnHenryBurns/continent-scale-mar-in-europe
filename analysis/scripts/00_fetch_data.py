"""00_fetch_data.py — acquire and verify raw inputs for an AOI.

    python 00_fetch_data.py --aoi dti            # report what is present
    python 00_fetch_data.py --aoi dti --download # fetch the scriptable sources
    python 00_fetch_data.py --aoi dti --download --force  # re-fetch

Three kinds of source:

* ``scriptable``  — stable public URL, downloaded and unpacked here.
* ``request``     — free but behind a request form (ESDAC). The user pastes the
                    emailed link into data/raw/<key>/REQUEST_LINK.txt and this
                    script downloads from it.
* ``manual``      — free registration required (Copernicus DEM, CORINE). The
                    user downloads once and drops files in place; we verify.

Exit code is 0 only when every source required by the pipeline is present, so
this doubles as the pre-flight check for 01_ingest.py.

NOTE ON EGRESS: this container reaches package registries only; the data hosts
below are refused by the egress proxy (403 on CONNECT). That is a policy
denial, not a bug — the script reports the blocked host and stops rather than
retrying. Run --download where egress is open, or fetch manually and drop the
files in data/raw/<key>/.
"""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import paths  # noqa: E402
from config.grid import aoi_names  # noqa: E402

# Every source the pipeline reads. `files` are globs that must match under
# data/raw/<key>/ for the source to count as present; they are what 01_ingest.py
# looks for, so keep the two in step.
#
# URLs could not be checked from this container (egress policy). `landing` is
# the stable, citable entry point and is what to trust if a `url` 404s.
SOURCES = {
    "hydrosheds_dem": {
        "kind": "scriptable",
        "desc": "HydroSHEDS v1 conditioned DEM, 3 arc-sec, Europe",
        "landing": "https://www.hydrosheds.org/hydrosheds-core-downloads",
        "url": "https://data.hydrosheds.org/file/hydrosheds-v1-con/eu_con_3s.zip",
        "files": ["**/*.tif"],
        "note": "Fallback DEM. Copernicus GLO-30 is preferred where present.",
    },
    "hydrorivers": {
        "kind": "scriptable",
        "desc": "HydroRIVERS v1.0 river network, Europe (Strahler order attribute)",
        "landing": "https://www.hydrosheds.org/products/hydrorivers",
        "url": "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_eu_shp.zip",
        "files": ["**/HydroRIVERS_v10_eu.shp"],
        "note": "L2 conveyance source points come from ORD_STRA >= 6 reaches.",
    },
    "hydrobasins": {
        "kind": "scriptable",
        "desc": "HydroBASINS v1c standard, Europe, levels 1-12",
        "landing": "https://www.hydrosheds.org/products/hydrobasins",
        "url": "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_eu_lev01-12_v1c.zip",
        "files": ["**/hybas_eu_lev06_v1c.shp"],
        "note": "AOI clip polygon: lev06 for dti, lev05 for po.",
    },
    "ihme1500": {
        "kind": "manual",
        "desc": "IHME1500 International Hydrogeological Map of Europe v1.2 (BGR)",
        "landing": "https://www.bgr.bund.de/EN/Themen/Wasser/Projekte/laufend/Beratung/Ihme1500/ihme1500_projektbeschr_en.html",
        "url": None,
        "files": ["**/*.shp"],
        "note": ("Distributed via the BGR product centre, no stable direct link; "
                 "a WMS also exists. Class-level use only (1:1.5M)."),
    },
    "wise_wfd": {
        "kind": "manual",
        "desc": "EEA WISE WFD groundwater body quantitative status",
        "landing": "https://www.eea.europa.eu/en/datahub/datahubitem-view/"
                   "0c220e15-91cd-4dcc-9d67-1c1b1b1d7b0e",
        "url": None,
        "files": ["**/*.shp", "**/*.gpkg", "**/*.csv"],
        "note": ("EEA datahub links are versioned; take the current WFD2022 "
                 "groundwater body spatial + status export."),
    },
    "esdac_texture": {
        "kind": "request",
        "desc": "ESDAC topsoil physical properties (texture fractions), 500 m",
        "landing": "https://esdac.jrc.ec.europa.eu/content/topsoil-physical-properties-europe-based-lucas-topsoil-data",
        "url": None,  # supplied by the user in REQUEST_LINK.txt
        "files": ["**/*.tif"],
        "note": "Free request form; JRC emails a download link. Paste it into "
                "data/raw/esdac_texture/REQUEST_LINK.txt and re-run --download.",
    },
    "copernicus_dem": {
        "kind": "manual",
        "desc": "Copernicus GLO-30 DEM tiles covering the AOI",
        "landing": "https://dataspace.copernicus.eu",
        "url": None,
        "files": ["**/*.tif"],
        "note": "Free account. Preferred DEM; hydrosheds_dem is the fallback.",
    },
    "corine2018": {
        "kind": "manual",
        "desc": "CORINE Land Cover 2018, 100 m raster",
        "landing": "https://land.copernicus.eu/en/products/corine-land-cover/clc2018",
        "url": None,
        "files": ["**/*.tif"],
        "note": "Free account. EU-wide raster is fine; 01_ingest.py clips it.",
    },
}

# A DEM is required, but either source satisfies it.
EITHER_OR = [("copernicus_dem", "hydrosheds_dem")]
REQUEST_LINK = "REQUEST_LINK.txt"
CHUNK = 1 << 20


def found(key: str) -> list[Path]:
    """Files under data/raw/<key>/ matching the source's globs, sorted."""
    root = paths.RAW / key
    if not root.is_dir():
        return []
    hits: set[Path] = set()
    for pattern in SOURCES[key]["files"]:
        hits.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(hits)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(key: str) -> None:
    """Record what we have, so ingest can fingerprint its inputs."""
    root = paths.RAW / key
    files = found(key)
    manifest = {
        "source": key,
        "files": [
            {"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
             "sha256": sha256(p)}
            for p in files  # already sorted: determinism
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def download(url: str, dest: Path) -> None:
    """Stream `url` to `dest`. Raises with a clear message on a policy denial."""
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            if r.status_code in (403, 407):
                raise RuntimeError(
                    f"egress proxy refused {url} ({r.status_code}). This host is "
                    f"not on the session's allow-list - fetch it outside the "
                    f"container and drop the file in {dest.parent}. Do not retry."
                )
            r.raise_for_status()
            with part.open("wb") as fh:
                for chunk in r.iter_content(CHUNK):
                    fh.write(chunk)
    except requests.exceptions.ProxyError as exc:
        raise RuntimeError(
            f"egress proxy refused a tunnel to {url}: {exc}. Host not allowed "
            f"for this session - fetch manually into {dest.parent}. Do not retry."
        ) from None
    part.replace(dest)


def unpack(archive: Path, into: Path) -> None:
    if not zipfile.is_zipfile(archive):
        return
    with zipfile.ZipFile(archive) as zf:
        for member in sorted(zf.namelist()):  # sorted: determinism
            # Refuse absolute paths and traversal before extracting.
            target = (into / member).resolve()
            if not str(target).startswith(str(into.resolve())):
                raise RuntimeError(f"{archive.name}: unsafe member path {member!r}")
            zf.extract(member, into)
    archive.unlink()  # keep data/raw lean; the manifest records what was in it


def fetch(key: str, force: bool) -> bool:
    """Fetch one source. Returns True if it ended up present."""
    spec = SOURCES[key]
    root = paths.RAW / key
    if found(key) and not force:
        print(f"  [have] {key}")
        return True

    url = spec["url"]
    if spec["kind"] == "request" and url is None:
        link = root / REQUEST_LINK
        if not link.is_file():
            print(f"  [need] {key}: paste the emailed link into "
                  f"{paths.rel(link)}")
            print(f"         request it at {spec['landing']}")
            return False
        url = link.read_text(encoding="utf-8").strip()
        if not url.startswith("https://"):
            print(f"  [need] {key}: {REQUEST_LINK} does not contain an https URL")
            return False

    if url is None:
        print(f"  [need] {key}: manual download -> {spec['landing']}")
        if spec["note"]:
            print(f"         {spec['note']}")
        return False

    if force and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / url.rsplit("/", 1)[-1].split("?")[0]
    print(f"  [get ] {key}: {url}")
    try:
        download(url, archive)
        unpack(archive, root)
    except Exception as exc:
        print(f"  [FAIL] {key}: {exc}")
        return False

    if not found(key):
        print(f"  [FAIL] {key}: downloaded but no file matched "
              f"{spec['files']} - the layout upstream may have changed")
        return False
    write_manifest(key)
    print(f"  [ok  ] {key}: {len(found(key))} file(s)")
    return True


def report(aoi: str, do_download: bool, force: bool) -> int:
    print(f"AOI: {aoi}\nraw data root: {paths.rel(paths.RAW)}\n")
    present = {}
    for key in sorted(SOURCES):  # sorted: determinism
        spec = SOURCES[key]
        hits = found(key)
        if hits and not force:
            present[key] = True
            print(f"  [have] {key:<16} {len(hits)} file(s)  {spec['desc']}")
            continue
        if do_download:
            present[key] = fetch(key, force)
        else:
            present[key] = False
            print(f"  [MISS] {key:<16} {spec['desc']}")
            print(f"         {spec['kind']}: {spec['landing']}")

    satisfied = dict(present)
    for group in EITHER_OR:
        if any(present.get(k) for k in group):
            for k in group:
                satisfied[k] = True

    missing = sorted(k for k, ok in satisfied.items() if not ok)
    print()
    if missing:
        print(f"{len(missing)} source(s) still missing: {', '.join(missing)}")
        if not do_download:
            print("re-run with --download to fetch the scriptable ones")
        for group in EITHER_OR:
            if all(m in missing for m in group):
                print(f"note: {' or '.join(group)} - either one satisfies the DEM "
                      f"requirement")
        return 1
    print("all sources present - ready for 01_ingest.py")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", default="dti", choices=aoi_names())
    ap.add_argument("--download", action="store_true",
                    help="fetch scriptable/request sources (needs open egress)")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if files are already present")
    a = ap.parse_args()
    sys.exit(report(a.aoi, a.download, a.force))
