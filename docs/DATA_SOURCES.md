# Data Sources

## Event data (Opta-style)
- **Location:** `data/France_League_1_25-26/*.csv` — one file per match.
- **Volume:** ~525,334 rows, 305 matches, 18 teams, 34 matchweeks.
- **Coordinates:** x, y ∈ [0, 100], attacking goal x = 100 (see zone_model).
- **Use:** touch/pass/defensive maps, player aggregates, inferred key passes,
  estimated xG, zones, goal-method classification.

## Wyscout team-match exports
- **Location:** `data/wyscout/`.
- **Volume:** 610 team-matches (both teams × 305 matches), 18 teams.
- **Use:** official scores (registry priority), xG, xGA, PPDA, possession.
- **Reconciliation:** 305/305 final scores match Wyscout exactly.

## Player position overrides
- **Location:** `data/reference/player_positions_ligue1_2025_26.csv`.
- **Use:** authoritative canonical positions by player. Columns: player_id,
  player_name, team_name_canon, primary_position, secondary_positions,
  position_group, source, source_url, confidence, notes.
- **Coverage:** curated corrections (e.g. O. Édouard → ST) plus season-roster
  dominance for the rest. FBref/Transfermarkt live scraping is blocked
  (HTTP 403) in this environment; see the file's README for the manual workflow.

## Derived disk cache
- **Location:** `data/.cache/<league>.parquet` (auto-generated, safe to delete).
- **Invalidation:** rebuilt when any source CSV is newer than the cache.
- **Excluded** from league discovery and packaging.

## Logos & colors
- **Location:** `assets/` — team logos; colors in `components/teams.py`.
- **Fallback:** short-name token when a logo is missing.
