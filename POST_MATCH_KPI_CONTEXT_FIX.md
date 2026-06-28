# Post-Match KPI Context Upgrade

This release adds season-average and league-average context to the Post-Match Report.

## What changed

Every important post-match KPI can now answer: **is this good, bad, normal, above the team’s usual level, or below the team’s usual level?**

The shared report model now includes `post_match_kpi_context`, with one row per metric:

- match value
- team season average per match
- league average per team-match
- difference vs team average
- difference vs league average
- percentile
- interpretation label
- direction: `higher_good`, `lower_good`, or `contextual`
- source and sample size

## Key implementation files

- `components/kpi_context.py`
  - `build_post_match_kpi_context()`
  - `build_post_match_kpi_contexts()`
  - cached team-match context table
- `components/report_model.py`
  - adds `post_match_kpi_context` to the canonical post-match model shared by Dash and PDF
- `components/report_pages.py`
  - adds visible KPI Context cards to the Dash Post-Match Report
  - upgrades Defensive Output with match-vs-season context for tackles, interceptions, recoveries, clearances, duels, and aerials
- `components/pdf_export.py`
  - includes the same KPI context table in exported post-match PDFs
- `tests/test_post_match_kpi_context.py`
  - validates Lyon defensive metrics, xGA lower-is-better, PPDA lower-is-better, and PDF model inclusion
- `components/release_qa.py`
  - release gate now checks post-match KPI context

## Interpretation rules

- xG, shots, big chances, final-third entries, box entries, progressive passes: higher is generally better.
- xGA, PPDA, fouls, yellow cards, red cards: lower is generally better.
- Tackles, interceptions, recoveries, clearances, duels, aerials: contextual. Higher values can mean strong defensive activity, but may also mean the team defended more often.

## QA verification

Commands verified:

```bash
python -m compileall .
python scripts/run_release_readiness_checks.py
python scripts/run_smoke_tests.py
python tests/test_goal_distribution.py
python tests/test_post_match_kpi_context.py
```

Current release gate:

```text
RESULT: RELEASE-READY (21/21 checks)
```

Note: full visual chart/map embedding in PDFs still depends on Kaleido/Chrome or Playwright being installed locally.
