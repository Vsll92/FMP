"""
components/overview_metrics.py — PURE team-situation analytics (no Dash).

compute_team_situation() produces the analytical context the Overview page
needs: form/xG/goals/defensive trends (last 5 vs prior 5), attacking
efficiency, Wyscout completeness, top strengths/risks, and league-relative
standing. Pure analytics so it is headless-testable.
"""


def _trend_word(recent, prior, higher_better=True, tol=0.05):
    if prior is None or recent is None:
        return "steady"
    diff = recent - prior
    if abs(diff) < tol:
        return "steady"
    improving = diff > 0 if higher_better else diff < 0
    return "improving" if improving else "declining"


def compute_team_situation(league_folder, team_name):
    """Return a dict of analytical context for the Overview page."""
    from data_loader import get_team_results, get_match_list
    from components.report_engine import compute_team_profile
    from components.metric_engine import get_wyscout_df

    tr = get_team_results(league_folder, team_name).sort_values("week")
    n_total = len(tr)
    last5 = tr.tail(5)
    prior5 = tr.iloc[-10:-5] if n_total >= 10 else tr.iloc[:max(n_total - 5, 0)]

    def _ppg(sub):
        if sub.empty:
            return 0.0
        pts = (sub["result"] == "W").sum() * 3 + (sub["result"] == "D").sum()
        return round(pts / len(sub), 2)

    def _gf_pm(sub):
        return round(sub["gf"].mean(), 2) if len(sub) else 0.0

    def _ga_pm(sub):
        return round(sub["ga"].mean(), 2) if len(sub) else 0.0

    form_ppg = _ppg(last5)
    prior_ppg = _ppg(prior5)
    gf_recent, gf_prior = _gf_pm(last5), _gf_pm(prior5)
    ga_recent, ga_prior = _ga_pm(last5), _ga_pm(prior5)

    # xG trend via team profile (Wyscout where available)
    prof5 = compute_team_profile(league_folder, team_name, 5) or {}
    prof10 = compute_team_profile(league_folder, team_name, 10) or {}
    xg_recent = prof5.get("wyscout_xg", prof5.get("xg_per_match"))
    xg_prior = prof10.get("wyscout_xg", prof10.get("xg_per_match"))
    xga_recent = prof5.get("wyscout_xga", prof5.get("xga_per_match"))

    # Attacking efficiency: goals vs xG
    efficiency = None
    if xg_recent:
        efficiency = round(gf_recent - xg_recent, 2)  # +ve = overperforming xG

    # Wyscout completeness over the team's matches
    wy = get_wyscout_df()
    wy_complete = None
    if wy is not None:
        team_wy = wy[wy["team_name_canon"] == team_name]
        wy_complete = round(min(len(team_wy) / max(n_total, 1), 1.0) * 100)

    trends = {
        "form": {"recent": form_ppg, "prior": prior_ppg,
                 "direction": _trend_word(form_ppg, prior_ppg, True, 0.2)},
        "xg": {"recent": xg_recent, "prior": xg_prior,
               "direction": _trend_word(xg_recent, xg_prior, True, 0.1) if xg_recent and xg_prior else "n/a"},
        "goals": {"recent": gf_recent, "prior": gf_prior,
                  "direction": _trend_word(gf_recent, gf_prior, True, 0.2)},
        "defense": {"recent": ga_recent, "prior": ga_prior,
                    "direction": _trend_word(ga_recent, ga_prior, False, 0.2)},
    }

    strengths = (prof5.get("threats") or [])[:3]
    risks = (prof5.get("weaknesses") or [])[:3]

    # League comparison (xG/match rank)
    rank_ctx = _league_xg_rank(league_folder, team_name)

    # What to watch next
    watch = []
    if trends["xg"]["direction"] == "improving" and trends["goals"]["direction"] != "improving":
        watch.append("Creating more (xG up) but goals haven't followed — finishing may regress upward.")
    if trends["goals"]["direction"] == "improving" and (xg_recent and gf_recent > xg_recent + 0.4):
        watch.append("Scoring above xG — current goal rate may not be sustainable.")
    if trends["defense"]["direction"] == "declining":
        watch.append("Conceding more recently — defensive structure worth monitoring.")
    if not watch:
        watch.append("Performance broadly stable across recent matches.")

    return {
        "team": team_name, "n_matches": n_total,
        "trends": trends, "efficiency": efficiency,
        "wyscout_completeness": wy_complete,
        "strengths": strengths, "risks": risks,
        "league_rank": rank_ctx, "watch": watch,
        "form_string": "".join(last5["result"].tolist()[-5:]),
    }


def _league_xg_rank(league_folder, team_name):
    """Rank the team's xG/match among the league (1 = best)."""
    try:
        from data_loader import get_teams
        from components.report_engine import compute_team_profile
        vals = []
        for t in get_teams(league_folder):
            p = compute_team_profile(league_folder, t, 10) or {}
            xg = p.get("wyscout_xg", p.get("xg_per_match"))
            if xg is not None:
                vals.append((t, xg))
        vals.sort(key=lambda kv: -kv[1])
        for i, (t, xg) in enumerate(vals, 1):
            if t == team_name:
                return {"xg_rank": i, "of": len(vals), "xg": round(xg, 2)}
    except Exception:
        pass
    return None
