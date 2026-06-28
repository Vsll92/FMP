"""
components/report_model.py — ONE shared report model for Dash + PDF.

Both the on-screen Dash report and the PDF export read from the same model so
values can never disagree. The model is a plain dict (JSON-serialisable except
for a few numeric types) with a stable schema:

{
  "report_type": "pre" | "post",
  "title", "league", "date",
  "match": {home, away, home_goals, away_goals, week, venue, score_source},
  "score": {home, away, source, winner, conflict, qa_warnings},
  "teams": {our, opponent, our_color, opp_color},
  "executive_summary": [str, ...],
  "kpis": [{label, value, source, context}, ...],
  "plan_vs_execution": {template, score, label, confidence, rows:[...]},
  "tactical_findings": [{title, body}, ...],
  "player_notes": [{name, note}, ...],
  "recommendations": [str, ...],
  "caveats": [str, ...],
  "qa": {warnings:[...], sample_size, wyscout_available},
}

Source priority for team metrics: Wyscout official → event-derived → estimated.
"""
import pandas as pd


def _src_label(metric, source):
    pre = {"Wyscout": "Wyscout ", "Event-derived": "", "Estimated": "Estimated ",
           "Pass Share": ""}.get(source, "")
    return f"{pre}{metric}"


def build_post_match_report_model(league_folder, match_id, our_team=None):
    """Build the canonical post-match report model (shared by Dash + PDF)."""
    from data_loader import get_match_list, short
    from components.report_engine import compute_post_match_report, compute_team_profile
    from components.target_engine import generate_targets, evaluate_targets
    from components.match_registry import get_match_score

    if our_team is not None:
        from data_loader import normalize_team
        our_team = normalize_team(our_team)

    rep = compute_post_match_report(league_folder, match_id)
    meta = rep["meta"]
    home, away = meta["home_team"], meta["away_team"]
    if our_team is None:
        our_team = home
    our_side = "home" if our_team == home else "away"
    opp_side = "away" if our_side == "home" else "home"
    us, them = rep[our_side], rep[opp_side]

    # Canonical score from the registry (single source of truth)
    sc = get_match_score(league_folder, match_id) or {
        "home_score": meta["home_goals"], "away_score": meta["away_goals"],
        "source": "match list", "conflict": False, "qa_warnings": []}
    winner = home if sc["home_score"] > sc["away_score"] else (away if sc["away_score"] > sc["home_score"] else "Draw")

    model = {
        "report_type": "post",
        "match_id": match_id,
        "title": f"Post-Match Report — {short(home)} {sc['home_score']}-{sc['away_score']} {short(away)}",
        "league": league_folder, "date": meta.get("date", ""),
        "match": {"match_id": match_id, "home": home, "away": away, "home_goals": sc["home_score"],
                  "away_goals": sc["away_score"], "week": meta.get("week"),
                  "venue": meta.get("venue", ""), "score_source": sc["source"]},
        "score": {"home": sc["home_score"], "away": sc["away_score"], "source": sc["source"],
                  "winner": winner, "conflict": sc["conflict"], "qa_warnings": sc["qa_warnings"]},
        "teams": {"our": our_team, "opponent": them["team"]},
        "sample": {"label": f"This match (W{meta.get('week', '')})", "n": 1, "match_ids": [match_id]},
        "executive_summary": [], "kpis": [], "plan_vs_execution": {},
        "goal_profile": {}, "goals_conceded_profile": {},
        "tactical_findings": [], "player_notes": [], "recommendations": [],
        "caveats": [], "qa": {"warnings": list(sc["qa_warnings"]), "wyscout_available": us.get("xg_source") == "Wyscout"},
    }

    # ── Goal distribution for THIS MATCH ONLY (parity with the Dash page) ──
    try:
        from data_loader import load_league_data
        from components.goal_profile import compute_goal_profile
        _df = load_league_data(league_folder)
        model["goal_profile"] = compute_goal_profile(_df, our_team, [match_id], side="for")
        model["goals_conceded_profile"] = compute_goal_profile(_df, our_team, [match_id], side="against")
    except Exception:
        pass

    # ── Executive summary ──
    res_word = "won" if winner == our_team else ("lost" if winner not in (our_team, "Draw") else "drew")
    model["executive_summary"].append(
        f"{short(our_team)} {res_word} {sc['home_score'] if our_side=='home' else sc['away_score']}–"
        f"{sc['away_score'] if our_side=='home' else sc['home_score']} against {short(them['team'])}.")
    model["executive_summary"].append(rep.get("game_story", ""))

    # ── KPIs (source-labelled) ──
    def kpi(label, value, source, context=""):
        if value is None:
            return
        v = f"{value:.2f}" if isinstance(value, float) else str(value)
        model["kpis"].append({"label": _src_label(label, source), "value": v,
                              "source": source, "context": context})
    kpi("xG", us.get("xg"), us.get("xg_source", "Estimated"), "Team total")
    kpi("xGA", us.get("xga"), us.get("xga_source", "Estimated"), "Opponent xG")
    kpi("Possession %", us.get("possession"), us.get("possession_source", "Pass Share"), "")
    kpi("PPDA", us.get("ppda"), us.get("ppda_source", "Estimated"), "Full-match")
    kpi("Field Tilt", us.get("field_tilt"), "Event-derived", "Territorial")
    kpi("Final-Third Entries", us.get("ft_entries"), "Event-derived", "")
    kpi("Box Entries", us.get("box_entries"), "Event-derived", "")
    kpi("Shots", us.get("shots_wyscout", us.get("shots")), "Wyscout" if us.get("shots_wyscout") else "Event-derived", "")
    kpi("Big Chances", us.get("big_chances"), "Event-derived", "")

    # ── Post-match KPI context: match vs team season average vs league average ──
    # These rows answer: is the match value good/bad compared with this team’s
    # normal level and the league norm? The selected match is excluded from the
    # season/league baselines to avoid self-comparison.
    try:
        from components.kpi_context import build_post_match_kpi_contexts
        _match_values = {
            "tackles_won": us.get("tackles_won"), "tackles": us.get("tackles"),
            "tackle_success_pct": (round(us.get("tackles_won", 0) / max(us.get("tackles", 0), 1) * 100, 1) if us.get("tackles") is not None else None),
            "interceptions": us.get("interceptions"), "recoveries": us.get("recoveries"),
            "clearances": us.get("clearances"), "duels_won": (us.get("tackles_won", 0) + us.get("aerials_won", 0)),
            "aerials_won": us.get("aerials_won"), "ppda": us.get("ppda"),
            "xg": us.get("xg"), "xga": us.get("xga"), "shots": us.get("shots_wyscout", us.get("shots")),
            "shots_on_target": us.get("sot_wyscout", us.get("shots_on_target")), "big_chances": us.get("big_chances"),
            "sp_shots": us.get("sp_shots"), "ft_entries": us.get("ft_entries"), "box_entries": us.get("box_entries"),
            "prog_passes": us.get("prog_passes"), "possession": us.get("possession"), "field_tilt": us.get("field_tilt"),
            "corners": us.get("corners_wyscout", us.get("corners")), "fouls_committed": us.get("fouls_committed"),
            "yellow_cards": us.get("yellow_cards"), "red_cards": us.get("red_cards"),
        }
        _metrics = [
            "xg", "xga", "shots", "shots_on_target", "big_chances",
            "tackles_won", "tackles", "tackle_success_pct", "interceptions", "recoveries",
            "clearances", "duels_won", "aerials_won", "ppda", "possession", "field_tilt",
            "ft_entries", "box_entries", "prog_passes", "sp_shots", "corners",
            "fouls_committed", "yellow_cards", "red_cards",
        ]
        model["post_match_kpi_context"] = build_post_match_kpi_contexts(league_folder, our_team, match_id, _match_values, _metrics)
    except Exception as _e:
        model["post_match_kpi_context"] = []
        model["qa"]["warnings"].append(f"Post-match KPI context unavailable: {_e}")

    # ── Plan vs Execution (target_engine, pre-match cutoff) ──
    mw = meta.get("week")
    op = compute_team_profile(league_folder, our_team, 5, before_matchweek=mw, exclude_match_id=match_id) \
        or compute_team_profile(league_folder, our_team, 5)
    pp = compute_team_profile(league_folder, them["team"], 5, before_matchweek=mw, exclude_match_id=match_id) \
        or compute_team_profile(league_folder, them["team"], 5)
    sample = op.get("matches_analyzed", 0) if op else 0
    plan = generate_targets(op or {}, pp or {}, sample_size=sample,
                            wyscout_available=(us.get("xg_source") == "Wyscout"))
    actuals = {"xg": us.get("xg"), "xga": us.get("xga"), "ppda": us.get("ppda"),
               "possession": us.get("possession"), "field_tilt": us.get("field_tilt"),
               "box_entries": us.get("box_entries"),
               "transition_xga": us.get("transition_xg_against"),
               "set_piece_shots": us.get("sp_shots"), "set_piece_conceded": us.get("opp_sp_shots")}
    ctx = {"won": winner == our_team, "goal_diff": abs(sc["home_score"] - sc["away_score"]),
           "xga": us.get("xga"), "big_chances_against": them.get("big_chances", 0)}
    teval = evaluate_targets(plan, actuals, ctx)
    model["plan_vs_execution"] = {
        "template": plan["template"].replace("_", " ").title(),
        "rationale": plan.get("rationale", ""), "confidence": plan.get("confidence", "High"),
        "score": teval["score"], "label": teval["label"], "counts": teval["counts"],
        "rows": [{"label": r["label"], "target": (f"{r['low']}–{r['high']}" if r.get("kind") == "range" else f"≤ {r['high']}"),
                  "actual": (f"{r['actual']:.2f}" if isinstance(r.get("actual"), float) else str(r.get("actual"))),
                  "status": r["status"], "interpretation": r.get("interpretation", "")} for r in teval["results"]],
    }
    model["qa"]["sample_size"] = sample
    if sample < 3:
        model["qa"]["warnings"].append("Small pre-match sample — targets are low confidence.")

    # ── Tactical findings ──
    tilt_word = "dominated territory" if us.get("field_tilt", 50) > 55 else ("ceded territory" if us.get("field_tilt", 50) < 45 else "shared territory")
    model["tactical_findings"].append({"title": "Territory & Control",
        "body": f"{short(our_team)} {tilt_word} ({us.get('field_tilt', 0):.0f}% field tilt) with "
                f"{us.get('possession', 0):.0f}% {us.get('possession_source', 'possession').lower()}."})
    model["tactical_findings"].append({"title": "Chance Quality",
        "body": f"{us.get('xg', 0):.2f} {us.get('xg_source', 'estimated')} xG from {us.get('shots', 0)} shots, "
                f"{us.get('big_chances', 0)} big chances; conceded {us.get('xga', 0):.2f} xGA."})
    press_word = "aggressive" if us.get("ppda", 15) < 10 else ("passive" if us.get("ppda", 15) > 18 else "balanced")
    model["tactical_findings"].append({"title": "Pressing & Transition",
        "body": f"{press_word.title()} press ({us.get('ppda', 0):.1f} {us.get('ppda_source', 'estimated')} PPDA). "
                f"Final-third entries: {us.get('ft_entries', 0)}, box entries: {us.get('box_entries', 0)}."})

    # ── Recommendations ──
    for r in teval["results"]:
        if r["status"] == "Missed":
            tgt = f"{r['low']}–{r['high']}" if r.get("kind") == "range" else f"≤ {r['high']}"
            lbl = r["label"].lower()
            model["recommendations"].append(
                f"Address {lbl}: came in at {r.get('actual')}, target {tgt}.")
    if not model["recommendations"]:
        model["recommendations"].append("Plan was executed well — maintain the current model and rotate to manage load.")

    # ── Caveats ──
    model["caveats"].append("Team-level xG, xGA, PPDA and possession use Wyscout official data where available.")
    model["caveats"].append("Final-third entries, box entries and field tilt are event-derived. Shot-level xG is estimated.")
    if sc["conflict"]:
        model["caveats"].append(f"Score conflict noted: {'; '.join(sc['qa_warnings'])}")

    # ── Key player notes (structured, from role profiles over this match) ──
    try:
        from components.report_engine import compute_player_roles
        roles = compute_player_roles(league_folder, our_team, 1)[:5]
        for p in roles:
            note = (f"{p.get('role', '')} · Influence {p.get('influence', 0)} · "
                    f"{p['goals']}G {p['assists']}A, {p['key_passes']} key passes, "
                    f"{p['prog_passes']} progressive passes · touch D/M/A "
                    f"{p.get('touch_def_pct', 0)}/{p.get('touch_mid_pct', 0)}/{p.get('touch_att_pct', 0)}%")
            model["player_notes"].append({"name": f"#{p['jersey']} {p['name']} ({p['position']})", "note": note})
    except Exception:
        pass

    return model


def build_pre_match_report_model(league_folder, our_team, opponent, last_n=5,
                                 before_match_id=None):
    """Build the canonical pre-match report model (shared by Dash + PDF).
    The sample (last_n matches, optionally before a selected match) is applied
    consistently to every section, including the goal profiles."""
    from data_loader import short, load_league_data, get_match_list, get_team_results, normalize_team
    from components.report_engine import compute_team_profile
    from components.target_engine import generate_targets, infer_plan_template
    from components.goal_profile import compute_goal_profile

    # Canonicalize the selected team/opponent so the stored identity (and the
    # PDF) match the Dash report regardless of whether a short alias was passed.
    our_team = normalize_team(our_team)
    opponent = normalize_team(opponent)

    # ── Resolve samples via the central resolver ──
    # Pre-match is an opponent-scouting report. The Goal Distribution section
    # must therefore describe the selected OPPONENT, not our selected/report
    # team. Keep our-team sample available for plan/targets, but drive the
    # goal-profile cards, goal KPIs, and PDF goal section from the opponent
    # sample so changing the opponent changes the distribution.
    df = load_league_data(league_folder)
    from components.report_sample import resolve_report_sample
    our_samp = resolve_report_sample(league_folder, our_team,
                                     sample_mode=(last_n if last_n else "season"),
                                     before_match_id=before_match_id)
    opp_samp = resolve_report_sample(league_folder, opponent,
                                     sample_mode=(last_n if last_n else "season"),
                                     before_match_id=before_match_id)
    samp = opp_samp
    sample_ids = opp_samp["match_ids"]
    n_sample = opp_samp["n_matches"]
    sample_label = opp_samp["sample_label"]

    op = compute_team_profile(league_folder, our_team, last_n) or {}
    pp = compute_team_profile(league_folder, opponent, last_n) or {}

    model = {
        "report_type": "pre",
        "title": f"Pre-Match Report — {short(our_team)} vs {short(opponent)}",
        "league": league_folder, "date": "",
        "match": {"home": our_team, "away": opponent},
        "teams": {"our": our_team, "opponent": opponent},
        "sample": {"label": sample_label, "n": n_sample, "match_ids": sample_ids,
                   "team": opponent, "scope": "opponent_goal_distribution"},
        "our_sample": {"label": our_samp["sample_label"], "n": our_samp["n_matches"],
                       "match_ids": our_samp["match_ids"], "team": our_team},
        "goal_profile_team": opponent,
        "executive_summary": [], "kpis": [], "plan_vs_execution": {},
        "goal_profile": {}, "goals_conceded_profile": {},
        "tactical_findings": [], "player_notes": [], "recommendations": [],
        "caveats": [], "qa": {"warnings": [], "sample_size": n_sample,
                              "wyscout_available": bool(op.get("wyscout_available"))},
    }
    if n_sample < 3:
        model["qa"]["warnings"].append(f"Small pre-match sample (N={n_sample}) — figures are low confidence.")

    # ── Opponent goal profiles over the opponent sample ──
    # In a pre-match report, this section answers: "How does the opponent score
    # and concede?" It is intentionally NOT our team's goal distribution.
    model["goal_profile"] = compute_goal_profile(df, opponent, sample_ids, side="for")
    model["goals_conceded_profile"] = compute_goal_profile(df, opponent, sample_ids, side="against")

    wy = bool(op.get("wyscout_available"))

    def kpi(label, val, source, context=""):
        if val is None:
            return
        v = f"{val:.2f}" if isinstance(val, float) else str(val)
        model["kpis"].append({"label": _src_label(label, source), "value": v, "source": source, "context": context})

    kpi("xG / Match", op.get("wyscout_xg", op.get("xg_per_match")), "Wyscout" if wy else "Estimated", "Recent form")
    kpi("xGA / Match", op.get("wyscout_xga", op.get("xga_per_match")), "Wyscout" if wy else "Estimated", "Recent form")
    kpi("PPDA", op.get("wyscout_ppda", op.get("ppda")), "Wyscout" if wy else "Estimated", "Pressing")
    kpi("Possession %", op.get("wyscout_possession_pct", op.get("possession_pct")), "Wyscout" if wy else "Pass Share", "")

    # Goal-profile KPIs (from the consistent sample)
    gf = model["goal_profile"]; ga = model["goals_conceded_profile"]
    kpi(f"{short(opponent)} Goals Scored", gf["total"], "Event-derived", f"{gf['per_match']}/match over {n_sample}")
    kpi(f"{short(opponent)} Goals Conceded", ga["total"], "Event-derived", f"{ga['per_match']}/match over {n_sample}")

    # Opponent comparison KPIs
    model["tactical_findings"].append({"title": "Opponent Profile",
        "body": f"{short(opponent)}: {pp.get('wyscout_xg', pp.get('xg_per_match', 0)):.2f} xG/match, "
                f"{pp.get('wyscout_ppda', pp.get('ppda', 0)):.1f} PPDA, "
                f"{pp.get('wyscout_possession_pct', pp.get('possession_pct', 0)):.0f}% possession."})

    inf = infer_plan_template(op, pp)
    plan = generate_targets(op, pp, sample_size=op.get("matches_analyzed", 0), wyscout_available=wy)
    model["plan_vs_execution"] = {
        "template": plan["template"].replace("_", " ").title(),
        "rationale": plan.get("rationale", ""), "confidence": plan.get("confidence", "High"),
        "rows": [{"label": t["label"], "target": (f"{t['low']}–{t['high']}" if t.get("kind") == "range" else f"≤ {t['high']}"),
                  "note": t.get("note", "")} for t in plan["targets"]],
    }

    model["executive_summary"].append(
        f"{short(our_team)} face {short(opponent)}. Recommended approach: {plan['template'].replace('_', ' ')}.")
    model["executive_summary"].append(plan.get("rationale", ""))

    # Strengths / vulnerabilities
    for s in (op.get("threats") or [])[:3]:
        model["tactical_findings"].append({"title": "Our Strength", "body": s})
    for w in (pp.get("weaknesses") or [])[:3]:
        model["tactical_findings"].append({"title": "Opponent Vulnerability", "body": w})

    model["recommendations"].append(f"Set up in a {plan['template'].replace('_', ' ')} structure and target the ranges above.")
    model["caveats"].append("Pre-match targets use only matches before this fixture. Wyscout official team xG/xGA/PPDA/possession are used where available; Estimated event xG is used only for shot/context breakdowns and may not equal Wyscout xG.")
    if op.get("matches_analyzed", 0) < 3:
        model["qa"]["warnings"].append("Small pre-match sample — targets are low confidence.")

    # ── Key player notes (structured, from role profiles) ──
    try:
        from components.report_engine import compute_player_roles
        roles = compute_player_roles(league_folder, our_team, last_n)[:5]
        for p in roles:
            note = (f"{p.get('role', '')} · Influence {p.get('influence', 0)} · "
                    f"{p['goals']}G {p['assists']}A, {p['key_passes']} key passes, "
                    f"{p['prog_passes']} progressive passes · touch D/M/A "
                    f"{p.get('touch_def_pct', 0)}/{p.get('touch_mid_pct', 0)}/{p.get('touch_att_pct', 0)}%")
            model["player_notes"].append({"name": f"#{p['jersey']} {p['name']} ({p['position']})", "note": note})
    except Exception:
        pass

    return model
