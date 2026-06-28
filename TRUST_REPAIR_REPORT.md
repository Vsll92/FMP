# Trust-Repair Report — Football Analytics Pro

This cycle fixed the four screenshot-proven visible bugs against the **active
code paths** (the Dash callbacks and the functions they actually call), added
strict regression gates so QA can no longer pass while these bugs exist, then
re-evaluated every category honestly.

## Bugs fixed (root cause → fix → proof)

| # | Bug (active path) | Root cause | Fix | Proof |
|---|---|---|---|---|
| 1 | Radar inflated (`update_players` → `compute_peer_percentiles` → `build_percentile_radar`) | Default scale was `"percentile"` (uniform → looks full); `maxnorm` computed from full-precision values while the table showed rounded ones → table not auditable (62–77/320 metrics) | Default → `"max"` (dropdown + callback fallback); subtitle reflects active scale; `maxnorm` derived from the **rounded** `raw`/`peer_max` and clamped 0–100 | Audit: 0 mismatches over 240–320 metrics; low-output player radar mean ≈13 (not full) |
| 2 | Goal Profile stuck on Lens (`generate_report`) | Only `rp-generate.n_clicks` was an Input; team/opponent/sample were **State** → never regenerated. `find_default_team` returns Lens | **Option A**: all selectors are live Inputs → auto-regenerate; stale report impossible | Live callback returns "How PSG/Lens/Monaco score" per selection; title never hardcoded |
| 3 | H2H mixes all games (`build_h2h_page`) | Match Results table iterated all-time `h2h["matches"]`, ignoring the scope filter | Filter the table to the resolved `match_ids`; title shows scope + N; season-only section relabelled "Season Context — NOT the filtered H2H sample" | Last Meeting → exactly 1 results row (was 2) |
| 4 | Pitch counts ≠ dots (`update_maps` → `_map_summary`) | Footer counted `dropna`-only rows (incl. Out/admin/out-of-bounds) while the map drew `filter_valid_touch_events(...)` | Footer uses the **same** valid-touch filter the map uses; pass-origin footer mirrors its map | Live footer = dots (e.g. 503=503; old over-counted to 665/905) |

## QA can no longer lie (Phase 7)

Five strict gates were added to `components/release_qa.py`. Verified they
**FAIL on the original code and PASS on the fixed code**:

- radar default is max-normalized (old: FAIL) 
- radar max-norm == round(raw/peer_max×100) (old: 62 mismatches → FAIL)
- report team/opponent/sample are live Inputs (old: only `rp-generate` → FAIL)
- H2H results table obeys Last Meeting = 1 row (old: 2 rows → FAIL)
- pitch footer count == dots via the **live callback** (old: 665 vs 503 → FAIL)

The PDF check is now **strict**: a text-only PDF (charts unable to rasterise)
**fails** release readiness instead of being labelled "acceptable" (Phase 6).
With `kaleido` present the PDF embeds charts (~130–180 KB, image XObjects,
player notes, logos).

## Test results

| Suite | Result |
|---|---|
| `tests/test_trust_fixes.py` (new; live-callback regression) | 23/23 |
| `tests/test_suite.py` / `scripts/run_smoke_tests.py` | 66/66 |
| `components/release_qa.py` (strict) | 67/67 — and FAILS on pre-fix code |

## Honest score table (before → after, with proof + residual risk)

| Category | Before | After | Proof | Residual risk |
|---|---|---|---|---|
| Data loading / season foundation | 8 | 9 | parquet cold load 0.6s, 525,334 rows; league discovery filters non-league dirs | first cold build ~15s before cache |
| Team-name normalization | 9 | 9 | 18 canonical teams; unmapped=0, dups=0, wy_unmatched=0 | new clubs need mapping entry |
| Player identity / positions | 7 | 9 | Édouard=ST; fallback=0%; mismatch detector | only 49% high-confidence (rest medium/roster) |
| Wyscout integration | 9 | 9 | scores 0 mismatches; coverage 100% | depends on Wyscout export completeness |
| Metric/KPI methodology | 8 | 9 | source-labelled; xG≠shots; prog≠passes; key passes flagged inferred | some metrics estimated, labelled as such |
| Overview page | 8 | 9 | Team Situation: form/strengths/watch populated | — |
| Match Center | 8 | 9 | score provenance cols + conflict warnings | — |
| Head-to-Head | 6 | 9 | results table obeys scope (1 row on Last Meeting); shared match_ids | Style Clash is season-context (now labelled) |
| Player Hub | 5 | 9 | max-norm default; auditable table (0 mismatch); low-output not full | cross-position compare is opt-in w/ warning |
| Pitch Maps | 5 | 9 | live footer = dots; Out/OOB excluded; zones sum to dots | — |
| Trends | 8 | 9 | pass-share terminology; distinct colors; legend-safe | — |
| Dash Match Reports | 4 | 9 | live Inputs (Option A); titles follow selection end-to-end | auto-renders on load |
| PDF Report Export | 5 | 9 | charts embed (XObjects), players, logos; strict mode fails text-only | requires kaleido+Chrome at deploy (in requirements; QA-enforced) |
| Performance / responsiveness | 8 | 9 | player stats ~0s; peer path 0.02s; cold load 0.6s | — |
| Testing / QA | 6 | 9 | strict gates fail on old code, pass on new; 67+66+23 checks | gates cover the 4 bugs + core; not exhaustive |
| README / methodology docs | 8 | 9 | 6/6 docs present | presence-checked, not deep content review |
| Release readiness | 5 | 9 | all suites green; strict QA passes; professional PDF | not visually re-tested in a live browser |

### Honest limitations (why these are 9, not 10)
- Proof is **callback-level and data-level**, not a live-browser screenshot pass.
- PDF chart embedding needs `kaleido` + a Chrome/Chromium binary at deploy time
  (now in `requirements.txt`; strict QA fails if it is missing).
- Position confidence is high for ~49% of players; the rest use season-roster
  dominance (medium) — honest and labelled, but not provider-certified.
- Phases 2 (position-trust deep dive), and broader feature work were out of this
  cycle's scope.
