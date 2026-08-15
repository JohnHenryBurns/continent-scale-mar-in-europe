"""Single source of truth: CRS, analysis grids, AOIs, and model weights.

Everything downstream imports from here. Changing a value here is a
config-only PR and must re-run the known-site recall gate (make check).
"""

CRS = "EPSG:3035"  # ETRS89-LAEA

# Analysis grids: (resolution_m, (xmin, ymin, xmax, ymax)) in EPSG:3035.
# Extents are generous bounding boxes; stages clip to the AOI polygon
# (HydroBASINS) after alignment.
AOIS = {
    # Milestone 1: Danube-Tisza interfluve (published DEEPWATER-CE suitability
    # maps exist -> strongest validation story for pipeline bring-up).
    "dti": {
        "resolution_m": 500,
        "bounds": (5_030_000, 2_640_000, 5_210_000, 2_880_000),
        "basin_note": "Duna-Tisza koze, Hungary; clip via HydroBASINS lev06",
    },
    # Milestone 2: Po plain (canal network as existing conveyance).
    "po": {
        "resolution_m": 500,
        "bounds": (4_200_000, 2_380_000, 4_680_000, 2_620_000),
        "basin_note": "Po basin plain section; clip via HydroBASINS lev05",
    },
}

# Overlay weights (see analysis/METHODOLOGY.md "Combination").
WEIGHTS = {
    "infiltration": 0.35,
    "conveyance": 0.25,
    "headroom": 0.20,
    "residence": 0.20,
}

# Candidate districts = cells above this score percentile, polygonized.
CANDIDATE_PERCENTILE = 80

# Screening capacity assumption (net m/yr through active infiltration surface,
# ~30 m/yr gross derated for clogging downtime and seasonal operation).
NET_INFILTRATION_M_PER_YR = 10
