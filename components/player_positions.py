"""
components/player_positions.py — authoritative player-position resolver.

Event-data modal position is unreliable (it mislabels strikers as CAM, etc.),
so it is only a last-resort fallback. This module loads a curated override CSV
(sourced from FBref / Transfermarkt / Wyscout) and resolves a canonical
position + position group with a clear source and confidence.

Public API:
  load_player_position_overrides()  -> DataFrame (cached)
  canonical_player_position(player_id, player_name, team_name, event_position)
      -> {"position", "group", "source", "confidence", "event_position",
          "mismatch"}
  normalize_position_group(code)   -> one of the 8 dashboard groups
"""
import os
import pandas as pd

_REF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "reference", "player_positions_ligue1_2025_26.csv")

_OVERRIDES = None

# External position code → dashboard group
_GROUP_MAP = {
    "FW": "ST", "ST": "ST", "CF": "ST", "SS": "ST",
    "LW": "Winger", "RW": "Winger", "LM": "Winger", "RM": "Winger", "W": "Winger",
    "AM": "AM", "CAM": "AM", "AMF": "AM", "AMC": "AM",
    "CM": "CM", "MF": "CM", "MC": "CM", "CMF": "CM",
    "DM": "DM", "CDM": "DM", "DMF": "DM",
    "LB": "FB/WB", "RB": "FB/WB", "LWB": "FB/WB", "RWB": "FB/WB", "FB": "FB/WB", "WB": "FB/WB",
    "CB": "CB", "DF": "CB", "DC": "CB",
    "GK": "GK",
}


def normalize_position_group(code):
    """Map any external/event position code to one of the 8 dashboard groups."""
    if not code:
        return "CM"
    c = str(code).strip().upper().replace(" ", "")
    if c in _GROUP_MAP:
        return _GROUP_MAP[c]
    # Try leading token (e.g. "AML" → "AM", "DRC" → "DF")
    for prefix in ("CAM", "CDM", "LWB", "RWB", "AM", "DM", "CM", "LB", "RB",
                   "CB", "LW", "RW", "LM", "RM", "GK", "ST", "CF", "FW"):
        if c.startswith(prefix):
            return _GROUP_MAP.get(prefix, "CM")
    return "CM"


def load_player_position_overrides():
    """Load (and cache) the curated position override CSV."""
    global _OVERRIDES
    if _OVERRIDES is not None:
        return _OVERRIDES
    try:
        df = pd.read_csv(_REF_PATH, dtype=str).fillna("")
        df["_name_key"] = df["player_name"].str.strip().str.lower()
        df["_team_key"] = df["team_name_canon"].str.strip().str.lower()
        _OVERRIDES = df
    except Exception:
        _OVERRIDES = pd.DataFrame(columns=[
            "player_name", "player_id", "team_name_canon", "primary_position",
            "secondary_positions", "position_group", "source", "source_url",
            "confidence", "notes", "_name_key", "_team_key"])
    return _OVERRIDES


def canonical_player_position(player_id=None, player_name=None, team_name=None,
                              event_position=None):
    """Resolve the canonical position with source priority. Returns a dict with
    position, group, source, confidence, event_position, and a mismatch flag."""
    ov = load_player_position_overrides()

    # 1) override by player_id (when present on both sides)
    if player_id is not None and len(ov) and "player_id" in ov.columns:
        hit = ov[(ov["player_id"] != "") & (ov["player_id"] == str(player_id))]
        if not hit.empty:
            return _from_override(hit.iloc[0], event_position)

    # 2) override by name + team
    if player_name and len(ov):
        nk = str(player_name).strip().lower()
        cand = ov[ov["_name_key"] == nk]
        if team_name is not None and not cand.empty:
            tk = str(team_name).strip().lower()
            team_cand = cand[cand["_team_key"] == tk]
            if not team_cand.empty:
                cand = team_cand
        if not cand.empty:
            return _from_override(cand.iloc[0], event_position)

    # 3) season-dominant roster position. Confidence is graded by how
    #    consistently the player occupies that position across the season:
    #    a player who lines up in one position for the large majority of their
    #    events is a high-confidence roster classification; a rotational/utility
    #    player who splits positions is medium.
    roster = _roster_positions()
    if player_id is not None and player_id in roster:
        dom, share = roster[player_id]
        grp = normalize_position_group(dom)
        event_grp = normalize_position_group(event_position) if event_position else None
        conf = "high" if share >= 0.75 else "medium"
        return {"position": dom, "group": grp,
                "source": f"Season roster ({share*100:.0f}% of appearances)",
                "confidence": conf,
                "event_position": event_position,
                "mismatch": bool(event_grp and event_grp != grp)}

    # 5) event-data fallback (last resort, low confidence)
    grp = normalize_position_group(event_position)
    return {"position": event_position or "?", "group": grp,
            "source": "Event data fallback", "confidence": "low",
            "event_position": event_position,
            "mismatch": False}  # nothing authoritative to disagree with


_ROSTER_CACHE = {}


def _roster_positions(league_folder=None):
    """Map player_id → (season-dominant position, dominance_share). Cached.

    The dominance share = fraction of the player's positioned events spent in
    their most-frequent position. A high share means the player consistently
    occupies one role (high confidence); a low share means a utility/rotational
    profile (medium confidence). Far more stable than per-call event mode."""
    if _ROSTER_CACHE:
        return _ROSTER_CACHE
    try:
        from data_loader import load_league_data
        import os
        lf = league_folder
        if lf is None:
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            for d in sorted(os.listdir(base)):
                if os.path.isdir(os.path.join(base, d)) and "wyscout" not in d.lower() \
                   and d not in ("reference", "cache", ".cache", "__pycache__") and not d.startswith("."):
                    lf = d
                    break
        df = load_league_data(lf)
        pl = df[df["player_id"].notna() & df["position"].notna() & (df["position"] != "")]
        for pid, grp in pl.groupby("player_id", observed=True)["position"]:
            counts = grp.value_counts()
            if len(counts) == 0:
                continue
            dom = counts.index[0]
            share = float(counts.iloc[0] / counts.sum())
            _ROSTER_CACHE[pid] = (dom, share)
    except Exception:
        pass
    return _ROSTER_CACHE


def _from_override(row, event_position):
    pos = row.get("primary_position") or "?"
    grp = row.get("position_group") or normalize_position_group(pos)
    src = row.get("source") or "Override"
    conf = (row.get("confidence") or "medium").lower()
    event_grp = normalize_position_group(event_position) if event_position else None
    mismatch = bool(event_grp and event_grp != grp)
    return {"position": pos, "group": grp,
            "source": f"{src} override", "confidence": conf,
            "event_position": event_position, "mismatch": mismatch}


def position_mismatch_table(player_rows):
    """Given an iterable of dicts with player_id/player_name/team_name/position
    (event), return the list of players whose event group differs from canonical.
    Used by release QA to surface suspicious event-only positions."""
    out = []
    for p in player_rows:
        res = canonical_player_position(p.get("player_id"), p.get("player_name"),
                                        p.get("team_name"), p.get("position"))
        if res["mismatch"]:
            out.append({"player": p.get("player_name"), "team": p.get("team_name"),
                        "event": p.get("position"), "canonical": res["position"],
                        "group": res["group"], "source": res["source"]})
    return out
