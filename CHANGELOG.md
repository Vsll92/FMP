# Changelog

## Trust-repair cycle (Phases 1, 3, 4, 5)
- **Player Radar (Phase 1):** default scale is now max-normalized (value ÷ peer
  max × 100), not percentile, so low-output players no longer look elite. The
  radar % is derived from the rounded raw/peer-max shown in the table, so
  `raw ÷ peer_max × 100` reproduces the radar % exactly (audited: 0/320 mismatch).
  Subtitle now reflects the active scale instead of hardcoding "percentile".
- **Match Reports (Phase 3):** report selectors (team / opponent / sample / type
  / match) are now live Inputs (Option A). Changing the team regenerates the
  report immediately — a stale "How Lens score" while another team is selected
  is now impossible. Goal Profile title and PDF model both follow the selected
  team end-to-end.
- **Head-to-Head (Phase 4):** the Match Results table now obeys the scope filter
  (Last Meeting → exactly one row). The one season-context section is explicitly
  labelled "Season Context — NOT the filtered H2H sample".
- **Pitch Maps (Phase 5):** the Touch-Map and Pass-Origin footers now count the
  exact frame the maps plot (via `filter_valid_touch_events`): Out/admin events
  and out-of-bounds coordinates are excluded (never clamped), so the footer
  "Plotted" equals the dots on screen and zone counts sum to plotted (e.g.
  728 == 728, was 905 vs 728).
- **Tests:** added `tests/test_trust_fixes.py` (23 strict checks against the live
  callbacks). Full suite 66/66 + trust suite 23/23.

## Release candidate (current)
- **Performance:** parquet disk cache for the event frame — cold load ~18s → ~1s;
  Player Hub cold open ~5s, cached < 0.2s; all-league stats < 5s.
- **Player Hub:** position-aware radars (GK shows saves/claims/sweeping, not
  outfield); real estimated xG and progressive passes (no mislabeled proxies);
  working comparison trace; inferred key passes (vectorized, cached).
- **Positions:** canonical resolver (override → season-roster dominance → event
  fallback); 0% event fallback for 5+ match players; confidence grading.
- **Pitch Maps:** central zone model; touch-map counts equal plotted dots;
  `clean_heatmap_events` boundary bug fixed; third filters proven leak-free.
- **Reports:** selected-team propagation proven; Report Team / Opponent / Sample
  badges in Dash and PDF; opponent-scouting clearly labelled.
- **Trends:** distinct metric colors (Pass Share ≠ Pass Accuracy); no overflow.
- **Registry:** Wyscout-priority scores; 305/305 reconcile; conflict flags.
- **Docs:** METHODOLOGY, DATA_SOURCES, KPI_DEFINITIONS, QA_CHECKS added.
- **QA:** 58 gate checks incl. performance + football-trust; 58 pytest; 58 smoke.

## Cup overview crash fix
- Fixed Coupe de France Overview crash caused by `_cup_match_table()` assuming `local_date` exists for both match-list and team-results dataframes.
- Cup team-run tables now render with `date`, opponent, venue, score, and result.
