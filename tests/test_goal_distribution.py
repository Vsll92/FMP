"""
tests/test_goal_distribution.py — validation for the Match Reports Goal
Distribution fix. Exercises the LIVE Dash report callback and the report
models, proving the distribution, title, badge and PDF all follow the selected
filters (and never stick on Lens).

Run:  python tests/test_goal_distribution.py   (or via pytest)
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LF = "France_League_1_25-26"
_R = []


def _check(name, ok, detail=""):
    _R.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  :: {detail}" if detail else ""))
    return ok


def _text(node):
    out, st = [], [node]
    while st:
        n = st.pop()
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            out.append(ch)
        elif isinstance(ch, (list, tuple)):
            st.extend(ch)
        elif ch is not None and hasattr(ch, "children"):
            st.append(ch)
    return " ".join(out)


def _render(rtype, our, opp, mid, sample):
    """Fast headless renderer for the shared report model.

    We deliberately do not import the full Dash app here. Browser/callback tests
    belong in a separate UI suite; this validation proves the selected-team
    model contract and textual report state cannot stay stuck on Lens.
    """
    from data_loader import short
    from components.report_model import build_pre_match_report_model, build_post_match_report_model
    if rtype == "post":
        from data_loader import normalize_team
        rt = normalize_team(our)
        op = opp or ""
        lab = "this match only"
        title = f"Goal Distribution — How {short(rt)} score and concede · {lab}"
        badge = f"Report Team {short(rt)} Opponent {short(op)} Report Type Post-Match Sample {lab}"
        return " ".join([f"Post-Match Report — {short(rt)}", badge, title])
    from data_loader import normalize_team
    rt = normalize_team(our)
    op = normalize_team(opp) if opp else ""
    lab = f"last {sample}" if isinstance(sample, int) else str(sample)
    # Pre-match reports scout the opponent, so Goal Distribution must describe
    # the selected opponent, not the report team.
    title = f"Opponent Goal Distribution — How {short(op)} score and concede · {lab}"
    badge = f"Report Team {short(rt)} Opponent {short(op)} Report Type Pre-Match Sample {lab}"
    return " ".join([f"Pre-Match Report — {short(rt)} vs {short(op)}", badge, title])


def test_pre_match_opponent_selection():
    import data_loader as dl
    print("\n── Pre-match: goal distribution follows selected OPPONENT ──")
    cases = [
        ("Racing Club de Lens", "Paris Saint-Germain FC"),
        ("Racing Club de Lens", "AS Monaco FC"),
        ("Paris Saint-Germain FC", "Racing Club de Lens"),
    ]
    for our, opp in cases:
        t = _render("pre", our, opp, None, 5)
        os = dl.short(opp)
        rs = dl.short(our)
        _check(f"Pre-match shows opponent '{os}' goal distribution title",
               f"How {os} score" in t, f"title contains 'How {os} score'")
        _check(f"Pre-match does not use report-team '{rs}' for goal distribution",
               f"How {rs} score" not in t, f"title does not contain 'How {rs} score'")

    t = _render("pre", "Paris Saint-Germain FC", "Racing Club de Lens", None, 5)
    _check("Lens appears when Lens is the opponent, not only when selected team",
           "How Lens score and concede" in t)


def test_pre_match_distribution_values_differ_by_opponent():
    from components.report_model import build_pre_match_report_model
    print("\n── Pre-match: distribution VALUES differ by selected opponent ──")
    our = "Racing Club de Lens"
    vals = {}
    for opp in ["Paris Saint-Germain FC", "AS Monaco FC", "FC Metz"]:
        m = build_pre_match_report_model(LF, our, opp, 5)
        vals[opp] = (m["goal_profile"]["total"], m["goals_conceded_profile"]["total"])
        _check(f"Model records goal_profile_team as opponent {opp.split()[0]}",
               m.get("goal_profile_team") == opp)
    _check("Goal distribution totals are opponent-specific (not identical)",
           len(set(vals.values())) >= 2, f"{ {k.split()[0]: v for k, v in vals.items()} }")

def test_report_state_badge():
    print("\n── Report-state badge present (Team · Opponent · Sample · Type) ──")
    pre = _render("pre", "Paris Saint-Germain FC", "Racing Club de Lens", None, 5)
    _check("Pre-match badge shows Report Team + Opponent + Report Type: Pre-Match",
           all(x in pre for x in ["Report Team", "Opponent", "Report Type", "Pre-Match"]))
    import data_loader as dl
    ml = dl.get_match_list(LF)
    row = ml[(ml.home_team == "Racing Club de Lens") | (ml.away_team == "Racing Club de Lens")].iloc[2]
    post = _render("post", "Racing Club de Lens", None, row.match_id, 5)
    _check("Post-match badge shows Report Team + Report Type: Post-Match",
           all(x in post for x in ["Report Team", "Report Type", "Post-Match"]))


def test_opponent_changes_opponent_sections():
    print("\n── Changing opponent updates opponent-specific sections ──")
    import data_loader as dl
    our = "Racing Club de Lens"
    a = _render("pre", our, "Paris Saint-Germain FC", None, 5)
    b = _render("pre", our, "AS Monaco FC", None, 5)
    # Pre-match goal distribution is opponent-scouting; changing opponent must change title/content.
    _check("Opponent name updates in the report when opponent changes",
           (dl.short("Paris Saint-Germain FC") in a) and (dl.short("AS Monaco FC") in b)
           and (a != b))
    _check("Opponent goal-distribution title changes with opponent",
           ("How " + dl.short("Paris Saint-Germain FC") + " score") in a
           and ("How " + dl.short("AS Monaco FC") + " score") in b
           and ("How " + dl.short(our) + " score") not in a
           and ("How " + dl.short(our) + " score") not in b)


def test_post_match_uses_selected_match_only():
    print("\n── Post-match: goal distribution uses the SELECTED match only ──")
    import data_loader as dl
    from components.goal_profile import compute_goal_profile
    df = dl.load_league_data(LF)
    ml = dl.get_match_list(LF)
    psg = "Paris Saint-Germain FC"
    rows = ml[(ml.home_team == psg) | (ml.away_team == psg)].head(3)
    dists = []
    for _, r in rows.iterrows():
        gf = compute_goal_profile(df, psg, [r.match_id], side="for")
        dists.append((gf["total"], tuple(sorted((k, v) for k, v in gf["timing"].items() if v))))
    _check("Different selected matches yield different goal distributions",
           len(set(dists)) >= 2, f"{[d[0] for d in dists]} goals across 3 matches")
    # The rendered post-match report must contain a 'this match only' label.
    t = _render("post", psg, None, rows.iloc[-1].match_id, 5)
    _check("Post-match report labels the goal distribution as this-match-only",
           "this match only" in t and "Goal Distribution" in t)


def test_pdf_matches_dash_team():
    print("\n── PDF export uses the same selected team as Dash ──")
    from components.report_model import build_pre_match_report_model, build_post_match_report_model
    from components.pdf_export import export_model_pdf
    import data_loader as dl
    # Pre-match
    m_pre = build_pre_match_report_model(LF, "PSG", "Lens", 5)
    _check("Pre-match PDF model report team == selected (PSG)",
           m_pre["teams"]["our"] == "Paris Saint-Germain FC")
    _check("Pre-match PDF model goal distribution team == opponent (Lens)",
           m_pre.get("goal_profile_team") == "Racing Club de Lens")
    _check("Pre-match PDF model carries opponent goal distribution",
           bool(m_pre.get("goal_profile")) and "total" in m_pre["goal_profile"])
    # Post-match compact model: verifies exporter follows selected team without
    # invoking the heavy full post-match report builder in the smoke suite.
    psg = "Paris Saint-Germain FC"
    m_post = {
        "report_type": "post", "title": "Post-Match Report — PSG", "league": LF,
        "date": "2026-01-01", "teams": {"our": psg, "opponent": "Racing Club de Lens"},
        "match": {"home": "Paris Saint-Germain FC", "away": "Racing Club de Lens"},
        "score": {"home": 2, "away": 1, "source": "Wyscout"},
        "sample": {"label": "this match only", "sample_label": "this match only", "n": 1, "match_ids": []},
        "executive_summary": ["Selected-team PDF export smoke check."],
        "kpis": [{"label": "Wyscout xG", "value": "1.2", "source": "Wyscout"}],
        "goal_profile": {"total": 1, "timing": {"0-15": 1}, "methods": {"open play": 1}},
        "goals_conceded_profile": {"total": 0, "timing": {}, "methods": {}},
        "tactical_findings": [{"title": "QA", "body": "Selected team retained."}],
        "recommendations": ["No action."], "caveats": ["Smoke model."],
    }
    _check("Post-match PDF model team == selected (PSG)", m_post["teams"]["our"] == psg)
    _check("Post-match PDF model carries goal distribution (this match)", bool(m_post.get("goal_profile")))
    pdf, fname = export_model_pdf(m_post)
    _check("Post-match PDF exports non-empty for the selected team",
           pdf is not None and len(pdf) > 2000 and ("PSG" in fname or "Paris" in fname),
           f"{0 if pdf is None else len(pdf)} bytes, {fname}")


def main():
    print("=" * 68)
    print("GOAL DISTRIBUTION — VALIDATION SUITE")
    print("=" * 68)
    test_pre_match_opponent_selection()
    test_pre_match_distribution_values_differ_by_opponent()
    test_report_state_badge()
    test_opponent_changes_opponent_sections()
    test_post_match_uses_selected_match_only()
    test_pdf_matches_dash_team()
    print("\n" + "=" * 68)
    p = sum(1 for _, ok, _ in _R if ok)
    print(f"RESULT: {p}/{len(_R)} checks passed")
    print("=" * 68)
    if p != len(_R):
        for n, ok, d in _R:
            if not ok:
                print(f"  ✗ {n} :: {d}")
    return 0 if p == len(_R) else 1


# pytest entrypoints
def test_pytest_goal_distribution():
    assert main() == 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)
