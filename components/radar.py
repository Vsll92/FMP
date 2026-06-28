"""
components/radar.py — Position-Specific Player Radar System
Features:
  - 8 position-group KPI templates (GK, CB, FB/WB, DM, CM, AM, Winger, ST)
  - Offensive vs Defensive split view
  - Per-90-minutes normalization
  - Comparison vs positional average
  - Comparison vs another player
  - Custom metric selection
"""

import plotly.graph_objects as go
import numpy as np
import pandas as pd

from components.charts import CARD_BG, GRID, TEXT, MUTED, GOLD, ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED

# ── Unified flag detection (single source of truth) ──────────────────
try:
    from components.definitions import is_flag as _FLAGVAL
except Exception:
    _FLAG_TRUE = {"si","sí","yes","y","1","true","t","x","✓"}
    def _FLAGVAL(v):
        if v is None: return False
        if isinstance(v, bool): return v
        if isinstance(v,(int,float)): return (v==1) and not (isinstance(v,float) and v!=v)
        if isinstance(v,str): return v.strip().lower() in _FLAG_TRUE
        return False
def _flagmask(series):
    """Vectorised flag mask for a Series; safe on missing/typed columns."""
    import pandas as _pd
    if series is None or len(series)==0: return _pd.Series([], dtype=bool)
    return series.apply(_FLAGVAL)


# ══════════════════════════════════════════════════════════════════════════
#  POSITION GROUP DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════
POSITION_GROUPS = {
    "GK":     ["GK"],
    "CB":     ["CB"],
    "FB/WB":  ["LB", "RB", "LWB", "RWB"],
    "DM":     ["CDM"],
    "CM":     ["CM", "MC"],
    "AM":     ["CAM", "SS"],
    "Winger": ["LW", "RW", "LM", "RM"],
    "ST":     ["CF"],
}

def get_position_group(position: str) -> str:
    """Canonical position group. Delegates to the authoritative normalizer so
    event codes (CAM, CF, LWB, …) and override groups resolve consistently."""
    try:
        from components.player_positions import normalize_position_group
        return normalize_position_group(position)
    except Exception:
        for group, positions in POSITION_GROUPS.items():
            if position in positions:
                return group
        return "CM"


# ══════════════════════════════════════════════════════════════════════════
#  POSITION-SPECIFIC KPI TEMPLATES
#  Each metric: (display_name, compute_key, category, higher_is_better)
# ══════════════════════════════════════════════════════════════════════════
RADAR_TEMPLATES = {
    "GK": {
        "metrics": [
            ("Saves", "saves_p90", "defensive", True),
            ("Save %", "save_pct", "defensive", True),
            ("Clean Sheets", "clean_sheets", "defensive", True),
            ("Distribution", "passes_p90", "buildup", True),
            ("Pass Acc %", "pass_accuracy", "buildup", True),
            ("Long Pass", "long_balls_p90", "buildup", True),
            ("Sweeping", "sweeps_p90", "defensive", True),
            ("Claims", "claims_p90", "defensive", True),
        ],
    },
    "CB": {
        "metrics": [
            ("Tackles", "tackles_p90", "defensive", True),
            ("Interceptions", "interceptions_p90", "defensive", True),
            ("Clearances", "clearances_p90", "defensive", True),
            ("Aerials Won", "aerials_won_p90", "defensive", True),
            ("Blocks", "blocks_p90", "defensive", True),
            ("Pass Acc %", "pass_accuracy", "buildup", True),
            ("Prog Passes", "prog_passes_p90", "buildup", True),
            ("Recoveries", "recoveries_p90", "defensive", True),
        ],
    },
    "FB/WB": {
        "metrics": [
            ("Crosses", "crosses_p90", "offensive", True),
            ("Prog Passes", "prog_passes_p90", "offensive", True),
            ("Prog Carries", "prog_carries_p90", "offensive", True),
            ("Key Passes", "key_passes_p90", "offensive", True),
            ("Tackles", "tackles_p90", "defensive", True),
            ("Interceptions", "interceptions_p90", "defensive", True),
            ("Recoveries", "recoveries_p90", "defensive", True),
            ("Aerials Won", "aerials_won_p90", "defensive", True),
        ],
    },
    "DM": {
        "metrics": [
            ("Tackles", "tackles_p90", "defensive", True),
            ("Interceptions", "interceptions_p90", "defensive", True),
            ("Recoveries", "recoveries_p90", "defensive", True),
            ("Pass Acc %", "pass_accuracy", "buildup", True),
            ("Prog Passes", "prog_passes_p90", "buildup", True),
            ("Aerials Won", "aerials_won_p90", "defensive", True),
            ("Ball Losses", "ball_losses_p90", "defensive", False),
            ("Fouls", "fouls_p90", "defensive", False),
        ],
    },
    "CM": {
        "metrics": [
            ("Goals", "goals_p90", "offensive", True),
            ("Assists", "assists_p90", "offensive", True),
            ("Key Passes", "key_passes_p90", "offensive", True),
            ("Prog Passes", "prog_passes_p90", "buildup", True),
            ("Prog Carries", "prog_carries_p90", "offensive", True),
            ("Pass Acc %", "pass_accuracy", "buildup", True),
            ("Tackles", "tackles_p90", "defensive", True),
            ("Interceptions", "interceptions_p90", "defensive", True),
        ],
    },
    "AM": {
        "metrics": [
            ("Goals", "goals_p90", "offensive", True),
            ("Assists", "assists_p90", "offensive", True),
            ("Shots", "shots_p90", "offensive", True),
            ("Key Passes", "key_passes_p90", "offensive", True),
            ("Dribbles Won", "dribbles_won_p90", "offensive", True),
            ("Prog Carries", "prog_carries_p90", "offensive", True),
            ("Through Balls", "through_balls_p90", "offensive", True),
            ("Recoveries", "recoveries_p90", "defensive", True),
        ],
    },
    "Winger": {
        "metrics": [
            ("Goals", "goals_p90", "offensive", True),
            ("Assists", "assists_p90", "offensive", True),
            ("Crosses", "crosses_p90", "offensive", True),
            ("Dribbles Won", "dribbles_won_p90", "offensive", True),
            ("Shots", "shots_p90", "offensive", True),
            ("Key Passes", "key_passes_p90", "offensive", True),
            ("Prog Carries", "prog_carries_p90", "offensive", True),
            ("Recoveries", "recoveries_p90", "defensive", True),
        ],
    },
    "ST": {
        "metrics": [
            ("Goals", "goals_p90", "offensive", True),
            ("xG", "xg_p90", "offensive", True),
            ("Shots", "shots_p90", "offensive", True),
            ("Shot Acc %", "shot_accuracy", "offensive", True),
            ("Aerials Won", "aerials_won_p90", "offensive", True),
            ("Hold-up", "hold_up_p90", "offensive", True),
            ("Assists", "assists_p90", "offensive", True),
            ("Pressing", "pressing_p90", "defensive", True),
        ],
    },
}

# All available metrics for custom selection
ALL_METRICS = [
    ("Goals", "goals_p90"), ("Assists", "assists_p90"),
    ("Shots", "shots_p90"), ("Shot Accuracy %", "shot_accuracy"),
    ("xG", "xg_p90"), ("Key Passes", "key_passes_p90"),
    ("Passes", "passes_p90"), ("Pass Accuracy %", "pass_accuracy"),
    ("Prog Passes", "prog_passes_p90"), ("Prog Carries", "prog_carries_p90"),
    ("Crosses", "crosses_p90"), ("Through Balls", "through_balls_p90"),
    ("Dribbles Won", "dribbles_won_p90"), ("Dribble %", "dribble_pct"),
    ("Tackles", "tackles_p90"), ("Interceptions", "interceptions_p90"),
    ("Recoveries", "recoveries_p90"), ("Clearances", "clearances_p90"),
    ("Aerials Won", "aerials_won_p90"), ("Aerial %", "aerial_pct"),
    ("Ball Losses", "ball_losses_p90"), ("Fouls", "fouls_p90"),
]


# ══════════════════════════════════════════════════════════════════════════
#  COMPUTE RADAR METRICS FROM EVENT DATA
# ══════════════════════════════════════════════════════════════════════════
def compute_player_radar_stats(df: pd.DataFrame, player_id, team_name: str = None) -> dict:
    """
    Compute all radar-relevant metrics for a player from event data.
    Returns per-90 normalized values where applicable.
    """
    from components.report_engine import _xg_from_distance

    pdf = df[df["player_id"] == player_id]
    if team_name:
        pdf = pdf[pdf["team_name"] == team_name]
    if pdf.empty:
        return {}

    # Estimate minutes played (approximate: count matches × avg minutes)
    matches = pdf["match_id"].nunique()
    if matches == 0:
        return {}

    # Rough minutes estimate: events span from min_time to max per match
    mins_total = 0
    for mid in pdf["match_id"].unique():
        mdf = pdf[pdf["match_id"] == mid]
        mins_total += max(mdf["time_min"].max(), 1) if not mdf["time_min"].isna().all() else 45
    p90 = max(mins_total / 90, 0.1)

    passes = pdf[pdf["event"] == "Pass"]
    passes_end = passes.dropna(subset=["Pass End X", "x"])
    shots = pdf[pdf["event"].isin(["Goal", "Miss", "Post", "Saved Shot"])]
    goals = pdf[pdf["event"] == "Goal"]
    tackles = pdf[pdf["event"] == "Tackle"]
    intercepts = pdf[pdf["event"] == "Interception"]
    recoveries = pdf[pdf["event"] == "Ball recovery"]
    clearances = pdf[pdf["event"] == "Clearance"]
    aerials = pdf[pdf["event"] == "Aerial"]
    take_ons = pdf[pdf["event"] == "Take On"]
    dispossessed = pdf[pdf["event"] == "Dispossessed"]
    saves = pdf[pdf["event"] == "Save"]
    fouls = pdf[(pdf["event"] == "Foul") & (pdf["outcome"] == 0)]

    # Progressive passes/carries
    prog_passes = passes_end[(passes_end["Pass End X"] - passes_end["x"]) > 10] if len(passes_end) > 0 else pd.DataFrame()
    prog_carries = take_ons[take_ons["outcome"] == 1]

    # xG
    xg = sum(_xg_from_distance(s["x"], s["y"],
             _FLAGVAL(s.get("Head")) if "Head" in s.index else False,
             _FLAGVAL(s.get("Big Chance")) if "Big Chance" in s.index else False)
             for _, s in shots.iterrows())

    # Key passes
    kp = 0
    if "Leading to attempt" in passes.columns:
        kp = passes["Leading to attempt"].notna().sum()

    # Crosses / through balls
    crosses = len(passes[_flagmask(passes["Cross"])]) if "Cross" in passes.columns else 0
    through_balls = len(passes[_flagmask(passes["Through ball"])]) if "Through ball" in passes.columns else 0

    # Assists
    assists = len(pdf[pdf["Assist"] == 16]) if "Assist" in pdf.columns else 0

    # Blocks (challenges/blocked passes)
    blocks = len(pdf[pdf["event"].isin(["Challenge", "Blocked Pass"])])

    # Hold-up play (passes + take-ons in attacking third)
    att_touches = pdf[(pdf["x"].notna()) & (pdf["x"] >= 66.6)]
    hold_up = len(att_touches[att_touches["event"].isin(["Pass", "Take On"])])

    # Pressing actions (tackles + interceptions + recoveries in opponent half)
    pressing = len(pdf[(pdf["event"].isin(["Tackle", "Interception", "Ball recovery"])) &
                       (pdf["x"].notna()) & (pdf["x"] > 50)])

    # Ball losses
    bad_passes = len(passes[passes["outcome"] == 0])
    ball_losses = len(dispossessed) + bad_passes

    # GK specific
    clean_sheets = 0
    if saves is not None and len(saves) > 0:
        # Approximate: matches where team didn't concede
        for mid in pdf["match_id"].unique():
            mdf_all = df[df["match_id"] == mid]
            opp_goals = mdf_all[(mdf_all["event"] == "Goal") & (mdf_all["team_name"] != team_name)]
            if len(opp_goals) == 0:
                clean_sheets += 1

    # Sweeps (keeper actions outside box)
    sweeps = len(pdf[pdf["event"] == "Keeper Sweeper"])
    claims = len(pdf[pdf["event"] == "Claim"])

    return {
        # Raw totals
        "matches": matches, "minutes_est": mins_total, "p90_factor": p90,
        # Per-90 metrics
        "goals_p90": round(len(goals) / p90, 2),
        "assists_p90": round(assists / p90, 2),
        "shots_p90": round(len(shots) / p90, 2),
        "xg_p90": round(xg / p90, 2),
        "passes_p90": round(len(passes) / p90, 1),
        "key_passes_p90": round(kp / p90, 2),
        "prog_passes_p90": round(len(prog_passes) / p90, 2),
        "prog_carries_p90": round(len(prog_carries) / p90, 2),
        "crosses_p90": round(crosses / p90, 2),
        "through_balls_p90": round(through_balls / p90, 2),
        "dribbles_won_p90": round(len(prog_carries) / p90, 2),
        "tackles_p90": round(len(tackles) / p90, 2),
        "interceptions_p90": round(len(intercepts) / p90, 2),
        "recoveries_p90": round(len(recoveries) / p90, 2),
        "clearances_p90": round(len(clearances) / p90, 2),
        "aerials_won_p90": round(len(aerials[aerials["outcome"] == 1]) / p90, 2),
        "blocks_p90": round(blocks / p90, 2),
        "ball_losses_p90": round(ball_losses / p90, 2),
        "fouls_p90": round(len(fouls) / p90, 2),
        "hold_up_p90": round(hold_up / p90, 2),
        "pressing_p90": round(pressing / p90, 2),
        "saves_p90": round(len(saves) / p90, 2),
        "sweeps_p90": round(sweeps / p90, 2),
        "claims_p90": round(claims / p90, 2),
        # Percentage metrics (not per-90)
        "pass_accuracy": round(passes["outcome"].mean() * 100, 1) if len(passes) > 0 else 0,
        "shot_accuracy": round(len(pdf[pdf["event"].isin(["Goal", "Saved Shot"])]) / max(len(shots), 1) * 100, 1),
        "dribble_pct": round(take_ons["outcome"].mean() * 100, 1) if len(take_ons) > 0 else 0,
        "aerial_pct": round(aerials["outcome"].mean() * 100, 1) if len(aerials) > 0 else 0,
        "save_pct": round(saves["outcome"].mean() * 100, 1) if len(saves) > 0 else 0,
        "clean_sheets": clean_sheets,
    }


def compute_positional_averages(df: pd.DataFrame, position_group: str, team_name: str = None) -> dict:
    """Compute average radar stats for all players in a position group."""
    positions = POSITION_GROUPS.get(position_group, [])
    players_df = df[df["position"].isin(positions) & df["player_name"].notna()]
    if team_name:
        players_df = players_df[players_df["team_name"] == team_name]

    player_ids = players_df["player_id"].unique()
    if len(player_ids) == 0:
        return {}

    all_stats = []
    for pid in player_ids[:30]:  # Limit to avoid slow computation
        s = compute_player_radar_stats(df, pid)
        if s and s.get("matches", 0) >= 3:
            all_stats.append(s)

    if not all_stats:
        return {}

    # Average across players
    avg = {}
    for key in all_stats[0]:
        if isinstance(all_stats[0][key], (int, float)):
            vals = [s[key] for s in all_stats if key in s]
            avg[key] = round(sum(vals) / len(vals), 2) if vals else 0
    return avg


# ══════════════════════════════════════════════════════════════════════════
#  RADAR CHART BUILDER
# ══════════════════════════════════════════════════════════════════════════
def build_radar_chart(
        player_stats: dict, player_name: str, position_group: str,
                      color: str = GOLD, comparison_stats: dict = None,
                      comparison_name: str = None, comparison_color: str = ACCENT_BLUE,
                      mode: str = "full", custom_metrics: list = None) -> go.Figure:
    """DEPRECATED — self-normalized radar (every nonzero metric → ~90). Replaced
    by build_percentile_radar (real peer percentiles). Retained for reference
    only; no longer called by the app.
    """
    template = RADAR_TEMPLATES.get(position_group, RADAR_TEMPLATES["CM"])

    if custom_metrics:
        # Use custom metric selection
        metrics = [(name, key, "custom", True) for name, key in custom_metrics]
    elif mode == "offensive":
        metrics = [m for m in template["metrics"] if m[2] in ("offensive", "buildup")]
    elif mode == "defensive":
        metrics = [m for m in template["metrics"] if m[2] == "defensive"]
    else:
        metrics = template["metrics"]

    if not metrics:
        metrics = template["metrics"]

    labels = [m[0] for m in metrics]
    keys = [m[1] for m in metrics]
    inverted = [not m[3] for m in metrics]  # Lower is better

    # Get values
    values = [player_stats.get(k, 0) for k in keys]

    # For inverted metrics (ball losses, fouls), flip for radar display
    # Higher on radar should always = better
    display_values = []
    for v, inv in zip(values, inverted):
        if inv and v > 0:
            display_values.append(max(0, 10 - v))  # Invert: less = more radar area
        else:
            display_values.append(v)

    # Normalize to 0-100 scale using comparison or sensible defaults
    if comparison_stats:
        # Normalize relative to comparison
        max_vals = [max(abs(display_values[i]), abs(comparison_stats.get(keys[i], 0.01)), 0.01)
                    for i in range(len(keys))]
    else:
        max_vals = [max(abs(v), 0.01) for v in display_values]

    norm_values = [min(v / m * 80 + 10, 100) for v, m in zip(display_values, max_vals)]

    fig = go.Figure()

    # Player trace
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig.add_trace(go.Scatterpolar(
        r=norm_values + [norm_values[0]],
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor=f"rgba({r},{g},{b},0.25)",
        line=dict(color=color, width=2.5),
        name=player_name,
        customdata=values + [values[0]],
        hovertemplate="<b>%{theta}</b><br>%{customdata:.2f}<extra>" + player_name + "</extra>",
    ))

    # Comparison trace
    if comparison_stats and comparison_name:
        comp_values = [comparison_stats.get(k, 0) for k in keys]
        comp_display = []
        for v, inv in zip(comp_values, inverted):
            if inv and v > 0:
                comp_display.append(max(0, 10 - v))
            else:
                comp_display.append(v)
        comp_norm = [min(v / m * 80 + 10, 100) for v, m in zip(comp_display, max_vals)]

        rc, gc, bc = int(comparison_color[1:3], 16), int(comparison_color[3:5], 16), int(comparison_color[5:7], 16)
        fig.add_trace(go.Scatterpolar(
            r=comp_norm + [comp_norm[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor=f"rgba({rc},{gc},{bc},0.12)",
            line=dict(color=comparison_color, width=2, dash="dot"),
            name=comparison_name,
            customdata=comp_values + [comp_values[0]],
            hovertemplate="<b>%{theta}</b><br>%{customdata:.2f}<extra>" + comparison_name + "</extra>",
        ))

    fig.update_layout(
        polar=dict(
            bgcolor=CARD_BG,
            radialaxis=dict(
                visible=True, gridcolor=GRID, tickfont=dict(color=MUTED, size=8),
                range=[0, 105], showticklabels=False,
            ),
            angularaxis=dict(tickfont=dict(color=TEXT, size=10), gridcolor=GRID),
        ),
        paper_bgcolor=CARD_BG, font=dict(color=TEXT),
        height=420, margin=dict(l=60, r=60, t=35, b=35),
        legend=dict(orientation="h", y=1.08, xanchor="center", x=0.5, font=dict(size=10)),
        showlegend=True,
    )
    return fig


_PEER_CACHE = {}
_PEER_ALLPS_CACHE = {}


def _get_peer_pool(position_group):
    """Cached league-wide peer table by position group.

    compute_peer_percentiles is called from Player Hub and QA loops. Building the
    league-wide player aggregate repeatedly makes tests/UI slow. This cache keeps
    the exact same peer pool for raw, peer max, radar %, percentile and rank.
    """
    from data_loader import get_player_stats as _gps
    league = _league_hint()
    key = (league, position_group)
    if key in _PEER_CACHE:
        return _PEER_CACHE[key].copy()
    if league not in _PEER_ALLPS_CACHE:
        _PEER_ALLPS_CACHE[league] = _gps(league)
    allps = _PEER_ALLPS_CACHE[league]
    if "position_group" in allps.columns:
        peers = allps[allps["position_group"] == position_group].copy()
    else:
        peers = allps[allps["position"].isin(POSITION_GROUPS.get(position_group, []))].copy()
    peers = peers[peers["matches"] >= 3].copy()
    for col in set(_AGG_METRIC_MAP.values()):
        if col in peers.columns and col != "pass_accuracy":
            peers[col + "_pm"] = peers[col] / peers["matches"].clip(lower=1)
    _PEER_CACHE[key] = peers
    return peers.copy()

# Map radar-template metric keys to fast per-player aggregate columns (per-match
# normalised). This lets peer percentiles use the cached get_player_stats table
# instead of recomputing event-level radar stats for ~150 players (which is slow).
_AGG_METRIC_MAP = {
    "goals": "goals", "xg": "xg", "shots": "shots", "assists": "assists",
    "key_passes": "key_passes", "pass_accuracy": "pass_accuracy",
    "prog_passes": "prog_passes", "tackles": "tackles", "interceptions": "interceptions",
    "recoveries": "recoveries", "clearances": "clearances", "aerials": "aerials_won",
    "take_ons": "take_ons", "saves": "saves", "claims": "claims",
    "sweeper_actions": "sweeper_actions",
}



# Position-aware radar metric sets — each maps a friendly label to an aggregate
# metric key. This ensures a GK radar shows Saves/Claims/Distribution, not
# Goals/xG/Shots. Metrics with no peer variation are still auto-excluded.
_RADAR_METRICS_BY_GROUP = {
    "GK": [("Saves", "saves"), ("Claims", "claims"), ("Sweeping", "sweeper_actions"),
           ("Pass Acc %", "pass_accuracy"), ("Prog Passes", "prog_passes"),
           ("Recoveries", "recoveries"), ("Clearances", "clearances")],
    "CB": [("Tackles", "tackles"), ("Interceptions", "interceptions"),
           ("Clearances", "clearances"), ("Aerials", "aerials"), ("Recoveries", "recoveries"),
           ("Pass Acc %", "pass_accuracy"), ("Prog Passes", "prog_passes")],
    "FB/WB": [("Tackles", "tackles"), ("Interceptions", "interceptions"),
              ("Take-ons", "take_ons"), ("Key Passes", "key_passes"),
              ("Prog Passes", "prog_passes"), ("Recoveries", "recoveries"),
              ("Pass Acc %", "pass_accuracy"), ("Assists", "assists")],
    "DM": [("Tackles", "tackles"), ("Interceptions", "interceptions"),
           ("Recoveries", "recoveries"), ("Pass Acc %", "pass_accuracy"),
           ("Prog Passes", "prog_passes"), ("Key Passes", "key_passes"),
           ("Aerials", "aerials")],
    "CM": [("Assists", "assists"), ("Key Passes", "key_passes"), ("Prog Passes", "prog_passes"),
           ("Pass Acc %", "pass_accuracy"), ("Tackles", "tackles"),
           ("Interceptions", "interceptions"), ("Take-ons", "take_ons"), ("Recoveries", "recoveries")],
    "AM": [("Goals", "goals"), ("xG", "xg"), ("Assists", "assists"), ("Key Passes", "key_passes"),
           ("Prog Passes", "prog_passes"), ("Take-ons", "take_ons"),
           ("Shots", "shots"), ("Pass Acc %", "pass_accuracy")],
    "Winger": [("Goals", "goals"), ("xG", "xg"), ("Assists", "assists"), ("Key Passes", "key_passes"),
               ("Take-ons", "take_ons"), ("Shots", "shots"), ("Prog Passes", "prog_passes"),
               ("Pass Acc %", "pass_accuracy")],
    "ST": [("Goals", "goals"), ("xG", "xg"), ("Shots", "shots"), ("Assists", "assists"),
           ("Key Passes", "key_passes"), ("Aerials", "aerials"), ("Take-ons", "take_ons"),
           ("Prog Passes", "prog_passes")],
}


def _radar_metrics_for(position_group):
    """Return the (label, agg_key) list for a position group (default CM)."""
    return _RADAR_METRICS_BY_GROUP.get(position_group, _RADAR_METRICS_BY_GROUP["CM"])


def compute_peer_percentiles(df, player_id, team_name, position_group):
    """Peer-relative player radar values for a position group.

    Important trust rule: raw value, peer max, radar %, percentile and rank are
    all computed from the SAME unrounded peer vector. Display rounding happens
    later in the Dash table only. This prevents rows such as: raw 1.76, peer
    max 1.76, radar 100, rank 3.
    """
    import math

    peers = _get_peer_pool(position_group)
    n_peers = len(peers)
    if n_peers == 0:
        return {"n_peers": 0, "percentiles": {}, "raw": {}, "raw_exact": {}, "labels": {},
                "strengths": [], "weaknesses": [], "stats": {}, "matches_played": 0,
                "confidence": "low", "unavailable": [],
                "scouting_summary": "Insufficient peer data for a scouting profile.",
                "maxnorm": {}, "peer_max": {}, "peer_max_exact": {}, "rank": {},
                "rank_display": {}, "leader": {}, "tie_status": {}, "leader_value": {}}

    target_row = peers[peers["player_id"] == player_id]
    metrics_for_pos = _radar_metrics_for(position_group)
    label_for = {key: label for label, key in metrics_for_pos}

    pct = {}
    maxnorm = {}
    peer_max = {}       # exact peer max; app decides display precision
    peer_max_exact = {}
    leader_value = {}
    rank = {}           # numeric competition rank (1 = best)
    rank_display = {}   # "1", "T-1", etc. for table/UI
    raw = {}            # exact raw value; app decides display precision
    raw_exact = {}
    leader = {}
    tie_status = {}
    unavailable = []
    matches_played = 0
    eps = 1e-9

    if not target_row.empty:
        tr = target_row.iloc[0]
        matches_played = int(tr.get("matches", 0))
        for mkey, agg in [(k, _AGG_METRIC_MAP[k]) for _, k in metrics_for_pos if k in _AGG_METRIC_MAP]:
            col = agg if agg == "pass_accuracy" else agg + "_pm"
            if col not in peers.columns:
                continue
            tv = tr.get(col)
            if tv is None:
                continue
            try:
                tv = float(tv)
            except Exception:
                continue
            if not math.isfinite(tv):
                continue

            vals = peers[col].dropna().astype(float)
            vals = vals[vals.apply(math.isfinite)]
            if len(vals) == 0:
                continue

            vmin = float(vals.min())
            vmax = float(vals.max())
            if abs(vmax - vmin) <= eps:
                unavailable.append(label_for.get(mkey, mkey))
                continue

            # Percentile and rank use the exact same unrounded values/vector.
            pct[mkey] = round(((vals <= tv + eps).sum()) / len(vals) * 100)
            raw[mkey] = tv
            raw_exact[mkey] = tv
            peer_max[mkey] = vmax
            peer_max_exact[mkey] = vmax
            leader_value[mkey] = vmax

            # Max-normalized radar value from exact values. Do not round 99.6
            # up to 100 unless the player is truly tied for peer max.
            if vmax > 0:
                rn = tv / vmax * 100.0
            else:
                rn = 0.0
            rn = max(0.0, min(100.0, rn))
            is_max_tie = abs(tv - vmax) <= eps
            if is_max_tie:
                maxnorm[mkey] = 100
            else:
                maxnorm[mkey] = round(rn, 1)

            better_count = int((vals > tv + eps).sum())
            rnk = better_count + 1
            tie_count = int((abs(vals - tv) <= eps).sum())
            rank[mkey] = rnk
            rank_display[mkey] = f"T-{rnk}" if tie_count > 1 else str(rnk)
            if is_max_tie and rnk != 1:
                # Defensive guard: by definition, a peer-max tie must rank first.
                rank[mkey] = 1
                rank_display[mkey] = "T-1" if tie_count > 1 else "1"

            leaders_df = peers.loc[(abs(peers[col].astype(float) - vmax) <= eps), ["player_name", "team_name"]].copy()
            leader_names = []
            for _, lr in leaders_df.head(3).iterrows():
                nm = str(lr.get("player_name", "Unknown"))
                tm = str(lr.get("team_name", ""))
                leader_names.append(f"{nm} ({tm})" if tm else nm)
            extra = max(0, len(leaders_df) - len(leader_names))
            leader[mkey] = ", ".join(leader_names) + (f" +{extra} tied" if extra else "")
            if tie_count > 1:
                tie_status[mkey] = f"Tied with {tie_count - 1} peer(s)"
            else:
                tie_status[mkey] = "No tie"

    ranked = sorted(pct.items(), key=lambda kv: kv[1], reverse=True)
    strengths = [(label_for.get(k, k), v) for k, v in ranked[:3] if v >= 60]
    weaknesses = [(label_for.get(k, k), v) for k, v in ranked[-3:] if v <= 40]

    if matches_played >= 10:
        confidence = "high"
    elif matches_played >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    role_word = {"ST": "striker", "CF": "centre-forward", "W": "wide forward",
                 "AM": "attacking midfielder", "CM": "central midfielder",
                 "DM": "holding midfielder", "FB": "full-back", "CB": "centre-back",
                 "GK": "goalkeeper"}.get(position_group, "player")
    if strengths:
        s_txt = ", ".join(f"{lbl.lower()} ({v}th pct)" for lbl, v in strengths[:2])
        summary = f"Profiles as a {role_word} whose standout traits are {s_txt} vs {n_peers} league peers."
    else:
        summary = f"Profiles as a {role_word} around peer average across template metrics (N={n_peers})."
    if weaknesses:
        w_txt = ", ".join(lbl.lower() for lbl, _ in weaknesses[:2])
        summary += f" Development areas: {w_txt}."

    return {"n_peers": n_peers, "percentiles": pct, "raw": raw, "raw_exact": raw_exact,
            "labels": label_for, "maxnorm": maxnorm, "peer_max": peer_max,
            "peer_max_exact": peer_max_exact, "rank": rank, "rank_display": rank_display,
            "leader": leader, "leader_value": leader_value, "tie_status": tie_status,
            "strengths": strengths, "weaknesses": weaknesses, "stats": {},
            "matches_played": matches_played, "confidence": confidence,
            "unavailable": unavailable, "scouting_summary": summary}


def _league_hint():
    """Best-effort current league folder for peer lookups."""
    import os
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    try:
        for d in os.listdir(base):
            if os.path.isdir(os.path.join(base, d)) and "wyscout" not in d.lower() \
               and d not in ("reference", "cache", ".cache", "__pycache__") \
               and not d.startswith("."):
                return d
    except Exception:
        pass
    return "France_League_1_25-26"


def _infer_league():
    return _league_hint()


def build_percentile_radar(peer, player_name, position_group, color=GOLD,
                           peer_b=None, name_b=None, color_b="#008FFB", scale="percentile"):
    """Build a radar from peer-relative values, excluding unavailable
    (zero-variance) metrics. `scale` selects the normalization:
      - "percentile": rank vs peers (0-100th percentile)
      - "max": player value as % of the peer-pool maximum (user-requested)
    Optionally overlays a second player (peer_b) as a comparison trace."""
    import plotly.graph_objects as go
    val_key = "maxnorm" if scale == "max" else "percentiles"
    pct = peer.get(val_key, {}) or peer.get("percentiles", {})
    raw = peer.get("raw_exact", peer.get("raw", {}))
    pmax = peer.get("peer_max_exact", peer.get("peer_max", {}))
    ranks = peer.get("rank_display", peer.get("rank", {}))
    leaders = peer.get("leader", {})
    _LBL = {"goals": "Goals", "xg": "xG", "shots": "Shots", "assists": "Assists",
            "key_passes": "Key Passes", "pass_accuracy": "Pass Acc %",
            "prog_passes": "Prog Passes", "tackles": "Tackles",
            "interceptions": "Interceptions", "recoveries": "Recoveries",
            "clearances": "Clearances", "aerials": "Aerials", "take_ons": "Take-ons",
            "saves": "Saves", "claims": "Claims", "sweeper_actions": "Sweeping"}
    # Order metrics by the position-aware schema so each role shows its own axes
    # (GK → Saves/Claims/Sweeping, not Goals/xG/Shots).
    order = [k for _, k in _radar_metrics_for(position_group)]
    # any extra keys present but not in the schema go last (defensive)
    order += [k for k in pct if k not in order]
    ordered = [k for k in order if k in pct]

    if len(ordered) < 3:
        fig = go.Figure()
        fig.add_annotation(text="Not enough comparable metrics<br>for a percentile radar",
                           x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                           font=dict(color=MUTED, size=13))
        fig.update_layout(height=420, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG)
        return fig

    labels = [_LBL.get(k, k) for k in ordered]
    rvals = [pct[k] for k in ordered]
    rawvals = [raw.get(k, 0) for k in ordered]
    pmaxvals = [pmax.get(k, 0) for k in ordered]
    rankvals = [str(ranks.get(k, "—")) for k in ordered]
    leadervals = [leaders.get(k, "—") for k in ordered]

    def _rgb(c):
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    _scale_word = "% of peer max" if scale == "max" else "th percentile"
    r, g, b = _rgb(color)
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=rvals + [rvals[0]], theta=labels + [labels[0]], fill="toself",
        fillcolor=f"rgba({r},{g},{b},0.25)", line=dict(color=color, width=2.5),
        name=player_name,
        customdata=[[rawvals[i], pmaxvals[i], rankvals[i], leadervals[i]] for i in range(len(ordered))]
                   + [[rawvals[0], pmaxvals[0], rankvals[0], leadervals[0]]],
        hovertemplate=("<b>%{theta}</b><br>%{r}" + _scale_word +
                       "<br>raw exact: %{customdata[0]:.4f}/match" +
                       "<br>peer max exact: %{customdata[1]:.4f}/match" +
                       "<br>rank: %{customdata[2]}" +
                       "<br>leader: %{customdata[3]}" +
                       "<br>formula: raw ÷ peer max × 100" +
                       "<extra>" + player_name + "</extra>"),
    ))

    show_legend = False
    if peer_b is not None and name_b:
        pct_b = peer_b.get(val_key, {}) or peer_b.get("percentiles", {})
        raw_b = peer_b.get("raw_exact", peer_b.get("raw", {}))
        # use the SAME ordered axes; missing metrics → 0 so shapes align
        rvals_b = [pct_b.get(k, 0) for k in ordered]
        rawvals_b = [raw_b.get(k, 0) for k in ordered]
        rb, gb, bb = _rgb(color_b)
        fig.add_trace(go.Scatterpolar(
            r=rvals_b + [rvals_b[0]], theta=labels + [labels[0]], fill="toself",
            fillcolor=f"rgba({rb},{gb},{bb},0.18)", line=dict(color=color_b, width=2.5, dash="dot"),
            name=name_b, customdata=[[rv] for rv in rawvals_b] + [[rawvals_b[0]]],
            hovertemplate="<b>%{theta}</b><br>%{r}" + _scale_word + "<br>raw exact: %{customdata[0]:.4f}/match<extra>" + name_b + "</extra>",
        ))
        show_legend = True

    _title = (f"Max-normalized vs {peer.get('n_peers', 0)} {position_group} peers"
              if scale == "max" else
              f"Percentile vs {peer.get('n_peers', 0)} {position_group} peers")
    fig.update_layout(
        polar=dict(bgcolor=CARD_BG,
                   radialaxis=dict(visible=True, range=[0, 100], gridcolor=GRID,
                                   tickfont=dict(color=MUTED, size=8), tickvals=[20, 40, 60, 80, 100]),
                   angularaxis=dict(tickfont=dict(color=TEXT, size=10), gridcolor=GRID)),
        paper_bgcolor=CARD_BG, font=dict(color=TEXT), height=420,
        margin=dict(l=60, r=60, t=35, b=35), showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="center", x=0.5, font=dict(size=10)),
        title=dict(text=_title, font=dict(size=11, color=MUTED), x=0.5, y=0.02),
    )
    return fig
