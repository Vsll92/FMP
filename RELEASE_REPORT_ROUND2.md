# Release-Readiness Report — Round 2

This round targeted the release blockers that remained after the visible-bug
fixes: short-alias failures, a one-size-fits-all influence score, un-normalized
"High xG" threats, QA reproducibility, and README accuracy. Every fix is gated
in `release_qa.py` so it cannot silently regress.

## Blockers fixed (root cause → fix → proof)

| Blocker | Root cause | Fix | Proof |
|---|---|---|---|
| #3 Short aliases fail (`get_player_stats("Lens")` → 0 rows) | Public data fns filtered on raw `team_name` without normalizing | Wired `normalize_team()` into `get_player_stats`, `get_head_to_head`, `get_team_results`, `compute_team_profile`, `compute_goal_profile`; unknown names now warn | `get_player_stats("Lens")` = 31 = canonical; H2H(Lens,Monaco)=2; unknown team warns |
| #10 Influence uses same KPIs for all positions | Single formula scored GK on goals/xG/shots, ST on tackles | Position templates (GK/CB/FB/DM/CM/AM/WING/ST), each scored only on relevant KPIs, with template + confidence + per-metric breakdown; missing KPIs (e.g. GK saves) excluded | 8 distinct templates; GK judged on pass_acc/passes/recoveries/interceptions, never goals/shots |
| #12 "High xG generation" is everyone's top threat | Absolute thresholds (`xg_per_match > 1.5`), no league context | League-percentile engine: a threat is flagged only at ≥70th pct, with percentile + raw evidence; weaknesses inverted correctly | xG is top threat for **4/18** teams (was ~all); 4 distinct top threats; every threat carries a percentile |
| #1 QA not reproducible | No single release runner; optional deps undocumented | Added `scripts/run_release_readiness_checks.py` (exit-coded, timed, honest skips); README documents the full command sequence; `pyarrow`/`kaleido` in requirements | Runner: 71/71 checks, 9 gates, RELEASE-READY in ~117s |
| #2 README outdated/overclaiming | Counts not stated / not verified | Accurate dataset table + testing + PDF reqs + known limitations; QA gate asserts counts match data | Gate I: README 525,334/305/18 == actual |

## New QA gates (all fail on pre-fix code, pass now)

Added to `components/release_qa.py`, on top of the 5 visible-bug gates from
round 1 (radar default, radar audit, report live-Inputs, H2H scope, pitch
footer==dots):

- **F** short aliases work (Lens == canonical)
- **G** influence is position-specific (≥3 templates, GK has no striker KPIs)
- **H** threats league-normalized (xG not top for all teams; percentiles present)
- **I** README counts match actual data

## Test results

| Suite | Result |
|---|---|
| `python -m compileall .` | OK |
| `scripts/run_smoke_tests.py` | 66/66 |
| `tests/test_trust_fixes.py` | 23/23 |
| `scripts/run_release_readiness_checks.py` | 71/71 (9 gates) — RELEASE-READY |

## Honest score table (after this round)

| Category | Score | Proof | Residual risk |
|---|---|---|---|
| Data loading / season foundation | 9 | parquet cold load ~0.6s, 525,334 rows | first cold build ~15s |
| Team-name normalization | 9 | aliases wired into all public fns; Lens==canonical; unknown warns | new clubs need a mapping entry |
| Player identity / positions | 9 | Édouard=ST; fallback 0%; mismatch detector | ~49% high-confidence positions |
| Wyscout integration | 9 | scores 0 mismatches; coverage 100% | export completeness dependent |
| Metric/KPI methodology | 9 | source-labelled; xG≠shots; prog≠passes | some estimated metrics (labelled) |
| Overview page | 9 | Team Situation: form/strengths/watch + league xG rank | — |
| Match Center | 9 | score provenance + conflict warnings | — |
| Head-to-Head | 9 | results table obeys scope (1 row Last Meeting); shared match_ids | Style Clash is labelled season-context |
| Player Hub | 9 | max-norm default; auditable radar (0 mismatch) | cross-position compare opt-in |
| Pitch Maps | 9 | live footer = dots; Out/OOB excluded on touch; zones reconcile | OOB on pass/def layers via zone-binning only |
| Trends | 9 | pass-share terminology; distinct colors; legend-safe | — |
| Dash Match Reports | 9 | live Inputs; titles follow selection; **position-specific influence**; **normalized threats** | influence is heuristic (confidence shown) |
| PDF Report Export | 9 | embeds charts (XObjects), players, logos; strict mode fails text-only | needs kaleido+Chrome at deploy (QA-enforced) |
| Performance / responsiveness | 9 | player stats ~0s; peer path 0.02s; QA full run ~117s | benchmark pass adds one cached league sweep |
| Testing / QA | 9 | reproducible runner; 9 gates fail on old code, pass on new; 71+66+23 checks | gates cover known bugs, not exhaustive |
| README / methodology docs | 9 | accurate counts (QA-asserted); testing + PDF + limitations | doc prose not exhaustively re-reviewed |
| Release readiness | 9 | all suites green; strict QA RELEASE-READY; professional PDF | **not yet verified in a live browser** |

### Why these are 9, not 10 (honest)
- Proof is **callback-level and data-level**, not a live-browser screenshot pass.
  Release readiness in particular would benefit from a Playwright/Selenium run
  against the running server before a public/club demo.
- Influence and threat engines are transparent **heuristics** with confidence
  and evidence shown — not provider-certified models.
- xG is labelled (Wyscout vs Estimated) but a side-by-side reconciliation *note*
  in the report body is still a recommended addition (#11 partially addressed).
- Out-of-bounds exclusion is enforced on the Touch Map; pass/reception/defensive
  layers drop out-of-range points via zone-binning rather than an explicit
  filter.
