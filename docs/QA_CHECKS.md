# QA Checks & Performance Targets

Release readiness is gated by `components/release_qa.run_release_readiness_checks`
(58 checks) plus `tests/test_suite.py` (pytest) and
`scripts/run_smoke_tests.py` (Dash-free smoke runner). All run headless (Dash
import is blocked during the gate to prove analytics paths are Dash-free).

## Football-trust checks
- Lens 2-1 Marseille and all 305 scores reconcile to Wyscout.
- 18 canonical teams, 0 duplicates, 0 unmapped Wyscout names.
- Player positions: ≤ 15% of 5+ match players on event fallback (currently 0%).
- O. Édouard = ST; radar percentiles are real (not self-normalized).
- xG ≠ shots, progressive passes ≠ total passes (no mislabeled proxies).
- Key passes inferred & non-zero; never 100th percentile on all-zero pools.
- GK radar uses keeper metrics (saves/claims/sweeping), not outfield metrics.
- Touch-map zone counts equal plotted dots; third filters never leak.
- `clean_heatmap_events` uses `allow_boundary_actions=False` (no boundary bug).
- Reports: goal data changes by selected team (not Lens-hardcoded).
- Trends: Pass Share ≠ Pass Accuracy color; legend-safe margins.
- League discovery excludes reference/cache/wyscout dirs.

## Performance targets (gated)
| Path | Target | Actual |
|------|--------|--------|
| Cold load (parquet) | < 6s | ~0.8s |
| Match list (cached) | < 1s | 0.000s |
| Player stats (team) | < 1s | ~0.5s |
| All-league stats | < 5s | ~3.7s |
| All-league (cached) | instant | 0.000s |
| Player Hub peer path (cached) | < 2s | ~0.01s |
| Key-pass table (vectorized/cached) | < 2s | ~0.0s |

## Running
```bash
python -m compileall .
python scripts/run_smoke_tests.py
python -m pytest tests/ -q
python -c "from components.release_qa import run_release_readiness_checks as r, format_report as f; print(f(r('France_League_1_25-26')))"
```
