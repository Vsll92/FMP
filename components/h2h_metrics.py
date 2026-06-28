"""
components/h2h_metrics.py — PURE Head-to-Head analytics (NO Dash import).

This module holds the analytical core of the Head-to-Head feature so it can be
imported and tested in a headless environment (release QA, pytest, CI) without
Dash being installed. The UI layer (components/h2h_engine.py) imports from here
and only adds rendering.

Functions:
  resolve_h2h_match_ids   — scope → match_ids (all/last1/last3/last5/specific)
  compute_buildup_patterns— lane distribution, progression, switches, directness
  compute_passing_profile — volume, accuracy, length/direction splits
  compute_h2h_team_stats  — full per-team aggregate over a match sample
  get_h2h_key_players     — top-N influential players over a match sample
"""
import pandas as pd

from components.report_engine import (
    _xg_from_distance, _safe_pct, _safe_div, SHOT_EVENTS,
)
try:
    from components.definitions import is_flag as _FLAGVAL
except Exception:
    def _FLAGVAL(v):
        return bool(v) and str(v).strip().lower() not in ("", "0", "0.0", "nan", "none", "false")


def _flagmask(series):
    return series.apply(_FLAGVAL)


# ── Sample resolution ───────────────────────────────────────────────────
def resolve_h2h_match_ids(ml, team_a, team_b, scope="all", selected_match_id=None):
    """Resolve H2H match_ids from the selected scope.

    Accepts canonical names, display names, short names and aliases (e.g. Lens,
    PSG, Monaco). This is a public metrics function, so it normalizes inputs
    internally rather than assuming the Dash UI already passed canonical names.
    """
    try:
        from data_loader import normalize_team
        team_a = normalize_team(team_a)
        team_b = normalize_team(team_b)
    except Exception:
        pass
    h2h_ml = ml[((ml["home_team"] == team_a) & (ml["away_team"] == team_b)) |
                ((ml["home_team"] == team_b) & (ml["away_team"] == team_a))].sort_values("week")
    if h2h_ml.empty:
        return [], "No direct H2H"
    if scope == "specific" and selected_match_id:
        return [selected_match_id], "Selected match"
    if scope == "last1":
        return h2h_ml["match_id"].tolist()[-1:], "Last meeting"
    if scope == "last3":
        return h2h_ml["match_id"].tolist()[-3:], "Last 3 meetings"
    if scope == "last5":
        return h2h_ml["match_id"].tolist()[-5:], "Last 5 meetings"
    return h2h_ml["match_id"].tolist(), "All H2H meetings"


# ── Build-up patterns ───────────────────────────────────────────────────
def compute_buildup_patterns(df, team_name, match_ids):
    """Build-up patterns over the selected H2H sample (event-derived)."""
    from components.metric_engine import (final_third_entries, box_entries,
                                          progressive_passes)
    try:
        from data_loader import normalize_team
        team_name = normalize_team(team_name)
    except Exception:
        pass
    tdf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] == team_name)]
    n = max(len(match_ids), 1)
    passes = tdf[tdf["event"] == "Pass"].copy()
    completed = passes[passes["outcome"] == 1] if "outcome" in passes.columns else passes
    pe = completed.dropna(subset=["Pass End X", "Pass End Y"]) if not completed.empty else completed

    def _lane(sub):
        if sub.empty:
            return 0, 0, 0
        y = pd.to_numeric(sub["y"], errors="coerce")
        left = int((y < 33.3).sum()); cen = int(((y >= 33.3) & (y <= 66.6)).sum()); right = int((y > 66.6).sum())
        return left, cen, right
    lL, lC, lR = _lane(pe)
    lane_total = max(lL + lC + lR, 1)

    if not pe.empty:
        sx = pd.to_numeric(pe["x"], errors="coerce"); ex = pd.to_numeric(pe["Pass End X"], errors="coerce")
        first_third_prog = int(((sx < 33.3) & (ex > sx + 8)).sum())
        mid_third_prog = int(((sx >= 33.3) & (sx <= 66.6) & (ex > sx + 8)).sum())
        sy = pd.to_numeric(pe["y"], errors="coerce"); ey = pd.to_numeric(pe["Pass End Y"], errors="coerce")
        switches = int(((ey - sy).abs() > 35).sum())
        lng = pd.to_numeric(pe["Length"], errors="coerce") if "Length" in pe.columns else None
        long_passes = int((lng > 30).sum()) if lng is not None else 0
        avg_len = round(float(lng.mean()), 1) if lng is not None and lng.notna().any() else 0
        directness = round(((ex - sx).clip(lower=0).sum() / max(pd.to_numeric(pe["Length"], errors="coerce").sum(), 1)) * 100, 1) if "Length" in pe.columns else 0
    else:
        first_third_prog = mid_third_prog = switches = long_passes = avg_len = directness = 0

    return {
        "n_matches": len(match_ids),
        "lane_left_pct": round(lL / lane_total * 100, 1),
        "lane_central_pct": round(lC / lane_total * 100, 1),
        "lane_right_pct": round(lR / lane_total * 100, 1),
        "first_third_prog_pm": round(first_third_prog / n, 1),
        "mid_third_prog_pm": round(mid_third_prog / n, 1),
        "progressive_passes_pm": round(len(progressive_passes(tdf)) / n, 1),
        "ft_entries_pm": round(len(final_third_entries(tdf)) / n, 1),
        "box_entries_pm": round(len(box_entries(tdf)) / n, 1),
        "switches_pm": round(switches / n, 1),
        "long_buildup_pm": round(long_passes / n, 1),
        "avg_pass_length": avg_len,
        "directness": directness,
    }


# ── Passing profile ─────────────────────────────────────────────────────
def compute_passing_profile(df, team_name, match_ids):
    """Passing profile over the selected H2H sample (event-derived)."""
    from components.metric_engine import progressive_passes, final_third_entries, box_entries
    try:
        from data_loader import normalize_team
        team_name = normalize_team(team_name)
    except Exception:
        pass
    tdf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] == team_name)]
    n = max(len(match_ids), 1)
    passes = tdf[tdf["event"] == "Pass"].copy()
    total = len(passes)
    completed = passes[passes["outcome"] == 1] if "outcome" in passes.columns else passes
    n_comp = len(completed)
    accuracy = round(n_comp / max(total, 1) * 100, 1)
    pe = completed.dropna(subset=["Pass End X", "Pass End Y"]) if not completed.empty else completed

    short_p = med_p = long_p = fwd = lat = back = key = crosses = through = 0
    if not pe.empty:
        lng = pd.to_numeric(pe["Length"], errors="coerce") if "Length" in pe.columns else pd.Series([], dtype=float)
        short_p = int((lng < 15).sum()); med_p = int(((lng >= 15) & (lng <= 30)).sum()); long_p = int((lng > 30).sum())
        sx = pd.to_numeric(pe["x"], errors="coerce"); ex = pd.to_numeric(pe["Pass End X"], errors="coerce")
        fwd = int((ex > sx + 5).sum()); back = int((ex < sx - 5).sum()); lat = int((~((ex > sx + 5) | (ex < sx - 5))).sum())
        sy = pd.to_numeric(pe["y"], errors="coerce"); ey = pd.to_numeric(pe["Pass End Y"], errors="coerce")
        crosses = int((((sy < 21) | (sy > 79)) & (ex > 83) & (ey >= 21) & (ey <= 79)).sum())
        through = int(((ex > 66.6) & (ex > sx + 15)).sum())
    if "Key pass" in passes.columns:
        from components.definitions import flag_mask
        key = int(flag_mask(passes["Key pass"]).sum())

    return {
        "n_matches": len(match_ids),
        "passes_pm": round(total / n, 1), "accuracy": accuracy,
        "short_pm": round(short_p / n, 1), "medium_pm": round(med_p / n, 1), "long_pm": round(long_p / n, 1),
        "forward_pm": round(fwd / n, 1), "lateral_pm": round(lat / n, 1), "backward_pm": round(back / n, 1),
        "progressive_pm": round(len(progressive_passes(tdf)) / n, 1),
        "final_third_pm": round(len(final_third_entries(tdf)) / n, 1),
        "box_entry_pm": round(len(box_entries(tdf)) / n, 1),
        "key_passes_pm": round(key / n, 1), "crosses_pm": round(crosses / n, 1),
        "through_balls_pm": round(through / n, 1),
    }


# ── Full per-team aggregate ─────────────────────────────────────────────
def compute_h2h_team_stats(df, team_name, match_ids):
    """Compute aggregated per-match stats for a team across specific matches."""
    tdf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] == team_name)]
    odf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] != team_name)]
    n = max(len(match_ids), 1)

    passes = tdf[tdf["event"] == "Pass"]
    passes_end = passes.dropna(subset=["Pass End X", "Pass End Y"])
    shots = tdf[tdf["event"].isin(SHOT_EVENTS)]
    goals = tdf[tdf["event"] == "Goal"]
    opp_passes = odf[odf["event"] == "Pass"]
    opp_shots = odf[odf["event"].isin(SHOT_EVENTS)]

    xg = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance"))) for _, s in shots.iterrows())
    xg_against = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance"))) for _, s in opp_shots.iterrows())

    xg_op = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if not _FLAGVAL(s.get("Set piece")) and not _FLAGVAL(s.get("From corner")) and not _FLAGVAL(s.get("Fast break")))
    xg_sp = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if _FLAGVAL(s.get("Set piece")) or _FLAGVAL(s.get("From corner")))
    xg_fb = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if _FLAGVAL(s.get("Fast break")))

    from components.metric_engine import (final_third_entries as _fte,
                                          box_entries as _bxe, progressive_passes as _pgp)
    prog = _pgp(tdf)
    ft_entries = _fte(tdf)
    box_entries = _bxe(tdf)

    possession = _safe_pct(len(passes), len(passes) + len(opp_passes))

    opp_own_half = len(opp_passes[opp_passes["x"] < 50])
    our_def_opp = len(tdf[(tdf["event"].isin(["Tackle", "Interception", "Foul"])) & (tdf["x"] > 50)])
    ppda = _safe_div(opp_own_half, our_def_opp)

    def_actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery"])]
    def_height = def_actions["x"].mean() if len(def_actions) > 0 else 50
    high_regains = len(tdf[(tdf["event"] == "Ball recovery") & (tdf["x"] > 50)])

    left = len(passes_end[passes_end["Pass End Y"] >= 66.6]) if len(passes_end) > 0 else 0
    center = len(passes_end[(passes_end["Pass End Y"] >= 33.3) & (passes_end["Pass End Y"] < 66.6)]) if len(passes_end) > 0 else 0
    right = len(passes_end[passes_end["Pass End Y"] < 33.3]) if len(passes_end) > 0 else 0
    total_lane = max(left + center + right, 1)

    sp_shots = len(shots[(_flagmask(shots["Set piece"])) | (_flagmask(shots["From corner"]))])
    opp_sp_shots = len(opp_shots[(_flagmask(opp_shots["Set piece"])) | (_flagmask(opp_shots["From corner"]))])
    corners = len(tdf[_flagmask(tdf["Corner taken"])])

    return {
        "team": team_name, "matches": n,
        "goals": len(goals), "goals_against": len(odf[odf["event"] == "Goal"]),
        "xg": round(xg, 2), "xg_against": round(xg_against, 2),
        "xg_pm": round(xg / n, 2), "xg_against_pm": round(xg_against / n, 2),
        "xg_open": round(xg_op, 2), "xg_sp": round(xg_sp, 2), "xg_fb": round(xg_fb, 2),
        "shots": len(shots), "shots_pm": round(len(shots) / n, 1),
        "sot": len(tdf[tdf["event"].isin(["Goal", "Saved Shot"])]),
        "big_chances": len(shots[_flagmask(shots["Big Chance"])]),
        "passes": len(passes), "pass_acc": _safe_pct((passes["outcome"] == 1).sum(), len(passes)),
        "possession": possession,
        "prog_passes": len(prog), "prog_pm": round(len(prog) / n, 1),
        "ft_entries": len(ft_entries), "ft_pm": round(len(ft_entries) / n, 1),
        "box_entries": len(box_entries), "box_pm": round(len(box_entries) / n, 1),
        "crosses": len(passes[_flagmask(passes["Cross"])]) if "Cross" in passes.columns else 0,
        "through_balls": len(passes[_flagmask(passes["Through ball"])]) if "Through ball" in passes.columns else 0,
        "long_balls": len(passes[_flagmask(passes["Long ball"])]) if "Long ball" in passes.columns else 0,
        "lane_left": _safe_pct(left, total_lane), "lane_center": _safe_pct(center, total_lane), "lane_right": _safe_pct(right, total_lane),
        "ppda": ppda, "def_height": round(def_height, 1), "high_regains": high_regains,
        "tackles": len(tdf[tdf["event"] == "Tackle"]),
        "interceptions": len(tdf[tdf["event"] == "Interception"]),
        "recoveries": len(tdf[tdf["event"] == "Ball recovery"]),
        "clearances": len(tdf[tdf["event"] == "Clearance"]),
        "fb_shots": len(shots[_flagmask(shots["Fast break"])]),
        "fb_xg": round(xg_fb, 2),
        "high_turnovers": len(tdf[(tdf["event"] == "Dispossessed") & (tdf["x"] > 50)]),
        "sp_shots": sp_shots, "sp_xg": round(xg_sp, 2),
        "opp_sp_shots": opp_sp_shots, "corners": corners,
        "aerials_won": len(tdf[(tdf["event"] == "Aerial") & (tdf["outcome"] == 1)]),
        "take_ons_won": len(tdf[(tdf["event"] == "Take On") & (tdf["outcome"] == 1)]),
        "fouls": len(tdf[(tdf["event"] == "Foul") & (tdf["outcome"] == 0)]),
        "yellows": len(tdf[(tdf["event"] == "Card") & (_flagmask(tdf["Yellow Card"]))]),
    }


# ── Key players ─────────────────────────────────────────────────────────
def get_h2h_key_players(df, team_name, match_ids, top_n=3):
    """Top N most influential players in H2H matches."""
    tdf = df[(df["match_id"].isin(match_ids)) & (df["team_name"] == team_name) & (df["player_name"].notna())]
    players = []
    for (pid, pn), pdf in tdf.groupby(["player_id", "player_name"], observed=True):
        shots = pdf[pdf["event"].isin(SHOT_EVENTS)]
        xg = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance"))) for _, s in shots.iterrows())
        prog = pdf[(pdf["event"] == "Pass") & (pdf["Pass End X"].notna())]
        prog_p = prog[(prog["Pass End X"] - prog["x"]) > 10] if len(prog) > 0 else pd.DataFrame()
        pos = pdf["position"].mode()
        jersey = pdf["Jersey Number"].dropna()
        players.append({
            "name": pn, "position": pos.iloc[0] if len(pos) > 0 else "?",
            "jersey": int(jersey.iloc[0]) if len(jersey) > 0 else 0,
            "goals": len(pdf[pdf["event"] == "Goal"]),
            "xg": round(xg, 2),
            "assists": len(pdf[pdf["Assist"] == 16]),
            "shots": len(shots),
            "prog_passes": len(prog_p),
            "touches": len(pdf[pdf["x"].notna()]),
            "tackles": len(pdf[pdf["event"] == "Tackle"]),
            "interceptions": len(pdf[pdf["event"] == "Interception"]),
            "recoveries": len(pdf[pdf["event"] == "Ball recovery"]),
            "take_ons": len(pdf[(pdf["event"] == "Take On") & (pdf["outcome"] == 1)]),
        })
    for p in players:
        p["influence"] = p["goals"] * 5 + p["xg"] * 3 + p["assists"] * 4 + p["prog_passes"] * 0.3 + p["tackles"] * 0.5 + p["recoveries"] * 0.2
    players.sort(key=lambda x: -x["influence"])
    return players[:top_n]


# ── Tactical interpretation (pure analytics) ────────────────────────────
def _advantage(va, vb, threshold, higher_better=True, n_sample=99):
    """Return 'A'|'B'|'neutral'|'small_sample' for a metric comparison."""
    if n_sample < 2:
        return "small_sample"
    diff = va - vb
    if abs(diff) < threshold:
        return "neutral"
    if higher_better:
        return "A" if diff > 0 else "B"
    return "B" if diff > 0 else "A"


def describe_buildup_pattern(bu):
    """Turn a build-up metrics dict into named tactical patterns."""
    patterns = []
    L, C, R = bu.get("lane_left_pct", 0), bu.get("lane_central_pct", 0), bu.get("lane_right_pct", 0)
    if R >= 40 and R > L + 8:
        patterns.append("right-side circulation")
    if L >= 40 and L > R + 8:
        patterns.append("left-side overload")
    if C >= 38:
        patterns.append("central progression")
    if bu.get("directness", 0) >= 45 or bu.get("long_buildup_pm", 0) >= 6:
        patterns.append("direct long build-up")
    if bu.get("switches_pm", 0) >= 18:
        patterns.append("switch-to-weak-side")
    if bu.get("box_entries_pm", 0) >= 5:
        patterns.append("box-entry through half-space")
    if not patterns:
        patterns.append("balanced circulation")
    return patterns


def compute_h2h_tactical_interpretation(df, team_a, team_b, match_ids):
    """Produce a tactical interpretation layer for an H2H sample:
    build-up patterns per team, passing edges, tactical mismatches, and an
    overall advantage read. Pure analytics (no Dash)."""
    n = len(match_ids)
    sa = compute_h2h_team_stats(df, team_a, match_ids)
    sb = compute_h2h_team_stats(df, team_b, match_ids)
    bua = compute_buildup_patterns(df, team_a, match_ids)
    bub = compute_buildup_patterns(df, team_b, match_ids)
    ppa = compute_passing_profile(df, team_a, match_ids)
    ppb = compute_passing_profile(df, team_b, match_ids)

    # Advantage reads on key dimensions
    advantages = {
        "xG creation": _advantage(sa["xg_pm"], sb["xg_pm"], 0.3, True, n),
        "defensive solidity": _advantage(sa["xg_against_pm"], sb["xg_against_pm"], 0.3, False, n),
        "territory (pass share)": _advantage(sa["possession"], sb["possession"], 5, True, n),
        "pressing (PPDA)": _advantage(sa["ppda"], sb["ppda"], 2, False, n),
        "transition threat": _advantage(sa["fb_xg"], sb["fb_xg"], 0.2, True, n),
        "set-piece threat": _advantage(sa["sp_xg"], sb["sp_xg"], 0.2, True, n),
        "box entries": _advantage(sa["box_pm"], sb["box_pm"], 1.5, True, n),
        "progression": _advantage(bua["progressive_passes_pm"], bub["progressive_passes_pm"], 3, True, n),
    }

    # Tactical mismatches: where one team's strength meets the other's weakness
    mismatches = []
    if sa["fb_xg"] > sb["fb_xg"] + 0.2 and sb["ppda"] > 14:
        mismatches.append(f"{team_a} transition threat vs {team_b} passive press — counters likely")
    if sb["fb_xg"] > sa["fb_xg"] + 0.2 and sa["ppda"] > 14:
        mismatches.append(f"{team_b} transition threat vs {team_a} passive press — counters likely")
    if sa["sp_xg"] > sb["opp_sp_shots"] * 0.05 and sa["corners"] / max(n, 1) > 5:
        mismatches.append(f"{team_a} set-piece volume could exploit {team_b} dead-ball defending")
    if bua["lane_right_pct"] >= 40 and bub.get("lane_left_pct", 0) < 30:
        mismatches.append(f"{team_a} right-side focus vs {team_b} thin left-side circulation")

    # Overall read
    a_edges = sum(1 for v in advantages.values() if v == "A")
    b_edges = sum(1 for v in advantages.values() if v == "B")
    if n < 2:
        overall = "Sample too small for a confident read"
    elif a_edges > b_edges + 1:
        overall = f"{team_a} hold the broader tactical edge"
    elif b_edges > a_edges + 1:
        overall = f"{team_b} hold the broader tactical edge"
    else:
        overall = "Evenly matched across most dimensions"

    return {
        "n_matches": n,
        "team_a": team_a, "team_b": team_b,
        "buildup_a": describe_buildup_pattern(bua),
        "buildup_b": describe_buildup_pattern(bub),
        "advantages": advantages,
        "mismatches": mismatches,
        "overall": overall,
        "a_edges": a_edges, "b_edges": b_edges,
    }
