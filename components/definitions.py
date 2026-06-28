"""
components/definitions.py — Single Source of Truth for football metric definitions.

This module centralizes every definition that was previously scattered and
inconsistent across the codebase (90+ ad-hoc equality checks). Import from
here everywhere so Big Chance, shot events, and metric direction are defined
ONCE and behave identically in the dashboard, reports, and pipeline.
"""

import pandas as pd
import numpy as np

# ── Central event definitions ──────────────────────────────────────────
SHOT_EVENTS = ["Goal", "Miss", "Post", "Saved Shot"]
ON_TARGET_EVENTS = ["Goal", "Saved Shot"]
DEFENSIVE_EVENTS = ["Tackle", "Interception", "Ball recovery"]

# ── Spatial event validation (for heatmaps) ────────────────────────────
# Derived from the actual event vocabulary in the Opta CSVs. Only events that
# represent a real on-ball / contested location belong on a spatial heatmap.
VALID_SPATIAL_EVENTS = {
    "Pass", "Take On", "Ball recovery", "Tackle", "Interception", "Clearance",
    "Aerial", "Challenge", "Foul", "Goal", "Miss", "Post", "Saved Shot",
    "Dispossessed", "Ball touch", "Blocked Pass", "Save", "Keeper pick-up",
    "Keeper Sweeper", "Punch", "Smother", "Claim", "Offside Pass", "Good skill",
    "Chance missed", "Shield ball opp", "Error",
}
# Administrative / technical / non-spatial rows — these cluster at (0,0) and must
# NEVER contribute to a heatmap. Confirmed present in the data at (0,0).
NON_SPATIAL_EVENTS = {
    "Card", "Player Off", "Player on", "Start", "Start delay", "End", "End delay",
    "Deleted event", "Formation change", "Collection End", "Injury Time Announcement",
    "Team setp up", "Coach Setup", "Official change", "Delayed Start", "Player retired",
    "Referee Drop Ball", "Contentious referee decision", "Offside provoked",
    "Offside given", "Substitution", "VAR", "Unknown", "Out",
}


def is_valid_spatial_event(event_name, x=None, y=None, allow_boundary_actions=False):
    """True only if a row is a real spatial football action (not admin/technical).
    Rejects NON_SPATIAL events and (0,0) artifacts unless explicitly allowed."""
    ev = str(event_name)
    if ev in NON_SPATIAL_EVENTS:
        return False
    if ev not in VALID_SPATIAL_EVENTS:
        return False
    if not allow_boundary_actions and x is not None and y is not None:
        try:
            if float(x) == 0.0 and float(y) == 0.0:
                return False
        except (TypeError, ValueError):
            return False
    return True
PROGRESSIVE_MIN_DX = 10  # min forward x-progress (in 0-100 units) for a progressive pass

# ── Touch semantics ──────────────────────────────────────────────────────
# A "touch" is a player deliberately playing the ball. Out-of-play, admin, and
# non-spatial rows are NOT touches even when they carry x/y coordinates.
VALID_TOUCH_EVENTS = {
    "Pass", "Take On", "Ball recovery", "Tackle", "Interception", "Clearance",
    "Aerial", "Ball touch", "Blocked Pass", "Goal", "Miss", "Post", "Saved Shot",
    "Dispossessed", "Save", "Keeper pick-up", "Keeper Sweeper", "Punch", "Smother",
    "Claim", "Good skill", "Shield ball opp", "Offside Pass",
}
OUT_OF_PLAY_EVENTS = {"Out", "Corner Awarded", "Offside given", "Offside provoked",
                      "Foul", "Foul Throw-in"}
ADMIN_EVENTS = {
    "Card", "Player Off", "Player on", "Start", "Start delay", "End", "End delay",
    "Deleted event", "Formation change", "Collection End", "Injury Time Announcement",
    "Team setp up", "Coach Setup", "Official change", "Delayed Start", "Player retired",
    "Referee Drop Ball", "Substitution", "VAR", "Unknown",
}


def filter_valid_touch_events(df, x_col="x", y_col="y"):
    """Keep only rows that are real on-ball touches with in-bounds coordinates.
    Returns (valid_df, n_excluded). Excludes Out/admin/non-spatial rows and
    out-of-bounds coordinates (never clamps them into the pitch)."""
    import pandas as pd
    if df is None or df.empty or "event" not in df.columns:
        return df, 0
    n0 = len(df)
    evs = df["event"].astype(str)
    keep = evs.isin(VALID_TOUCH_EVENTS)
    xs = pd.to_numeric(df[x_col], errors="coerce")
    ys = pd.to_numeric(df[y_col], errors="coerce")
    in_bounds = xs.between(0, 100) & ys.between(0, 100)
    valid = df[keep & in_bounds].copy()
    return valid, n0 - len(valid)




VALID_PASS_EVENTS = {"Pass"}
VALID_DEFENSIVE_EVENTS = {"Tackle", "Interception", "Ball recovery", "Clearance", "Challenge", "Aerial"}
VALID_SHOT_EVENTS = set(SHOT_EVENTS)

def _valid_xy_mask(df, x_col="x", y_col="y"):
    """In-bounds coordinate mask for 0-100 Opta pitch coordinates."""
    xs = pd.to_numeric(df[x_col], errors="coerce") if x_col in df.columns else pd.Series([np.nan] * len(df), index=df.index)
    ys = pd.to_numeric(df[y_col], errors="coerce") if y_col in df.columns else pd.Series([np.nan] * len(df), index=df.index)
    return xs.between(0, 100) & ys.between(0, 100)

def filter_valid_pass_events(df, x_col="x", y_col="y", completed_only=False):
    """Valid pass-origin rows: Pass events with in-bounds start coordinates."""
    if df is None or df.empty or "event" not in df.columns:
        return df, 0
    n0 = len(df)
    keep = df["event"].astype(str).isin(VALID_PASS_EVENTS) & _valid_xy_mask(df, x_col, y_col)
    if completed_only and "outcome" in df.columns:
        keep &= (pd.to_numeric(df["outcome"], errors="coerce") == 1)
    valid = df[keep].copy()
    return valid, n0 - len(valid)

def filter_valid_reception_events(df, x_col="Pass End X", y_col="Pass End Y"):
    """Completed pass receptions with valid pass-end coordinates."""
    if df is None or df.empty or "event" not in df.columns:
        return df, 0
    n0 = len(df)
    keep = (df["event"].astype(str) == "Pass") & (pd.to_numeric(df.get("outcome"), errors="coerce") == 1)
    keep &= _valid_xy_mask(df, x_col, y_col)
    valid = df[keep].copy()
    return valid, n0 - len(valid)

def filter_valid_defensive_events(df, x_col="x", y_col="y"):
    """Valid defensive-action rows with in-bounds coordinates."""
    if df is None or df.empty or "event" not in df.columns:
        return df, 0
    n0 = len(df)
    keep = df["event"].astype(str).isin(VALID_DEFENSIVE_EVENTS) & _valid_xy_mask(df, x_col, y_col)
    valid = df[keep].copy()
    return valid, n0 - len(valid)

def filter_valid_shot_events(df, x_col="x", y_col="y"):
    """Valid shot rows with in-bounds coordinates."""
    if df is None or df.empty or "event" not in df.columns:
        return df, 0
    n0 = len(df)
    keep = df["event"].astype(str).isin(VALID_SHOT_EVENTS) & _valid_xy_mask(df, x_col, y_col)
    valid = df[keep].copy()
    return valid, n0 - len(valid)

# ── Pitch geometry (0-100 coordinate system, attacking goal at x=100) ──
FINAL_THIRD_X = 66.6
MID_THIRD_X = 33.3
BOX_X, BOX_Y_LO, BOX_Y_HI = 83.5, 21.1, 78.9

# ── Metric direction: True = higher is better, False = lower is better ──
# Used everywhere for rank/percentile/status so we never treat e.g. PPDA
# or xGA as if higher were better.
METRIC_DIRECTION = {
    # Attack (higher better)
    "xg_per_match": True, "xg_for_pm": True, "goals_for_pm": True,
    "shots_for_pm": True, "shots_on_target_pm": True,
    "big_chances_for_pm": True, "big_chances_pm": True,
    "box_entries_pm": True, "ft_entries_pm": True,
    "prog_passes_pm": True, "crosses_pm": True, "through_balls_pm": True,
    "possession_pct": True, "pass_accuracy": True, "field_tilt": True,
    "fast_break_xg": True, "fast_break_shots_pm": True,
    "sp_xg_for": True, "xg_set_piece": True,
    # Defence (lower better)
    "xg_against": False, "xg_against_pm": False, "goals_against_pm": False,
    "shots_against_pm": False, "big_chances_against_pm": False,
    "ppda": False, "turnovers_own_half_pm": False, "sp_xg_against": False,
    # Defensive activity (higher better)
    "def_action_height": True, "high_regains_pm": True,
    "tackles_pm": True, "interceptions_pm": True, "recoveries_pm": True,
    # Additional tracked metrics (explicit so direction is never heuristic)
    "goals_pm": True, "shots_pm": True, "cutbacks_pm": True,
    "switches_pm": True, "sp_shots_pm": True, "corners_pm": True,
}


def metric_higher_better(metric_key: str) -> bool:
    """Direction lookup with sensible default (higher = better)."""
    if metric_key in METRIC_DIRECTION:
        return METRIC_DIRECTION[metric_key]
    # Heuristics for unknown keys
    low = metric_key.lower()
    if any(t in low for t in ("against", "conceded", "ppda", "loss", "turnover", "foul")):
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════
#  ROBUST QUALIFIER FLAG DETECTION — the Big Chance fix
# ══════════════════════════════════════════════════════════════════════════
_TRUE_TOKENS = {"si", "sí", "yes", "y", "1", "true", "t", "x", "✓"}


def is_flag(value) -> bool:
    """
    Detect an Opta qualifier 'flag' across ALL formats seen in the wild:
    'Si', 'sí', 'SI', 'yes', 'y', '1', 1, 1.0, True, 'x', '✓'.
    Treats '0', 0, '', None, NaN as not-flagged.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and np.isnan(value):
            return False
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TOKENS
    return False


def flag_mask(series: pd.Series) -> pd.Series:
    """Vectorised boolean mask for a qualifier column. Safe on missing/typed cols."""
    if series is None or len(series) == 0:
        return pd.Series([], dtype=bool)
    # Fast path for already-categorical/string "Si" columns, but robust fallback
    return series.apply(is_flag)


def flag_count(series: pd.Series) -> int:
    """Count flagged rows robustly."""
    if series is None or len(series) == 0:
        return 0
    return int(flag_mask(series).sum())


def safe_col(df: pd.DataFrame, col: str) -> pd.Series:
    """Return a column or an empty (index-aligned) Series if it's missing."""
    if col in df.columns:
        return df[col]
    return pd.Series([np.nan] * len(df), index=df.index, dtype="object")


# ══════════════════════════════════════════════════════════════════════════
#  CENTRAL SHOT / BIG-CHANCE SELECTORS
# ══════════════════════════════════════════════════════════════════════════
def shots_of(df: pd.DataFrame, team_name: str = None) -> pd.DataFrame:
    """All shot events, optionally for one team."""
    s = df[df["event"].isin(SHOT_EVENTS)]
    if team_name:
        s = s[s["team_name"] == team_name]
    return s


def big_chances_of(df: pd.DataFrame, team_name: str = None) -> pd.DataFrame:
    """
    Shots flagged as Big Chance. A shot is a big chance iff it is a shot event
    AND the 'Big Chance' qualifier is flagged (robust detection).
    """
    s = shots_of(df, team_name)
    if "Big Chance" not in s.columns or s.empty:
        return s.iloc[0:0]
    return s[flag_mask(s["Big Chance"])]


# ══════════════════════════════════════════════════════════════════════════
#  DATA AVAILABILITY — so we never show a misleading 0.0
# ══════════════════════════════════════════════════════════════════════════
def big_chance_availability(df: pd.DataFrame) -> dict:
    """
    Report whether Big Chance data is actually present in this dataset.
    Returns {available: bool, flagged_shots: int, total_shots: int, reason: str}.
    A season where the feed never carried qualifier 256 will have 0 flagged
    shots across hundreds of shots -> we treat as 'not captured', not '0.0'.
    """
    shots = shots_of(df)
    total = len(shots)
    if total == 0:
        return {"available": False, "flagged_shots": 0, "total_shots": 0,
                "reason": "no_shots"}
    if "Big Chance" not in df.columns:
        return {"available": False, "flagged_shots": 0, "total_shots": total,
                "reason": "column_missing"}
    flagged = flag_count(shots["Big Chance"])
    # If a sizeable sample of shots exists but zero are ever flagged, the feed
    # almost certainly didn't capture qualifier 256 for this season.
    if flagged == 0 and total >= 50:
        return {"available": False, "flagged_shots": 0, "total_shots": total,
                "reason": "not_captured_in_feed"}
    return {"available": True, "flagged_shots": flagged, "total_shots": total,
            "reason": "ok"}


def metric_value_or_unavailable(value, available: bool, fmt="{:.1f}"):
    """Render a metric or an explicit 'Not captured' instead of a false 0.0."""
    if not available:
        return "Not captured"
    if value is None:
        return "—"
    try:
        return fmt.format(value)
    except Exception:
        return str(value)


# ══════════════════════════════════════════════════════════════════════════
#  METRIC EXTREME / DATA-QUALITY VALIDATION
# ══════════════════════════════════════════════════════════════════════════
def validate_metric_extremes(metrics: dict) -> list:
    """Return a list of QA warning strings for suspicious/extreme values.
    Used to flag possible definition or data-quality problems in reports."""
    warnings = []
    def _v(*keys):
        for k in keys:
            if k in metrics and metrics[k] is not None:
                return metrics[k]
        return None

    xg = _v("xg_per_match", "xg", "est_xg")
    if xg is not None and xg > 4.0:
        warnings.append(f"Estimated xG {xg:.2f} exceeds 4.0/match — verify model calibration (shot volume may inflate it).")
    shots = _v("shots_pm", "shots")
    if shots is not None and shots > 30:
        warnings.append(f"Shots {shots:.0f} exceeds 30 — verify shot-event definition.")
    box = _v("box_entries_pm", "box_entries")
    if box is not None and box > 25:
        warnings.append(f"Box entries {box:.0f} exceeds 25 — verify entry definition (must start outside, end inside, completed).")
    corners = _v("corners_pm", "corners")
    if corners is not None and corners > 15:
        warnings.append(f"Corners {corners:.0f} exceeds 15 — possible double-count (use 'Corner taken', not 'Corner Awarded').")
    ppda = _v("ppda")
    if ppda is not None and (ppda < 5 or ppda > 35):
        warnings.append(f"PPDA {ppda:.1f} outside [5, 35] — verify pressing definition or sample size.")
    ft = _v("ft_entries_pm", "ft_entries")
    if ft is not None and ft > 80:
        warnings.append(f"Final-third entries {ft:.0f} exceeds 80 — verify entry definition.")
    bc = _v("big_chances_pm", "big_chances")
    if bc is not None and bc > 8:
        warnings.append(f"Big chances {bc:.1f} exceeds 8 — verify Big Chance flag handling.")
    return warnings


def validate_score_fraction(numerator, denominator, displayed_text="") -> list:
    """Warn if a displayed fraction's denominator doesn't match the real count."""
    warnings = []
    if denominator == 0:
        warnings.append("Denominator is 0 — fraction undefined.")
    elif displayed_text and "/" in str(displayed_text):
        try:
            shown_den = int(str(displayed_text).split("/")[1].split()[0])
            if shown_den != denominator:
                warnings.append(f"Fraction denominator mismatch: shown /{shown_den} but real /{denominator}.")
        except (ValueError, IndexError):
            pass
    return warnings
