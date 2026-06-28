# Opponent Goal Distribution Fix

## Problem fixed
In the Pre-Match Report, the Goal Profile / Goal Distribution section was still showing the selected report team's goal distribution. For a pre-match scouting report, this section must describe the selected opponent.

## Implemented behavior
- Pre-match report header remains: `Report Team: {our_team} · Opponent: {opponent}`.
- Pre-match Goal Profile now renders: `How {opponent} score and concede`.
- Pre-match goal distribution values are calculated from the opponent's last-N sample.
- PDF export uses the same opponent goal-profile model.
- Post-match reports are unchanged: post-match Goal Distribution still describes the selected team for the selected match only.

## Verified
- `python -m compileall .` passes.
- `python scripts/run_release_readiness_checks.py` passes 20/20 checks.
- `python scripts/run_smoke_tests.py` passes 20/20 checks.
- `python tests/test_goal_distribution.py` passes 23/23 checks.

## Example validation
- Lens vs PSG pre-match report -> Goal Profile: `How PSG score and concede`.
- Lens vs Monaco pre-match report -> Goal Profile: `How Monaco score and concede`.
- PSG vs Lens pre-match report -> Goal Profile: `How Lens score and concede`.
