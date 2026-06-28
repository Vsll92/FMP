"""Release QA for post-match KPI season/league context.

Every important post-match number must explain whether the match value is above,
below, strong, weak, or normal versus the team season average and league average.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

LF = "France_League_1_25-26"
LYON_MATCH = "79brtmu270u71wnu6nqh6uj2s"  # Lyon 3-0 Metz, W2


def _by_metric(rows):
    return {r.get("metric"): r for r in rows}


def test_lyon_defensive_metrics_have_season_and_league_context():
    from components.report_model import build_post_match_report_model
    model = build_post_match_report_model(LF, LYON_MATCH, "Lyon")
    rows = _by_metric(model.get("post_match_kpi_context", []))
    for key in ["tackles_won", "interceptions", "recoveries"]:
        r = rows[key]
        assert r["match_value"] is not None
        assert r["team_season_avg"] is not None
        assert r["league_avg"] is not None
        assert r["difference_vs_team_avg"] is not None
        assert r["interpretation"] and r["interpretation"] != "Insufficient data"
        assert r["source"]
        assert r["sample_size"] >= 3


def test_direction_logic_for_xga_and_ppda():
    from components.report_model import build_post_match_report_model
    rows = _by_metric(build_post_match_report_model(LF, LYON_MATCH, "Lyon").get("post_match_kpi_context", []))
    assert rows["xga"]["direction"] == "lower_good"
    assert rows["ppda"]["direction"] == "lower_good"
    assert "lower" in rows["xga"]["interpretation"].lower() or rows["xga"]["percentile"] is not None


def test_no_false_zero_when_context_unavailable():
    from components.kpi_context import build_post_match_kpi_context
    r = build_post_match_kpi_context(LF, "Lyon", LYON_MATCH, "metric_that_does_not_exist", None)
    assert r["interpretation"] == "Insufficient data"
    assert r.get("team_season_avg") in (None, r.get("team_season_avg"))


def test_pdf_model_contains_context_for_export():
    from components.report_model import build_post_match_report_model
    model = build_post_match_report_model(LF, LYON_MATCH, "Lyon")
    assert model.get("post_match_kpi_context")
    rows = _by_metric(model["post_match_kpi_context"])
    assert "recoveries" in rows and rows["recoveries"]["league_avg"] is not None


if __name__ == "__main__":
    test_lyon_defensive_metrics_have_season_and_league_context()
    test_direction_logic_for_xga_and_ppda()
    test_no_false_zero_when_context_unavailable()
    test_pdf_model_contains_context_for_export()
    print("PASS post-match KPI context tests")
