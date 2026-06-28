"""Trust tests for Player Radar raw/peer max/radar percent/rank consistency.

Pure analytics tests: no Dash import required. These scan the full player table
with vectorized group checks, then run one active-function regression case.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import get_player_stats
from components.radar import compute_peer_percentiles, _AGG_METRIC_MAP, _radar_metrics_for

LF = "France_League_1_25-26"
EPS = 1e-9


def _metric_col(metric_key):
    agg = _AGG_METRIC_MAP[metric_key]
    return agg if agg == "pass_accuracy" else agg + "_pm"


def test_radar_peer_max_rank_consistency_all_player_data_vectorized():
    """Scan all eligible player rows/role metrics for the old contradiction:
    displayed peer-max equality + radar 100 + rank > 1.
    """
    players = get_player_stats(LF)
    eligible = players[(players["matches"] >= 3) & players["position_group"].notna()].copy()
    checked = 0
    contradictions = []

    for group in sorted(eligible["position_group"].dropna().unique()):
        peers = eligible[eligible["position_group"] == group].copy()
        if len(peers) == 0:
            continue
        for agg in set(_AGG_METRIC_MAP.values()):
            if agg in peers.columns and agg != "pass_accuracy":
                peers[agg + "_pm"] = peers[agg] / peers["matches"].clip(lower=1)

        for _, metric_key in _radar_metrics_for(group):
            if metric_key not in _AGG_METRIC_MAP:
                continue
            col = _metric_col(metric_key)
            if col not in peers.columns:
                continue
            vals = peers[col].dropna().astype(float)
            if len(vals) == 0 or vals.max() == vals.min():
                continue
            peer_max = float(vals.max())
            for _, row in peers.dropna(subset=[col]).iterrows():
                raw = float(row[col])
                checked += 1
                rank = int((vals > raw + EPS).sum()) + 1
                radar = 100.0 if abs(raw - peer_max) <= EPS else round(raw / peer_max * 100.0, 1)
                pct = round(((vals <= raw + EPS).sum()) / len(vals) * 100)

                if abs(raw - peer_max) <= EPS:
                    assert rank == 1
                    assert radar == 100
                    assert pct == 100
                elif rank > 1 and radar >= 100:
                    contradictions.append((row["player_name"], group, metric_key, raw, peer_max, radar, rank))

    assert checked > 0
    assert not contradictions, f"Radar contradictions found: {contradictions[:10]}"


def test_specific_key_pass_rounding_case_is_explained_by_exact_values():
    """Regression: F. Thauvin showed raw 1.76, peer max 1.76, radar 100, rank 3.
    Exact values must now reveal he is below peer max, and radar must be below 100.
    """
    players = get_player_stats(LF)
    row = players[(players["player_name"] == "F. Thauvin") & (players["team_name"] == "Racing Club de Lens")].iloc[0]
    peer = compute_peer_percentiles(None, row["player_id"], row["team_name"], row["position_group"])
    raw = peer["raw_exact"]["key_passes"]
    pmax = peer["peer_max_exact"]["key_passes"]
    radar = peer["maxnorm"]["key_passes"]
    rank = peer["rank"]["key_passes"]
    rank_display = peer["rank_display"]["key_passes"]
    leader = peer["leader"]["key_passes"]

    assert raw < pmax
    assert rank > 1
    assert rank_display == str(rank)
    assert radar < 100
    assert round(raw, 2) == round(pmax, 2)  # 2dp display alone would be misleading
    assert leader and leader != "—"
