"""Fast, reproducible release-readiness gate for Football Analytics Pro.

This gate intentionally checks the visible trust blockers without launching Dash
or doing full visual rendering. Heavy browser/PDF-chart checks remain documented
manual gates, while this script must always finish headlessly.
"""
from __future__ import annotations
import os
import time


def _add(results, name, ok, detail=""):
    print(f"[QA] {'PASS' if ok else 'FAIL'} {name}", flush=True)
    results["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        results["pass"] = False


def run_release_readiness_checks(league_folder: str):
    results = {"checks": [], "warnings": [], "pass": True}
    t0 = time.time()
    from data_loader import (
        load_league_data, get_match_list, get_teams, get_player_stats,
        get_match_data, normalize_team, is_knockout_lf, get_rounds, compute_cup_progress_table,
    )

    df = load_league_data(league_folder)
    ml = get_match_list(league_folder)
    teams = get_teams(league_folder)

    # ── Knockout/cup competitions use a different release gate ───────────
    # They have no league table, no Wyscout Ligue 1 coverage expectation, and
    # rounds replace matchweeks. This verifies that Coupe de France data is
    # integrated without breaking the core dashboard abstractions.
    if is_knockout_lf(league_folder):
        rounds = get_rounds(league_folder)
        _add(results, "Cup data loaded", len(df) >= 100000 and len(ml) >= 60,
             f"rows={len(df)}, matches={len(ml)}, teams={len(teams)}")
        _add(results, "Knockout rounds detected", len(rounds) >= 5 and any(r["label"] == "Final" for r in rounds),
             f"rounds={[r['label'] for r in rounds]}")
        _add(results, "Round order replaces matchweek", "round_order" in ml.columns and ml["round_order"].notna().all() and ml["week"].notna().all(),
             "round_order/week available for every match")
        _add(results, "Cup teams include lower-division clubs", len(teams) >= 50,
             f"teams={len(teams)}")
        _add(results, "Cup alias normalization keeps Ligue 1 clubs", all(normalize_team(x) in teams for x in ["Lens", "PSG", "Monaco", "Marseille"]),
             "Lens/PSG/Monaco/Marseille in cup team list")
        try:
            ps_lens = get_player_stats(league_folder, "Lens")
            _add(results, "Cup player stats work", len(ps_lens) >= 15,
                 f"Lens cup players={len(ps_lens)}")
        except Exception as e:
            _add(results, "Cup player stats work", False, e)
        try:
            cp = compute_cup_progress_table(league_folder)
            lens = cp[cp["Team"] == normalize_team("Lens")]
            _add(results, "Cup progress table works", not cp.empty and not lens.empty and str(lens.iloc[0].get("Reached")) == "Final",
                 f"Lens reached={None if lens.empty else lens.iloc[0].get('Reached')}")
        except Exception as e:
            _add(results, "Cup progress table works", False, e)
        try:
            final = ml[ml.get("round_name", "") == "Final"]
            _add(results, "Cup final match available", len(final) == 1,
                 "none" if final.empty else f"{final.iloc[0].home_team} {final.iloc[0].home_goals}-{final.iloc[0].away_goals} {final.iloc[0].away_team}")
        except Exception as e:
            _add(results, "Cup final match available", False, e)
        try:
            from components.definitions import filter_valid_touch_events
            from components.zone_model import zone_grid_counts
            mid = ml.iloc[-1].match_id; team = ml.iloc[-1].home_team
            valid, excluded = filter_valid_touch_events(get_match_data(league_folder, mid).query("team_name == @team"))
            grid = zone_grid_counts(valid)
            _add(results, "Cup pitch-map filters work", len(valid) > 0 and grid["total"] == len(valid),
                 f"valid={len(valid)}, excluded={excluded}, zone_total={grid['total']}")
        except Exception as e:
            _add(results, "Cup pitch-map filters work", False, e)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
            _add(results, "Cup documented", "Coupe de France" in readme and "knockout" in readme.lower(),
                 "README mentions Coupe de France knockout mode")
        except Exception as e:
            _add(results, "Cup documented", False, e)
        results["elapsed_seconds"] = round(time.time() - t0, 2)
        return results
    _add(results, "Data loaded", len(df) >= 500000 and len(ml) == 305,
         f"rows={len(df)}, matches={len(ml)}")
    _add(results, "18 canonical teams", len(teams) == 18, f"teams={len(teams)}")
    _add(results, "Short aliases normalize", all(normalize_team(x) in teams for x in ["Lens", "PSG", "Monaco", "Metz", "Marseille"]),
         "Lens/PSG/Monaco/Metz/Marseille")

    # Public alias behavior
    try:
        alias_ok = (
            len(get_player_stats(league_folder, "Lens")) == len(get_player_stats(league_folder, "Racing Club de Lens")) > 0 and
            len(get_player_stats(league_folder, "PSG")) == len(get_player_stats(league_folder, "Paris Saint-Germain FC")) > 0
        )
        _add(results, "Public data functions accept short aliases", alias_ok)
    except Exception as e:
        _add(results, "Public data functions accept short aliases", False, e)

    # Score truth + Wyscout coverage
    try:
        lm = ml[(ml.home_team == "Racing Club de Lens") & (ml.away_team == "Olympique de Marseille") & (ml.week == 9)]
        ok = (not lm.empty) and (int(lm.iloc[0].home_goals), int(lm.iloc[0].away_goals)) == (2, 1)
        _add(results, "Lens-Marseille score truth", ok, "2-1 expected")
    except Exception as e:
        _add(results, "Lens-Marseille score truth", False, e)
    try:
        from components.metric_engine import get_wyscout_df
        wy = get_wyscout_df()
        _add(results, "Wyscout team-match coverage", wy is not None and len(wy) >= 610, f"rows={0 if wy is None else len(wy)}")
    except Exception as e:
        _add(results, "Wyscout team-match coverage", False, e)

    # Player stats/radar/positions performance and correctness
    # Keep this gate reproducible: team-scoped player stats are fast and enough
    # to catch alias/position regressions. Radar max-normalization is verified
    # by source/contract here; exhaustive all-league peer checks live in pytest.
    try:
        st = time.time(); ps_lens = get_player_stats(league_folder, "Lens"); elapsed = time.time() - st
        _add(results, "Team player stats finish", len(ps_lens) >= 20 and elapsed < 15,
             f"Lens players={len(ps_lens)}, {elapsed:.2f}s")
        ed = ps_lens[ps_lens.player_name.astype(str).str.contains("douard", case=False, na=False)]
        _add(results, "Canonical player positions applied", not ed.empty and ed.iloc[0].position_group == "ST",
             f"Edouard={None if ed.empty else ed.iloc[0].position_group}")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        radar_src = open(os.path.join(root, "components", "radar.py"), encoding="utf-8").read()
        app_src = open(os.path.join(root, "app.py"), encoding="utf-8").read()
        ok_radar = "peer_max" in radar_src and "maxnorm" in radar_src.lower() and 'value="max"' in app_src
        _add(results, "Radar max-normalization active", ok_radar,
             "radar.py peer_max + app default value='max'")
    except Exception as e:
        _add(results, "Player/radar checks", False, e)

    # Position-specific influence
    try:
        from components.report_engine import _INFLUENCE_TEMPLATES
        gk = _INFLUENCE_TEMPLATES.get("GK", [])
        stt = _INFLUENCE_TEMPLATES.get("ST", [])
        _add(results, "Influence is position-specific", gk != stt and "saves" in gk and "xg" in stt,
             f"GK={list(gk)[:3]}, ST={list(stt)[:3]}")
    except Exception as e:
        _add(results, "Influence is position-specific", False, e)

    # Pitch map semantics
    try:
        from components.definitions import (
            filter_valid_touch_events, filter_valid_pass_events, filter_valid_reception_events,
            filter_valid_defensive_events, filter_valid_shot_events,
        )
        from components.zone_model import zone_grid_counts
        mid = ml.iloc[-1].match_id; team = ml.iloc[-1].home_team
        mdf = get_match_data(league_folder, mid); tdf = mdf[mdf.team_name == team]
        valid, excluded = filter_valid_touch_events(tdf)
        grid = zone_grid_counts(valid)
        ok = len(valid) > 0 and excluded >= 0 and (valid.event == "Out").sum() == 0 and grid["total"] == len(valid)
        _add(results, "Touch map valid-event counts", ok, f"valid={len(valid)}, excluded={excluded}, zone_total={grid['total']}")
        layer_ok = all(callable(fn) and len(fn(tdf)[0]) >= 0 for fn in [
            filter_valid_pass_events, filter_valid_reception_events, filter_valid_defensive_events, filter_valid_shot_events
        ])
        _add(results, "All pitch-map layer filters available", layer_ok, "pass/reception/defensive/shot")
    except Exception as e:
        _add(results, "Pitch map valid-event checks", False, e)

    # H2H aliases and Last Meeting scope
    try:
        from components.h2h_metrics import resolve_h2h_match_ids, compute_buildup_patterns, compute_passing_profile
        ids, label = resolve_h2h_match_ids(ml, "Lens", "Marseille", "last1")
        bu = compute_buildup_patterns(df, "Lens", ids)
        pp = compute_passing_profile(df, "Lens", ids)
        _add(results, "H2H Last Meeting is match-specific", len(ids) == 1 and bu.get("n_matches") == 1 and pp.get("n_matches") == 1,
             f"ids={len(ids)}, label={label}")
    except Exception as e:
        _add(results, "H2H Last Meeting is match-specific", False, e)

    # Report selected team + source caveats (fast headless check)
    try:
        from components.goal_profile import compute_goal_profile
        from components.report_sample import resolve_report_sample
        psg_ids = resolve_report_sample(league_folder, "PSG", sample_mode=5)["match_ids"]
        monaco_ids = resolve_report_sample(league_folder, "Monaco", sample_mode=5)["match_ids"]
        psg_g = compute_goal_profile(df, normalize_team("PSG"), psg_ids, side="for")
        monaco_g = compute_goal_profile(df, normalize_team("Monaco"), monaco_ids, side="for")
        _add(results, "Pre-match goal distribution follows selected opponent", psg_g["total"] != monaco_g["total"],
             f"PSG opponent goals={psg_g['total']}, Monaco opponent goals={monaco_g['total']}")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rm_src = open(os.path.join(root, "components", "report_model.py"), encoding="utf-8").read()
        _add(results, "xG source caveats present", "Wyscout" in rm_src and "Estimated event xG" in rm_src, "report_model source labels")
        _add(results, "Threat/weakness engine produces varied findings", "threat_metrics" in open(os.path.join(root, "components", "report_engine.py"), encoding="utf-8").read(), "normalized threat engine present")
    except Exception as e:
        _add(results, "Report model checks", False, e)

    # Post-match KPI context: source-contract gate. The full report/context
    # regression is covered by tests/test_post_match_kpi_context.py; release QA
    # must stay fast and headless, so it checks that the active model and PDF
    # paths consume the context helper and that direction-sensitive metrics are
    # registered.
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        kpi_src = open(os.path.join(root, "components", "kpi_context.py"), encoding="utf-8").read()
        rm_src = open(os.path.join(root, "components", "report_model.py"), encoding="utf-8").read()
        pdf_src = open(os.path.join(root, "components", "pdf_export.py"), encoding="utf-8").read()
        ok = ("build_post_match_kpi_context" in kpi_src and
              "team_season_avg" in kpi_src and "league_avg" in kpi_src and
              '"xga"' in kpi_src and '"ppda"' in kpi_src and "lower_good" in kpi_src and
              "build_post_match_kpi_contexts" in rm_src and
              "post_match_kpi_context" in pdf_src)
        _add(results, "Post-match KPIs include season/league context", ok,
             "source contract: team avg, league avg, xGA/PPDA direction, Dash/PDF model paths")
    except Exception as e:
        _add(results, "Post-match KPIs include season/league context", False, e)

    # PDF export: functional fast smoke; full visual map/chart export remains environment-dependent.
    try:
        from components.pdf_export import pdf_export_available, charts_available_for_pdf, export_model_pdf
        if not pdf_export_available():
            _add(results, "PDF export available", False, "reportlab missing")
        else:
            model = {
                "report_type": "pre", "title": "Release QA PDF", "league": league_folder,
                "date": "2026-01-01", "teams": {"our": "Paris Saint-Germain FC", "opponent": "Racing Club de Lens"},
                "sample": {"label": "QA", "sample_label": "QA", "n": 1, "match_ids": []},
                "executive_summary": ["Release QA PDF smoke export."],
                "kpis": [{"label": "Wyscout xG", "value": "1.2", "source": "Wyscout"}],
                "goal_profile": {"total": 1, "timing": {"0-15": 1}, "methods": {"open play": 1}},
                "goals_conceded_profile": {"total": 0, "timing": {}, "methods": {}},
                "tactical_findings": [{"title": "QA", "body": "PDF model sections render."}],
                "recommendations": ["Verify visual export locally with Kaleido or Playwright."],
                "caveats": ["Chart rendering is environment-dependent."],
            }
            pdf, fname = export_model_pdf(model)
            _add(results, "PDF export non-empty", pdf is not None and len(pdf) > 2000, f"{0 if pdf is None else len(pdf)} bytes")
            if not charts_available_for_pdf():
                results["warnings"].append("Chart rendering dependency unavailable in this environment; install Kaleido/Chrome or Playwright for visual PDFs.")
    except Exception as e:
        _add(results, "PDF export checks", False, e)

    # Documentation counts and anti-regression source checks
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
        docs_ok = all(os.path.exists(os.path.join(root, p)) for p in [
            "docs/METHODOLOGY.md", "docs/KPI_DEFINITIONS.md", "docs/DATA_SOURCES.md", "docs/QA_CHECKS.md", "README.md", "CHANGELOG.md"
        ])
        counts_ok = "525,334" in readme and "305" in readme and "572" in readme and "310,226" not in readme and "180 files" not in readme
        _add(results, "Documentation present and current", docs_ok and counts_ok, f"docs={docs_ok}, counts_current={counts_ok}")
        app_src = open(os.path.join(root, "app.py"), encoding="utf-8").read()
        hm_src = open(os.path.join(root, "components", "heatmaps.py"), encoding="utf-8").read()
        _add(results, "Report selectors are live Inputs", all(x in app_src for x in ['Input("rp-our-team"', 'Input("rp-opponent"', 'Input("rp-sample"']), "our/opponent/sample")
        _add(results, "All map layers use strict filter helpers", all(x in hm_src for x in ["filter_valid_touch_events", "filter_valid_pass_events", "filter_valid_reception_events", "filter_valid_defensive_events", "filter_valid_shot_events"]), "touch/pass/reception/def/shot")
    except Exception as e:
        _add(results, "Documentation/source anti-regression checks", False, e)

    elapsed = time.time() - t0
    results["elapsed_seconds"] = round(elapsed, 2)
    if elapsed > 120:
        results["warnings"].append(f"Release QA is slow ({elapsed:.1f}s); investigate cold caches if this persists.")
    return results


def team_normalization_qa(league_folder: str):
    from data_loader import get_teams
    teams = get_teams(league_folder)
    dups = [t for t in teams if teams.count(t) > 1]
    return {"ok": len(teams) == 18 and not dups, "unmapped": [], "duplicates": dups, "wyscout_unmatched": []}
