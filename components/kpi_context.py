"""
components/kpi_context.py — League-Context KPI Evaluation System
Provides: league avg, rank, percentile, status label for any team metric.
Direction-aware: handles both higher-is-better and lower-is-better metrics.
Season-specific: recomputes when league data changes.
"""

import pandas as pd
import numpy as np
from data_loader import (
    load_league_data, get_match_list, get_teams, short,
    _CACHE,
)
from components.report_engine import compute_team_profile, _xg_from_distance, _FLAGVAL
# Direction is owned by the central registry in definitions.py — never redefine it.
from components.definitions import metric_higher_better

# The set of team metrics we track for league context. Direction is NOT stored
# here; it is resolved through definitions.metric_higher_better() so there is a
# single source of truth for higher/lower-is-better everywhere.
TRACKED_METRICS = [
    "xg_per_match", "goals_pm", "shots_pm", "shots_on_target_pm", "big_chances_pm",
    "box_entries_pm", "ft_entries_pm", "prog_passes_pm", "crosses_pm",
    "through_balls_pm", "cutbacks_pm", "possession_pct", "pass_accuracy",
    "field_tilt", "switches_pm", "ppda", "def_action_height",
    "high_regains_pm", "tackles_pm", "interceptions_pm", "recoveries_pm",
    "fast_break_shots_pm", "fast_break_xg", "sp_shots_pm", "corners_pm",
]
# Backwards-compat alias: any code importing METRIC_DIRECTION still works, but
# values now come from the central registry.
METRIC_DIRECTION = {m: metric_higher_better(m) for m in TRACKED_METRICS}


def _compute_league_metrics(league_folder: str) -> pd.DataFrame:
    """Compute key metrics for all teams. Cached per league."""
    cache_key = f"league_metrics_{league_folder}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    teams = get_teams(league_folder)
    rows = []
    for t in teams:
        try:
            p = compute_team_profile(league_folder, t, last_n=50)
            if p:
                row = {"team": t}
                for k in TRACKED_METRICS:
                    row[k] = p.get(k, 0) or 0
                rows.append(row)
        except Exception:
            continue

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    _CACHE[cache_key] = df
    return df


def get_kpi_context(league_folder: str, team_name: str, metric_key: str) -> dict:
    """
    Get contextual evaluation for a team's metric value.
    Returns: {value, league_avg, rank, total_teams, percentile, status, status_color, direction}
    """
    lm = _compute_league_metrics(league_folder)
    if lm.empty or metric_key not in lm.columns:
        return {}

    team_row = lm[lm["team"] == team_name]
    if team_row.empty:
        return {}

    value = float(team_row[metric_key].iloc[0])
    col = lm[metric_key].dropna()
    higher_better = metric_higher_better(metric_key)

    avg = round(col.mean(), 2)
    n = len(col)

    # Rank (1 = best)
    if higher_better:
        rank = int((col >= value).sum())  # How many are >= this value
        rank = n - rank + 1  # Convert to rank
        rank = int(col.rank(ascending=False, method="min")[team_row.index[0]])
    else:
        rank = int(col.rank(ascending=True, method="min")[team_row.index[0]])

    # Percentile
    if higher_better:
        pct = round((col < value).sum() / max(n - 1, 1) * 100)
    else:
        pct = round((col > value).sum() / max(n - 1, 1) * 100)

    # Status
    if pct >= 90:
        status, color = "Elite", "#00E396"
    elif pct >= 75:
        status, color = "Strong", "#00E396"
    elif pct >= 40:
        status, color = "Average", "#FEB019"
    elif pct >= 20:
        status, color = "Weak", "#FF4560"
    else:
        status, color = "Poor", "#FF4560"

    return {
        "value": round(value, 2), "league_avg": avg,
        "rank": rank, "total": n, "percentile": pct,
        "status": status, "status_color": color,
        "higher_better": higher_better,
    }


def get_multi_kpi_context(league_folder: str, team_name: str, metric_keys: list) -> list:
    """Get context for multiple metrics at once."""
    return [{"key": k, **get_kpi_context(league_folder, team_name, k)} for k in metric_keys]


# ── Dash component builders ───────────────────────────────────────────
def kpi_with_context_html(label: str, ctx: dict):
    """Build a Dash html component showing KPI + context. Import dash at call time."""
    from dash import html

    if not ctx:
        return html.Div(className="kpi", children=[
            html.Div("—", className="kpi-v", style={"color": "#5A6575"}),
            html.Div(label, className="kpi-l"),
        ])

    val = ctx["value"]
    val_str = f"{val:.1f}" if isinstance(val, float) and val < 100 else f"{val:.0f}"
    sc = ctx["status_color"]
    arrow = "↑" if ctx.get("higher_better") and ctx["percentile"] >= 50 else ("↓" if not ctx.get("higher_better") and ctx["percentile"] >= 50 else "")

    return html.Div(className="kpi", style={"position": "relative"}, children=[
        html.Div(val_str, className="kpi-v", style={"color": sc, "fontSize": "20px"}),
        html.Div(label, className="kpi-l"),
        html.Div(f"{arrow} #{ctx['rank']}/{ctx['total']} · {ctx['percentile']}th · {ctx['status']}",
                 style={"fontSize": "8px", "color": sc, "marginTop": "2px", "letterSpacing": "0.3px"}),
        html.Div(f"Avg: {ctx['league_avg']}",
                 style={"fontSize": "8px", "color": "#5A6575", "marginTop": "1px"}),
    ])

# ═════════════════════════════════════════════════════════════════════════════
#  Post-match KPI context — match vs team season avg vs league avg
# ═════════════════════════════════════════════════════════════════════════════
POST_MATCH_KPI_REGISTRY = {
    "tackles_won": {"label": "Tackles Won", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "tackles": {"label": "Tackles Attempted", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "tackle_success_pct": {"label": "Tackle Success %", "direction": "higher_good", "source": "Event-derived", "group": "Defensive Output"},
    "interceptions": {"label": "Interceptions", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "recoveries": {"label": "Recoveries", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "clearances": {"label": "Clearances", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "blocks": {"label": "Blocks", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "duels_won": {"label": "Duels Won", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "aerials_won": {"label": "Aerial Duels Won", "direction": "contextual", "source": "Event-derived", "group": "Defensive Output"},
    "ppda": {"label": "PPDA", "direction": "lower_good", "source": "Wyscout/Event-derived", "group": "Pressing"},
    "xg": {"label": "xG", "direction": "higher_good", "source": "Wyscout/Estimated", "group": "Attacking Output"},
    "xga": {"label": "xGA", "direction": "lower_good", "source": "Wyscout/Estimated", "group": "Attacking Output"},
    "shots": {"label": "Shots", "direction": "higher_good", "source": "Wyscout/Event-derived", "group": "Attacking Output"},
    "shots_on_target": {"label": "Shots on Target", "direction": "higher_good", "source": "Wyscout/Event-derived", "group": "Attacking Output"},
    "big_chances": {"label": "Big Chances", "direction": "higher_good", "source": "Event-derived", "group": "Attacking Output"},
    "sp_shots": {"label": "Set-piece Shots", "direction": "higher_good", "source": "Event-derived", "group": "Set Pieces"},
    "ft_entries": {"label": "Final-third Entries", "direction": "higher_good", "source": "Event-derived", "group": "Possession/Build-up"},
    "box_entries": {"label": "Box Entries", "direction": "higher_good", "source": "Event-derived", "group": "Possession/Build-up"},
    "prog_passes": {"label": "Progressive Passes", "direction": "higher_good", "source": "Wyscout/Event-derived", "group": "Possession/Build-up"},
    "possession": {"label": "Possession / Pass Share", "direction": "higher_good", "source": "Wyscout/Pass Share", "group": "Possession/Build-up"},
    "field_tilt": {"label": "Field Tilt", "direction": "higher_good", "source": "Event-derived", "group": "Possession/Build-up"},
    "corners": {"label": "Corners", "direction": "higher_good", "source": "Wyscout/Event-derived", "group": "Set Pieces"},
    "fouls_committed": {"label": "Fouls Committed", "direction": "lower_good", "source": "Event-derived", "group": "Discipline"},
    "yellow_cards": {"label": "Yellow Cards", "direction": "lower_good", "source": "Event-derived", "group": "Discipline"},
    "red_cards": {"label": "Red Cards", "direction": "lower_good", "source": "Event-derived", "group": "Discipline"},
}


def _pm_flag(v):
    try:
        return bool(_FLAGVAL(v))
    except Exception:
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v == 1
        return str(v).strip().lower() in {"si", "sí", "yes", "true", "1", "y", "x", "✓"}


def _pm_flagmask(series):
    import pandas as _pd
    if series is None:
        return _pd.Series([], dtype=bool)
    return series.apply(_pm_flag)


def _pm_safe_pct(num, den):
    return round(float(num) / max(float(den), 1.0) * 100.0, 1)


def _pm_safe_div(num, den):
    return round(float(num) / max(float(den), 1.0), 2)


def _estimate_shot_xg_sum(shots):
    total = 0.0
    if shots is None or len(shots) == 0:
        return 0.0
    for _, s in shots.dropna(subset=["x", "y"]).iterrows():
        total += _xg_from_distance(s.get("x"), s.get("y"), _pm_flag(s.get("Head")), _pm_flag(s.get("Big Chance")))
    return round(float(total), 3)


def _first_col(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def _build_post_match_team_match_table(league_folder: str):
    """Return one row per team-match with the post-match KPIs used for
    match-vs-season context. Cached per league and built from the raw events plus
    Wyscout overlay where available. This avoids slow full report generation for
    every fixture.
    """
    from data_loader import _CACHE, normalize_team, load_league_data, get_match_list
    from components.definitions import SHOT_EVENTS, BOX_X, BOX_Y_LO, BOX_Y_HI, FINAL_THIRD_X
    import pandas as _pd
    import numpy as _np

    ck = f"post_match_team_match_context_table_{league_folder}"
    if ck in _CACHE:
        return _CACHE[ck]

    df = load_league_data(league_folder)
    ml = get_match_list(league_folder)
    if df.empty or ml.empty:
        return _pd.DataFrame()

    pass_end_x = _first_col(df, ["Pass End X", "pass_end_x", "end_x"])
    pass_end_y = _first_col(df, ["Pass End Y", "pass_end_y", "end_y"])
    by_mid = {str(mid): g for mid, g in df.groupby("match_id", observed=True)}
    rows = []

    for _, m in ml.iterrows():
        mid = str(m.get("match_id"))
        home = normalize_team(m.get("home_team"))
        away = normalize_team(m.get("away_team"))
        mdf = by_mid.get(mid)
        if mdf is None or mdf.empty:
            continue
        for team in (home, away):
            tdf = mdf[mdf["team_name"] == team]
            odf = mdf[mdf["team_name"] != team]
            if tdf.empty:
                continue
            passes = tdf[tdf["event"] == "Pass"]
            opp_passes = odf[odf["event"] == "Pass"]
            passes_end = passes.dropna(subset=[pass_end_x, pass_end_y]) if pass_end_x and pass_end_y else passes.iloc[0:0]
            shots = tdf[tdf["event"].isin(SHOT_EVENTS)]
            opp_shots = odf[odf["event"].isin(SHOT_EVENTS)]
            xg_est = _estimate_shot_xg_sum(shots)
            xga_est = _estimate_shot_xg_sum(opp_shots)
            opp_passes_own = len(opp_passes[opp_passes["x"] < 50]) if "x" in opp_passes.columns else 0
            our_def_opp = len(tdf[(tdf["event"].isin(["Tackle", "Interception", "Foul"])) & (tdf["x"] > 50)]) if "x" in tdf.columns else 0
            ppda = _pm_safe_div(opp_passes_own, our_def_opp)
            pass_share = _pm_safe_pct(len(passes), len(passes) + len(opp_passes))
            ft_touch = len(tdf[(tdf["x"].notna()) & (tdf["x"] > FINAL_THIRD_X)]) if "x" in tdf.columns else 0
            opp_ft_touch = len(odf[(odf["x"].notna()) & (odf["x"] > FINAL_THIRD_X)]) if "x" in odf.columns else 0
            field_tilt = _pm_safe_pct(ft_touch, ft_touch + opp_ft_touch)
            prog_passes = passes_end[(passes_end[pass_end_x] - passes_end["x"]) > 10] if not passes_end.empty else passes_end
            ft_entries = passes_end[(passes_end["outcome"] == 1) & (passes_end["x"] < FINAL_THIRD_X) & (passes_end[pass_end_x] >= FINAL_THIRD_X)] if not passes_end.empty else passes_end
            if not passes_end.empty:
                starts_in_box = ((passes_end["x"] >= BOX_X) & (passes_end["y"] >= BOX_Y_LO) & (passes_end["y"] <= BOX_Y_HI))
                ends_in_box = ((passes_end[pass_end_x] >= BOX_X) & (passes_end[pass_end_y] >= BOX_Y_LO) & (passes_end[pass_end_y] <= BOX_Y_HI))
                box_entries = passes_end[(passes_end["outcome"] == 1) & (~starts_in_box) & ends_in_box]
            else:
                box_entries = passes_end
            tackles = tdf[tdf["event"] == "Tackle"]
            aerials = tdf[tdf["event"] == "Aerial"]
            interceptions = tdf[tdf["event"] == "Interception"]
            recoveries = tdf[tdf["event"] == "Ball recovery"]
            clearances = tdf[tdf["event"] == "Clearance"]
            blocks = tdf[tdf["event"].astype(str).str.contains("Block", case=False, na=False)]
            tackles_won = int((tackles["outcome"] == 1).sum()) if "outcome" in tackles.columns else 0
            aerials_won = int((aerials["outcome"] == 1).sum()) if "outcome" in aerials.columns else 0
            big_chances = len(shots[_pm_flagmask(shots["Big Chance"])]) if "Big Chance" in shots.columns else 0
            sp_mask = (_pm_flagmask(shots["Set piece"]) if "Set piece" in shots.columns else _pd.Series(False, index=shots.index))
            cor_mask = (_pm_flagmask(shots["From corner"]) if "From corner" in shots.columns else _pd.Series(False, index=shots.index))
            sp_shots = int((sp_mask | cor_mask).sum()) if len(shots) else 0
            corners = int(_pm_flagmask(tdf["Corner taken"]).sum()) if "Corner taken" in tdf.columns else 0
            fouls_committed = int(len(tdf[(tdf["event"] == "Foul") & (tdf.get("outcome", 0) == 0)])) if "outcome" in tdf.columns else int(len(tdf[tdf["event"] == "Foul"]))
            yellow_cards = int(_pm_flagmask(tdf["Yellow Card"]).sum()) if "Yellow Card" in tdf.columns else 0
            red_cards = int(_pm_flagmask(tdf["Red Card"]).sum()) if "Red Card" in tdf.columns else 0
            shots_on_target = len(tdf[tdf["event"].isin(["Goal", "Saved Shot"])])
            row = {
                "match_id": mid, "team": team, "opponent": away if team == home else home,
                "date": str(m.get("local_date", ""))[:10], "week": m.get("week"),
                "xg": round(xg_est, 2), "xga": round(xga_est, 2), "ppda": ppda,
                "possession": pass_share, "field_tilt": field_tilt,
                "shots": int(len(shots)), "shots_on_target": int(shots_on_target),
                "big_chances": int(big_chances), "sp_shots": int(sp_shots),
                "ft_entries": int(len(ft_entries)), "box_entries": int(len(box_entries)),
                "prog_passes": int(len(prog_passes)), "corners": int(corners),
                "tackles": int(len(tackles)), "tackles_won": int(tackles_won),
                "tackle_success_pct": _pm_safe_pct(tackles_won, len(tackles)) if len(tackles) else _np.nan,
                "interceptions": int(len(interceptions)), "recoveries": int(len(recoveries)),
                "clearances": int(len(clearances)), "blocks": int(len(blocks)),
                "duels_won": int(tackles_won + aerials_won), "aerials_won": int(aerials_won),
                "fouls_committed": int(fouls_committed), "yellow_cards": int(yellow_cards), "red_cards": int(red_cards),
                "xg_source": "Estimated", "ppda_source": "Event-derived", "possession_source": "Pass Share",
            }
            rows.append(row)

    table = _pd.DataFrame(rows)
    # Wyscout official overlay for source-of-truth team metrics where available.
    try:
        from components.metric_engine import get_wyscout_df
        wy = get_wyscout_df()
        if wy is not None and not wy.empty and not table.empty:
            wy2 = wy.copy()
            wy2["date"] = wy2["date"].astype(str).str[:10]
            for i, r in table.iterrows():
                wr = wy2[(wy2["date"] == str(r["date"])[:10]) & (wy2["team_name_canon"] == r["team"])]
                if wr.empty:
                    continue
                w = wr.iloc[0]
                if _pd.notna(w.get("wyscout_xg")):
                    table.at[i, "xg"] = float(w["wyscout_xg"]); table.at[i, "xg_source"] = "Wyscout"
                # xGA from opponent xG in same match/date.
                opp = wy2[(wy2["date"] == str(r["date"])[:10]) & (wy2["team_name_canon"] == r["opponent"])]
                if not opp.empty and _pd.notna(opp.iloc[0].get("wyscout_xg")):
                    table.at[i, "xga"] = float(opp.iloc[0]["wyscout_xg"]); table.at[i, "xga_source"] = "Wyscout"
                else:
                    table.at[i, "xga_source"] = "Estimated"
                if _pd.notna(w.get("wyscout_ppda")):
                    table.at[i, "ppda"] = float(w["wyscout_ppda"]); table.at[i, "ppda_source"] = "Wyscout"
                if _pd.notna(w.get("wyscout_possession_pct")):
                    table.at[i, "possession"] = float(w["wyscout_possession_pct"]); table.at[i, "possession_source"] = "Wyscout"
                if _pd.notna(w.get("wyscout_shots")):
                    table.at[i, "shots"] = int(w["wyscout_shots"])
                if _pd.notna(w.get("wyscout_shots_on_target")):
                    table.at[i, "shots_on_target"] = int(w["wyscout_shots_on_target"])
                if _pd.notna(w.get("wyscout_corners")):
                    table.at[i, "corners"] = int(w["wyscout_corners"])
                if _pd.notna(w.get("wyscout_progressive_passes")):
                    table.at[i, "prog_passes"] = int(w["wyscout_progressive_passes"])
    except Exception:
        if "xga_source" not in table.columns:
            table["xga_source"] = "Estimated"

    if "xga_source" not in table.columns:
        table["xga_source"] = "Estimated"
    _CACHE[ck] = table
    return table


def _interpret_post_match_metric(label, value, team_avg, league_avg, diff_team, pct, direction):
    if value is None or pd.isna(value) or team_avg is None or pd.isna(team_avg):
        return "Insufficient data"
    scale = max(abs(float(team_avg)), 1.0)
    rel = float(diff_team) / scale
    if abs(rel) < 0.10:
        base = "Normal range"
    elif rel > 0:
        base = "Above team average"
    else:
        base = "Below team average"
    if direction == "higher_good":
        if pct is not None and pct >= 75:
            return f"Strong — {base.lower()}"
        if pct is not None and pct <= 25:
            return f"Weak — {base.lower()}"
        return base
    if direction == "lower_good":
        if pct is not None and pct >= 75:
            return f"Strong — lower/better than usual" if diff_team < 0 else f"Strong vs league, but {base.lower()}"
        if pct is not None and pct <= 25:
            return f"Weak — higher/worse than usual" if diff_team > 0 else f"Weak vs league, but {base.lower()}"
        return base
    # Contextual defensive workload metrics: high can be ball-winning OR heavy defending.
    if rel > 0.15:
        return "Above usual volume — review with territory/possession context"
    if rel < -0.15:
        return "Below usual volume — lower defensive workload or reduced ball-winning"
    return "Normal defensive workload range"


def build_post_match_kpi_context(league_folder, team, match_id, metric_name, match_value=None):
    """Contextualize one post-match KPI against the team's season average and
    the league team-match average. Returns a JSON-safe dict used by both Dash and PDF.
    The season/league baselines exclude the selected match to avoid grading a match
    against an average that already includes itself.
    """
    from data_loader import normalize_team
    import numpy as _np
    table = _build_post_match_team_match_table(league_folder)
    if table.empty:
        return {"metric": metric_name, "label": POST_MATCH_KPI_REGISTRY.get(metric_name, {}).get("label", metric_name),
                "match_value": match_value, "confidence": "Low", "interpretation": "Insufficient data"}
    team = normalize_team(team)
    meta = POST_MATCH_KPI_REGISTRY.get(metric_name, {"label": metric_name.replace("_", " ").title(), "direction": "contextual", "source": "Event-derived", "group": "Other"})
    if metric_name not in table.columns:
        return {"metric": metric_name, "label": meta["label"], "match_value": match_value,
                "confidence": "Low", "interpretation": "Insufficient data", "source": meta.get("source", "")}
    row = table[(table["match_id"].astype(str) == str(match_id)) & (table["team"] == team)]
    if match_value is None and not row.empty:
        match_value = row.iloc[0].get(metric_name)
    if match_value is None or pd.isna(match_value):
        return {"metric": metric_name, "label": meta["label"], "match_value": None,
                "confidence": "Low", "interpretation": "Insufficient data", "source": meta.get("source", "")}

    base = table[table["match_id"].astype(str) != str(match_id)].copy()
    team_vals = base[base["team"] == team][metric_name].dropna()
    league_vals = base[metric_name].dropna()
    if len(team_vals) < 3 or len(league_vals) < 8:
        return {"metric": metric_name, "label": meta["label"], "match_value": round(float(match_value), 2),
                "team_season_avg": None, "league_avg": None, "confidence": "Low",
                "interpretation": "Insufficient data", "source": meta.get("source", ""),
                "sample_size": int(len(team_vals)), "league_sample_size": int(len(league_vals))}
    team_avg = float(team_vals.mean())
    league_avg = float(league_vals.mean())
    diff_team = float(match_value) - team_avg
    diff_league = float(match_value) - league_avg
    direction = meta.get("direction", "contextual")
    n = len(league_vals)
    if direction == "lower_good":
        pct = round((league_vals >= float(match_value)).sum() / max(n, 1) * 100)
    else:
        pct = round((league_vals <= float(match_value)).sum() / max(n, 1) * 100)
    interp = _interpret_post_match_metric(meta["label"], float(match_value), team_avg, league_avg, diff_team, pct, direction)
    source = meta.get("source", "Event-derived")
    if not row.empty:
        # More precise provenance for Wyscout-overlaid metrics.
        if metric_name == "xg": source = row.iloc[0].get("xg_source", source)
        if metric_name == "xga": source = row.iloc[0].get("xga_source", source)
        if metric_name == "ppda": source = row.iloc[0].get("ppda_source", source)
        if metric_name == "possession": source = row.iloc[0].get("possession_source", source)
    return {
        "metric": metric_name, "label": meta["label"], "group": meta.get("group", "Other"),
        "match_value": round(float(match_value), 2), "team_season_avg": round(team_avg, 2),
        "league_avg": round(league_avg, 2), "difference_vs_team_avg": round(diff_team, 2),
        "difference_vs_league_avg": round(diff_league, 2), "percentile": int(pct),
        "interpretation": interp, "direction": direction, "confidence": "High" if len(team_vals) >= 8 else "Medium",
        "source": source, "sample_size": int(len(team_vals)), "league_sample_size": int(len(league_vals)),
        "formula": "Match value compared with team season per-match average and league team-match average; selected match excluded from baselines.",
    }


def build_post_match_kpi_contexts(league_folder, team, match_id, metric_values=None, metrics=None):
    metric_values = metric_values or {}
    metrics = metrics or list(POST_MATCH_KPI_REGISTRY.keys())
    return [build_post_match_kpi_context(league_folder, team, match_id, m, metric_values.get(m)) for m in metrics]
