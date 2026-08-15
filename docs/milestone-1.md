# Milestone 1 — Pipeline bring-up on the Danube–Tisza interfluve (AOI: `dti`)

Why this AOI first: simple geology (wind-blown sand over alluvium), a genuinely
depleted aquifer (the white paper's best storage story), and published
DEEPWATER-CE suitability maps to validate against. Po basin is milestone 2.

Definition of done: `make check` exits 0 with a real recall gate, and
`data/outputs/dti_candidates.geojson` + quicklooks exist and look sane.

Each task below is one PR. Order matters.

1. **Wire the gate.** Implement `analysis/scripts/90_assert_grid.py`
   (every .tif in data/outputs matches the AOI grid transform/shape from
   `config/grid.py`) and `91_recall_gate.py` (known sites with `aoi == active AOI`
   must score ≥ 70th percentile in the suitability raster; exits 0 with a skip
   message while no suitability raster exists). Make `make check` run clean.

2. **Data ingest.** Flesh out `00_fetch_data.py` for the scriptable sources
   (HydroSHEDS, IHME, WISE; ESDAC if the request-link file is present). Add
   `01_ingest.py`: reproject everything to EPSG:3035, clip to the `dti` bounds,
   snap to the grid, write to `data/interim/dti/`. Quicklook per layer.

3. **L1 infiltration suitability.** `02_suitability.py` per METHODOLOGY.md.
   Quicklook + histogram.

4. **L2 conveyance cost.** `03_conveyance.py`: source points from HydroRIVERS
   (order ≥ 6 within/adjacent to AOI), cost-distance with uphill penalty
   (whitebox or scipy). Note: the DTI's defining feature is that it is a ridge
   *above* the Danube — expect high lift costs; that is a finding, not a bug
   (historical replenishment plans died on exactly this pumping cost).

5. **L3 headroom.** `04_headroom.py`: WISE status + urban buffer. If Hungarian
   depth-to-groundwater data is available in data/raw, prefer it and document.

6. **L4 residence band.** `05_residence.py`: distance-to-stream ÷ class-K.
   Output is a 4-class band raster, not numeric days.

7. **Combine + candidates.** `06_combine.py`: weighted overlay per config,
   polygonize ≥ 80th percentile, rank, tag attributes, capacity estimate,
   write `dti_candidates.geojson` (< 5 MB) + final quicklook map with the
   known sites plotted on top.

8. **Validate + write up.** Recall gate now enforced (remove skip path for dti).
   Add `analysis/RESULTS_dti.md`: quicklook figures, top-10 candidate table,
   comparison notes against the DEEPWATER-CE published map, and an honest
   limitations paragraph (screening-level; IHME class-level; no Natura 2000
   exclusion yet).

Backlog (do not start in M1): Natura 2000 exclusion layer; Po AOI; Rhine
tributary AOIs; canal-offtake source points for Po; sensitivity analysis over
WEIGHTS; continental tiling.
