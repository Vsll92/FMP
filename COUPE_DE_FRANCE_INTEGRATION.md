# Coupe de France 2025-26 Integration

This build integrates the uploaded **France Coupe de France 2025-26 Opta/eventing CSVs** as a second competition folder:

```text
data/France_Coupe_de_France_25-26/
```

## Knockout adaptation

Cup files usually do not contain a numeric league matchweek. The loader now infers the stage from the filename prefix:

- `32nd Finals` → round order 1
- `16th Finals` → round order 2
- `8th Finals` → round order 3
- `Quarter-finals` → round order 4
- `Semi-finals` → round order 5
- `Final` → round order 6

The dashboard keeps both:

- `round_name` for labels and UI filters
- `round_order` / `week` for sorting and compatibility with existing components

## UI behavior

When a knockout competition is selected:

- Overview switches from a league table to a knockout progress table.
- Match filters display cup stages instead of matchweeks.
- Match labels show the round name, scoreline, and date.
- Lower-division cup clubs are accepted as valid teams even if no logo is available.
- Existing Match Center, H2H, Player Hub, Pitch Maps, Trends, and Reports can load cup matches through the same event schema.

## QA checks

Run:

```bash
python scripts/run_release_readiness_checks.py --league France_Coupe_de_France_25-26
python tests/test_coupe_de_france_integration.py
```

Expected core counts:

- Events: 108,703
- Matches: 63
- Teams: 64
- Rounds: 6

## Caveats

- Wyscout Ligue 1 team-match spreadsheets do not cover Coupe de France, so cup scores fall back to event-derived, own-goal-aware scoring.
- Cup teams outside Ligue 1 use generated colors and no-logo fallbacks unless custom logo files are added.
- Penalty shootout winners are not separately modelled if the event data does not expose shootout metadata; level scorelines are displayed as `D/Pens` in progress summaries.
