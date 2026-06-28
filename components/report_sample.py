"""
components/report_sample.py — ONE centralized sample resolver (Dash-free).

Every report section (KPIs, goal profile, conceded profile, build-up, passing,
pressing, player roles, targets, PDF, Dash) resolves its match sample through
this single function, so changing the sample mode changes every section
consistently and pre-match reports never leak the selected match.

resolve_report_sample(...) returns:
{
    "match_ids": [...],
    "n_matches": int,
    "sample_label": str,
    "sample_mode": str,
    "before_match_id": id | None,
    "cutoff_week": int | None,
    "venue": "home"|"away"|None,
    "warnings": [...],
}
"""

# Map a sample_mode string → number of most-recent matches (None = all)
_MODE_N = {
    "last5": 5, "last10": 10, "season": None, "full": None,
    "last3": 3, "last1": 1,
}


def resolve_report_sample(league_folder, team_name, sample_mode="last5",
                          before_match_id=None, before_date=None,
                          venue=None, opponent=None):
    """Resolve the exact match_ids + metadata for a report sample.

    sample_mode: 'last1'|'last3'|'last5'|'last10'|'season'|'full'|'home'|'away'
                 (an int is also accepted and treated as last-N).
    before_match_id: exclude this match and everything from its week onward
                     (pre-match cutoff).
    venue: 'home' or 'away' to restrict; or pass sample_mode='home'/'away'.
    opponent: when set, restrict to head-to-head matches vs this opponent.
    """
    from data_loader import get_match_list, get_team_results

    warnings = []
    ml = get_match_list(league_folder)

    # Venue can arrive either as its own arg or folded into sample_mode
    if sample_mode in ("home", "away"):
        venue = sample_mode
        last_n = None
    elif isinstance(sample_mode, int):
        last_n = sample_mode
    else:
        last_n = _MODE_N.get(sample_mode, 5)

    # Cutoff week from the selected match (pre-match: use only prior matches)
    cutoff_week = None
    if before_match_id is not None:
        row = ml[ml["match_id"] == before_match_id]
        if not row.empty:
            cutoff_week = int(row.iloc[0]["week"])

    tr = get_team_results(league_folder, team_name)
    if tr is None or tr.empty or "week" not in tr.columns:
        # Unknown / unmatched team name → no results. Fail loud-but-safe with a
        # clear warning rather than crashing the whole report.
        return {"match_ids": [], "n_matches": 0,
                "sample_label": f"No matches found for '{team_name}'",
                "sample_mode": sample_mode, "before_match_id": before_match_id,
                "cutoff_week": None, "venue": venue,
                "warnings": [f"No results found for team '{team_name}'. Check the team name."]}
    tr = tr.sort_values("week")

    # Opponent restriction (H2H)
    if opponent is not None and "opponent" in tr.columns:
        tr = tr[tr["opponent"] == opponent]

    # Venue restriction (get_team_results uses 'H'/'A' codes)
    if venue in ("home", "away") and "venue" in tr.columns:
        code = "H" if venue == "home" else "A"
        tr = tr[tr["venue"] == code]

    # Pre-match cutoff: drop the selected match + everything from its week on
    if cutoff_week is not None:
        tr = tr[tr["week"] < cutoff_week]
    if before_match_id is not None:
        tr = tr[tr["match_id"] != before_match_id]

    # Date cutoff
    if before_date is not None and "local_date" in tr.columns:
        tr = tr[tr["local_date"] < before_date]

    all_ids = tr["match_id"].tolist()
    match_ids = all_ids[-last_n:] if last_n else all_ids
    n = len(match_ids)

    # Human-readable label
    if last_n:
        label = f"Last {last_n} matches"
    elif venue:
        label = f"{venue.title()} matches"
    else:
        label = "Season to date"
    if before_match_id is not None:
        label += " · before selected match"
    if opponent is not None:
        label += f" · vs {opponent}"

    if n == 0:
        warnings.append("No matches in the selected sample.")
    elif n < 3:
        warnings.append(f"Small sample (N={n}) — figures are low confidence.")

    return {
        "match_ids": match_ids, "n_matches": n, "sample_label": label,
        "sample_mode": sample_mode, "before_match_id": before_match_id,
        "cutoff_week": cutoff_week, "venue": venue, "warnings": warnings,
    }


# ── Report-model completeness validation (Dash-free, used by QA) ──
_REQUIRED_MODEL_KEYS = [
    "report_type", "title", "league", "teams", "sample", "kpis",
    "tactical_findings", "recommendations", "caveats", "qa",
]
_REQUIRED_PRE_KEYS = ["goal_profile", "goals_conceded_profile", "plan_vs_execution"]
_REQUIRED_POST_KEYS = ["score", "match", "plan_vs_execution", "player_notes"]


def validate_report_model(model):
    """Return (ok, missing_keys) for a built report model. Dash-free so release
    QA can validate model completeness without importing the UI."""
    missing = [k for k in _REQUIRED_MODEL_KEYS if k not in model]
    rtype = model.get("report_type")
    if rtype == "pre":
        missing += [k for k in _REQUIRED_PRE_KEYS if k not in model]
    elif rtype == "post":
        missing += [k for k in _REQUIRED_POST_KEYS if k not in model]
    return (len(missing) == 0, missing)
