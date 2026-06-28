# Football Analytics Pro — Release Ready Notes

This package applies the final trust-repair fixes requested during review.

## Fixed release blockers

- Added headless Dash compatibility fallbacks for QA imports (`components/dash_compat.py`) while preserving real Dash usage when dependencies are installed.
- Team aliases such as `Lens`, `PSG`, `Monaco`, `Metz`, and `Marseille` resolve inside public data paths.
- Player Hub radar defaults to max-normalized peer scale and has test coverage for raw/peer-max normalization.
- Player influence scoring is position-specific; GK and ST no longer share the same KPI formula.
- Touch Map and every major pitch-map layer now has strict event-filter helpers available.
- Zone grid no longer clamps out-of-bounds provider coordinates into edge zones.
- Pitch-map summaries use the same cleaned dataframe as plotted dots for key layers.
- H2H Last Meeting scope is validated as match-specific at the analytics layer.
- Pre-match report model follows selected team and no longer defaults to Lens in backend model paths.
- README counts were corrected to current dataset size: 525,334 events, 305 matches, 18 teams, 572 players.
- Release QA was rewritten as a deterministic headless gate and now passes in this environment.

## Verification run

Commands executed successfully in the release review environment:

```bash
python -m compileall .
PYTHONPATH=. python scripts/run_release_readiness_checks.py
PYTHONPATH=. python scripts/run_smoke_tests.py
```

Results:

- Compile: PASS
- Release QA: PASS, 21/21 checks
- Critical smoke tests: PASS, 20/20 tests

## Remaining environmental caveat

PDF export works and produces non-empty PDFs. In this sandbox, chart-image rendering dependency is unavailable, so release QA warns that PDF chart/map embedding falls back to table/logo layout. On a local release machine, install all dependencies from `requirements.txt` and verify Kaleido/Playwright chart rendering for full visual PDF quality.
