# Radar consistency fix

This release fixes the Player Radar raw / peer max / radar percent / percentile / rank inconsistency.

## Fixed behaviour

- Raw value, peer max, radar %, percentile and rank are computed from the same unrounded peer vector.
- Max-normalized radar uses exact `player_value / peer_max * 100`.
- A player tied for peer max is ranked `1` or `T-1` and radar is exactly `100`.
- A player below the true peer max can no longer be rounded up to `100` in the radar table.
- The radar table now exposes exact values in hover text and includes the metric leader.
- If two displayed 2-decimal values look equal but the rank is not first, the table increases visible precision so the difference is explainable.

## Regression example

For the previous Key Passes bug:

- F. Thauvin raw key passes: `1.7575757576/match`
- Peer max: `1.7647058824/match` by S. Boufal
- Radar: `99.6`, not `100`
- Rank: `2`, not a misleading `3` with peer max rounded to the same visible value

## Added tests

- `tests/test_radar_value_consistency.py`
  - scans all eligible player data by position group
  - validates max/tie/rank consistency
  - validates the F. Thauvin key-pass rounding regression
