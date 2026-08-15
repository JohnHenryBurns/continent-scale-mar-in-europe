# Methodology — MAR Screening Pipeline

Goal: for each AOI, produce **ranked candidate recharge districts** — polygons tagged
with estimated intake source, infiltration area (km²), residence-time band, headroom
class, and rough annual capacity (km³/yr) — by combining four layers the standard
MAR-suitability literature does not combine: infiltration suitability, conveyance
cost, storage headroom, and residence-time band.

Prior art: GIS-MCDA MAR suitability mapping is a mature method (INOWAS / TU Dresden
standardized it; IGRAC's MAR portal hosts regional suitability maps; DEEPWATER-CE
produced suitability maps for Central European pilots including the Danube–Tisza
interfluve). We reuse their suitability recipe for layer 1 and add layers 2–4, which
encode this project's specific objective: routing winter/flood water to ground that
returns it to the river months-to-years later.

## Layers

### L1 — Infiltration suitability (0–1)
Weighted overlay of:
- soil texture / hydraulic class (ESDAC topsoil texture; sand+gravel high, clay low)
- land cover (CORINE): dual-use candidates score high — non-irrigated & irrigated
  arable, rice, mineral extraction sites, natural grassland in floodplain; urban,
  forest on steep ground, wetlands-as-is score zero (wetlands are receivers, not basins)
- slope (Copernicus DEM): <1% high, >5% zero
- hydrogeology (IHME 1:1.5M): unconsolidated porous aquifers high; karst and
  crystalline zero (karst noted separately as "unmeterable storage" — excluded)

### L2 — Conveyance cost (cost-distance, € proxy)
Cost-distance from **source points** = river reaches with divertible winter surplus
(EU-Hydro network, Strahler order ≥ 6 for milestone AOIs) and existing canal
offtakes where mapped. Friction = horizontal distance + heavy penalty per meter of
uphill lift (permanent pumping energy). Gravity-reachable cells (downhill or flat
from source) get near-zero cost. Output in meters-equivalent; classed low/med/high.

### L3 — Storage headroom (class)
Proxy for depth-to-water and depletion:
- primary: EEA WISE groundwater body quantitative status — **failing = high headroom
  (best targets)**, good status = check depth
- modifier: distance to dense urban fabric (CORINE) — water tables can't be raised
  under towns; buffer urban areas out
- where national depth-to-groundwater rasters exist for the AOI (e.g., Hungary's
  monitoring network for the DTI), substitute them and say so.

### L4 — Residence-time band (class: weeks / months / years / decades)
travel time ≈ distance-to-receiving-stream ÷ (K·i/n) using class-level hydraulic
conductivity from IHME lithology and regional gradient from the DEM-derived water
table proxy. **Objective band = months-to-years.** "Weeks" cells are wasted budget
(drain back too fast); "decades" cells are donation to the far future — both
downweighted, not zeroed (decades-band cells still serve multi-year drought banking).
This inverts conventional MAR mapping, which rewards proximity to recovery wells.

## Combination

`score = L1 × w1 + L2' × w2 + L3' × w3 + L4' × w4` with primed layers rescaled 0–1,
starting weights `0.35 / 0.25 / 0.20 / 0.20`. Weights live in `config/grid.py`, are
changed only in weight-only PRs, and every weight change must re-run the known-site
recall gate. Candidate districts = contiguous cells above the 80th percentile,
polygonized, ranked by (score × area), tagged with mean values of all four layers
and a capacity estimate: `area_km² × assumed_net_infiltration (10 m/yr screening
figure, i.e. ~30 m/yr gross derated for clogging downtime and wet-season-only
operation)`.

## Validation

`validation/known_sites.csv` holds operating or formally studied MAR sites. Gate:
every known site inside the AOI must fall in the top 30% of the suitability score.
Secondary check for the DTI AOI: visual comparison against the published
DEEPWATER-CE suitability map — broad agreement expected, disagreements documented.

## Data sources (all open)

| Layer | Source | Access |
|---|---|---|
| DEM (30 m) | Copernicus GLO-30 | free registration; manual download documented in 00_fetch_data.py; HydroSHEDS fallback is scriptable |
| Land cover | CORINE 2018 (100 m) | Copernicus Land portal, free registration |
| Soil texture | ESDAC topsoil physical properties | scriptable |
| Hydrogeology | IHME 1500 (BGR) | scriptable (WMS/download) |
| River network | EU-Hydro / HydroRIVERS | scriptable |
| GW body status | EEA WISE WFD database | scriptable |
| Basins/AOIs | HydroBASINS | scriptable |

Attribution: © European Union, Copernicus Land Monitoring Service; ESDAC (JRC);
BGR & UNESCO (IHME1500); EEA; HydroSHEDS (Lehner et al.).

## Known limitations (state in every output)

Screening-level. IHME lithology is 1:1.5M — class-level only. No site geotechnics,
no water-quality screening (turbidity/pretreatment assumed as O&M per the white
paper), no land-ownership or protected-area exclusions yet (Natura 2000 exclusion
is a planned layer, milestone 2). Residence-time bands are order-of-magnitude.
