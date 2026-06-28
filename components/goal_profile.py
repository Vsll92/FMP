"""
components/goal_profile.py — attacking & defensive goal profiles for reports.

compute_goal_profile(df, team, match_ids, side="for"|"against") returns totals,
per-match rates, half splits, timing bands, and method distribution. Uses the
central flag logic (no ad-hoc "Si" checks) and the registry's own-goal rule.
"""
import pandas as pd
from components.definitions import flag_mask

# Goal timing bands (minute ranges)
_TIMING_BANDS = [("0-15", 0, 15), ("16-30", 16, 30), ("31-45+", 31, 45),
                 ("46-60", 46, 60), ("61-75", 61, 75), ("76-90+", 76, 200)]

_OWN_GOAL_MAX_X = 35.0


def classify_goal_method(goal_row, match_df=None, team_name=None):
    """Classify a single goal into a primary method bucket.

    Backward compatible: returns a list of method strings (the historical API).
    For richer output use classify_goal_detail(), which returns method, phase,
    body_part, confidence and the evidence flags used."""
    detail = classify_goal_detail(goal_row, match_df, team_name)
    return detail["methods"]


def classify_goal_detail(goal_row, match_df=None, team_name=None):
    """Rich goal classification → {methods, primary, phase, body_part,
    confidence, evidence}. Uses event flags (no ad-hoc 'Si' checks) plus, when
    a match frame is supplied, nearby preceding events for transition context."""
    def f(col):
        return col in goal_row and pd.notna(goal_row.get(col)) and flag_mask(pd.Series([goal_row.get(col)])).iloc[0]

    x = pd.to_numeric(pd.Series([goal_row.get("x")]), errors="coerce").iloc[0]
    evidence = []
    methods = []

    # Own goal (scored from own half) — high confidence
    if pd.notna(x) and x < _OWN_GOAL_MAX_X:
        return {"methods": ["own goal"], "primary": "own goal", "phase": "own goal",
                "body_part": "unknown", "confidence": "high",
                "evidence": [f"shot x={x:.0f} < {_OWN_GOAL_MAX_X:.0f} (own half)"]}

    is_corner = f("From corner")
    is_fk = f("Free kick taken")
    is_sp = f("Set piece")
    is_fb = f("Fast break")
    is_head = f("Head")
    is_individual = f("Individual Play")

    if is_corner:
        methods.append("corner"); evidence.append("From corner flag")
    if is_fk:
        methods.append("free kick"); evidence.append("Free kick taken flag")
    if is_sp and not methods:
        methods.append("set piece"); evidence.append("Set piece flag")
    if is_fb:
        methods.append("counter"); evidence.append("Fast break flag")
    if is_head:
        methods.append("header"); evidence.append("Head flag")
    if f("Penalty"):
        methods.append("penalty"); evidence.append("Penalty flag")
    if f("Regular play") and not methods:
        methods.append("open play"); evidence.append("Regular play flag")
    if is_individual and "open play" not in methods:
        methods.append("open play"); evidence.append("Individual Play flag")
    if not methods:
        methods.append("open play"); evidence.append("no set-piece/transition flag → assumed open play")

    # Phase
    if is_corner or is_fk or is_sp:
        phase = "set piece"
    elif is_fb:
        phase = "transition"
    else:
        phase = "open play"

    # Body part
    if is_head:
        body_part = "head"
    elif f("Right footed"):
        body_part = "right foot"
    elif f("Left footed"):
        body_part = "left foot"
    else:
        body_part = "unknown"

    # Confidence: explicit method flags = high; pure fallback = low
    if is_corner or is_fk or f("Penalty"):
        confidence = "high"
    elif is_sp or is_fb or f("Regular play"):
        confidence = "medium"
    else:
        confidence = "low"

    return {"methods": methods, "primary": methods[0], "phase": phase,
            "body_part": body_part, "confidence": confidence, "evidence": evidence}


def compute_goal_profile(df, team_name, match_ids, side="for"):
    """Goal profile for a team over the selected matches.
    side='for' = goals scored by the team; side='against' = goals conceded.
    Own goals are attributed to the opponent (so a team's own-goal-for is the
    opponent's mistake; conceded includes opponents' own goals against us)."""
    from data_loader import normalize_team
    team_name = normalize_team(team_name)
    sub = df[df["match_id"].isin(match_ids)]
    goals = sub[sub["event"] == "Goal"].copy()
    if goals.empty:
        return _empty_profile(len(match_ids))
    goals["x"] = pd.to_numeric(goals["x"], errors="coerce")
    goals["is_og"] = goals["x"].notna() & (goals["x"] < _OWN_GOAL_MAX_X)

    # A goal counts FOR team_name if: scored by team_name and not OG, OR scored
    # by the opponent as an own goal. Conceded is the mirror.
    by_team = goals["team_name"] == team_name
    credited_to_team = (by_team & ~goals["is_og"]) | (~by_team & goals["is_og"])
    if side == "for":
        rel = goals[credited_to_team]
    else:
        rel = goals[~credited_to_team]

    n_matches = max(len(match_ids), 1)
    total = len(rel)

    # Half split
    first_half = int((pd.to_numeric(rel["period_id"], errors="coerce") == 1).sum())
    second_half = total - first_half

    # Timing bands
    mins = pd.to_numeric(rel["time_min"], errors="coerce")
    timing = {}
    for label, lo, hi in _TIMING_BANDS:
        timing[label] = int(((mins >= lo) & (mins <= hi)).sum())

    # Method / phase / body-part / confidence distribution
    methods = {"open play": 0, "set piece": 0, "corner": 0, "free kick": 0,
               "penalty": 0, "counter": 0, "own goal": 0, "header": 0}
    phases = {"open play": 0, "set piece": 0, "transition": 0, "own goal": 0}
    body_parts = {"right foot": 0, "left foot": 0, "head": 0, "unknown": 0}
    confidence = {"high": 0, "medium": 0, "low": 0}
    for _, g in rel.iterrows():
        d = classify_goal_detail(g)
        for m in d["methods"]:
            methods[m] = methods.get(m, 0) + 1
        phases[d["phase"]] = phases.get(d["phase"], 0) + 1
        body_parts[d["body_part"]] = body_parts.get(d["body_part"], 0) + 1
        confidence[d["confidence"]] = confidence.get(d["confidence"], 0) + 1

    return {
        "n_matches": len(match_ids), "total": total,
        "per_match": round(total / n_matches, 2),
        "first_half": first_half, "second_half": second_half,
        "timing": timing, "methods": methods,
        "phases": phases, "body_parts": body_parts, "confidence": confidence,
    }


def _empty_profile(n):
    return {"n_matches": n, "total": 0, "per_match": 0.0, "first_half": 0,
            "second_half": 0, "timing": {b[0]: 0 for b in _TIMING_BANDS},
            "methods": {}, "phases": {}, "body_parts": {}, "confidence": {}}
