#!/usr/bin/env python3
"""Regression checks for Coupe de France knockout integration."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LF = "France_Coupe_de_France_25-26"

from data_loader import (
    discover_leagues, load_league_data, get_match_list, get_teams,
    get_rounds, is_knockout_lf, get_player_stats, compute_cup_progress_table,
    get_team_results, normalize_team,
)
from components.definitions import filter_valid_touch_events
from components.zone_model import zone_grid_counts


def _assert(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS {msg}")


def main():
    leagues = [x["folder"] for x in discover_leagues()]
    _assert(LF in leagues, "Coupe de France folder is discovered")
    _assert(is_knockout_lf(LF), "Coupe de France is detected as knockout competition")

    df = load_league_data(LF)
    ml = get_match_list(LF)
    teams = get_teams(LF)
    _assert(len(df) == 108703, f"event rows match uploaded cup data ({len(df)})")
    _assert(len(ml) == 63, f"match count is 63 ({len(ml)})")
    _assert(len(teams) == 64, f"team count is 64 ({len(teams)})")

    rounds = get_rounds(LF)
    labels = [r["label"] for r in rounds]
    _assert(labels == ["32nd Finals", "16th Finals", "8th Finals", "Quarter-finals", "Semi-finals", "Final"],
            f"round labels/order are correct: {labels}")
    _assert(ml["week"].notna().all() and ml["round_order"].notna().all(), "cup stage maps to numeric week/round_order")
    _assert(set(ml["competition_type"].astype(str)) == {"knockout"}, "match registry marks cup as knockout")

    final = ml[ml["round_name"] == "Final"]
    _assert(len(final) == 1, "single cup final is available")
    f = final.iloc[0]
    _assert(f["home_team"] == normalize_team("Lens") and f["away_team"] == "OGC Nice Côte d'Azur", "final teams are Lens vs Nice")
    _assert((int(f["home_goals"]), int(f["away_goals"])) == (3, 1), "final score is Lens 3-1 Nice")

    ps_lens = get_player_stats(LF, "Lens")
    _assert(len(ps_lens) >= 15 and ps_lens["goals"].sum() > 0, "Lens cup player stats work")

    cp = compute_cup_progress_table(LF)
    lens = cp[cp["Team"] == normalize_team("Lens")].iloc[0]
    _assert(lens["Reached"] == "Final" and int(lens["W"]) == 6, "Lens cup run reaches final with six wins")

    tr = get_team_results(LF, "Lens")
    _assert(len(tr) == 6 and tr.iloc[-1]["round_name"] == "Final", "team results use cup round labels")

    mid = final.iloc[0]["match_id"]
    tdf = df[(df["match_id"] == mid) & (df["team_name"] == normalize_team("Lens"))]
    valid, excluded = filter_valid_touch_events(tdf)
    grid = zone_grid_counts(valid)
    _assert(len(valid) > 0 and grid["total"] == len(valid), "cup pitch-map valid-touch count equals zone total")

    print("\nCoupe de France integration checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
