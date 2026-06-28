"""
components/zone_model.py — ONE authoritative pitch-zone model (Dash-free).

COORDINATE CONVENTION (Opta-style, as used throughout this project):
  • x ∈ [0, 100], attacking goal at x = 100. Higher x = closer to the goal
    the team is attacking.
  • y ∈ [0, 100].
  • We define y = 100 as the LEFT touchline and y = 0 as the RIGHT touchline
    from the attacking team's perspective (facing x = 100). This is the
    standard Opta orientation. All L/R labels below follow this single rule,
    so "Wide Left" = high y, "Wide Right" = low y.

If a future data source flips this, change ONLY this module.

Five-lane model (football-standard), by y:
  Wide Right   : y <  20
  Right HS     : 20 ≤ y < 37   (half-space)
  Central      : 37 ≤ y < 63
  Left HS      : 63 ≤ y < 80   (half-space)
  Wide Left    : y ≥ 80

Thirds, by x:
  Defensive third : x < 33.33
  Middle third    : 33.33 ≤ x < 66.67
  Attacking third : x ≥ 66.67

Penalty box (attacking): x ≥ 83 and 21.1 ≤ y ≤ 78.9
"""

# ── Thirds ──────────────────────────────────────────────────────────────
THIRD_DEF_MAX = 33.33
THIRD_ATT_MIN = 66.67

# ── Five lanes (y boundaries) ───────────────────────────────────────────
LANES = [
    ("Wide Right", 0.0, 20.0),
    ("Right Half-Space", 20.0, 37.0),
    ("Central", 37.0, 63.0),
    ("Left Half-Space", 63.0, 80.0),
    ("Wide Left", 80.0, 100.0),
]

# ── Penalty box (attacking) ─────────────────────────────────────────────
BOX_X_MIN = 83.0
BOX_Y_MIN = 21.1
BOX_Y_MAX = 78.9


def third_of(x):
    """Return 'def' | 'mid' | 'att' for an x coordinate."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if x < THIRD_DEF_MAX:
        return "def"
    if x < THIRD_ATT_MIN:
        return "mid"
    return "att"


def lane_of(y):
    """Return the five-lane label for a y coordinate (L/R per module convention)."""
    if y is None:
        return None
    try:
        y = float(y)
    except (TypeError, ValueError):
        return None
    for name, lo, hi in LANES:
        if lo <= y < hi:
            return name
    if y >= 100.0:
        return "Wide Left"
    if y < 0.0:
        return "Wide Right"
    return "Central"


def is_in_box(x, y):
    """True if (x, y) is inside the attacking penalty box."""
    try:
        x = float(x); y = float(y)
    except (TypeError, ValueError):
        return False
    return x >= BOX_X_MIN and BOX_Y_MIN <= y <= BOX_Y_MAX


def assign_pitch_zone(x, y):
    """Return a structured zone dict for a coordinate: third + lane + box flag
    + a compact zone id and display label."""
    t = third_of(x)
    lane = lane_of(y)
    box = is_in_box(x, y)
    third_label = {"def": "Def 3rd", "mid": "Mid 3rd", "att": "Att 3rd", None: "?"}[t]
    return {
        "third": t, "lane": lane, "in_box": box,
        "zone_id": f"{t}:{lane}" if t and lane else None,
        "label": f"{third_label} · {lane}" + (" · Box" if box else ""),
    }


def normalize_attacking_direction(df, team_name, match_id=None):
    """Ensure x increases toward the attacking goal for `team_name`.

    The event feed in this project is already normalized so x=100 is the
    attacking goal for the acting team (goal x-mean ≈ 87). This helper is the
    single place to flip coordinates if a future feed is not normalized; it
    returns the df unchanged when already consistent, and is safe to call.
    """
    if df is None or df.empty:
        return df
    sub = df
    if match_id is not None and "match_id" in df.columns:
        sub = df[df["match_id"] == match_id]
    team_shots = sub[(sub.get("team_name") == team_name) &
                     (sub.get("event").isin(["Goal", "Miss", "Post", "Saved Shot"]))] \
        if "event" in sub.columns else sub.iloc[0:0]
    # If this team's shots cluster at LOW x, coordinates are reversed for them.
    if len(team_shots) >= 5:
        import pandas as pd
        mean_x = pd.to_numeric(team_shots["x"], errors="coerce").mean()
        if mean_x < 50:
            out = df.copy()
            out["x"] = 100 - pd.to_numeric(out["x"], errors="coerce")
            out["y"] = 100 - pd.to_numeric(out["y"], errors="coerce")
            if "Pass End X" in out.columns:
                out["Pass End X"] = 100 - pd.to_numeric(out["Pass End X"], errors="coerce")
                out["Pass End Y"] = 100 - pd.to_numeric(out["Pass End Y"], errors="coerce")
            return out
    return df


def validate_zone_counts(df, plotted_points, displayed_counts):
    """Sanity-check that displayed zone counts equal the number of plotted points.
    Returns (ok, detail)."""
    total_plotted = int(plotted_points)
    total_displayed = int(sum(displayed_counts.values())) if isinstance(displayed_counts, dict) else int(displayed_counts)
    ok = total_plotted == total_displayed
    return ok, f"plotted={total_plotted}, displayed_sum={total_displayed}"


def zone_breakdown(df, x_col="x", y_col="y"):
    """Count events per third and per lane from raw coordinates. Used by map
    summaries and QA so the displayed numbers always equal the plotted rows."""
    import pandas as pd
    if df is None or df.empty:
        return {"total": 0, "thirds": {}, "lanes": {}}
    xs = pd.to_numeric(df[x_col], errors="coerce")
    ys = pd.to_numeric(df[y_col], errors="coerce")
    valid = xs.notna() & ys.notna()
    xs, ys = xs[valid], ys[valid]
    thirds = {"def": 0, "mid": 0, "att": 0}
    lanes = {name: 0 for name, _, _ in LANES}
    for x, y in zip(xs, ys):
        t = third_of(x)
        if t:
            thirds[t] += 1
        lane = lane_of(y)
        if lane in lanes:
            lanes[lane] += 1
    return {"total": int(valid.sum()), "thirds": thirds, "lanes": lanes}


# ── 18-zone grid (6 columns × 3 rows) for Touch/occupancy maps ──────────
# Columns by x, rows by y. Upper edges are INCLUSIVE on the last cell so every
# plotted point falls into exactly one cell (counts sum to plotted points).
ZONE_GRID_COLS = [(0, 16.5), (16.5, 33.3), (33.3, 50), (50, 66.6), (66.6, 83.5), (83.5, 100.01)]
ZONE_GRID_ROWS = [(0, 33.3), (33.3, 66.6), (66.6, 100.01)]


def _cell_index(v, bands):
    """Index of the band containing v. Invalid/out-of-bounds coordinates are
    rejected, never clamped into edge cells. Values exactly on the valid top
    edge (100.0) are counted because final bands end at 100.01.
    """
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v < bands[0][0] or v >= bands[-1][1]:
        return None
    for i, (lo, hi) in enumerate(bands):
        if lo <= v < hi:
            return i
    return None


def zone_grid_counts(df, x_col="x", y_col="y"):
    """Count events into the 18-zone grid using the EXACT dataframe passed in.

    Returns {"cells": {(col, row): count}, "total": n_in_grid}. Invalid or
    out-of-bounds coordinates are ignored, never clamped, so zone counts match
    valid plotted football actions rather than provider boundary artifacts.
    """
    import pandas as pd
    out = {(c, r): 0 for c in range(len(ZONE_GRID_COLS)) for r in range(len(ZONE_GRID_ROWS))}
    if df is None or df.empty:
        return {"cells": out, "total": 0}
    xs = pd.to_numeric(df[x_col], errors="coerce")
    ys = pd.to_numeric(df[y_col], errors="coerce")
    valid = xs.notna() & ys.notna()
    n = 0
    for x, y in zip(xs[valid], ys[valid]):
        ci = _cell_index(x, ZONE_GRID_COLS)
        ri = _cell_index(y, ZONE_GRID_ROWS)
        if ci is not None and ri is not None:
            out[(ci, ri)] += 1
            n += 1
    return {"cells": out, "total": n}
