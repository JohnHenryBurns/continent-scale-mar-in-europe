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
        # Covers the Duna-Tisza koze (approx. 18.6-20.4E, 45.85-47.65N) plus a
        # margin, so both bounding rivers are inside the box: L2 conveyance
        # source points sit on the Danube (west) and the Tisza (east), and an
        # AOI that excludes them has no intake to route water from. Derived by
        # projecting a densified lat/lon envelope to EPSG:3035 and rounding
        # outward to 5 km; a lat/lon box is a curved quadrilateral in LAEA, so
        # the corners alone would clip the edges.
        "bounds": (4_965_000, 2_560_000, 5_130_000, 2_785_000),
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

# Known-site recall gate: every validation site inside the AOI must score at or
# above this percentile of the suitability raster (i.e. top 30% of cells).
RECALL_MIN_PERCENTILE = 70


# --- derived grid geometry -------------------------------------------------
# Pure derivations of the values above; no new numbers are introduced here.
# Every raster stage must align to grid_for(aoi) exactly.


class GridError(ValueError):
    """AOI grid definition is not self-consistent."""


def aoi_names():
    """AOI keys, sorted for deterministic iteration."""
    return sorted(AOIS)


def grid_for(aoi: str) -> dict:
    """Return the canonical grid for `aoi`.

    Keys: crs, resolution_m, bounds, width, height, transform.
    `transform` is a plain 6-tuple in affine order (a, b, c, d, e, f), so this
    module stays dependency-free; consumers do ``Affine(*grid["transform"])``.
    """
    try:
        spec = AOIS[aoi]
    except KeyError:
        raise GridError(
            f"unknown AOI {aoi!r}; known AOIs: {', '.join(aoi_names())}"
        ) from None

    res = spec["resolution_m"]
    xmin, ymin, xmax, ymax = spec["bounds"]
    if res <= 0:
        raise GridError(f"{aoi}: resolution_m must be positive, got {res}")
    if xmax <= xmin or ymax <= ymin:
        raise GridError(f"{aoi}: bounds are not (xmin, ymin, xmax, ymax): {spec['bounds']}")

    span_x, span_y = xmax - xmin, ymax - ymin
    for name, span in (("width", span_x), ("height", span_y)):
        if span % res:
            raise GridError(
                f"{aoi}: {name} span {span} m is not a whole number of {res} m "
                f"cells - adjust bounds so the AOI snaps to the grid"
            )
    # Origin must sit on the global res-metre lattice so AOIs that touch share
    # cell edges exactly.
    for name, val in (("xmin", xmin), ("ymin", ymin)):
        if val % res:
            raise GridError(f"{aoi}: {name} {val} is not a multiple of the {res} m resolution")

    return {
        "crs": CRS,
        "resolution_m": res,
        "bounds": (xmin, ymin, xmax, ymax),
        "width": span_x // res,
        "height": span_y // res,
        # north-up, square cells, origin at the upper-left corner
        "transform": (float(res), 0.0, float(xmin), 0.0, float(-res), float(ymax)),
    }
