"""
components/map_insights.py — multi-part tactical insights for Pitch Maps (Dash-free).

Each insight returns a structured dict:
  {"primary", "secondary", "risk", "coaching", "evidence"}
so the UI can render a detailed, data-backed read for a coach rather than a
one-line label. All numbers come from the central zone model so they match the
plotted points.
"""
import pandas as pd
from components.zone_model import zone_breakdown, third_of, lane_of, is_in_box


def _pct(n, d):
    return round(n / d * 100) if d else 0


def _team_events(df, team):
    return df[df["team_name"] == team] if team else df


def touch_map_insight(df, team):
    """Where the team spends events; build-up side; territory depth; final-third access."""
    tdf = _team_events(df, team)
    br = zone_breakdown(tdf)
    total = br["total"]
    if total == 0:
        return _empty("No touches in the current filter.")
    th, ln = br["thirds"], br["lanes"]
    def_p, mid_p, att_p = _pct(th["def"], total), _pct(th["mid"], total), _pct(th["att"], total)
    left = ln["Wide Left"] + ln["Left Half-Space"]
    right = ln["Wide Right"] + ln["Right Half-Space"]
    central = ln["Central"]
    side = "left" if left > right * 1.15 else ("right" if right > left * 1.15 else "balanced")
    side_pct = _pct(max(left, right), total)

    primary = f"{att_p}% of touches in the attacking third, {mid_p}% middle, {def_p}% defensive."
    secondary = (f"Build-up tilts {side}" + (f" ({side_pct}% of touches down that flank)" if side != "balanced" else "")
                 + f"; central lane holds {_pct(central, total)}%.")
    if att_p < 22:
        risk = "Limited attacking-third presence — the team struggles to sustain territory high up."
        coaching = "Work on progression patterns to reach the final third more often (third-man runs, switches into the box)."
    elif def_p > 45:
        risk = "Heavily camped in own half — inviting pressure and long transitions."
        coaching = "Raise the defensive line and build with shorter, higher first passes to avoid deep camps."
    else:
        risk = "Territory balanced; main risk is predictability if one flank dominates."
        coaching = ("Vary the entry side — overload the strong flank then switch to the weak side to unbalance the block."
                    if side != "balanced" else "Maintain balance; add half-space rotations for penetration.")
    evidence = f"{total} touches plotted · Def/Mid/Att {th['def']}/{th['mid']}/{th['att']} · L/C/R {left}/{central}/{right}"
    return {"primary": primary, "secondary": secondary, "risk": risk, "coaching": coaching, "evidence": evidence}


def reception_insight(df, team):
    """Which lanes receive passes; half-space usage; wide/central balance → chance creation link."""
    tdf = _team_events(df, team)
    passes = tdf[tdf["event"] == "Pass"]
    rec = passes.dropna(subset=["Pass End X", "Pass End Y"])
    if rec.empty:
        return _empty("No completed receptions in the current filter.")
    total = len(rec)
    lanes = {name: 0 for name in ("Wide Left", "Left Half-Space", "Central", "Right Half-Space", "Wide Right")}
    box = 0
    for _, r in rec.iterrows():
        ln = lane_of(r["Pass End Y"])
        if ln in lanes:
            lanes[ln] += 1
        if is_in_box(r["Pass End X"], r["Pass End Y"]):
            box += 1
    hs = lanes["Left Half-Space"] + lanes["Right Half-Space"]
    wide = lanes["Wide Left"] + lanes["Wide Right"]
    central = lanes["Central"]

    primary = f"Receptions: {_pct(central, total)}% central, {_pct(hs, total)}% half-spaces, {_pct(wide, total)}% wide."
    secondary = f"{_pct(box, total)}% of receptions land inside the box ({box} of {total})."
    if _pct(hs, total) < 18:
        risk = "Half-spaces under-used — the most dangerous creative channels are being bypassed."
        coaching = "Train pockets of receipt between the lines; reward half-space receptions before crossing."
    elif _pct(wide, total) > 55:
        risk = "Very wide-dependent — easy to defend with a compact block and full-backs tucked in."
        coaching = "Add cut-backs and half-space combinations so wide play has a central finish option."
    else:
        risk = "Balanced reception map; risk is low if box entries stay healthy."
        coaching = "Keep feeding half-spaces; time third-man runs to convert receptions into box entries."
    evidence = f"{total} receptions · WL/LHS/C/RHS/WR {lanes['Wide Left']}/{lanes['Left Half-Space']}/{central}/{lanes['Right Half-Space']}/{lanes['Wide Right']} · box {box}"
    return {"primary": primary, "secondary": secondary, "risk": risk, "coaching": coaching, "evidence": evidence}


def pass_origin_insight(df, team):
    """Build-up side; directness; progression sources; failed-pass zones."""
    tdf = _team_events(df, team)
    passes = tdf[tdf["event"] == "Pass"]
    if passes.empty:
        return _empty("No passes in the current filter.")
    total = len(passes)
    comp = passes[passes["outcome"] == 1] if "outcome" in passes.columns else passes
    acc = _pct(len(comp), total)
    br = zone_breakdown(passes)
    th = br["thirds"]
    # Directness: forward share among completed
    pe = comp.dropna(subset=["Pass End X"])
    fwd = int((pd.to_numeric(pe["Pass End X"], errors="coerce") > pd.to_numeric(pe["x"], errors="coerce") + 5).sum()) if not pe.empty else 0
    fwd_pct = _pct(fwd, len(pe)) if len(pe) else 0
    # Failed passes by third
    failed = passes[passes["outcome"] == 0] if "outcome" in passes.columns else passes.iloc[0:0]
    fbr = zone_breakdown(failed) if not failed.empty else {"thirds": {"def": 0, "mid": 0, "att": 0}, "total": 0}

    primary = f"{total} passes at {acc}% completion; origins Def/Mid/Att {th['def']}/{th['mid']}/{th['att']}."
    secondary = f"{fwd_pct}% of completed passes go forward — {'direct, vertical' if fwd_pct >= 45 else 'patient, possession-based'} build-up."
    if fbr["total"] and _pct(fbr["thirds"]["def"], fbr["total"]) > 35:
        risk = "Many losses in the defensive third — risky build-up under pressure."
        coaching = "Add a spare man in the first line; use the goalkeeper to beat the first press."
    elif fwd_pct < 30:
        risk = "Low forward share — possession may be sterile without penetration."
        coaching = "Encourage line-breaking passes and forward runs to raise progression."
    else:
        risk = "Build-up risk is moderate; watch turnovers when forcing forward passes."
        coaching = "Keep the vertical intent but secure rest-defence behind the ball."
    evidence = f"{total} passes · {acc}% complete · forward {fwd_pct}% · failed by third D/M/A {fbr['thirds']['def']}/{fbr['thirds']['mid']}/{fbr['thirds']['att']}"
    return {"primary": primary, "secondary": secondary, "risk": risk, "coaching": coaching, "evidence": evidence}


def defensive_insight(df, team):
    """Press height; recovery zones; block height; exposed zones."""
    tdf = _team_events(df, team)
    actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery", "Clearance"])]
    if actions.empty:
        return _empty("No defensive actions in the current filter.")
    total = len(actions)
    br = zone_breakdown(actions)
    th = br["thirds"]
    mean_x = pd.to_numeric(actions["x"], errors="coerce").mean()
    high = _pct(th["att"] + th["mid"], total)
    if mean_x >= 55:
        block = "high block / aggressive press"
    elif mean_x >= 42:
        block = "mid block"
    else:
        block = "low block"

    primary = f"Defensive actions average x={mean_x:.0f} → {block}."
    secondary = f"{high}% of regains happen in the middle/attacking thirds ({th['att']} att, {th['mid']} mid, {th['def']} def)."
    if mean_x < 40:
        risk = "Deep defending — concedes territory and invites sustained pressure."
        coaching = "Push the line up after regains; press the first pass to prevent deep camps."
    elif mean_x > 58:
        risk = "Very high line — exposed to balls in behind and quick transitions."
        coaching = "Coordinate the offside line and cover runs in behind; protect the space for the keeper to sweep."
    else:
        risk = "Block height balanced; main exposure is the flank with fewer regains."
        coaching = "Set clear press triggers; funnel play to the side with stronger recovery numbers."
    evidence = f"{total} defensive actions · mean x={mean_x:.1f} · Def/Mid/Att {th['def']}/{th['mid']}/{th['att']}"
    return {"primary": primary, "secondary": secondary, "risk": risk, "coaching": coaching, "evidence": evidence}


def _empty(msg):
    return {"primary": msg, "secondary": "", "risk": "", "coaching": "", "evidence": ""}


# Map layer id → insight function
INSIGHT_FOR_LAYER = {
    "touch": touch_map_insight,
    "recept": reception_insight,
    "passorg": pass_origin_insight,
    "defheat": defensive_insight,
}
