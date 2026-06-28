"""
components/insights.py — Tactical Insight Generator
Generates short, data-driven insight text for charts, maps, KPIs.
All comparisons are season-specific and direction-aware.

Uses central definitions (components/definitions.py) for flag detection,
shot events, and metric direction so behaviour is identical everywhere.
"""

import pandas as pd
import numpy as np
from data_loader import load_league_data, get_match_list, get_team_results, _safe_col
from components.report_engine import (
    _xg_from_distance, _safe_pct, _safe_div,
)
from components.definitions import (
    is_flag, flag_mask, flag_count, safe_col,
    SHOT_EVENTS, FINAL_THIRD_X, BOX_X, BOX_Y_LO, BOX_Y_HI,
    metric_higher_better, big_chances_of, big_chance_availability,
)
from components.kpi_context import get_kpi_context, _compute_league_metrics


def count_flag(series):
    """Backwards-compatible alias -> central flag_count."""
    return flag_count(series)


# ══════════════════════════════════════════════════════════════════════════
#  UNIFIED COMPARISON — match vs club-season vs last-5 vs league
# ══════════════════════════════════════════════════════════════════════════
def build_comparison(league_folder, team, metric_key, match_value=None):
    """
    Return a full comparison context dict for one metric:
      match value, club season avg, club last-5 avg, league avg,
      rank, percentile, status, direction, and a one-line interpretation.
    Any piece that can't be computed is returned as None (never a false 0).
    """
    ctx = get_kpi_context(league_folder, team, metric_key) or {}
    higher = metric_higher_better(metric_key)

    out = {
        "metric": metric_key,
        "match_value": match_value,
        "club_season_avg": ctx.get("value"),       # season profile value
        "league_avg": ctx.get("league_avg"),
        "rank": ctx.get("rank"), "total": ctx.get("total"),
        "percentile": ctx.get("percentile"),
        "status": ctx.get("status"),
        "status_color": ctx.get("status_color"),
        "higher_better": higher,
    }

    # Interpretation text
    parts = []
    cs = out["club_season_avg"]; la = out["league_avg"]
    if match_value is not None and cs is not None:
        better = (match_value > cs) if higher else (match_value < cs)
        parts.append(f"{'above' if better else 'below'} club norm ({cs})")
    if la is not None and (match_value is not None or cs is not None):
        ref = match_value if match_value is not None else cs
        better = (ref > la) if higher else (ref < la)
        parts.append(f"{'above' if better else 'below'} league avg ({la})")
    if out["status"]:
        parts.append(out["status"])
    out["interpretation"] = " · ".join(parts) if parts else "data limited"
    return out


# ══════════════════════════════════════════════════════════════════════════
#  TACTICAL INSIGHT TEXT GENERATORS
# ══════════════════════════════════════════════════════════════════════════
def insight_kpi(team: str, metric_key: str, league_folder: str, label: str = "") -> str:
    """Generate insight text for a single KPI vs league context."""
    ctx = get_kpi_context(league_folder, team, metric_key)
    if not ctx:
        return f"{label or metric_key}: data unavailable"

    val = ctx["value"]; avg = ctx["league_avg"]
    status = ctx["status"]; pct = ctx["percentile"]
    rank = ctx["rank"]; total = ctx["total"]
    higher = ctx.get("higher_better", True)

    direction = "above" if (higher and val > avg) or (not higher and val < avg) else "below"
    return f"{label or metric_key}: {val} ({direction} league avg {avg}) · #{rank}/{total} · {pct}th pct · {status}"


def insight_shot_profile(match_data: pd.DataFrame, team_name: str) -> str:
    """Tactical insight on shot location pattern."""
    shots = match_data[match_data["event"].isin(SHOT_EVENTS)]
    if team_name:
        shots = shots[shots["team_name"] == team_name]
    if shots.empty:
        return "No shots recorded."

    box_shots = shots[(shots["x"] >= BOX_X) & (shots["y"] >= BOX_Y_LO) & (shots["y"] <= BOX_Y_HI)]
    long_shots = shots[shots["x"] < BOX_X]
    central = shots[(shots["y"] >= 30) & (shots["y"] <= 70)]

    box_pct = round(len(box_shots) / max(len(shots), 1) * 100)
    central_pct = round(len(central) / max(len(shots), 1) * 100)
    big_chances = count_flag(shots["Big Chance"]) if "Big Chance" in shots.columns else 0
    goals = len(shots[shots["event"] == "Goal"])

    parts = [f"{len(shots)} shots ({goals}G)"]
    if box_pct >= 65:
        parts.append(f"high-quality profile — {box_pct}% from inside box")
    elif box_pct >= 40:
        parts.append(f"{box_pct}% from inside box")
    else:
        parts.append(f"low box penetration ({box_pct}%)")

    if big_chances >= 3:
        parts.append(f"{big_chances} big chances created — clinical attacking output")
    elif big_chances > 0:
        parts.append(f"{big_chances} big chance(s)")

    if central_pct >= 60:
        parts.append("central shooting bias")
    elif central_pct <= 30:
        parts.append("wide shooting profile")

    return " · ".join(parts) + "."


def insight_defensive_zone(match_data: pd.DataFrame, team_name: str) -> str:
    """Tactical insight on defensive action distribution."""
    def_evts = match_data[(match_data["event"].isin(["Tackle", "Interception", "Ball recovery"])) &
                          (match_data["team_name"] == team_name)]
    def_evts = def_evts.dropna(subset=["x"])
    if def_evts.empty:
        return "No defensive actions recorded."

    avg_x = def_evts["x"].mean()
    own_half = len(def_evts[def_evts["x"] < 50])
    opp_half = len(def_evts[def_evts["x"] >= 50])
    total = len(def_evts)

    if avg_x >= 45:
        block = "high block — aggressive pressing identity"
    elif avg_x >= 38:
        block = "mid block — balanced defensive line"
    else:
        block = "deep block — low defensive line"

    return f"{total} defensive actions · avg x={avg_x:.0f} · {block} · {round(opp_half/max(total,1)*100)}% in opposition half."


def insight_pass_network(match_data: pd.DataFrame, team_name: str) -> str:
    """Tactical insight on passing patterns."""
    passes = match_data[(match_data["event"] == "Pass") & (match_data["team_name"] == team_name)]
    if passes.empty:
        return "No passes recorded."

    succ = (passes["outcome"] == 1).sum()
    acc = round(succ / max(len(passes), 1) * 100)
    long_balls = count_flag(passes["Long ball"]) if "Long ball" in passes.columns else 0
    long_pct = round(long_balls / max(len(passes), 1) * 100)

    passes_end = passes.dropna(subset=["Pass End X"])
    if len(passes_end) > 0:
        prog = passes_end[(passes_end["Pass End X"] - passes_end["x"]) > 10]
        prog_count = len(prog)
    else:
        prog_count = 0

    style = "direct" if long_pct >= 18 else ("possession-based" if acc >= 82 else "balanced")
    return f"{len(passes)} passes · {acc}% accuracy · {prog_count} progressive · {long_pct}% long balls — {style} approach."


def insight_zone_occupancy(match_data: pd.DataFrame, team_name: str) -> str:
    """Tactical insight on territory."""
    df = match_data[match_data["team_name"] == team_name].dropna(subset=["x"])
    if df.empty:
        return "No territorial data."

    def_third = len(df[df["x"] < 33.3])
    mid_third = len(df[(df["x"] >= 33.3) & (df["x"] < 66.6)])
    att_third = len(df[df["x"] >= 66.6])
    total = max(def_third + mid_third + att_third, 1)

    att_pct = round(att_third / total * 100)
    mid_pct = round(mid_third / total * 100)

    if att_pct >= 35:
        identity = "high territorial dominance"
    elif att_pct >= 25:
        identity = "balanced territory"
    else:
        identity = "defensive posture — limited final-third presence"

    return f"Def: {round(def_third/total*100)}% · Mid: {mid_pct}% · Att: {att_pct}% — {identity}."


def insight_reception_zones(match_data: pd.DataFrame, team_name: str) -> str:
    """Tactical insight on where team receives the ball."""
    passes = match_data[(match_data["event"] == "Pass") & (match_data["outcome"] == 1) &
                        (match_data["team_name"] == team_name)]
    passes = passes.dropna(subset=["Pass End X", "Pass End Y"])
    if passes.empty:
        return "No reception data."

    total = len(passes)
    att_3rd = len(passes[passes["Pass End X"] >= 66.6])
    box = len(passes[(passes["Pass End X"] >= BOX_X) & (passes["Pass End Y"] >= BOX_Y_LO) & (passes["Pass End Y"] <= BOX_Y_HI)])
    central = len(passes[(passes["Pass End Y"] >= 33.3) & (passes["Pass End Y"] <= 66.6)])
    wide = total - central

    att_pct = round(att_3rd / max(total, 1) * 100)
    wide_pct = round(wide / max(total, 1) * 100)

    if att_pct >= 35:
        verdict = "high attacking reception volume — final-third penetration is a strength"
    elif att_pct >= 20:
        verdict = "moderate attacking reception"
    else:
        verdict = "low final-third receptions — buildup struggles to reach forwards"

    return f"{total} receptions · Att 3rd: {att_pct}% · Wide: {wide_pct}% · Box: {box} — {verdict}."


def insight_post_match_vs_season(team: str, league_folder: str, match_xg: float,
                                 match_shots: int, match_ppda: float, match_box: int) -> str:
    """Compare match performance to season norms — for post-match reports."""
    ctx_xg = get_kpi_context(league_folder, team, "xg_per_match")
    ctx_ppda = get_kpi_context(league_folder, team, "ppda")
    ctx_box = get_kpi_context(league_folder, team, "box_entries_pm")

    parts = []
    if ctx_xg:
        diff = match_xg - ctx_xg["league_avg"]
        if abs(diff) >= 0.5:
            parts.append(f"xG {match_xg:.1f} {'above' if diff > 0 else 'below'} league avg ({ctx_xg['league_avg']:.1f})")
    if ctx_ppda and match_ppda > 0:
        diff = match_ppda - ctx_ppda["league_avg"]
        if abs(diff) >= 2:
            parts.append(f"PPDA {match_ppda:.1f} — {'more passive' if diff > 0 else 'more aggressive pressing'} than league norm")
    if ctx_box:
        diff = match_box - ctx_box["league_avg"]
        if abs(diff) >= 5:
            parts.append(f"{match_box} box entries — {'above' if diff > 0 else 'below'} league norm ({ctx_box['league_avg']:.0f})")

    return " · ".join(parts) if parts else f"In line with league averages."


# ── Dash component ─────────────────────────────────────────────────────
def insight_card_html(text: str, icon: str = "💡"):
    """Render insight text as a styled Dash card."""
    from dash import html
    if not text:
        return None
    return html.Div(style={
        "padding": "10px 14px", "background": "rgba(255,215,0,0.06)",
        "borderLeft": "3px solid rgba(255,215,0,0.6)", "borderRadius": "6px",
        "marginTop": "8px", "marginBottom": "8px", "fontSize": "11px",
        "color": "#C8D0DA", "lineHeight": "1.55",
    }, children=[
        html.Span(icon, style={"marginRight": "8px", "fontSize": "13px"}),
        html.Span(text),
    ])
