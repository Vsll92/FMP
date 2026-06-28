# Coupe de France Overview Date-Schema Fix

## Bug fixed
The Cup Overview crashed when rendering a team's cup run because `_cup_match_table()` expected `local_date`, `home_team`, `away_team`, `home_goals`, and `away_goals` columns.

`get_match_list()` returns that full match-list schema, but `get_team_results()` returns a team-run schema:

- `date`
- `opponent`
- `venue`
- `gf`
- `ga`
- `result`

That mismatch caused:

```text
KeyError: 'local_date'
```

## Fix
- Added `_safe_sort_cup_df()` to sort by whichever date column is actually available: `local_date` or `date`.
- Updated `_cup_match_table()` to support both schemas:
  - full cup match list: Home / Score / Away
  - team cup run: Venue / Opponent / Score / Result
- Verified `_cup_overview_home('France_Coupe_de_France_25-26', 'Racing Club de Lens')` renders without crashing.

## Verification
- `python -m compileall .` — PASS
- `python tests/test_coupe_de_france_integration.py` — PASS
- `python scripts/run_release_readiness_checks.py --league France_Coupe_de_France_25-26` — PASS, 10/10
- `python scripts/run_smoke_tests.py` — PASS, 21/21
- `python scripts/run_release_readiness_checks.py` — PASS, 21/21
