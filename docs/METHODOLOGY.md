# Methodology

Football Analytics Pro converts Opta-style event data and Wyscout team-match exports into coach-facing analysis. The goal is not only to display numbers but to make them interpretable through source labels, season averages, league benchmarks, tactical maps, and report narratives.

---

## 1. Data Pipeline

1. **Competition discovery**
   - The app scans `data/` for competition-season folders.
   - League folders use matchweeks.
   - Cup folders use knockout round labels.

2. **Event loading**
   - CSVs are loaded into a unified event dataframe.
   - Team names are canonicalized.
   - Coordinate columns are normalized to the 0–100 pitch model.

3. **Match registry**
   - The match registry is the score source of truth.
   - Wyscout score is preferred where available.
   - Event-derived score is used as fallback.
   - Own goals and score conflicts are handled centrally.

4. **Wyscout integration**
   - Team-match metrics such as xG, xGA, PPDA and possession use Wyscout where available.
   - Event-derived estimates remain labelled separately.

5. **Player aggregation**
   - Player stats are built from event data and cached.
   - Key passes are inferred when no direct provider key-pass flag exists.
   - Player positions come from curated overrides, roster dominance, and event fallback with confidence labels.

6. **Reports and PDF**
   - Dash reports and PDFs use shared report models where possible.
   - Pre-match goal profile focuses on the selected opponent.
   - Post-match KPIs include team season average and league average context.

---

## 2. Competition Logic

### League competitions

League competitions support:

- standings
- matchweeks
- recent form
- season averages
- league comparisons
- trends

### Cup competitions

Knockout competitions support:

- round ordering
- cup-run summary
- round-by-round results
- no fake league table
- lower-division team fallback styling/logos

---

## 3. Source Hierarchy

### Scores

1. Wyscout official score
2. Event-derived valid goal count
3. Filename fallback
4. Conflict warning if disagreement exists

### Team-level performance

1. Wyscout metrics where available
2. Event-derived metrics where Wyscout does not provide the detail
3. Estimated/internal models only when labelled

### Player positions

1. Curated override by player ID
2. Curated override by name + team
3. Roster/season dominance
4. Event mode as last fallback

---

## 4. Report Methodology

### Pre-match reports

A pre-match report is an opposition and game-plan document. Goal Distribution should focus on the selected opponent, not always the report team.

Pre-match report includes:

- opponent goal profile
- opponent goals conceded profile
- team vs opponent KPIs
- threats and weaknesses
- key player roles
- recommended tactical plan
- sample-size badge
- source/caveats

### Post-match reports

A post-match report is an evaluation document. Key KPIs must answer whether a value was good or bad compared with:

- the team season average
- the league average
- the match context

Examples:

- Tackles Won: match vs team season avg vs league avg.
- Interceptions: match vs team season avg vs league avg.
- Recoveries: contextual interpretation, not automatically positive.
- PPDA: lower means more aggressive pressing.
- xGA: lower is better.

---

## 5. Radar Methodology

The Player Hub supports two radar modes.

### Max-normalized peer scale

Each metric is scaled against the maximum value in the player's position peer group.

```text
radar_value = player_value / peer_group_max * 100
```

This is intuitive for users who want the best player in a metric to be 100.

### Percentile rank

Each metric is ranked against position peers. This shows distribution position rather than distance from the leader.

### Consistency rule

Raw value, peer max, radar %, percentile and rank must be calculated from the same unrounded peer pool. If a value displays as 100, exact values and tie status must support that.

---

## 6. Pitch Map Methodology

Pitch maps use the central zone model and valid-event filtering.

### Valid-event filtering

Maps should not count:

- out-of-play events
- admin events
- substitutions
- deleted events
- null coordinates
- out-of-bounds coordinates

### Map-data parity

For each map:

- plotted dots
- zone counts
- footer counts
- tactical insights

should all use the same cleaned dataframe.

### Zone model

- Defensive third: x < 33.33
- Middle third: 33.33 <= x < 66.67
- Attacking third: x >= 66.67
- Five lanes: Wide L, Half-Space L, Central, Half-Space R, Wide R

---

## 7. Threat / Weakness Methodology

Threats and weaknesses are selected using normalized values:

- team value
- league average
- percentile
- directionality
- sample size
- confidence

This prevents generic repetition such as every team being labelled as a high-xG threat.

---

## 8. QA Methodology

QA must include:

- compile check
- smoke tests
- release-readiness checks
- goal-distribution tests
- radar consistency tests
- post-match KPI context tests
- cup integration tests
- manual browser QA for callbacks

A project should not be called public-release ready if tests hang, PDF export is broken, or the browser UI shows stale state.

---

## 9. Known Trust Boundaries

- Wyscout xG and Estimated Event xG differ by design.
- Player-position confidence is not always official provider data.
- Key passes are inferred unless official flags exist.
- PDF visual quality depends on local chart-rendering dependencies.
- Cup competitions may include clubs without logos/colors.

