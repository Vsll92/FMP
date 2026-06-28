"""
components/report_engine.py — Pre-Match & Post-Match Report Data Engine
Computes all advanced tactical metrics from eventing data:
  PPDA, field tilt, progressive passes, xG model, buildup profiles,
  transition metrics, set-piece analysis, player role profiles, etc.
"""

import pandas as pd
import numpy as np
from data_loader import (


    load_league_data, get_match_list, get_match_data, get_teams,
    get_player_stats, get_team_results, compute_match_stats,
    get_match_lineup, short, team_color, filter_by_period,
    TEAM_COLORS, DEFAULT_CLUB,
)

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
#  CONSTANTS  — sourced from the central registry (components/definitions.py)
#  so shot-event and pitch-geometry definitions exist in exactly one place.
# ══════════════════════════════════════════════════════════════════════════
from components.definitions import (
    SHOT_EVENTS, ON_TARGET_EVENTS, DEFENSIVE_EVENTS,
    BOX_X, BOX_Y_LO, BOX_Y_HI, FINAL_THIRD_X, MID_THIRD_X,
)
DEF_ACTIONS = ["Tackle", "Interception", "Foul"]  # for PPDA (includes fouls)


def _xg_from_distance(x, y, is_head=False, is_big_chance=False):
    """Distance + angle based xG model (calibrated to realistic range)."""
    dist = np.sqrt((100 - x)**2 + (50 - y)**2)
    angle = np.arctan2(7.32, max(dist, 1))  # radians
    # Base xG from distance (exponential decay)
    xg = np.exp(-dist / 16) * 0.55
    # Angle factor (narrow angle = lower xG)
    xg *= min(angle / 0.30, 1.0)
    xg = np.clip(xg, 0.02, 0.85)
    if is_head:
        xg *= 0.7
    if is_big_chance:
        xg = max(xg * 1.5, 0.35)
        xg = min(xg, 0.90)
    return round(xg, 3)


def _safe_pct(num, den):
    return round(num / max(den, 1) * 100, 1)


def _safe_div(num, den):
    return round(num / max(den, 1), 2)


# ══════════════════════════════════════════════════════════════════════════
#  TEAM PROFILE (multi-match aggregate for pre-match scouting)
# ══════════════════════════════════════════════════════════════════════════
def _percentile_of(value, distribution):
    """Percentile rank (0-100) of value within distribution (higher value =>
    higher percentile). Returns None if distribution too small."""
    vals = [v for v in distribution if v is not None]
    if value is None or len(vals) < 4:
        return None
    return round(sum(1 for v in vals if v <= value) / len(vals) * 100)


def _league_threat_benchmarks(league_folder, last_n):
    """Fast league-wide distribution of threat/weakness metrics.

    Older versions recursively called compute_team_profile for every team, which
    made report generation and release QA hang. This lightweight benchmark uses
    the already-loaded event and match tables directly and computes only the
    metrics required by the threat/weakness normalizer.
    """
    from data_loader import _CACHE, get_teams, load_league_data, get_match_list
    _ck = f"threatbench_fast_{league_folder}_{last_n}"
    if _ck in _CACHE:
        return _CACHE[_ck]
    df = load_league_data(league_folder)
    ml = get_match_list(league_folder)
    dist = {"xg_per_match": [], "big_chances_pm": [], "sp_shots_pm": [],
            "fast_break_share": [], "ppda": [], "opp_pass_acc": [],
            "high_turnovers_pm": [], "def_height": []}
    for team in get_teams(league_folder):
        mids = ml[(ml["home_team"] == team) | (ml["away_team"] == team)].sort_values("week", ascending=False).head(last_n)["match_id"].tolist()
        if not mids:
            continue
        tdf = df[(df["match_id"].isin(mids)) & (df["team_name"] == team)]
        odf = df[(df["match_id"].isin(mids)) & (df["team_name"] != team)]
        n = max(len(mids), 1)
        shots = tdf[tdf["event"].isin(SHOT_EVENTS)]
        xg_total = 0.0
        fast_xg = 0.0
        for _, r in shots.iterrows():
            xg = _xg_from_distance(r.get("x"), r.get("y"), _FLAGVAL(r.get("Head")), _FLAGVAL(r.get("Big Chance")))
            xg_total += xg
            if _FLAGVAL(r.get("Fast break")):
                fast_xg += xg
        big = len(shots[_flagmask(shots["Big Chance"])]) if "Big Chance" in shots.columns else 0
        sp = len(shots[_flagmask(shots["Set piece"])]) + len(shots[_flagmask(shots["From corner"])]) if len(shots) else 0
        opp_passes = odf[odf["event"] == "Pass"]
        opp_passes_own = len(opp_passes[opp_passes["x"] < 50]) if not opp_passes.empty else 0
        our_def_opp = len(tdf[(tdf["event"].isin(DEF_ACTIONS)) & (tdf["x"] > 50)])
        ppda = _safe_div(opp_passes_own, our_def_opp)
        opp_acc = _safe_pct((opp_passes["outcome"] == 1).sum(), len(opp_passes)) if len(opp_passes) else 0
        dispossessed = tdf[tdf["event"] == "Dispossessed"]
        high_turn = len(dispossessed[dispossessed["x"] > 50])
        def_actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery"])]
        def_h = float(def_actions["x"].mean()) if len(def_actions) else 50.0
        vals = {
            "xg_per_match": round(_safe_div(xg_total, n), 3),
            "big_chances_pm": round(_safe_div(big, n), 3),
            "sp_shots_pm": round(_safe_div(sp, n), 3),
            "fast_break_share": round(_safe_div(fast_xg, xg_total), 3) if xg_total else 0.0,
            "ppda": round(ppda, 2),
            "opp_pass_acc": round(opp_acc, 1),
            "high_turnovers_pm": round(_safe_div(high_turn, n), 3),
            "def_height": round(def_h, 1),
        }
        for k, v in vals.items():
            dist[k].append(v)
    _CACHE[_ck] = dist
    return dist


def compute_team_profile(league_folder: str, team_name: str, last_n: int = 5,
                         before_matchweek=None, before_date=None,
                         exclude_match_id=None, _skip_benchmark: bool = False) -> dict:
    """
    Build a comprehensive tactical profile for a team over recent matches.
    This powers the Pre-Match Report.

    Pre-match cutoff (prevents data leakage in post-match reports):
      before_matchweek: only use matches with week < this value
      before_date:      only use matches before this date
      exclude_match_id: drop this specific match (e.g. the one being graded)
    """
    from data_loader import _CACHE, normalize_team
    team_name = normalize_team(team_name)
    _ck = f"teamprofile_{league_folder}_{team_name}_{last_n}_{before_matchweek}_{before_date}_{exclude_match_id}_{_skip_benchmark}"
    if _ck in _CACHE:
        return _CACHE[_ck]

    df = load_league_data(league_folder)
    ml = get_match_list(league_folder)

    # Get recent matches for this team
    tm_matches = ml[(ml["home_team"] == team_name) | (ml["away_team"] == team_name)]
    # ── Pre-match cutoff: keep only matches available BEFORE the target match ──
    if before_matchweek is not None:
        tm_matches = tm_matches[tm_matches["week"] < before_matchweek]
    if before_date is not None and "local_date" in tm_matches.columns:
        tm_matches = tm_matches[tm_matches["local_date"] < before_date]
    if exclude_match_id is not None:
        tm_matches = tm_matches[tm_matches["match_id"] != exclude_match_id]
    tm_matches = tm_matches.sort_values("week", ascending=False).head(last_n)
    match_ids = tm_matches["match_id"].tolist()

    if not match_ids:
        return {}

    tdf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] == team_name)]
    opp_df = df[(df["match_id"].isin(match_ids)) & (df["team_name"] != team_name)]
    n_matches = len(match_ids)

    passes = tdf[tdf["event"] == "Pass"].copy()
    passes_with_end = passes.dropna(subset=["Pass End X", "Pass End Y"])
    succ_passes = passes[passes["outcome"] == 1]
    shots = tdf[tdf["event"].isin(SHOT_EVENTS)].copy()
    goals = tdf[tdf["event"] == "Goal"]
    tackles = tdf[tdf["event"] == "Tackle"]
    intercepts = tdf[tdf["event"] == "Interception"]
    recoveries = tdf[tdf["event"] == "Ball recovery"]
    clearances = tdf[tdf["event"] == "Clearance"]
    take_ons = tdf[tdf["event"] == "Take On"]
    aerials = tdf[tdf["event"] == "Aerial"]
    fouls_committed = tdf[(tdf["event"] == "Foul") & (tdf["outcome"] == 0)]
    corners = tdf[tdf["event"] == "Corner Awarded"]

    # Opponent data
    opp_passes = opp_df[opp_df["event"] == "Pass"]
    opp_shots = opp_df[opp_df["event"].isin(SHOT_EVENTS)]

    # ── A. GAME CONTROL ──
    total_events = len(tdf[tdf["x"].notna()])
    total_opp_events = len(opp_df[opp_df["x"].notna()])
    # Pass Share (event-derived proxy, NOT true time-based possession)
    pass_share = _safe_pct(len(passes), len(passes) + len(opp_passes))
    possession_pct = pass_share  # back-compat alias; labelled "Pass Share" in UI

    # Field tilt = final-third touch SHARE between the two teams (territorial),
    # not a team's FT touches over its own total touches.
    ft_touches = len(tdf[(tdf["x"].notna()) & (tdf["x"] > FINAL_THIRD_X)])
    opp_ft_touches = len(opp_df[(opp_df["x"].notna()) & (opp_df["x"] > FINAL_THIRD_X)])
    field_tilt = _safe_pct(ft_touches, ft_touches + opp_ft_touches)

    # Passes per sequence (approximate: count passes between turnovers)
    avg_pass_count = _safe_div(len(passes), n_matches)

    # ── B. PROGRESSION ──
    prog_passes = passes_with_end[(passes_with_end["Pass End X"] - passes_with_end["x"]) > 10]
    prog_carries = tdf[(tdf["event"] == "Take On") & (tdf["outcome"] == 1)]

    # Line-breaking (passes into final third)
    line_breaks = passes_with_end[
        (passes_with_end["x"] < FINAL_THIRD_X) &
        (passes_with_end["Pass End X"] >= FINAL_THIRD_X)
    ]

    # Final third entries: must START outside the final third and END inside,
    # and the pass must be COMPLETED (the ball actually entered the zone).
    _completed = passes_with_end["outcome"] == 1
    ft_entries = passes_with_end[
        _completed &
        (passes_with_end["x"] < FINAL_THIRD_X) &
        (passes_with_end["Pass End X"] >= FINAL_THIRD_X)
    ]

    # Box entries: completed pass that STARTS outside the box and ENDS inside.
    _starts_in_box = (
        (passes_with_end["x"] >= BOX_X) &
        (passes_with_end["y"] >= BOX_Y_LO) &
        (passes_with_end["y"] <= BOX_Y_HI)
    )
    _ends_in_box = (
        (passes_with_end["Pass End X"] >= BOX_X) &
        (passes_with_end["Pass End Y"] >= BOX_Y_LO) &
        (passes_with_end["Pass End Y"] <= BOX_Y_HI)
    )
    box_entries = passes_with_end[_completed & (~_starts_in_box) & _ends_in_box]

    # Lane distribution (left/center/right based on y)
    left_prog = passes_with_end[passes_with_end["Pass End Y"] >= 66.6]
    center_prog = passes_with_end[(passes_with_end["Pass End Y"] >= 33.3) & (passes_with_end["Pass End Y"] < 66.6)]
    right_prog = passes_with_end[passes_with_end["Pass End Y"] < 33.3]

    total_prog = max(len(passes_with_end), 1)
    lane_dist = {
        "left": _safe_pct(len(left_prog), total_prog),
        "center": _safe_pct(len(center_prog), total_prog),
        "right": _safe_pct(len(right_prog), total_prog),
    }

    # Buildup side
    buildup_passes = passes_with_end[passes_with_end["x"] < MID_THIRD_X]
    if len(buildup_passes) > 0:
        avg_buildup_y = buildup_passes["y"].mean()
        buildup_side = "Left" if avg_buildup_y > 55 else ("Right" if avg_buildup_y < 45 else "Central")
    else:
        buildup_side = "Unknown"

    # Switches of play
    switches = len(passes[_flagmask(passes["Switch of play"])]) if "Switch of play" in passes.columns else 0

    # ── C. CREATION ──
    # xG computation
    xg_total = 0
    shot_details = []
    for _, s in shots.iterrows():
        is_head = _FLAGVAL(s.get("Head"))
        is_bc = _FLAGVAL(s.get("Big Chance"))
        xg = _xg_from_distance(s["x"], s["y"], is_head, is_bc)
        xg_total += xg
        shot_details.append({
            "event": s["event"], "player": s.get("player_name", ""),
            "x": s["x"], "y": s["y"], "xg": xg,
            "body": "Head" if is_head else ("Left" if _FLAGVAL(s.get("Left footed")) else "Right"),
            "context": "Set Piece" if _FLAGVAL(s.get("Set piece")) else ("Fast Break" if _FLAGVAL(s.get("Fast break")) else "Open Play"),
            "big_chance": is_bc, "minute": s.get("time_min", 0),
        })

    xg_per_match = _safe_div(xg_total, n_matches)
    xg_open_play = sum(s["xg"] for s in shot_details if s["context"] == "Open Play")
    xg_set_piece = sum(s["xg"] for s in shot_details if s["context"] == "Set Piece")
    xg_fast_break = sum(s["xg"] for s in shot_details if s["context"] == "Fast Break")

    big_chances = len(shots[_flagmask(shots["Big Chance"])])
    crosses = len(passes[_flagmask(passes["Cross"])])
    through_balls = len(passes[_flagmask(passes["Through ball"])])
    long_balls = len(passes[_flagmask(passes["Long ball"])])

    # Cut-backs (passes from wide into box, going backwards in x)
    cutbacks = passes_with_end[
        (passes_with_end["x"] > BOX_X) &
        (passes_with_end["Pass End X"] < passes_with_end["x"]) &
        (passes_with_end["Pass End X"] > BOX_X - 15) &
        ((passes_with_end["y"] < 30) | (passes_with_end["y"] > 70))
    ]

    # ── D. PRESSING / DEFENSIVE CONTROL ──
    # PPDA = opponent passes in their own half / our defensive actions in their half
    opp_passes_own_half = len(opp_passes[opp_passes["x"] < 50])
    our_def_actions_opp_half = len(tdf[
        (tdf["event"].isin(DEF_ACTIONS)) & (tdf["x"] > 50)
    ])
    ppda = _safe_div(opp_passes_own_half, our_def_actions_opp_half)

    # Defensive action height
    def_actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery"])]
    def_height = def_actions["x"].mean() if len(def_actions) > 0 else 50

    # High regains (in opponent half)
    high_regains = len(recoveries[recoveries["x"] > 50])

    # Opponent pass completion under our press
    opp_pass_acc = _safe_pct((opp_passes["outcome"] == 1).sum(), len(opp_passes))

    # ── E. TRANSITION ──
    # Fast break shots
    fast_break_shots = len(shots[_flagmask(shots["Fast break"])])
    fast_break_xg = xg_fast_break

    # High turnovers (ball losses in own half)
    dispossessed = tdf[tdf["event"] == "Dispossessed"]
    high_turnovers = len(dispossessed[dispossessed["x"] > 50])

    # ── F. SET PIECES ──
    corner_count = len(tdf[_flagmask(tdf["Corner taken"])])
    fk_count = len(tdf[_flagmask(tdf["Free kick taken"])])
    sp_shots = len(shots[_flagmask(shots["Set piece"])]) + len(shots[_flagmask(shots["From corner"])])
    sp_goals = len(goals[(_flagmask(goals["Set piece"])) | (_flagmask(goals["From corner"]))])

    # Opponent set piece threat
    opp_sp_shots = len(opp_shots[(_flagmask(opp_shots["Set piece"])) | (_flagmask(opp_shots["From corner"]))])

    # ── G. FORMATIONS ──
    formations = tdf["formation"].dropna().unique()
    formation_strs = [str(int(f)) for f in formations if pd.notna(f)]
    # Format formation: e.g., "4231" -> "4-2-3-1"
    def fmt_form(s):
        return "-".join(list(s)) if len(s) <= 5 else s
    formation_display = [fmt_form(f) for f in formation_strs]

    # ── H. STYLE ARCHETYPE ──
    style_tags = []
    if possession_pct > 55:
        style_tags.append("Possession-based")
    elif possession_pct < 45:
        style_tags.append("Counter-attacking")
    if ppda < 9:
        style_tags.append("High-pressing")
    elif ppda > 13:
        style_tags.append("Mid/Low block")
    if lane_dist["left"] > 38 or lane_dist["right"] > 38:
        style_tags.append("Wing-oriented")
    if lane_dist["center"] > 40:
        style_tags.append("Central-focused")
    if long_balls / max(len(passes), 1) > 0.12:
        style_tags.append("Direct")
    else:
        style_tags.append("Patient buildup")
    if fast_break_shots / max(len(shots), 1) > 0.1:
        style_tags.append("Transition-heavy")
    if sp_goals / max(len(goals), 1) > 0.25:
        style_tags.append("Set-piece threat")
    if not style_tags:
        style_tags.append("Balanced")

    # ── WEAKNESSES / THREATS (league-normalized, evidence-backed) ──
    # Raw per-match metrics for this team (also exposed for the league benchmark).
    threat_metrics = {
        "xg_per_match": round(xg_per_match, 3),
        "big_chances_pm": round(_safe_div(big_chances, n_matches), 3),
        "sp_shots_pm": round(_safe_div(sp_shots, n_matches), 3),
        "fast_break_share": round(_safe_div(fast_break_xg, xg_total), 3) if xg_total else 0.0,
        "ppda": round(ppda, 2),
        "opp_pass_acc": round(opp_pass_acc, 1),
        "high_turnovers_pm": round(_safe_div(high_turnovers, n_matches), 3),
        "def_height": round(def_height, 1),
    }

    threats = []
    weaknesses = []
    if not _skip_benchmark:
        bench = _league_threat_benchmarks(league_folder, last_n)

        def _pct(metric):
            return _percentile_of(threat_metrics.get(metric), bench.get(metric, []))

        # THREATS — only flagged when the team is genuinely high vs the league
        # (>=70th percentile), each with its percentile + raw evidence. This
        # stops "High xG generation" appearing for every above-average side.
        threat_defs = [
            ("xg_per_match", "Chance volume (xG)", lambda v: f"{v:.2f} xG/match", True),
            ("big_chances_pm", "Big-chance creation", lambda v: f"{v:.1f} big chances/match", True),
            ("sp_shots_pm", "Set-piece threat", lambda v: f"{v:.1f} set-play shots/match", True),
            ("fast_break_share", "Transition threat", lambda v: f"{v*100:.0f}% of xG from fast breaks", True),
        ]
        scored = []
        for metric, label, eviden, _hib in threat_defs:
            pct = _pct(metric)
            if pct is not None and pct >= 70:
                scored.append((pct, f"{label} — {pct}th pct, {eviden(threat_metrics[metric])}"))
        scored.sort(reverse=True)
        threats = [s for _, s in scored]

        # WEAKNESSES — high-is-bad metrics flagged when in the worst third.
        if (p := _pct("opp_pass_acc")) is not None and p >= 70:
            weaknesses.append(f"Allow high opponent pass completion — {p}th pct, {opp_pass_acc:.1f}%")
        if (p := _pct("ppda")) is not None and p >= 70:
            weaknesses.append(f"Passive pressing — {p}th pct PPDA {ppda:.1f} (higher = less pressing)")
        if (p := _pct("high_turnovers_pm")) is not None and p >= 70:
            weaknesses.append(f"Turnover-prone in advanced areas — {p}th pct, {_safe_div(high_turnovers, n_matches):.1f}/match")
        # Deep line: low def_height is the weakness, so invert the percentile.
        dh_pct = _pct("def_height")
        if dh_pct is not None and dh_pct <= 30:
            weaknesses.append(f"Deep defensive line — bottom {dh_pct}th pct, {def_height:.0f} avg height")
        if buildup_side != "Central":
            weaknesses.append(f"Predictable buildup ({buildup_side} side) — Season Context")
    else:
        # Benchmark pass: keep a minimal absolute fallback (not shown to users).
        if xg_per_match > 1.5:
            threats.append(f"High xG generation ({xg_per_match:.2f}/match)")

    _result = {
        "team": team_name,
        "matches_analyzed": n_matches,
        "match_ids": match_ids,
        "threat_metrics": threat_metrics,
        # Form
        "results": get_team_results(league_folder, team_name).tail(last_n).to_dict("records"),
        # Style
        "style_tags": style_tags,
        "formations": formation_display,
        "buildup_side": buildup_side,
        # Game control
        "possession_pct": possession_pct,
        "field_tilt": field_tilt,
        "passes_per_match": _safe_div(len(passes), n_matches),
        "pass_accuracy": _safe_pct((passes["outcome"]==1).sum(), len(passes)),
        # Progression
        "prog_passes_pm": _safe_div(len(prog_passes), n_matches),
        "line_breaks_pm": _safe_div(len(line_breaks), n_matches),
        "ft_entries_pm": _safe_div(len(ft_entries), n_matches),
        "box_entries_pm": _safe_div(len(box_entries), n_matches),
        "lane_distribution": lane_dist,
        "switches_pm": _safe_div(switches, n_matches),
        "long_balls_pm": _safe_div(long_balls, n_matches),
        # Creation
        "xg_total": round(xg_total, 2),
        "xg_per_match": xg_per_match,
        "xg_open_play": round(xg_open_play, 2),
        "xg_set_piece": round(xg_set_piece, 2),
        "xg_fast_break": round(xg_fast_break, 2),
        "shots_pm": _safe_div(len(shots), n_matches),
        "shots_on_target_pm": _safe_div(len(tdf[tdf["event"].isin(["Goal","Saved Shot"])]), n_matches),
        "big_chances_pm": _safe_div(big_chances, n_matches),
        "crosses_pm": _safe_div(crosses, n_matches),
        "through_balls_pm": _safe_div(through_balls, n_matches),
        "cutbacks_pm": _safe_div(len(cutbacks), n_matches),
        "goals_pm": _safe_div(len(goals), n_matches),
        "shot_details": shot_details,
        # Pressing / Defense
        "ppda": ppda,
        "def_action_height": round(def_height, 1),
        "high_regains_pm": _safe_div(high_regains, n_matches),
        "tackles_pm": _safe_div(len(tackles), n_matches),
        "interceptions_pm": _safe_div(len(intercepts), n_matches),
        "recoveries_pm": _safe_div(len(recoveries), n_matches),
        "clearances_pm": _safe_div(len(clearances), n_matches),
        "opp_pass_acc": opp_pass_acc,
        # Transition
        "fast_break_shots_pm": _safe_div(fast_break_shots, n_matches),
        "fast_break_xg": round(fast_break_xg, 2),
        "high_turnovers_pm": _safe_div(high_turnovers, n_matches),
        # Set pieces
        "corners_pm": _safe_div(corner_count, n_matches),
        "fk_pm": _safe_div(fk_count, n_matches),
        "sp_shots_pm": _safe_div(sp_shots, n_matches),
        "sp_goals": sp_goals,
        "opp_sp_shots_pm": _safe_div(opp_sp_shots, n_matches),
        # Analysis
        "threats": threats,
        "weaknesses": weaknesses,
    }

    # ── Wyscout season enrichment (pre-match, before cutoff) ──
    # Average the team's Wyscout xG/xGA/PPDA/possession over the SAME matches used
    # for this profile so plan inference uses official values, not event pass-share.
    try:
        from components.metric_engine import get_wyscout_df
        wy = get_wyscout_df()
        if wy is not None and match_ids:
            mdates = ml[ml["match_id"].isin(match_ids)]["local_date"].astype(str).str[:10].tolist()
            wsub = wy[(wy["team_name_canon"] == team_name) & (wy["date"].isin(mdates))]
            if not wsub.empty:
                import numpy as _np
                def _wm(col):
                    v = wsub[col].dropna() if col in wsub.columns else None
                    return round(float(v.mean()), 2) if v is not None and len(v) else None
                _result["wyscout_xg"] = _wm("wyscout_xg")
                _result["wyscout_ppda"] = _wm("wyscout_ppda")
                _result["wyscout_possession_pct"] = _wm("wyscout_possession_pct")
                _result["wyscout_shots"] = _wm("wyscout_shots")
                # opponent Wyscout xG over same fixtures = xGA proxy
                oppd = wy[(wy["date"].isin(mdates)) & (wy["opponent_name_canon"] == team_name)]
                if not oppd.empty and "wyscout_xg" in oppd.columns:
                    _result["wyscout_xga"] = round(float(oppd["wyscout_xg"].dropna().mean()), 2) if oppd["wyscout_xg"].dropna().size else None
                _result["wyscout_available"] = True
    except Exception as _e:
        print(f"[PROFILE_QA] Wyscout enrichment skipped: {_e}")

    _CACHE[_ck] = _result
    return _result


# ══════════════════════════════════════════════════════════════════════════
#  POST-MATCH REPORT
# ══════════════════════════════════════════════════════════════════════════
def compute_post_match_report(league_folder: str, match_id: str) -> dict:
    """
    Full post-match analytics for a single match.
    Powers the Post-Match Report with plan-vs-reality evaluation.
    """
    mdf = get_match_data(league_folder, match_id)
    if mdf.empty:
        return {}

    ml = get_match_list(league_folder)
    info_df = ml[ml["match_id"] == match_id]
    if info_df.empty:
        return {}
    info = info_df.iloc[0]

    home_name = info["home_team"]
    away_name = info["away_team"]

    report = {"match_id": match_id, "home": {}, "away": {}}
    report["meta"] = {
        "home_team": home_name, "away_team": away_name,
        "home_goals": int(info["home_goals"]), "away_goals": int(info["away_goals"]),
        "week": int(info["week"]), "date": info["local_date"],
        "venue": info.get("venue", ""),
    }

    for side, team_name in [("home", home_name), ("away", away_name)]:
        tdf = mdf[mdf["team_name"] == team_name]
        odf = mdf[mdf["team_name"] != team_name]

        passes = tdf[tdf["event"] == "Pass"].copy()
        passes_end = passes.dropna(subset=["Pass End X", "Pass End Y"])
        shots = tdf[tdf["event"].isin(SHOT_EVENTS)].copy()
        goals = tdf[tdf["event"] == "Goal"]
        opp_passes = odf[odf["event"] == "Pass"]
        opp_shots = odf[odf["event"].isin(SHOT_EVENTS)]

        # ── Game Control ──
        pass_share = _safe_pct(len(passes), len(passes) + len(opp_passes))
        possession = pass_share  # labelled "Pass Share" in UI (event-derived)
        ft_touch = len(tdf[(tdf["x"].notna()) & (tdf["x"] > FINAL_THIRD_X)])
        opp_ft_touch = len(odf[(odf["x"].notna()) & (odf["x"] > FINAL_THIRD_X)])
        field_tilt = _safe_pct(ft_touch, ft_touch + opp_ft_touch)

        # ── Progression ──
        prog_passes = passes_end[(passes_end["Pass End X"] - passes_end["x"]) > 10]
        line_breaks = passes_end[(passes_end["x"] < FINAL_THIRD_X) & (passes_end["Pass End X"] >= FINAL_THIRD_X)]
        # Final-third entries: completed pass, start outside, end inside
        _comp = passes_end["outcome"] == 1
        ft_entries = passes_end[_comp & (passes_end["x"] < FINAL_THIRD_X) & (passes_end["Pass End X"] >= FINAL_THIRD_X)]
        # Box entries: completed pass, start outside box, end inside box
        _sib = ((passes_end["x"] >= BOX_X) & (passes_end["y"] >= BOX_Y_LO) & (passes_end["y"] <= BOX_Y_HI))
        _eib = ((passes_end["Pass End X"] >= BOX_X) & (passes_end["Pass End Y"] >= BOX_Y_LO) & (passes_end["Pass End Y"] <= BOX_Y_HI))
        box_entries = passes_end[_comp & (~_sib) & _eib]

        # Lane distribution
        left = len(passes_end[passes_end["Pass End Y"] >= 66.6])
        center = len(passes_end[(passes_end["Pass End Y"] >= 33.3) & (passes_end["Pass End Y"] < 66.6)])
        right = len(passes_end[passes_end["Pass End Y"] < 33.3])
        total_lane = max(left + center + right, 1)

        # Switches
        switches = len(passes[_flagmask(passes["Switch of play"])]) if "Switch of play" in passes.columns else 0

        # ── Creation & xG ──
        xg_total = 0
        xg_by_context = {"Open Play": 0, "Set Piece": 0, "Fast Break": 0}
        shot_list = []
        for _, s in shots.iterrows():
            is_head = _FLAGVAL(s.get("Head"))
            is_bc = _FLAGVAL(s.get("Big Chance"))
            xg = _xg_from_distance(s["x"], s["y"], is_head, is_bc)
            xg_total += xg
            ctx = "Set Piece" if _FLAGVAL(s.get("Set piece")) or _FLAGVAL(s.get("From corner")) else (
                "Fast Break" if _FLAGVAL(s.get("Fast break")) else "Open Play")
            xg_by_context[ctx] += xg
            shot_list.append({
                "event": s["event"], "player": s.get("player_name", ""),
                "x": s["x"], "y": s["y"], "xg": xg, "minute": s.get("time_min", 0),
                "context": ctx,
                "body": "Head" if is_head else ("Left" if _FLAGVAL(s.get("Left footed")) else "Right"),
                "big_chance": is_bc,
            })

        big_chances = len(shots[_flagmask(shots["Big Chance"])])
        crosses = len(passes[_flagmask(passes["Cross"])])
        through_balls = len(passes[_flagmask(passes["Through ball"])])

        # ── Pressing ──
        opp_passes_own = len(opp_passes[opp_passes["x"] < 50])
        our_def_opp = len(tdf[(tdf["event"].isin(DEF_ACTIONS)) & (tdf["x"] > 50)])
        ppda = _safe_div(opp_passes_own, our_def_opp)

        def_actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery"])]
        def_height = def_actions["x"].mean() if len(def_actions) > 0 else 50
        high_regains = len(tdf[(tdf["event"] == "Ball recovery") & (tdf["x"] > 50)])

        # Counterpress (recoveries within 5 seconds concept — approximate by recoveries in opp half)
        counterpress = len(tdf[(tdf["event"] == "Ball recovery") & (tdf["x"] > 60)])

        # ── Transition ──
        fast_break_shots = len(shots[_flagmask(shots["Fast break"])])
        opp_fb_shots = len(opp_shots[_flagmask(opp_shots["Fast break"])])
        transition_xg_for = sum(s["xg"] for s in shot_list if s["context"] == "Fast Break")
        # opponent transition xG against
        opp_fb_xg = 0
        for _, s in opp_shots[_flagmask(opp_shots["Fast break"])].iterrows():
            opp_fb_xg += _xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))

        # ── Set Pieces ──
        sp_shots = len(shots[(_flagmask(shots["Set piece"])) | (_flagmask(shots["From corner"]))])
        sp_goals = len(goals[(_flagmask(goals["Set piece"])) | (_flagmask(goals["From corner"]))])
        opp_sp_shots = len(opp_shots[(_flagmask(opp_shots["Set piece"])) | (_flagmask(opp_shots["From corner"]))])
        corners = len(tdf[_flagmask(tdf["Corner taken"])])

        # ── Duels ──
        tackles_data = tdf[tdf["event"] == "Tackle"]
        aerials_data = tdf[tdf["event"] == "Aerial"]
        take_ons_data = tdf[tdf["event"] == "Take On"]

        # ── Game Story ──
        h1_shots = len(shots[shots["time_min"] <= 45])
        h2_shots = len(shots[shots["time_min"] > 45])
        h1_xg = sum(s["xg"] for s in shot_list if s["minute"] <= 45)
        h2_xg = sum(s["xg"] for s in shot_list if s["minute"] > 45)

        # ── xG Timeline (rolling) ──
        sorted_shots = sorted(shot_list, key=lambda s: s["minute"])
        xg_timeline = []
        cum_xg = 0
        for s in sorted_shots:
            cum_xg += s["xg"]
            xg_timeline.append({"minute": s["minute"], "cum_xg": round(cum_xg, 3), "event": s["event"], "player": s["player"]})

        report[side] = {
            "team": team_name,
            # Control
            "possession": possession,
            "field_tilt": field_tilt,
            "pass_accuracy": _safe_pct((passes["outcome"]==1).sum(), len(passes)),
            "passes": len(passes),
            # Progression
            "prog_passes": len(prog_passes),
            "line_breaks": len(line_breaks),
            "ft_entries": len(ft_entries),
            "box_entries": len(box_entries),
            "lane_left": _safe_pct(left, total_lane),
            "lane_center": _safe_pct(center, total_lane),
            "lane_right": _safe_pct(right, total_lane),
            "switches": switches,
            # Creation
            "xg": round(xg_total, 2),
            "xg_by_context": {k: round(v, 2) for k, v in xg_by_context.items()},
            "shots": len(shots),
            "shots_on_target": len(tdf[tdf["event"].isin(["Goal", "Saved Shot"])]),
            # Canonical goals from the registry/meta (own-goal-aware, Wyscout-true),
            # NOT raw len(Goal events) which mis-credits own goals.
            "goals": int(info["home_goals"]) if side == "home" else int(info["away_goals"]),
            "raw_goal_events": len(goals),
            "big_chances": big_chances,
            "crosses": crosses,
            "through_balls": through_balls,
            "shot_list": shot_list,
            "xg_timeline": xg_timeline,
            # Pressing
            "ppda": ppda,
            "def_height": round(def_height, 1),
            "high_regains": high_regains,
            "counterpress": counterpress,
            "tackles": len(tackles_data),
            "tackles_won": len(tackles_data[tackles_data["outcome"]==1]),
            "interceptions": len(tdf[tdf["event"] == "Interception"]),
            "recoveries": len(tdf[tdf["event"] == "Ball recovery"]),
            "clearances": len(tdf[tdf["event"] == "Clearance"]),
            # Transition
            "fast_break_shots": fast_break_shots,
            "transition_xg_for": round(transition_xg_for, 2),
            "transition_xg_against": round(opp_fb_xg, 2),
            "opp_fast_break_shots": opp_fb_shots,
            # Set pieces
            "corners": corners,
            "sp_shots": sp_shots,
            "sp_goals": sp_goals,
            "opp_sp_shots": opp_sp_shots,
            # Duels
            "aerials_won": len(aerials_data[aerials_data["outcome"]==1]),
            "aerials_total": len(aerials_data),
            "take_ons_won": len(take_ons_data[take_ons_data["outcome"]==1]),
            "take_ons_total": len(take_ons_data),
            "fouls_committed": len(tdf[(tdf["event"]=="Foul") & (tdf["outcome"]==0)]),
            "yellow_cards": len(tdf[(tdf["event"]=="Card") & (_flagmask(tdf["Yellow Card"]))]),
            "red_cards": len(tdf[(tdf["event"]=="Card") & (_flagmask(tdf["Red Card"]))]),
            # Halves
            "h1_xg": round(h1_xg, 2),
            "h2_xg": round(h2_xg, 2),
            "h1_shots": h1_shots,
            "h2_shots": h2_shots,
        }

    # ── Wyscout official overlay (source of truth for team-level metrics) ──
    # Preserve event-derived values under event_* keys, then make the main
    # metric keys Wyscout-sourced where the fixture is matched. Per-side
    # 'xg_source' / 'ppda_source' / 'possession_source' record provenance.
    try:
        from components.metric_engine import get_wyscout_df
        from components.wyscout_loader import wyscout_lookup
        wy = get_wyscout_df()
        meta = report.get("meta", {})
        mdate = meta.get("date")
        if wy is not None and mdate:
            for side, opp_side in (("home", "away"), ("away", "home")):
                tcanon = report[side]["team"]
                ocanon = report[opp_side]["team"]
                sub = wy[wy["date"] == str(mdate)[:10]]
                trow = sub[sub["team_name_canon"] == tcanon]
                orow = sub[sub["team_name_canon"] == ocanon]
                rec = report[side]
                # Always keep event-derived copies
                rec["event_xg"] = rec["xg"]
                rec["event_ppda"] = rec["ppda"]
                rec["event_possession"] = rec["possession"]
                rec["event_shots"] = rec["shots"]
                rec["event_corners"] = rec["corners"]
                rec["xg_source"] = "Estimated"
                rec["ppda_source"] = "Estimated"
                rec["possession_source"] = "Pass Share"
                if not trow.empty:
                    w = trow.iloc[0]
                    if pd.notna(w.get("wyscout_xg")):
                        rec["xg"] = float(w["wyscout_xg"]); rec["xg_source"] = "Wyscout"
                    if pd.notna(w.get("wyscout_ppda")):
                        rec["ppda"] = float(w["wyscout_ppda"]); rec["ppda_source"] = "Wyscout"
                    if pd.notna(w.get("wyscout_possession_pct")):
                        rec["possession"] = float(w["wyscout_possession_pct"]); rec["possession_source"] = "Wyscout"
                    if pd.notna(w.get("wyscout_shots")):
                        rec["shots_wyscout"] = int(w["wyscout_shots"])
                    if pd.notna(w.get("wyscout_corners")):
                        rec["corners_wyscout"] = int(w["wyscout_corners"])
                    if pd.notna(w.get("wyscout_passes")):
                        rec["passes_wyscout"] = int(w["wyscout_passes"])
                    if pd.notna(w.get("wyscout_shots_on_target")):
                        rec["sot_wyscout"] = int(w["wyscout_shots_on_target"])
                # xGA = opponent Wyscout xG
                if not orow.empty and pd.notna(orow.iloc[0].get("wyscout_xg")):
                    rec["xga"] = float(orow.iloc[0]["wyscout_xg"]); rec["xga_source"] = "Wyscout"
                else:
                    rec["xga"] = report[opp_side].get("event_xg", report[opp_side]["xg"]); rec["xga_source"] = "Estimated"
    except Exception as _e:
        print(f"[REPORT_QA] Wyscout overlay skipped: {_e}")

    # ── Game Story Classification ──
    h = report["home"]
    a = report["away"]
    total_shots = h["shots"] + a["shots"]
    total_xg = h["xg"] + a["xg"]
    xg_diff = abs(h["xg"] - a["xg"])
    poss_diff = abs(h["possession"] - a["possession"])
    fb_total = h["fast_break_shots"] + a["fast_break_shots"]
    sp_total = h["sp_goals"] + a["sp_goals"]

    if xg_diff > 1.5 and poss_diff > 10:
        game_story = "Controlled Dominance"
    elif fb_total > 4:
        game_story = "Transition Battle"
    elif total_shots > 30 and total_xg > 3:
        game_story = "Open & Chaotic"
    elif total_shots < 16:
        game_story = "Cagey / Low-Block Struggle"
    elif sp_total >= 2:
        game_story = "Set-Piece Decided"
    elif poss_diff > 15 and xg_diff < 0.5:
        game_story = "Sterile Dominance"
    elif fb_total > 2:
        game_story = "Transition-Heavy"
    else:
        game_story = "Competitive / Balanced"

    report["game_story"] = game_story

    return report


# ══════════════════════════════════════════════════════════════════════════
#  PLAYER ROLE PROFILES (for a specific team in recent matches)
# ══════════════════════════════════════════════════════════════════════════
def compute_player_roles(league_folder: str, team_name: str, last_n: int = 5) -> list:
    """
    Role-based player profiles: touches by zone, progressive actions,
    chance creation, ball losses, duel profile, defensive contribution.
    """
    df = load_league_data(league_folder)
    ml = get_match_list(league_folder)
    tm = ml[(ml["home_team"] == team_name) | (ml["away_team"] == team_name)]
    tm = tm.sort_values("week", ascending=False).head(last_n)
    mids = tm["match_id"].tolist()
    n = len(mids)

    tdf = df[(df["match_id"].isin(mids)) & (df["team_name"] == team_name) & (df["player_name"].notna())]

    players = []
    for (pid, pname), pdf in tdf.groupby(["player_id", "player_name"], observed=True):
        pos = pdf["position"].mode()
        position = pos.iloc[0] if len(pos) > 0 else "?"
        jersey = pdf["Jersey Number"].dropna()
        jnum = int(jersey.iloc[0]) if len(jersey) > 0 else 0

        passes = pdf[pdf["event"] == "Pass"]
        passes_end = passes.dropna(subset=["Pass End X", "Pass End Y"])
        shots = pdf[pdf["event"].isin(SHOT_EVENTS)]
        prog = passes_end[(passes_end["Pass End X"] - passes_end["x"]) > 10] if len(passes_end) > 0 else pd.DataFrame()

        # Touch zones
        touches = pdf[pdf["x"].notna()]
        def_third = len(touches[touches["x"] < MID_THIRD_X])
        mid_third = len(touches[(touches["x"] >= MID_THIRD_X) & (touches["x"] < FINAL_THIRD_X)])
        att_third = len(touches[touches["x"] >= FINAL_THIRD_X])

        # xG/xA
        player_xg = 0
        for _, s in shots.iterrows():
            player_xg += _xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))

        # Key passes
        key_p = len(passes[passes.get("Leading to attempt", pd.Series()).notna()]) if "Leading to attempt" in passes.columns else 0

        # Ball losses
        dispossessed = len(pdf[pdf["event"] == "Dispossessed"])
        bad_passes = len(passes[passes["outcome"] == 0])

        players.append({
            "player_id": pid, "name": pname, "position": position, "jersey": jnum,
            "matches": pdf["match_id"].nunique(),
            "touches": len(touches),
            "touch_def": def_third, "touch_mid": mid_third, "touch_att": att_third,
            "passes": len(passes),
            "pass_acc": _safe_pct((passes["outcome"]==1).sum(), len(passes)),
            "prog_passes": len(prog),
            "prog_carries": len(pdf[(pdf["event"]=="Take On") & (pdf["outcome"]==1)]),
            "key_passes": key_p,
            "shots": len(shots),
            "goals": len(pdf[pdf["event"]=="Goal"]),
            "xg": round(player_xg, 2),
            "assists": len(pdf[pdf["Assist"] == 16]) if "Assist" in pdf.columns else 0,
            "crosses": len(passes[_flagmask(passes["Cross"])]) if "Cross" in passes.columns else 0,
            "through_balls": len(passes[_flagmask(passes["Through ball"])]) if "Through ball" in passes.columns else 0,
            "tackles": len(pdf[pdf["event"]=="Tackle"]),
            "tackles_won": len(pdf[(pdf["event"]=="Tackle") & (pdf["outcome"]==1)]),
            "interceptions": len(pdf[pdf["event"]=="Interception"]),
            "recoveries": len(pdf[pdf["event"]=="Ball recovery"]),
            "aerials_won": len(pdf[(pdf["event"]=="Aerial") & (pdf["outcome"]==1)]),
            "aerials_total": len(pdf[pdf["event"]=="Aerial"]),
            "saves": len(pdf[pdf["event"].isin(["Save", "Keeper Save"])]),
            "claims": len(pdf[pdf["event"].isin(["Claim", "Punch", "Keeper pick-up", "Smother"])]),
            "sweeper_actions": len(pdf[pdf["event"] == "Keeper Sweeper"]),
            "take_ons": len(pdf[pdf["event"]=="Take On"]),
            "take_ons_won": len(pdf[(pdf["event"]=="Take On") & (pdf["outcome"]==1)]),
            "dispossessed": dispossessed,
            "bad_passes": bad_passes,
            "ball_losses": dispossessed + bad_passes,
            "fouls": len(pdf[(pdf["event"]=="Foul") & (pdf["outcome"]==0)]),
        })

    # ── Role tag + position-specific influence score for each player ──
    for p in players:
        p["role"] = _infer_player_role(p)
        _inf = _player_influence_detail(p)
        p["influence"] = _inf["score"]
        p["influence_template"] = _inf["template"]
        p["influence_confidence"] = _inf["confidence"]
        p["influence_components"] = _inf["components"]
        p["influence_missing"] = _inf["missing"]
        tt = max(p["touches"], 1)
        p["touch_def_pct"] = round(p["touch_def"] / tt * 100)
        p["touch_mid_pct"] = round(p["touch_mid"] / tt * 100)
        p["touch_att_pct"] = round(p["touch_att"] / tt * 100)

    # Sort by influence (most influential first)
    players.sort(key=lambda p: p["influence"], reverse=True)
    return players


def _infer_player_role(p):
    """Tag a player's primary role from their event profile."""
    pos = str(p.get("position", "")).upper()
    if pos in ("GK",):
        return "Goalkeeper"
    if p["goals"] >= 3 or (p["shots"] >= 8 and p["touch_att"] > p["touch_def"]):
        return "Finisher"
    if p["key_passes"] >= 6 or p["assists"] >= 2:
        return "Creator"
    if p["take_ons_won"] >= 6 and p["touch_att"] >= p["touch_mid"]:
        return "Wide Outlet"
    if p["prog_passes"] >= 25 or p["prog_carries"] >= 10:
        return "Progressor"
    if p["tackles"] + p["interceptions"] + p["recoveries"] >= 20:
        return "Ball-Winner"
    return "Link Player"


def _influence_group(pos):
    """Map a raw position token to an influence template group."""
    p = str(pos or "").upper().strip()
    if p in ("GK",):
        return "GK"
    if p in ("CB", "RCB", "LCB", "SW"):
        return "CB"
    if p in ("RB", "LB", "RWB", "LWB", "WB"):
        return "FB"
    if p in ("DM", "CDM", "DMF"):
        return "DM"
    if p in ("CM", "RCM", "LCM", "MC"):
        return "CM"
    if p in ("AM", "CAM", "AMF", "SS"):
        return "AM"
    if p in ("RW", "LW", "RM", "LM", "RAM", "LAM", "W"):
        return "WING"
    if p in ("ST", "CF", "FW", "RF", "LF"):
        return "ST"
    return "CM"  # safe default for unknown midfield-ish tokens


# Per-template metric weights + an "elite per-match" reference for each metric, so
# every player is scored ONLY on the KPIs that matter for their role. A GK is
# never judged on goals/shots; a striker is never judged on tackles. Each metric
# value is taken per-match, divided by its reference (capped at 1.0 = elite),
# then weighted-averaged to 0-100. Metrics absent from the event stream (e.g. GK
# saves) are simply omitted and flagged as reducing confidence.
_INFLUENCE_TEMPLATES = {
    # metric: (weight, elite_per_match_reference)
    "GK":   {"saves": (0.30, 4), "claims": (0.18, 3), "sweeper_actions": (0.12, 2),
             "pass_acc_unit": (0.20, 1.0), "passes": (0.12, 35), "recoveries": (0.08, 4)},
    "CB":   {"aerials_won": (0.20, 3), "interceptions": (0.18, 3), "tackles_won": (0.15, 2),
             "recoveries": (0.17, 7), "prog_passes": (0.15, 6), "pass_acc_unit": (0.15, 1.0)},
    "FB":   {"prog_carries": (0.18, 3), "crosses": (0.16, 3), "key_passes": (0.16, 1.5),
             "recoveries": (0.16, 6), "tackles_won": (0.14, 2), "interceptions": (0.12, 2), "touch_att": (0.08, 20)},
    "DM":   {"recoveries": (0.22, 8), "interceptions": (0.20, 3), "prog_passes": (0.20, 8),
             "tackles_won": (0.16, 2), "pass_acc_unit": (0.14, 1.0), "touches": (0.08, 70)},
    "CM":   {"prog_passes": (0.22, 8), "prog_carries": (0.16, 3), "key_passes": (0.18, 2),
             "recoveries": (0.16, 6), "pass_acc_unit": (0.12, 1.0), "touch_att": (0.16, 22)},
    "AM":   {"xg": (0.20, 0.4), "key_passes": (0.22, 2.5), "through_balls": (0.12, 1),
             "shots": (0.14, 2.5), "prog_carries": (0.16, 3), "assists": (0.16, 0.4)},
    "WING": {"take_ons_won": (0.22, 3), "crosses": (0.16, 3), "key_passes": (0.18, 2),
             "shots": (0.14, 2), "touch_att": (0.14, 25), "prog_carries": (0.16, 3)},
    "ST":   {"xg": (0.28, 0.6), "shots": (0.20, 3), "goals": (0.20, 0.6),
             "touch_att": (0.12, 22), "aerials_won": (0.10, 2), "key_passes": (0.10, 1.2)},
}


def _player_influence_score(p):
    """Position-aware influence score (0-100). Each role is judged ONLY on the
    KPIs relevant to it (see _INFLUENCE_TEMPLATES), so GK/CB/DM/CM/AM/Winger/ST
    are not compared on the same formula. Returns an int for backward
    compatibility; richer detail is attached via _player_influence_detail()."""
    return _player_influence_detail(p)["score"]


def _player_influence_detail(p):
    """Full influence breakdown: score, template, confidence, per-metric inputs."""
    grp = _influence_group(p.get("position"))
    tmpl = _INFLUENCE_TEMPLATES[grp]
    n = max(p.get("matches", 1), 1)
    used, missing = [], []
    num = den = 0.0
    for metric, (w, ref) in tmpl.items():
        if metric == "pass_acc_unit":
            val = p.get("pass_acc")
            if val is None:
                missing.append("pass_acc"); continue
            per_match = float(val) / 100.0  # already a percentage
        else:
            if metric not in p or p.get(metric) is None:
                missing.append(metric); continue
            per_match = float(p[metric]) / n
        norm = min(per_match / ref, 1.0) if ref else 0.0
        num += w * norm
        den += w
        used.append({"metric": metric.replace("_unit", ""), "weight": w,
                     "per_match": round(per_match, 2), "ref": ref, "norm_pct": round(norm * 100)})
    score = round(num / den * 100) if den > 0 else 0
    # Confidence: how much of the template's weight had data + sample size.
    coverage = den / sum(w for w, _ in tmpl.values()) if tmpl else 0
    if coverage >= 0.85 and n >= 3:
        conf = "High"
    elif coverage >= 0.6 and n >= 2:
        conf = "Medium"
    else:
        conf = "Low"
    return {"score": score, "template": grp, "confidence": conf,
            "components": used, "missing": missing, "coverage_pct": round(coverage * 100)}


# ══════════════════════════════════════════════════════════════════════════
#  PLAN vs REALITY (auto-generate tactical targets from team profile)
# ══════════════════════════════════════════════════════════════════════════
def infer_game_model(our_profile: dict, opp_profile: dict, venue=None) -> dict:
    """Infer the intended tactical game model from pre-match profiles.
    Returns {model, rationale, weights} used to generate realistic targets."""
    our_ppda = our_profile.get("ppda", 13)
    our_poss = our_profile.get("possession_pct", 50)
    opp_poss = opp_profile.get("possession_pct", 50)
    our_ft = our_profile.get("fast_break_shots_pm", 0)
    opp_press_weak = opp_profile.get("ppda", 13) > 13  # opponent presses passively

    # Heuristic classification
    if our_ppda <= 9.5 and our_poss >= 52:
        model = "High Press / Control"
        rationale = "Aggressive pressing and ball dominance profile."
    elif our_poss >= 55:
        model = "Possession Control"
        rationale = "Team normally controls the ball and dictates tempo."
    elif our_ft >= 1.0 and our_poss < 50:
        model = "Mid-Block + Fast Attack"
        rationale = "Compact out of possession, dangerous in transition."
    elif our_poss < 45:
        model = "Low Block + Transition"
        rationale = "Cedes possession, threatens on the counter."
    else:
        model = "Balanced"
        rationale = "No single dominant tactical identity."
    return {"model": model, "rationale": rationale}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def generate_plan_targets(our_profile: dict, opp_profile: dict, venue=None) -> list:
    """DEPRECATED — superseded by components.target_engine.generate_targets().
    Retained only for backward compatibility; no longer used by the report UI."""
    """Generate realistic, context-aware tactical targets based on the inferred
    game model, team/opponent profiles, and league-sane caps. Each target carries
    a weight (Critical/Important/Supporting/Context) and an applicability flag."""
    if not our_profile:
        return []
    gm = infer_game_model(our_profile, opp_profile, venue)
    model = gm["model"]
    targets = [{"metric": "_game_model", "model": model, "rationale": gm["rationale"]}]

    our_ppda = our_profile.get("ppda", 13.0)
    league_ppda = 13.8
    our_xg = our_profile.get("xg_per_match", 1.4)
    our_box = our_profile.get("box_entries_pm", 10)

    # ── PPDA — weight & target depend on game model ──
    if model in ("High Press / Control",):
        tp = round(min(our_ppda * 0.9, league_ppda * 0.85), 1)
        targets.append({"metric": "PPDA", "target": f"< {tp}", "weight": "Critical",
                        "rationale": "High-press identity: sustain aggressive pressing",
                        "score_state_sensitive": True})
    elif model in ("Mid-Block + Fast Attack", "Low Block + Transition"):
        hi = round(our_ppda * 1.25, 1)
        targets.append({"metric": "PPDA", "target": f"< {hi}", "weight": "Context",
                        "rationale": "Transition model: pressing is situational, not the core objective",
                        "score_state_sensitive": True})
    else:
        targets.append({"metric": "PPDA", "target": f"< {round(our_ppda * 1.1, 1)}", "weight": "Supporting",
                        "rationale": "Maintain balanced pressing intensity",
                        "score_state_sensitive": True})

    # ── Estimated xG — realistic target from team's own level + opponent leak.
    # No fixed constant (the old `2.5 * 1.10` forced ~2.8 for most teams).
    opp_xga = opp_profile.get("xga_per_match", opp_profile.get("xg_against_pm", 1.4)) if opp_profile else 1.4
    blended = (our_xg + opp_xga) / 2.0
    tx = _clamp(max(1.1, blended * 0.9), 1.0, 2.4)
    targets.append({"metric": "Estimated xG", "target": f"> {tx:.1f}", "weight": "Important",
                    "rationale": "Create above-par chance quality (scaled to opponent, realistic cap)"})

    # ── Box entries — important in attack-focused models ──
    box_t = round(_clamp(max(8, our_box * 0.9), 6, 18))
    targets.append({"metric": "Box Entries", "target": f"> {box_t}", "weight": "Important",
                    "rationale": "Penetrate the box through open play"})

    # ── Big chances ──
    targets.append({"metric": "Big Chances", "target": "> 2", "weight": "Important",
                    "rationale": "Generate clear high-quality chances"})

    # ── Transition defence ──
    if opp_profile.get("fast_break_shots_pm", 0) > 1:
        targets.append({"metric": "Transition xG Against", "target": "< 0.30", "weight": "Critical",
                        "rationale": "Opponent dangerous in transition — protect against counters"})
    else:
        targets.append({"metric": "Transition xG Against", "target": "< 0.50", "weight": "Supporting",
                        "rationale": "Standard transition control"})

    # ── Pass Share — only a real target when the model demands ball control ──
    if model in ("Possession Control", "High Press / Control"):
        ps = round(our_profile.get("possession_pct", 52))
        targets.append({"metric": "Pass Share", "target": f"> {max(ps, 52)}%", "weight": "Supporting",
                        "rationale": "Control model: dominate the ball"})
    else:
        targets.append({"metric": "Pass Share", "target": "n/a", "weight": "Context",
                        "rationale": "Not a core objective for this transition/direct game model",
                        "not_applicable": True})

    # ── Set-piece defence ──
    if opp_profile.get("sp_shots_pm", 0) > 2:
        targets.append({"metric": "Set-Piece Shots Conceded", "target": "< 3", "weight": "Supporting",
                        "rationale": "Opponent strong from set pieces"})
    return targets


_WEIGHTS = {"Critical": 2.0, "Important": 1.5, "Supporting": 1.0, "Context": 0.5}
_STATUS_SCORE = {"Hit": 1.0, "Strategically Acceptable": 0.75, "Partial": 0.5,
                 "Missed": 0.0, "Not Applicable": None}


def evaluate_plan(targets: list, actual_report: dict, side: str) -> list:
    """Compare targets vs actuals with outcome-aware, score-state-sensitive logic.
    Produces rich statuses (Hit / Partial / Missed / Strategically Acceptable /
    Not Applicable) rather than a blunt green/red."""
    data = actual_report.get(side, {})
    opp = actual_report.get("away" if side == "home" else "home", {})
    meta = actual_report.get("meta", {})
    gf = data.get("goals", 0)
    ga = opp.get("goals", 0)
    won = gf > ga
    won_comfortably = (gf - ga) >= 2
    xga = data.get("xga", opp.get("xg", 0))
    big_chances_against = opp.get("big_chances", 0)

    results = []
    for t in targets:
        metric = t.get("metric", "")
        if metric == "_game_model":
            results.append(t)
            continue
        target_str = str(t.get("target", ""))
        weight = t.get("weight", "Supporting")

        # Resolve actual
        actual = None
        amap = {
            "PPDA": "ppda", "Box Entries": "box_entries", "Estimated xG": "xg",
            "Big Chances": "big_chances", "Transition xG Against": "transition_xg_against",
            "Pass Share": "possession", "Set-Piece Shots Conceded": "opp_sp_shots",
        }
        if metric in amap:
            actual = data.get(amap[metric], opp.get("sp_shots", 0) if metric == "Set-Piece Shots Conceded" else 0)

        # Not-applicable targets
        if t.get("not_applicable") or target_str == "n/a":
            results.append({**t, "actual": actual if actual is not None else "—",
                            "status": "Not Applicable",
                            "interpretation": "Not a core objective for this game model."})
            continue

        status = "Partial"
        interp = ""
        try:
            if "<" in target_str:
                thr = float(target_str.replace("<", "").replace("%", "").strip())
                if actual < thr:
                    status = "Hit"
                elif actual < thr * 1.2:
                    status = "Partial"
                else:
                    status = "Missed"
            elif ">" in target_str:
                thr = float(target_str.replace(">", "").replace("%", "").strip())
                if actual > thr:
                    status = "Hit"
                elif actual > thr * 0.8:
                    status = "Partial"
                else:
                    status = "Missed"
        except (ValueError, TypeError):
            status = "Partial"

        # ── Outcome-aware reclassification ──
        # PPDA after a comfortable lead: high full-match PPDA is acceptable if the
        # box was protected and the team won.
        if metric == "PPDA" and t.get("score_state_sensitive") and status == "Missed":
            if won and xga < 1.2 and big_chances_against <= 2:
                status = "Strategically Acceptable"
                interp = ("Pressing intensity dropped after control of the scoreline, "
                          "but the opponent created little — acceptable game-state management.")
        # xG missed but team won and scored well: partial credit
        if metric == "Estimated xG" and status == "Missed" and won_comfortably:
            status = "Partial"
            interp = "Chance volume below target, but finishing and result were strong."
        if not interp:
            interp = t.get("rationale", "")

        results.append({**t, "actual": round(actual, 2) if isinstance(actual, (int, float)) else actual,
                        "status": status, "interpretation": interp})
    return results


def compute_plan_adherence(plan_eval: list) -> dict:
    """Weighted, context-aware adherence score with a tactical outcome label."""
    num = den = 0.0
    counts = {"Hit": 0, "Partial": 0, "Missed": 0, "Strategically Acceptable": 0, "Not Applicable": 0}
    for t in plan_eval:
        if t.get("metric") == "_game_model":
            continue
        st = t.get("status", "Partial")
        counts[st] = counts.get(st, 0) + 1
        sc = _STATUS_SCORE.get(st)
        if sc is None:  # Not Applicable — excluded from denominator
            continue
        w = _WEIGHTS.get(t.get("weight", "Supporting"), 1.0)
        num += w * sc
        den += w
    score = round(num / den * 100) if den > 0 else 0

    if score >= 80:
        label = "Plan Executed"
    elif score >= 65:
        label = "Mostly Executed"
    elif score >= 45:
        label = "Mixed Execution"
    else:
        label = "Plan Not Followed"
    return {"score": score, "label": label, "counts": counts,
            "valid_denominator": den}
