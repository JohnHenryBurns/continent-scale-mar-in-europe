# CLAUDE.md — Continent-Scale MAR in Europe

## What this project is

A GIS screening analysis identifying candidate lands for continent-scale managed
aquifer recharge (MAR) in European river basins, supporting the white paper
published at the repo root (`index.html`, docx alongside). The paper's Section 5
contains hand-estimated basin figures; this analysis replaces them with mapped,
ranked candidate recharge districts.

Read `analysis/METHODOLOGY.md` before writing any pipeline code. Read
`docs/milestone-1.md` for the current scope.

## Repo layout

```
index.html, *.docx        # published white paper (GitHub Pages, root). Do not break.
analysis/                 # all pipeline code lives here
  METHODOLOGY.md          # criteria, weights, data sources — the spec
  requirements.txt
  config/grid.py          # CRS, grid, AOI definitions — single source of truth
  scripts/                # numbered pipeline stages
  validation/known_sites.csv
data/                     # gitignored except .gitkeep and small derived outputs
  raw/                    # manual + scripted downloads land here (never committed)
  interim/                # reprojected/clipped layers (never committed)
  outputs/                # final rasters/vectors; commit only small vectors + PNGs
docs/milestone-1.md       # current milestone task list
```

## Hard conventions

- **CRS:** everything in ETRS89-LAEA, EPSG:3035. Reproject on ingest, never mid-pipeline.
- **Grid:** defined once in `analysis/config/grid.py` (resolution, origin, extent per AOI).
  Every raster stage must align to it exactly (same transform, same shape). A stage that
  produces a misaligned raster is a bug, not a warning.
- **Units in names:** every raster filename and every DataFrame column carries units
  (`infil_rate_m_per_yr.tif`, `dist_to_stream_m`). No bare numbers.
- **Quicklooks:** every stage writes a small PNG quicklook of its output to
  `data/outputs/quicklooks/` so results can be eyeballed. A stage without a quicklook
  is not done.
- **Determinism:** identical inputs must produce byte-identical outputs. Pin tile/file
  processing order (sorted paths), pin library versions in requirements.txt, no
  wall-clock timestamps inside output files.
- **Stages are scripts, not notebooks:** `analysis/scripts/NN_name.py`, runnable as
  `python NN_name.py --aoi <name>`, idempotent (skip work if output exists and inputs
  unchanged, `--force` to override).

## Gates (run before any push)

```
make check    # or: bash analysis/checks.sh
```
must exit 0. It runs, at minimum:
1. `python -m py_compile` over analysis/scripts
2. grid-alignment assertion over every raster in data/outputs for the active AOI
3. **known-site recall test:** the current suitability raster must score every
   validation site inside the AOI (analysis/validation/known_sites.csv) in the top
   30% of cells. If the model doesn't light up sites that really exist, the weights
   are wrong — fix the model, never the test, and never edit known_sites.csv to pass.

If `make check` doesn't exist yet, building it is the first task of milestone 1.

## PR discipline

Single-concern PRs with specific commit messages. Pipeline-stage changes and
weight/config changes never share a PR. Pure refactors must be verified
output-identical (re-run the stage, diff the outputs) and say so in the PR body.

## Data handling

- `data/raw/` is never committed (see .gitignore). Some sources are gated behind
  free registration (Copernicus DEM, CORINE); `analysis/scripts/00_fetch_data.py`
  documents the manual steps and verifies expected files exist before the pipeline runs.
- Do not commit anything over ~5 MB. Final candidate polygons (GeoJSON) and
  quicklook PNGs are the committable outputs.
- Respect data licenses: all planned sources are open (Copernicus, EEA, ESDAC,
  HydroSHEDS); keep attribution strings in `analysis/METHODOLOGY.md` current.

## Honest-labeling rule

This is a screening model on coarse public data. Hydrogeology (IHME 1:1.5M) supports
class-level statements only. Travel-time outputs are bands (weeks / months / years /
decades), never numeric days. Any figure, README, or map legend produced by this
pipeline must say "screening-level" and must not present suitability scores as
site-verified. The white paper's credibility depends on this.
