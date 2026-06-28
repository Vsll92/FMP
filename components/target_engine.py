"""
components/target_engine.py — professional, Wyscout-aware pre-match target system.

Design rules (non-negotiable):
  * Targets use ONLY data available before the selected match (no leakage).
  * Realistic RANGES, not hard single thresholds.
  * No constant that forces xG near 2.8 (the old `2.5 * 1.10` bug is gone).
  * Targets and weights depend on the inferred tactical plan template.
  * Possession is NOT a success target for transition/direct/low-block plans.
  * Full-match PPDA is not auto-punished after a comfortable lead.
  * Wyscout official pre-match xG / xGA / PPDA / possession drive the targets
    where available; event-derived estimates are the fallback (clearly flagged).

Plan templates: possession_control, high_press, mid_block, transition, low_block,
set_piece, balanced.
"""
import numpy as np


PLAN_TEMPLATES = ["possession_control", "high_press", "mid_block",
                  "transition", "low_block", "set_piece", "balanced"]

# Per-template metric weights. 0 weight = not a success criterion for that plan.
_TEMPLATE_WEIGHTS = {
    "possession_control": {"xg": 1.5, "xga": 1.5, "possession": 1.0, "field_tilt": 1.0,
                           "ppda": 1.0, "box_entries": 1.0},
    "high_press":         {"xg": 1.5, "xga": 1.5, "ppda": 2.0, "field_tilt": 1.0,
                           "box_entries": 1.0, "possession": 0.5},
    "mid_block":          {"xg": 1.5, "xga": 1.5, "box_entries": 1.0, "ppda": 0.5,
                           "transition_xga": 1.5, "possession": 0.0},
    "transition":         {"xg": 1.5, "xga": 1.5, "transition_xga": 2.0, "box_entries": 1.0,
                           "ppda": 0.5, "possession": 0.0},
    "low_block":          {"xga": 2.0, "xg": 1.0, "set_piece_conceded": 1.5, "ppda": 0.0,
                           "possession": 0.0},
    "set_piece":          {"xg": 1.5, "set_piece_shots": 1.5, "xga": 1.0, "box_entries": 1.0},
    "balanced":           {"xg": 1.5, "xga": 1.5, "box_entries": 1.0, "ppda": 1.0,
                           "possession": 0.5},
}

_STATUS_SCORE = {"Hit": 1.0, "Strategically Acceptable": 0.75, "Partial": 0.5,
                 "Missed": 0.0, "Low Confidence": None, "Not Applicable": None,
                 "Unavailable": None}


def infer_plan_template(our_profile, opp_profile, venue=None) -> dict:
    """Infer the intended tactical plan from PRE-MATCH profiles (Wyscout-aware).
    Prefers Wyscout possession/PPDA over event-derived pass-share so a direct/
    transition team is not misread as possession-control."""
    # Wyscout possession is the real possession signal; pass-share inflates it.
    wy_poss = _g(our_profile, "wyscout_possession_pct")
    our_ppda = _g(our_profile, "wyscout_ppda", "ppda", default=13.0)
    # Only fall back to event pass-share if Wyscout possession is missing
    our_poss = wy_poss if wy_poss is not None else _g(our_profile, "possession", "possession_pct", default=50.0)

    if our_ppda <= 9.5 and our_poss >= 52:
        return {"template": "high_press", "rationale": "Aggressive press + ball dominance."}
    if our_poss >= 55:
        return {"template": "possession_control", "rationale": "Controls the ball, dictates tempo."}
    if our_poss < 48:
        return {"template": "transition", "rationale": "Cedes the ball, threatens in transition / direct attack."}
    if our_ppda >= 16:
        return {"template": "low_block", "rationale": "Sits deep, limits space."}
    return {"template": "mid_block", "rationale": "Compact mid-block, balanced approach."}


def _g(profile, *keys, default=None):
    if not profile:
        return default
    for k in keys:
        if k in profile and profile[k] is not None:
            return profile[k]
    return default


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def generate_targets(our_profile, opp_profile, template=None, venue=None,
                     sample_size=None, wyscout_available=False) -> dict:
    """Generate realistic target RANGES for the inferred (or chosen) plan.
    Returns {template, rationale, targets:[...], confidence}."""
    inf = infer_plan_template(our_profile, opp_profile, venue)
    template = template or inf["template"]
    weights = _TEMPLATE_WEIGHTS.get(template, _TEMPLATE_WEIGHTS["balanced"])

    our_xg = _g(our_profile, "wyscout_xg", "xg_per_match", "xg", default=1.4)
    opp_xga = _g(opp_profile, "wyscout_xga", "xga_per_match", default=1.4)
    our_ppda = _g(our_profile, "wyscout_ppda", "ppda", default=13.0)
    our_box = _g(our_profile, "box_entries_pm", "box_entries", default=10)

    confidence = "High"
    if sample_size is not None and sample_size < 3:
        confidence = "Low"

    targets = []

    def add(metric, lo, hi, label, kind="range", note=""):
        w = weights.get(metric, 0.0)
        if w <= 0:
            return  # not a success criterion for this plan
        targets.append({"metric": metric, "label": label, "low": round(lo, 2),
                        "high": round(hi, 2), "kind": kind, "weight": w, "note": note})

    # xG range — blend our recent xG and opponent's defensive leakiness.
    # NO fixed 2.5*1.10 constant. Range scales with the two inputs, clamped sane.
    base_xg = (our_xg + opp_xga) / 2.0
    xg_lo = _clamp(base_xg * 0.85, 0.9, 2.4)
    xg_hi = _clamp(base_xg * 1.15, 1.2, 3.0)
    add("xg", xg_lo, xg_hi, "Wyscout xG" if wyscout_available else "Estimated xG")

    # xGA — strict for defensive plans, moderate otherwise
    xga_hi = 1.0 if template in ("low_block", "mid_block") else 1.3
    add("xga", 0.0, xga_hi, "Wyscout xGA" if wyscout_available else "Estimated xGA", kind="max")

    # PPDA — template-specific RANGE (not <9 for everyone)
    if template == "high_press":
        add("ppda", 6, 11, "Wyscout PPDA" if wyscout_available else "Estimated PPDA")
    elif template == "possession_control":
        add("ppda", 8, 13, "Wyscout PPDA" if wyscout_available else "Estimated PPDA")
    elif template == "mid_block":
        add("ppda", 11, 18, "PPDA")
    elif template == "transition":
        add("ppda", 14, 25, "PPDA", note="High PPDA acceptable in transition plan")
    elif template == "low_block":
        add("ppda", 18, 30, "PPDA", note="High PPDA expected in low block")

    # Possession — ONLY for control templates
    if template in ("possession_control", "high_press"):
        add("possession", 52, 62, "Wyscout Possession %" if wyscout_available else "Pass Share %")

    # Field tilt — territorial, control templates
    add("field_tilt", 52, 70, "Estimated Field Tilt")

    # Box entries — event-derived, attack templates
    add("box_entries", max(8, our_box * 0.85), max(14, our_box * 1.15), "Box Entries")

    # Transition xGA — for transition/mid-block plans
    add("transition_xga", 0.0, 0.35, "Transition xGA (est.)", kind="max")

    # Set-piece focus
    add("set_piece_shots", 2, 5, "Set-Piece Shots")
    add("set_piece_conceded", 0, 3, "Set-Piece Shots Conceded", kind="max")

    return {"template": template, "rationale": inf["rationale"],
            "targets": targets, "confidence": confidence,
            "wyscout_available": wyscout_available}


def evaluate_targets(plan: dict, actuals: dict, match_context: dict) -> dict:
    """Grade each target vs actual with outcome-aware, score-state logic.
    `actuals` maps metric → value. `match_context` carries goals/xga/etc."""
    won = match_context.get("won", False)
    won_comfortably = match_context.get("goal_diff", 0) >= 2
    xga_actual = match_context.get("xga", actuals.get("xga"))
    big_chances_against = match_context.get("big_chances_against", 0)

    results = []
    for t in plan["targets"]:
        metric = t["metric"]
        actual = actuals.get(metric)
        if actual is None:
            results.append({**t, "actual": None, "status": "Unavailable",
                            "interpretation": "Metric not available for this match."})
            continue

        kind = t.get("kind", "range")
        status = "Partial"
        if kind == "max":
            if actual <= t["high"]:
                status = "Hit"
            elif actual <= t["high"] * 1.3:
                status = "Partial"
            else:
                status = "Missed"
        else:  # range
            if t["low"] <= actual <= t["high"]:
                status = "Hit"
            elif actual > t["high"]:
                status = "Hit" if metric in ("xg", "box_entries", "field_tilt", "possession") else "Partial"
            elif actual >= t["low"] * 0.8:
                status = "Partial"
            else:
                status = "Missed"

        interp = t.get("note", "")

        # ── Outcome-aware reclassification ──
        # When a team wins comfortably (>=2), control-style targets they did NOT
        # meet (possession, field tilt, low PPDA) are Strategically Acceptable:
        # they achieved the result through a different (transition/game-state)
        # model rather than failing the plan.
        control_metrics = ("possession", "field_tilt", "ppda")
        if metric == "ppda" and status in ("Missed", "Partial") and won and (xga_actual or 0) < 2.5 and big_chances_against <= 3:
            status = "Strategically Acceptable"
            interp = "Higher PPDA after managing the scoreline; opponent created little of real danger."
        elif metric in control_metrics and status in ("Missed", "Partial") and won_comfortably:
            status = "Strategically Acceptable"
            interp = "Below the control-plan range, but strategically fine — the win came via an efficient/transition route."
        if metric == "xg" and status == "Missed" and won_comfortably:
            status = "Partial"
            interp = "Chance volume below range, but finishing and result were strong."
        # xGA missed but won comfortably = honest signal, keep as Partial not Missed
        if metric == "xga" and status == "Missed" and won_comfortably and (xga_actual or 0) < 2.5:
            status = "Partial"
            interp = "Conceded above target chance quality, but defended the result and won comfortably."

        if t.get("confidence") == "Low" and status not in ("Unavailable", "Not Applicable"):
            status = "Low Confidence"

        results.append({**t, "actual": round(actual, 2) if isinstance(actual, (int, float)) else actual,
                        "status": status, "interpretation": interp})
    return {"results": results, **_score(results)}


def _score(results) -> dict:
    num = den = 0.0
    counts = {}
    for r in results:
        st = r["status"]
        counts[st] = counts.get(st, 0) + 1
        sc = _STATUS_SCORE.get(st)
        if sc is None:
            continue
        w = r.get("weight", 1.0)
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
    return {"score": score, "label": label, "counts": counts}
