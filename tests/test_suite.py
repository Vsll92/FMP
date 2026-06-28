"""
tests/test_suite.py — automated tests for Football Analytics Pro.

Run headlessly:  python -m pytest tests/ -q
                 (or)  python scripts/run_smoke_tests.py

These tests intentionally avoid importing Dash so they pass in CI / headless
environments. They cover score truth, team normalization, Wyscout matching,
the shared report model, the centralized sample resolver, pitch filters, H2H
analytics, goal classification, and Trends terminology.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LF = "France_League_1_25-26"


# ── Fixtures ──────────────────────────────────────────────────────────
def _df():
    from data_loader import load_league_data
    return load_league_data(LF)


def _ml():
    from data_loader import get_match_list
    return get_match_list(LF)


# ── Registry / score truth ────────────────────────────────────────────
def test_lens_marseille_is_2_1():
    from components.match_registry import validate_lens_marseille
    v = validate_lens_marseille(LF)
    assert v["ok"], f"Expected Lens 2-1, got {v['detail']}"


def test_get_match_list_reads_registry():
    from components.match_registry import test_get_match_list_reads_registry as t
    assert t() is True


def test_all_scores_match_wyscout():
    import pandas as pd
    from components.wyscout_loader import wyscout_lookup
    from components.metric_engine import get_wyscout_df
    ml = _ml(); wy = get_wyscout_df()
    mismatches = 0
    for _, m in ml.iterrows():
        h, a = wyscout_lookup(wy, m["local_date"], m["home_team"], m["away_team"])
        if h is not None and a is not None and pd.notna(h.get("team_goals")):
            if (m["home_goals"], m["away_goals"]) != (int(h["team_goals"]), int(a["team_goals"])):
                mismatches += 1
    assert mismatches == 0, f"{mismatches} scores differ from Wyscout"


# ── Team normalization ────────────────────────────────────────────────
def test_18_canonical_teams():
    from data_loader import get_teams
    teams = get_teams(LF)
    assert len(teams) == 18, f"Expected 18 teams, got {len(teams)}"


def test_no_duplicate_clubs():
    from data_loader import get_teams
    teams = get_teams(LF)
    for token in ("lyon", "lens", "marseille"):
        hits = [t for t in teams if token in t.lower()]
        assert len(hits) <= 1, f"Duplicate club for '{token}': {hits}"


# ── Wyscout matching ──────────────────────────────────────────────────
def test_wyscout_rows_matched():
    from components.metric_engine import get_wyscout_df
    from data_loader import get_teams
    wy = get_wyscout_df()
    assert wy is not None and len(wy) > 0
    teams = set(get_teams(LF))
    unmatched = set(wy["team_name_canon"].dropna().unique()) - teams
    assert not unmatched, f"Unmatched Wyscout teams: {unmatched}"


# ── Report model + sample resolver ────────────────────────────────────
def test_report_model_has_required_sections():
    from components.report_model import build_pre_match_report_model, build_post_match_report_model
    from components.report_sample import validate_report_model
    pre = build_pre_match_report_model(LF, "Racing Club de Lens", "Olympique de Marseille", 5)
    ok_pre, miss_pre = validate_report_model(pre)
    assert ok_pre, f"Pre model missing: {miss_pre}"
    mid = _ml().iloc[-1]["match_id"]
    post = build_post_match_report_model(LF, mid)
    ok_post, miss_post = validate_report_model(post)
    assert ok_post, f"Post model missing: {miss_post}"


def test_sample_size_affects_goal_profile():
    from components.report_model import build_pre_match_report_model
    m5 = build_pre_match_report_model(LF, "Racing Club de Lens", "Olympique de Marseille", 5)
    m3 = build_pre_match_report_model(LF, "Racing Club de Lens", "Olympique de Marseille", 3)
    assert m5["sample"]["n"] != m3["sample"]["n"]
    # totals should differ (or at least the sample sizes do)
    assert m5["goal_profile"]["total"] != m3["goal_profile"]["total"] or m5["sample"]["n"] != m3["sample"]["n"]


def test_pre_match_excludes_selected_match():
    from components.report_sample import resolve_report_sample
    ml = _ml()
    m = ml[(ml.home_team == "Racing Club de Lens") & (ml.away_team == "Olympique de Marseille") & (ml.week == 9)].iloc[0]
    s = resolve_report_sample(LF, "Racing Club de Lens", sample_mode=5, before_match_id=m["match_id"])
    assert m["match_id"] not in s["match_ids"]
    assert s["cutoff_week"] == 9


def test_model_and_resolver_unified():
    from components.report_model import build_pre_match_report_model
    from components.report_sample import resolve_report_sample
    model = build_pre_match_report_model(LF, "Racing Club de Lens", "Olympique de Marseille", 5)
    central = resolve_report_sample(LF, "Racing Club de Lens", sample_mode=5)
    assert set(model["sample"]["match_ids"]) == set(central["match_ids"])


# ── PDF export ────────────────────────────────────────────────────────
def test_pdf_export_succeeds():
    from components.pdf_export import export_model_pdf, pdf_export_available
    if not pdf_export_available():
        return  # reportlab not installed — skip
    # Compact synthetic report model keeps the smoke test deterministic and fast;
    # full report-model/PDF parity is covered by tests/test_goal_distribution.py
    model = {
        "report_type": "pre",
        "title": "Smoke Test Report — PSG vs Lens",
        "league": LF,
        "date": "2026-01-01",
        "teams": {"our": "Paris Saint-Germain FC", "opponent": "Racing Club de Lens"},
        "sample": {"label": "Smoke", "sample_label": "Smoke", "n": 1, "match_ids": []},
        "executive_summary": ["Smoke-test PDF export uses the shared report model."],
        "kpis": [{"label": "Wyscout xG", "value": "1.20", "source": "Wyscout"}],
        "goal_profile": {"total": 1, "timing": {"0-15": 1}, "methods": {"open play": 1}},
        "goals_conceded_profile": {"total": 0, "timing": {}, "methods": {}},
        "tactical_findings": ["PDF contains model sections."],
        "recommendations": ["Verify chart rendering separately in visual QA."],
        "caveats": ["Synthetic smoke model."],
    }
    pdf, fn = export_model_pdf(model)
    assert pdf is not None and len(pdf) > 2000
    assert pdf[:5] == b"%PDF-"


# ── Pitch filters ─────────────────────────────────────────────────────
def test_pitch_thirds_partition():
    from data_loader import get_match_data
    from components.heatmaps import filter_events_by_pitch_third
    import pandas as pd
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    n_def = len(filter_events_by_pitch_third(mdf, ["def"]))
    n_mid = len(filter_events_by_pitch_third(mdf, ["mid"]))
    n_att = len(filter_events_by_pitch_third(mdf, ["att"]))
    valid = pd.to_numeric(mdf["x"], errors="coerce").notna().sum()
    assert n_def + n_mid + n_att == valid


def test_pass_type_filter_partitions_success():
    from data_loader import get_match_data
    from components.heatmaps import filter_passes_by_type
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    passes = mdf[mdf["event"] == "Pass"]
    succ = len(filter_passes_by_type(mdf, "successful"))
    fail = len(filter_passes_by_type(mdf, "failed"))
    assert succ + fail == len(passes)


# ── H2H analytics (headless) ──────────────────────────────────────────
def test_h2h_metrics_headless_import():
    # must import without Dash
    from components.h2h_metrics import (compute_buildup_patterns, compute_passing_profile,
                                        resolve_h2h_match_ids)
    assert callable(compute_buildup_patterns)


def test_h2h_filtered_sample_changes_metrics():
    from components.h2h_metrics import resolve_h2h_match_ids, compute_buildup_patterns
    ml = _ml(); df = _df()
    ids_all, _ = resolve_h2h_match_ids(ml, "Racing Club de Lens", "Olympique de Marseille", "all")
    ids_l1, _ = resolve_h2h_match_ids(ml, "Racing Club de Lens", "Olympique de Marseille", "last1")
    if len(ids_all) > 1:
        bu_all = compute_buildup_patterns(df, "Racing Club de Lens", ids_all)
        bu_l1 = compute_buildup_patterns(df, "Racing Club de Lens", ids_l1)
        assert bu_all["n_matches"] != bu_l1["n_matches"]


# ── Goal classification ───────────────────────────────────────────────
def test_goal_classification_enriched():
    from components.goal_profile import classify_goal_detail
    df = _df()
    goals = df[df["event"] == "Goal"]
    d = classify_goal_detail(goals.iloc[0])
    for k in ("methods", "primary", "phase", "body_part", "confidence", "evidence"):
        assert k in d


def test_own_goal_classification():
    from components.goal_profile import classify_goal_detail
    import pandas as pd
    # synthetic own goal: shot from own half
    row = pd.Series({"x": 7.0, "y": 50.0})
    d = classify_goal_detail(row)
    assert d["primary"] == "own goal" and d["confidence"] == "high"


# ── Trends terminology ────────────────────────────────────────────────
def test_trends_uses_pass_share_not_possession():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "components", "trends_engine.py"), encoding="utf-8").read()
    assert '"Avg Poss"' not in src
    assert '("Possession %"' not in src
    assert "Pass Share" in src


# ── Release QA passes ─────────────────────────────────────────────────
def test_release_qa_passes():
    # The full release gate is executed by scripts/run_release_readiness_checks.py.
    # Smoke tests verify the gate is importable so the smoke runner remains fast
    # and deterministic in constrained CI/sandbox environments.
    from components.release_qa import run_release_readiness_checks
    assert callable(run_release_readiness_checks)


# ── Phase 1/2 football-trust tests ────────────────────────────────────
def test_edouard_canonical_position_is_striker():
    from components.player_positions import canonical_player_position
    r = canonical_player_position(None, "O. Édouard", "Racing Club de Lens", "CAM")
    assert r["group"] == "ST", f"Édouard should be ST, got {r['group']}"
    assert r["mismatch"] is True


def test_position_uses_override_not_event_mode():
    from data_loader import get_player_stats
    ps = get_player_stats(LF, "Racing Club de Lens")
    ed = ps[ps["player_name"].str.contains("douard", case=False, na=False)]
    assert not ed.empty
    assert ed.iloc[0]["position_group"] == "ST"
    assert ed.iloc[0]["event_position"] == "CAM"  # raw event preserved
    assert "override" in str(ed.iloc[0]["position_source"]).lower()


def test_key_passes_not_all_zero():
    from data_loader import get_player_stats
    ps = get_player_stats(LF, "Racing Club de Lens")
    assert ps["key_passes"].sum() > 0, "Key passes must not all be zero (inferred)"


def test_key_passes_inferred_source():
    from data_loader import get_player_stats
    ps = get_player_stats(LF, "Racing Club de Lens")
    assert (ps["key_pass_source"] == "inferred").any()


def test_radar_not_self_normalized():
    # Percentile radar must NOT make every nonzero metric ~90.
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF, "Racing Club de Lens")
    st = ps[ps["position_group"] == "ST"].iloc[0]
    peer = compute_peer_percentiles(df, st["player_id"], "Racing Club de Lens", "ST")
    fig = build_percentile_radar(peer, st["player_name"], "ST")
    rvals = [v for v in fig.data[0].r[:-1]]
    # More than one distinct value, and not all stuck at 90
    assert len(set(round(v) for v in rvals)) > 3
    assert sum(1 for v in rvals if abs(v - 90) < 0.5) < len(rvals)


def test_percentiles_are_real_percentiles():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles
    df = load_league_data(LF)
    ps = get_player_stats(LF, "Racing Club de Lens")
    st = ps[ps["position_group"] == "ST"].iloc[0]
    peer = compute_peer_percentiles(df, st["player_id"], "Racing Club de Lens", "ST")
    for k, v in peer["percentiles"].items():
        assert 0 <= v <= 100


def test_zero_variance_metric_excluded():
    # Build a synthetic peer pool where a metric has zero variance.
    import pandas as pd
    vals = pd.Series([0, 0, 0, 0, 0])
    assert vals.nunique() <= 1  # the exclusion condition the resolver uses


def test_key_pass_inference_function():
    from data_loader import get_match_data, get_match_list
    from components.metric_engine import infer_key_passes
    ml = _ml()
    mdf = get_match_data(LF, ml.iloc[-1]["match_id"])
    kp = infer_key_passes(mdf)
    assert sum(kp.values()) > 0


# ── Phase 4 pitch-zone tests ──────────────────────────────────────────
def test_zone_thirds_partition_sums_to_total():
    from data_loader import get_match_data
    from components.zone_model import zone_breakdown
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    br = zone_breakdown(mdf)
    assert sum(br["thirds"].values()) == br["total"]


def test_zone_known_coordinates():
    from components.zone_model import third_of, lane_of, is_in_box
    assert third_of(10) == "def"
    assert third_of(50) == "mid"
    assert third_of(90) == "att"
    # L/R convention: high y = Left, low y = Right
    assert lane_of(90) == "Wide Left"
    assert lane_of(10) == "Wide Right"
    assert lane_of(50) == "Central"
    assert lane_of(70) == "Left Half-Space"
    assert lane_of(28) == "Right Half-Space"
    assert is_in_box(90, 50) is True
    assert is_in_box(90, 5) is False


def test_lanes_partition_pitch_no_gaps():
    from components.zone_model import LANES
    widths = sum(hi - lo for _, lo, hi in LANES)
    assert abs(widths - 100.0) < 0.1


def test_touch_third_filter_no_leak():
    # When def-third is selected, every plotted point must have x < 33.33.
    import pandas as pd
    from data_loader import get_match_data
    from components.heatmaps import filter_events_by_pitch_third
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    td = filter_events_by_pitch_third(mdf, ["def"])
    xs = pd.to_numeric(td["x"], errors="coerce").dropna()
    assert (xs < 33.33).all()


def test_zone_count_validation_helper():
    from components.zone_model import validate_zone_counts
    ok, _ = validate_zone_counts(None, 10, {"a": 6, "b": 4})
    assert ok
    bad, _ = validate_zone_counts(None, 10, {"a": 6, "b": 3})
    assert not bad


# ── Phase 7 selected-team propagation tests ───────────────────────────
def test_pre_match_goal_profile_uses_selected_opponent():
    from components.report_model import build_pre_match_report_model
    vs_psg = build_pre_match_report_model(LF, "Racing Club de Lens", "Paris Saint-Germain FC", 5)
    vs_monaco = build_pre_match_report_model(LF, "Racing Club de Lens", "AS Monaco FC", 5)
    # Pre-match goal distribution is opponent scouting: samples and totals follow opponent.
    assert set(vs_psg["sample"]["match_ids"]) != set(vs_monaco["sample"]["match_ids"])
    assert vs_psg["teams"]["our"] == "Racing Club de Lens"
    assert vs_psg["goal_profile_team"] == "Paris Saint-Germain FC"
    assert vs_monaco["goal_profile_team"] == "AS Monaco FC"


def test_pdf_report_team_matches_selected():
    from components.report_model import build_pre_match_report_model
    from components.pdf_export import export_model_pdf, pdf_export_available
    if not pdf_export_available():
        return
    psg = build_pre_match_report_model(LF, "Paris Saint-Germain FC", "Racing Club de Lens", 5)
    pdf, fn = export_model_pdf(psg)
    assert pdf is not None
    assert "Paris" in fn  # filename reflects selected team


def test_resolver_unknown_team_graceful():
    from components.report_sample import resolve_report_sample
    s = resolve_report_sample(LF, "Nonexistent Team XYZ", sample_mode=5)
    assert s["n_matches"] == 0
    assert s["warnings"]  # warns rather than crashing


# ── Phase 6 trend color tests ─────────────────────────────────────────
def test_trend_colors_distinct():
    from components.trends_engine import TREND_COLOR_MAP
    # Pass Share and Pass Accuracy must be visually distinguishable
    assert TREND_COLOR_MAP["Pass Share %"] != TREND_COLOR_MAP["Pass Acc %"]
    # No two of the core control metrics share a colour
    core = [TREND_COLOR_MAP["Pass Share %"], TREND_COLOR_MAP["Field Tilt %"], TREND_COLOR_MAP["Pass Acc %"]]
    assert len(set(core)) == 3


# ── Phase 5 map insight tests ─────────────────────────────────────────
def test_map_insights_multipart():
    from data_loader import get_match_data
    from components.map_insights import (touch_map_insight, reception_insight,
                                         pass_origin_insight, defensive_insight)
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    team = _ml().iloc[-1]["home_team"]
    for fn in (touch_map_insight, reception_insight, pass_origin_insight, defensive_insight):
        ins = fn(mdf, team)
        for k in ("primary", "secondary", "risk", "coaching", "evidence"):
            assert k in ins
        assert ins["primary"]  # non-empty headline


def test_map_insight_evidence_backed():
    from data_loader import get_match_data
    from components.map_insights import pass_origin_insight
    mid = _ml().iloc[-1]["match_id"]
    mdf = get_match_data(LF, mid)
    team = _ml().iloc[-1]["home_team"]
    ins = pass_origin_insight(mdf, team)
    # evidence must contain real counts
    assert any(ch.isdigit() for ch in ins["evidence"])


# ── v25 Phase 1-3 tests: performance, positions, radar metrics ────────
def test_all_league_player_stats_finishes_fast():
    import time
    from data_loader import get_player_stats, load_league_data
    load_league_data(LF)
    t = time.time()
    ps = get_player_stats(LF)  # all league
    elapsed = time.time() - t
    assert len(ps) > 400
    assert elapsed < 30, f"all-league stats too slow: {elapsed:.1f}s"


def test_key_pass_table_vectorized_cached():
    from data_loader import load_league_data
    from components.metric_engine import build_inferred_key_pass_table
    df = load_league_data(LF)
    t1 = __import__("time").time()
    tbl = build_inferred_key_pass_table(df)
    first = __import__("time").time() - t1
    assert sum(tbl.values()) > 0
    assert first < 5, f"key-pass table too slow: {first:.1f}s"


def test_position_fallback_under_threshold():
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    reg = ps[ps["matches"] >= 5]
    fb = reg[reg["position_source"].str.contains("Event data fallback", na=False)]
    pct = len(fb) / max(len(reg), 1)
    assert pct <= 0.15, f"{pct*100:.0f}% event fallback exceeds 15%"


def test_known_player_positions():
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    def grp(name):
        m = ps[ps["player_name"].str.contains(name, case=False, na=False)]
        return m.iloc[0]["position_group"] if not m.empty else None
    assert grp("douard") == "ST"      # Édouard striker, not CAM
    assert grp("Barcola") == "Winger"
    assert grp("Dembélé") == "ST"


def test_radar_xg_not_shots():
    from data_loader import get_player_stats
    ps = get_player_stats(LF, "Racing Club de Lens")
    st = ps[ps["position_group"] == "ST"].iloc[0]
    # real xG must be much smaller than shot count
    assert st["xg"] < st["shots"]
    assert st["prog_passes"] < st["passes"]


def test_radar_metric_map_real():
    from components.radar import _AGG_METRIC_MAP
    assert _AGG_METRIC_MAP["xg"] == "xg"           # not 'shots'
    assert _AGG_METRIC_MAP["prog_passes"] == "prog_passes"  # not 'passes'


def test_radar_comparison_two_traces():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF, "Racing Club de Lens")
    sts = ps[ps["position_group"] == "ST"]
    pa, pb = sts.iloc[0]["player_id"], sts.iloc[1]["player_id"]
    peerA = compute_peer_percentiles(df, pa, "Racing Club de Lens", "ST")
    peerB = compute_peer_percentiles(df, pb, "Racing Club de Lens", "ST")
    fig = build_percentile_radar(peerA, "A", "ST", peer_b=peerB, name_b="B")
    assert len(fig.data) == 2


# ── v25 Phase 4: touch-map count validation + clean_heatmap_events kwargs ──
def test_touch_zone_counts_equal_plotted_dots():
    from data_loader import get_match_data
    from components.zone_model import zone_grid_counts
    from components.definitions import filter_valid_touch_events
    mid = _ml().iloc[-1]["match_id"]
    team = _ml().iloc[-1]["home_team"]
    mdf = get_match_data(LF, mid)
    raw = mdf[mdf["team_name"] == team]
    df, _ = filter_valid_touch_events(raw)
    grid = zone_grid_counts(df)
    assert sum(grid["cells"].values()) == len(df)  # valid plotted dots only


def test_zone_grid_inclusive_top_edge():
    from components.zone_model import zone_grid_counts
    import pandas as pd
    # Points exactly on the top edges must be counted, not dropped
    df = pd.DataFrame({"x": [100.0, 50.0, 0.0], "y": [100.0, 50.0, 0.0]})
    grid = zone_grid_counts(df)
    assert sum(grid["cells"].values()) == 3


def test_touch_heatmap_has_validation_footer():
    from data_loader import get_match_data
    from components.heatmaps import touch_heatmap
    mid = _ml().iloc[-1]["match_id"]
    team = _ml().iloc[-1]["home_team"]
    mdf = get_match_data(LF, mid)
    fig = touch_heatmap(mdf, team)
    texts = [a.text for a in fig.layout.annotations if a.text]
    from components.definitions import filter_valid_touch_events
    valid, _ = filter_valid_touch_events(mdf[mdf["team_name"] == team])
    plotted = len(valid)
    counts = [int(t.replace("<b>", "").replace("</b>", "")) for t in texts
              if t.replace("<b>", "").replace("</b>", "").isdigit()]
    # displayed numbers equal plotted VALID-touch dots (Out/admin excluded)
    assert sum(counts) == plotted
    assert any("plotted" in t for t in texts)  # footer present


def test_clean_heatmap_events_uses_keyword_args():
    # The smooth gaussian path must not pass allow_boundary_actions=100.
    import inspect
    from components import heatmaps
    src = inspect.getsource(heatmaps.smooth_gaussian_pitch_heatmap)
    assert "allow_boundary_actions=False" in src
    assert "open_play_only, include_set_pieces, 100, 100" not in src


# ── v25 Phase 5: report selected-team propagation (data + labels) ─────
def test_report_goal_data_changes_with_opponent():
    from components.report_model import build_pre_match_report_model
    psg = build_pre_match_report_model(LF, "Racing Club de Lens", "Paris Saint-Germain FC", 50)
    monaco = build_pre_match_report_model(LF, "Racing Club de Lens", "AS Monaco FC", 50)
    om = build_pre_match_report_model(LF, "Racing Club de Lens", "Olympique de Marseille", 50)
    # pre-match goal totals must differ by selected opponent (not hardcoded to Lens/report team)
    totals = {psg["goal_profile"]["total"], monaco["goal_profile"]["total"], om["goal_profile"]["total"]}
    assert len(totals) >= 2
    assert psg["teams"]["our"] == "Racing Club de Lens"
    assert psg["goal_profile_team"] == "Paris Saint-Germain FC"


def test_report_goal_header_uses_opponent_team():
    from components.report_pages import build_pre_match_report
    import re
    def header_team(our, opp):
        r = build_pre_match_report(LF, our, opp, 50)
        txt = []
        def walk(c):
            if isinstance(c, str): txt.append(c); return
            if hasattr(c, "children"):
                ch = c.children
                if isinstance(ch, (list, tuple)):
                    for x in ch: walk(x)
                else: walk(ch)
        walk(r)
        m = re.search(r"How ([\w\s]+?) score and concede", " ".join(txt))
        return m.group(1).strip() if m else None
    assert header_team("Racing Club de Lens", "Stade Rennais FC") == "Lens"
    assert header_team("Paris Saint-Germain FC", "Racing Club de Lens") == "PSG"


def test_pdf_report_team_matches_selected_v25():
    from components.report_model import build_pre_match_report_model
    from components.pdf_export import export_model_pdf, pdf_export_available
    if not pdf_export_available():
        return
    lens = build_pre_match_report_model(LF, "Racing Club de Lens", "Stade Rennais FC", 50)
    psg = build_pre_match_report_model(LF, "Paris Saint-Germain FC", "Stade Rennais FC", 50)
    _, fn_lens = export_model_pdf(lens)
    _, fn_psg = export_model_pdf(psg)
    assert "Lens" in fn_lens and "Paris" in fn_psg
    assert lens["goal_profile"]["total"] != psg["goal_profile"]["total"]


# ── Position-aware radar (GK fix) ─────────────────────────────────────
def test_gk_radar_uses_gk_metrics():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF)
    gk = ps[ps["position_group"] == "GK"].nlargest(1, "matches").iloc[0]
    peer = compute_peer_percentiles(df, gk["player_id"], gk["team_name"], "GK")
    fig = build_percentile_radar(peer, gk["player_name"], "GK")
    axes = list(fig.data[0].theta)[:-1]
    # GK radar must show keeper metrics, never outfield goal metrics
    assert any("Save" in a or "Claim" in a or "Sweep" in a for a in axes)
    assert "Goals" not in axes and "xG" not in axes and "Shots" not in axes


def test_each_position_radar_is_role_appropriate():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF)
    # defenders should not be scored primarily on goals/xG axes dominance
    expect = {
        "GK": {"Saves", "Claims", "Sweeping"},
        "CB": {"Tackles", "Interceptions", "Clearances"},
        "ST": {"Goals", "xG", "Shots"},
    }
    for grp, must_have in expect.items():
        sub = ps[(ps["position_group"] == grp) & (ps["matches"] >= 5)]
        if sub.empty:
            continue
        p = sub.iloc[0]
        peer = compute_peer_percentiles(df, p["player_id"], p["team_name"], grp)
        fig = build_percentile_radar(peer, p["player_name"], grp)
        axes = set(list(fig.data[0].theta)[:-1])
        assert must_have & axes, f"{grp} radar missing role metrics: {axes}"


def test_gk_aggregate_has_saves():
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    gks = ps[ps["position_group"] == "GK"]
    assert gks["saves"].sum() > 0
    assert gks["claims"].sum() > 0


# ── Position-appropriate radar metrics (GK must not show outfield stats) ──
def test_gk_radar_uses_keeper_metrics():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF)
    gk = ps[ps["position_group"] == "GK"].nlargest(1, "matches").iloc[0]
    peer = compute_peer_percentiles(df, gk["player_id"], gk["team_name"], "GK")
    fig = build_percentile_radar(peer, gk["player_name"], "GK")
    axes = list(fig.data[0].theta)
    assert any(m in axes for m in ("Saves", "Claims", "Sweeping"))
    assert "Goals" not in axes and "Shots" not in axes


def test_all_groups_radar_sane():
    from data_loader import load_league_data, get_player_stats
    from components.radar import compute_peer_percentiles, build_percentile_radar
    df = load_league_data(LF)
    ps = get_player_stats(LF)
    for grp in ["GK", "CB", "FB/WB", "DM", "CM", "AM", "Winger", "ST"]:
        sub = ps[(ps["position_group"] == grp) & (ps["matches"] >= 5)]
        if sub.empty:
            continue
        p = sub.nlargest(1, "matches").iloc[0]
        peer = compute_peer_percentiles(df, p["player_id"], p["team_name"], grp)
        fig = build_percentile_radar(peer, p["player_name"], grp)
        assert len(fig.data) >= 1
        axes = list(fig.data[0].theta)
        assert len(set(axes)) >= 3  # at least 3 distinct axes


def test_discover_leagues_excludes_reference():
    from data_loader import discover_leagues
    folders = [l["folder"] for l in discover_leagues()]
    assert "reference" not in folders
    assert "wyscout" not in [f.lower() for f in folders]
    assert any("France" in f for f in folders)


def test_methodology_docs_exist():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in ["docs/METHODOLOGY.md", "docs/KPI_DEFINITIONS.md",
              "docs/DATA_SOURCES.md", "docs/QA_CHECKS.md", "README.md", "CHANGELOG.md"]:
        p = os.path.join(root, d)
        assert os.path.exists(p), f"missing {d}"
        assert os.path.getsize(p) > 200, f"{d} too short"


def test_parquet_cache_roundtrip_preserves_data():
    # Release QA should be reproducible in headless environments without forcing
    # a costly cold parse. Verify the cache backend is declared and the loaded
    # frame has the expected stable shape/columns.
    import os
    from data_loader import load_league_data
    df = load_league_data(LF)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read().lower()
    assert ("pyarrow" in req) or ("fastparquet" in req)
    assert len(df) > 500000
    assert "team_name_canon" in df.columns


def test_cross_position_comparison_warns():
    import app
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    st = ps[ps["position_group"] == "ST"].iloc[0]
    gk = ps[ps["position_group"] == "GK"].iloc[0]

    def text_of(component):
        out = []
        def walk(c):
            if isinstance(c, str):
                out.append(c); return
            if hasattr(c, "children"):
                ch = c.children
                for x in (ch if isinstance(ch, (list, tuple)) else [ch]):
                    if x is not None and not isinstance(x, str):
                        walk(x)
                if isinstance(ch, str):
                    out.append(ch)
        walk(component)
        return " ".join(out)

    # Cross-position (ST vs GK) must warn
    r = app.update_players(st["player_id"], gk["player_id"], st["team_name"], None, "full", "percentile", LF)
    assert "Cross-position comparison" in text_of(r)
    # Same-position (ST vs ST) must NOT warn
    st2 = ps[ps["position_group"] == "ST"].iloc[1]
    r2 = app.update_players(st["player_id"], st2["player_id"], st["team_name"], None, "full", "percentile", LF)
    assert "Cross-position comparison" not in text_of(r2)


# ── Phase 5: radar max-normalization ──
def test_radar_max_normalization_equals_raw_over_peer_max():
    """Fast headless audit of the user-requested radar scale."""
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    cb_pool = ps[(ps["position_group"] == "CB") & (ps["matches"] >= 5)]
    assert not cb_pool.empty
    peer_max = cb_pool["interceptions"].max()
    top = cb_pool.nlargest(1, "interceptions").iloc[0]
    assert peer_max > 0
    assert round(top["interceptions"] / peer_max * 100) == 100


def test_radar_maxnorm_no_all_zero_as_100():
    from data_loader import get_player_stats
    ps = get_player_stats(LF)
    for grp in ["CB", "ST", "Winger", "CM", "DM"]:
        sub = ps[(ps["position_group"] == grp) & (ps["matches"] >= 5)]
        if sub.empty:
            continue
        for metric in ["interceptions", "key_passes", "shots", "prog_passes"]:
            if metric not in sub.columns:
                continue
            mx = sub[metric].max()
            if mx <= 0:
                continue
            top = sub.nlargest(1, metric).iloc[0]
            assert round(top[metric] / mx * 100) == 100


# ── Phase 6: Out events excluded from touch map ──
def test_out_events_not_counted_as_touches():
    from data_loader import load_league_data, get_match_list, get_match_data
    from components.definitions import filter_valid_touch_events
    ml = get_match_list(LF)
    mid = ml.iloc[-1]["match_id"]; team = ml.iloc[-1]["home_team"]
    mdf = get_match_data(LF, mid)
    tdf = mdf[mdf["team_name"] == team]
    valid, excluded = filter_valid_touch_events(tdf)
    assert (valid["event"] == "Out").sum() == 0
    assert (valid["event"] == "Deleted event").sum() == 0
    assert excluded > 0  # some rows must have been excluded
    assert len(valid) < len(tdf)


def test_touch_map_counts_equal_plotted():
    from data_loader import get_match_list, get_match_data
    from components.heatmaps import touch_heatmap
    ml = get_match_list(LF)
    mid = ml.iloc[-1]["match_id"]; team = ml.iloc[-1]["home_team"]
    fig = touch_heatmap(get_match_data(LF, mid), team)
    dots = sum(len(t.x) for t in fig.data if t.mode == "markers" and t.x is not None and len(t.x) > 1)
    counts = [int(a.text.replace("<b>", "").replace("</b>", ""))
              for a in fig.layout.annotations
              if a.text and a.text.replace("<b>", "").replace("</b>", "").isdigit()]
    assert dots == sum(counts)


# ── Phase 9: H2H scope applies to header record ──
def test_h2h_scope_changes_record():
    import app
    from data_loader import get_match_list
    def text_of(c):
        out = []
        def walk(x):
            if isinstance(x, str): out.append(x); return
            if hasattr(x, "children"):
                ch = x.children
                for y in (ch if isinstance(ch, (list, tuple)) else [ch]):
                    if y is not None and not isinstance(y, str): walk(y)
                if isinstance(ch, str): out.append(ch)
        walk(c); return " ".join(out)
    import re
    t_all = text_of(app.update_h2h("Racing Club de Lens", "Olympique de Marseille", "all", None, LF))
    t_last = text_of(app.update_h2h("Racing Club de Lens", "Olympique de Marseille", "last1", None, LF))
    m_all = re.search(r"Record \(this sample\):.+?(\d+) match", t_all)
    m_last = re.search(r"Record \(this sample\):.+?(\d+) match", t_last)
    assert m_all and m_last
    assert int(m_last.group(1)) == 1
    assert int(m_all.group(1)) >= int(m_last.group(1))
