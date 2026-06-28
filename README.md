# Football Analytics Pro

Professional football analytics dashboard for **Ligue 1 2025-26** and **Coupe de France 2025-26**, built with Dash, Plotly, Opta-style event data, and Wyscout team-match exports.

The project is designed for analysts, coaches, scouts, and portfolio/demo use. It combines match intelligence, tactical maps, player profiling, head-to-head analysis, pre/post-match reporting, PDF export, and release QA checks.

---

## 1. Project Status

This GitHub-ready version includes:

- Ligue 1 league workflow with standings, matchweeks, trends, and season context.
- Coupe de France knockout workflow with round detection and cup-run tables.
- Wyscout-priority match registry for score truth where Wyscout data is available.
- Event-derived tactical maps, player radars, H2H analysis, and reports.
- Position-specific player influence logic.
- Post-match KPI context: match value vs team season average vs league average.
- Pre-match opponent goal-distribution logic for scouting reports.
- Release QA, smoke tests, and targeted regression tests.

> Recommended use: internal analytics demo, portfolio project, and controlled release testing. Before public/club-facing release, run the full QA checklist and verify the Dash UI in a browser on your machine.

---

## 2. Current Dataset Snapshot

### France Ligue 1 2025-26

| Metric | Value |
|---|---:|
| Events | 525,334 |
| Matches | 305 |
| Teams | 18 |
| Players | 572 |
| Competition format | League |

### France Coupe de France 2025-26

| Metric | Value |
|---|---:|
| Events | 108,703 |
| Matches | 63 |
| Teams | 64 |
| Competition format | Knockout cup |
| Supported rounds | 32nd Finals, 16th Finals, 8th Finals, Quarter-finals, Semi-finals, Final |

---

## 3. Main Features

### Overview

- League table and recent results for league competitions.
- Cup-round overview and team cup-run summary for knockout competitions.
- Team situation summary, Wyscout completeness banner, and context panels.

### Match Center

- Score banner and source-labelled match metrics.
- Match momentum and key events.
- Match statistics with Wyscout/Event source boundaries.
- Pitch-based lineup/formation view with fallback player tokens.

### Head-to-Head

- Team A vs Team B filtering.
- All H2H, Last Meeting, Last 3, Last 5, and Specific Match sample modes.
- Build-up profile, passing profile, tactical edge cards, and coaching summary.
- Season-context blocks are labelled separately from filtered H2H samples.

### Player Hub

- Canonical player position groups.
- Radar modes: max-normalized peer scale and percentile rank.
- Raw radar audit table: raw value, peer max, radar %, percentile, rank, source, confidence.
- Position-specific peer pools.
- Player heatmap / activity visuals and source caveats.

### Pitch Maps

- Touch map, pass origins, receptions, defensive actions, zone occupancy, shot zones, pass network, and shot map.
- Valid-event filtering for core tactical maps.
- Excludes out-of-play/admin/out-of-bounds rows where map semantics require valid football actions.
- Map footer summaries show plotted and excluded events.

### Trends

- Rolling form and tactical indicators.
- Pass Share is separated from Wyscout Possession.
- Trend interpretation and source labels.

### Match Reports

- Pre-match report uses the **selected opponent** for opposition goal distribution.
- Post-match report uses the selected team/match and adds season-average context for KPIs.
- Position-specific individual performance templates.
- Wyscout xG and Estimated Event xG are separated and caveated.
- PDF export uses the shared report model.

---

## 4. Installation

Use Python 3.11 where possible.

```bash
cd ligue1_dashboard
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Start the dashboard:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8050
```

---

## 5. Quality Checks

Run from the `ligue1_dashboard/` directory.

```bash
python -m compileall .
python scripts/run_smoke_tests.py
python scripts/run_release_readiness_checks.py
python tests/test_goal_distribution.py
python tests/test_post_match_kpi_context.py
python tests/test_radar_value_consistency.py
python tests/test_coupe_de_france_integration.py
```

Optional, if pytest is installed:

```bash
pytest -q
```

### Important QA expectations

The QA suite should verify:

- Lens vs Marseille score remains correct.
- Short aliases such as Lens, PSG, Monaco, Metz, and Marseille resolve correctly.
- Radar values are internally consistent.
- Pre-match goal profile follows the selected opponent.
- Post-match KPI context includes team and league averages.
- Coupe de France overview renders without league-table assumptions.
- Release checks do not hide critical blockers.

---

## 6. PDF Export Notes

PDF export works through the shared report model. For full chart/map embedding, install and verify chart-rendering dependencies:

- `kaleido` with compatible Chrome/Chromium, or
- a Playwright/Chromium HTML-to-PDF route if implemented locally.

If chart rendering is unavailable, PDFs fall back to table/logo/model-based output. Treat that as a debug/degraded mode, not a final club-facing visual export.

---

## 7. Data Structure

```text
data/
├── France_League_1_25-26/
│   └── *.csv
├── France_Coupe_de_France_25-26/
│   └── *.csv
├── reference/
│   ├── README.md
│   └── player_positions_ligue1_2025_26.csv
└── wyscout/
    └── *.csv / *.xlsx if available
```

The loader auto-discovers competition folders. Cup folders are detected as knockout competitions and use round labels instead of matchweeks.

---

## 8. Adding More Data

### Add another league

1. Create a new folder inside `data/`, for example:

```text
data/England_Premier_League_25-26/
```

2. Add event CSVs.
3. Restart the app.

### Add another cup

Cup filenames should start with a recognizable round label:

```text
32nd Finals_TeamA_TeamB_matchid.csv
Quarter-finals_TeamA_TeamB_matchid.csv
Final_TeamA_TeamB_matchid.csv
```

### Add logos

Add `128x128` PNG files to:

```text
assets/logos/
```

Update logo mappings in `data_loader.py` if needed.

### Add player positions

Update:

```text
data/reference/player_positions_ligue1_2025_26.csv
```

Use the columns documented in `docs/DATA_SOURCES.md`.

---

## 9. Known Limitations

- Wyscout data coverage is strongest for Ligue 1 team-match metrics. Coupe data relies mainly on event-derived scoring and metrics.
- Player positions are a mix of curated overrides and roster/event-derived inference. Confidence is labelled.
- Estimated Event xG is not official provider xG and is shown separately from Wyscout xG.
- PDF visual quality depends on local chart-rendering dependencies.
- A full manual browser QA pass is recommended after every major callback or UI change.

---

## 10. Repository Structure

```text
ligue1_dashboard/
├── app.py
├── data_loader.py
├── requirements.txt
├── assets/
│   ├── style.css
│   └── logos/
├── components/
│   ├── match_registry.py
│   ├── report_model.py
│   ├── report_pages.py
│   ├── pdf_export.py
│   ├── heatmaps.py
│   ├── radar.py
│   ├── h2h_engine.py
│   ├── h2h_metrics.py
│   └── ...
├── data/
├── docs/
├── scripts/
└── tests/
```

---

## 11. Recommended Release Checklist

Before public release:

- [ ] Run all QA commands successfully.
- [ ] Open the Dash app in a browser and test every page.
- [ ] Verify Pre-Match Report opponent goal distribution.
- [ ] Verify Post-Match KPI context for defensive/attacking metrics.
- [ ] Verify H2H Last Meeting filtering.
- [ ] Verify Player Hub radar values and raw table.
- [ ] Verify Pitch Map counts and map footer.
- [ ] Export pre/post PDFs and confirm visual quality.
- [ ] Review README and methodology for accuracy.


---

## 12. Project Presentation

A high-level professional PowerPoint deck is included in:

```text
docs/Football_Analytics_Pro_Project_Presentation.pptx
```

It summarises the project thesis, data estate, architecture, KPI methodology, dashboard modules, report workflow, cup integration, QA strategy, and demo storyline.
