"""
components/metric_engine.py — SINGLE SOURCE OF TRUTH for football metrics.

Every page (H2H, Trends, Reports, Charts, Match Center) must call these
functions instead of re-deriving metrics inline. This guarantees that a
"box entry" or "field tilt" means exactly the same thing everywhere.

All functions take a per-team event DataFrame (already filtered to one team
and the relevant matches) plus, where needed, the opponent frame.

Definitions (locked):
  Final-third entry : COMPLETED pass starting outside the final third (x < 66.6)
                      and ending inside it (end_x >= 66.6).
  Box entry         : COMPLETED pass starting outside the box and ending inside
                      the 18-yard box (x in [83.5,100], y in [21.1,78.9]).
  Field tilt        : team FT touches / (team + opponent FT touches).
  Corners           : passes flagged 'Corner taken' (NOT 'Corner Awarded').
  Progressive pass  : pass that moves the ball >= 10 (x units) towards goal.
  Pass Share        : team passes / (team + opp passes) — event-derived proxy,
                      NOT true time-based possession.
"""
import numpy as np
import pandas as pd

from components.definitions import (
    FINAL_THIRD_X, BOX_X, BOX_Y_LO, BOX_Y_HI, SHOT_EVENTS, is_flag,
)

PASS_SHARE_NOTE = "Pass Share is event-derived from pass counts, not true time-based possession."
EST_XG_NOTE = "Estimated xG is a dashboard model, not official provider xG."


def flag_mask(series):
    """Vectorized central flag detection (handles Si/sí/yes/1/True/x/✓)."""
    if series is None:
        return pd.Series(dtype=bool)
    return series.apply(is_flag)


def _passes(team_df):
    p = team_df[team_df["event"] == "Pass"]
    return p, p.dropna(subset=["Pass End X", "Pass End Y"]) if "Pass End X" in p.columns else (p, p.iloc[0:0])


def _completed(passes_end):
    if "outcome" in passes_end.columns:
        return passes_end["outcome"] == 1
    return pd.Series(True, index=passes_end.index)


# ── ENTRIES ────────────────────────────────────────────────────────────────
def final_third_entries(team_df):
    """Completed passes starting outside final third, ending inside."""
    _, pe = _passes(team_df)
    if pe.empty:
        return pe
    comp = _completed(pe)
    return pe[comp & (pe["x"] < FINAL_THIRD_X) & (pe["Pass End X"] >= FINAL_THIRD_X)]


def box_entries(team_df):
    """Completed passes starting outside the box, ending inside it."""
    _, pe = _passes(team_df)
    if pe.empty:
        return pe
    comp = _completed(pe)
    starts_in = ((pe["x"] >= BOX_X) & (pe["y"] >= BOX_Y_LO) & (pe["y"] <= BOX_Y_HI))
    ends_in = ((pe["Pass End X"] >= BOX_X) & (pe["Pass End Y"] >= BOX_Y_LO) & (pe["Pass End Y"] <= BOX_Y_HI))
    return pe[comp & (~starts_in) & ends_in]


def progressive_passes(team_df):
    """Completed passes advancing the ball >= 10 x-units towards goal."""
    _, pe = _passes(team_df)
    if pe.empty:
        return pe
    comp = _completed(pe)
    return pe[comp & ((pe["Pass End X"] - pe["x"]) >= 10)]


# ── TERRITORY ────────────────────────────────────────────────────────────────
def field_tilt(team_df, opp_df):
    """Team final-third touches / both teams' final-third touches (territorial)."""
    t = len(team_df[(team_df["x"].notna()) & (team_df["x"] > FINAL_THIRD_X)])
    o = len(opp_df[(opp_df["x"].notna()) & (opp_df["x"] > FINAL_THIRD_X)])
    return round(t / (t + o) * 100, 1) if (t + o) > 0 else 0.0


def pass_share(team_df, opp_df):
    """Team passes / (team + opp passes). Event-derived proxy, not possession."""
    t = len(team_df[team_df["event"] == "Pass"])
    o = len(opp_df[opp_df["event"] == "Pass"])
    return round(t / (t + o) * 100, 1) if (t + o) > 0 else 0.0


# ── SET PIECES & SHOTS ────────────────────────────────────────────────────────
def corners(team_df):
    """Corners = passes flagged 'Corner taken' (NOT the double-counted event)."""
    p = team_df[team_df["event"] == "Pass"]
    if "Corner taken" not in p.columns:
        return 0
    return int(flag_mask(p["Corner taken"]).sum())


def shots(team_df):
    return team_df[team_df["event"].isin(SHOT_EVENTS)]


def big_chances(team_df):
    s = shots(team_df)
    if "Big Chance" not in s.columns:
        return 0
    return int(flag_mask(s["Big Chance"]).sum())


def set_piece_shots(team_df):
    """Shots originating from a set piece (flag on the shot event)."""
    s = shots(team_df)
    n = 0
    for col in ("From corner", "Set piece", "Free kick taken"):
        if col in s.columns:
            n = max(n, int(flag_mask(s[col]).sum()))
    return n


# ── PPDA ─────────────────────────────────────────────────────────────────────
def ppda(team_df, opp_df, max_x_def=60.0):
    """Passes allowed per defensive action in the opponent's build-up area.
    PPDA = opp passes in their own 60% / our defensive actions in that zone."""
    opp_passes = opp_df[(opp_df["event"] == "Pass") & (opp_df["x"].notna()) & (opp_df["x"] < max_x_def)]
    defs = team_df[team_df["event"].isin(["Tackle", "Interception", "Challenge", "Foul"])]
    # our defensive actions occur in opponent's build-up = our attacking 60%+
    defs = defs[defs["x"].notna() & (defs["x"] > (100 - max_x_def))]
    d = len(defs)
    return round(len(opp_passes) / d, 1) if d > 0 else 0.0


# ── ESTIMATED xG ─────────────────────────────────────────────────────────────
def estimated_xg(team_df):
    """Sum of per-shot estimated xG using the shared distance/angle model."""
    s = shots(team_df)
    if s.empty:
        return 0.0
    total = 0.0
    for _, r in s.iterrows():
        x = r.get("x"); y = r.get("y")
        if pd.isna(x) or pd.isna(y):
            continue
        is_head = is_flag(r.get("Head")) if "Head" in s.columns else False
        is_bc = is_flag(r.get("Big Chance")) if "Big Chance" in s.columns else False
        total += _xg_one(float(x), float(y), is_head, is_bc)
    return round(total, 2)


def _xg_one(x, y, is_head=False, is_big_chance=False):
    dist = np.sqrt((100 - x) ** 2 + (50 - y) ** 2)
    angle = np.arctan2(7.32, max(dist, 1))
    xg = np.exp(-dist / 16) * 0.55
    xg *= min(angle / 0.30, 1.0)
    xg = float(np.clip(xg, 0.02, 0.85))
    if is_head:
        xg *= 0.7
    if is_big_chance:
        xg = min(max(xg * 1.5, 0.35), 0.90)
    return xg


# ── BUNDLED PER-TEAM METRICS (used by H2H / Trends so they agree) ────────────
def team_match_metrics(team_df, opp_df):
    """Return the locked metric set for one team in one match (or sample)."""
    return {
        "passes": len(team_df[team_df["event"] == "Pass"]),
        "pass_share": pass_share(team_df, opp_df),
        "field_tilt": field_tilt(team_df, opp_df),
        "ft_entries": len(final_third_entries(team_df)),
        "box_entries": len(box_entries(team_df)),
        "prog_passes": len(progressive_passes(team_df)),
        "corners": corners(team_df),
        "shots": len(shots(team_df)),
        "big_chances": big_chances(team_df),
        "set_piece_shots": set_piece_shots(team_df),
        "est_xg": estimated_xg(team_df),
        "ppda": ppda(team_df, opp_df),
    }


# ══════════════════════════════════════════════════════════════════════════
#  WYSCOUT-FIRST SOURCE HIERARCHY  (single entry point for team-level metrics)
# ══════════════════════════════════════════════════════════════════════════
# Source priority for TEAM-LEVEL metrics:
#   1. Wyscout official team metric (if the fixture is matched)        → "Wyscout"
#   2. Event-derived metric                                            → "Event-derived"
#   3. Estimated model value (e.g. shot-quality xG)                    → "Estimated"
#   4. Neither available                                               → "Unavailable"
#
# Wyscout values here are TEAM MATCH TOTALS, never shot-level or player-level.
# Shot maps / player xG stay "Estimated" because no shot-level Wyscout exists.

_WYSCOUT_CACHE = {}


def get_wyscout_df():
    """Load (and cache) the bundled Wyscout team-match dataframe. Returns df or None.
    Uses an on-disk pickle cache so repeat app starts skip the 5s Excel parse."""
    import os
    if "df" in _WYSCOUT_CACHE:
        return _WYSCOUT_CACHE["df"]
    from components.wyscout_loader import load_wyscout_team_matches
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(here, ".cache")
    pkl = os.path.join(cache_dir, "wyscout_team_matches.pkl")
    for cand in (os.path.join(here, "data", "wyscout", "Stats Teams France Ligue 1"),
                 os.path.join(here, "data", "wyscout")):
        if os.path.isdir(cand):
            # Fast path: load from pickle if newer than the source folder
            try:
                if os.path.exists(pkl):
                    src_mtime = max((os.path.getmtime(os.path.join(cand, f)) for f in os.listdir(cand)), default=0)
                    if os.path.getmtime(pkl) >= src_mtime:
                        import pandas as pd
                        df = pd.read_pickle(pkl)
                        _WYSCOUT_CACHE["df"] = df
                        _WYSCOUT_CACHE["qa"] = {"team_matches": len(df), "teams": df["team_name_canon"].nunique()}
                        print(f"[WYSCOUT] Loaded {len(df)} team-matches from cache.")
                        return df
            except Exception:
                pass
            try:
                df, qa = load_wyscout_team_matches(cand)
                _WYSCOUT_CACHE["df"] = df
                _WYSCOUT_CACHE["qa"] = qa
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                    df.to_pickle(pkl)
                except Exception:
                    pass
                print(f"[WYSCOUT] Loaded {qa['team_matches']} team-matches, {qa['teams']} teams.")
                return df
            except Exception as e:
                print(f"[WYSCOUT] Load failed: {e}")
    _WYSCOUT_CACHE["df"] = None
    return None


def get_wyscout_qa():
    if "qa" not in _WYSCOUT_CACHE:
        get_wyscout_df()
    return _WYSCOUT_CACHE.get("qa", {})


def source_badge(source: str) -> str:
    """Short human label for a metric source."""
    return {"Wyscout": "Wyscout official", "Event-derived": "Event-derived",
            "Estimated": "Estimated", "Unavailable": "Unavailable"}.get(source, source)


def get_match_summary_metrics(league_folder, match_id, team_canon, opp_canon,
                              date=None, team_df=None, opp_df=None):
    """Unified team-level match metrics with Wyscout-first source hierarchy.

    Returns a dict of {metric: {"value", "source", "label"}}. Wyscout official
    values win where the fixture is matched; otherwise event-derived/estimated.
    Pass team_df/opp_df (event frames) to enable the event-derived fallback and
    the always-event-derived entries/field-tilt."""
    out = {}
    wy = get_wyscout_df()
    wrow = orow = None
    if wy is not None and date is not None:
        from components.wyscout_loader import wyscout_lookup
        # caller gives home/away; we look up by team/opp regardless of side
        sub = wy[wy["date"] == str(date)[:10]]
        tw = sub[sub["team_name_canon"] == team_canon]
        ow = sub[sub["team_name_canon"] == opp_canon]
        wrow = tw.iloc[0].to_dict() if not tw.empty else None
        orow = ow.iloc[0].to_dict() if not ow.empty else None

    def put(metric, wy_key, ev_func=None, label_w=None, label_e=None, fmt=None):
        if wrow is not None and wy_key in wrow and pd.notna(wrow.get(wy_key)):
            v = wrow[wy_key]
            out[metric] = {"value": v, "source": "Wyscout", "label": label_w or metric}
        elif ev_func is not None:
            try:
                v = ev_func()
                out[metric] = {"value": v, "source": "Event-derived", "label": label_e or metric}
            except Exception:
                out[metric] = {"value": None, "source": "Unavailable", "label": metric}
        else:
            out[metric] = {"value": None, "source": "Unavailable", "label": metric}

    # xG / xGA — Wyscout team totals preferred; estimated fallback
    put("xg", "wyscout_xg",
        ev_func=(lambda: estimated_xg(team_df)) if team_df is not None else None,
        label_w="Wyscout xG", label_e="Estimated xG")
    # xGA = opponent's xG
    if orow is not None and pd.notna(orow.get("wyscout_xg")):
        out["xga"] = {"value": orow["wyscout_xg"], "source": "Wyscout", "label": "Wyscout xGA"}
    elif opp_df is not None:
        out["xga"] = {"value": estimated_xg(opp_df), "source": "Estimated", "label": "Estimated xGA"}
    else:
        out["xga"] = {"value": None, "source": "Unavailable", "label": "xGA"}

    put("ppda", "wyscout_ppda",
        ev_func=(lambda: ppda(team_df, opp_df)) if (team_df is not None and opp_df is not None) else None,
        label_w="Wyscout PPDA", label_e="Estimated PPDA")
    put("possession", "wyscout_possession_pct",
        ev_func=(lambda: pass_share(team_df, opp_df)) if (team_df is not None and opp_df is not None) else None,
        label_w="Wyscout Possession %", label_e="Pass Share %")
    put("shots", "wyscout_shots",
        ev_func=(lambda: len(shots(team_df))) if team_df is not None else None,
        label_w="Wyscout Shots", label_e="Shots")
    put("shots_on_target", "wyscout_shots_on_target",
        ev_func=(lambda: len(team_df[team_df["event"].isin(["Goal", "Saved Shot"])])) if team_df is not None else None,
        label_w="Wyscout SoT", label_e="Shots on Target")
    put("corners", "wyscout_corners",
        ev_func=(lambda: corners(team_df)) if team_df is not None else None,
        label_w="Wyscout Corners", label_e="Corners")
    put("passes", "wyscout_passes",
        ev_func=(lambda: len(team_df[team_df["event"] == "Pass"])) if team_df is not None else None,
        label_w="Wyscout Passes", label_e="Passes")

    # Always event-derived (no Wyscout equivalent): entries, field tilt
    if team_df is not None:
        out["ft_entries"] = {"value": len(final_third_entries(team_df)), "source": "Event-derived", "label": "Final-Third Entries"}
        out["box_entries"] = {"value": len(box_entries(team_df)), "source": "Event-derived", "label": "Box Entries"}
        if opp_df is not None:
            out["field_tilt"] = {"value": field_tilt(team_df, opp_df), "source": "Event-derived", "label": "Estimated Field Tilt"}
    return out


# ══════════════════════════════════════════════════════════════════════════
#  KEY PASS INFERENCE
#  Provider schema has no clean "Key pass" flag and "Leading to attempt" is
#  attached to Error/Deleted rows (0 passes), so key passes are inferred:
#  the last completed same-team pass before a shot, within a short time window.
# ══════════════════════════════════════════════════════════════════════════
SHOT_EVENTS_KP = ["Goal", "Miss", "Post", "Saved Shot"]


def infer_key_passes(match_df, window_seconds=15, include_set_pieces=False):
    """Single-match inferred key passes. Delegates to the vectorized core so the
    same logic is used everywhere (kept for tests / per-match use)."""
    return _vectorized_key_passes(match_df, window_seconds)


def _legacy_infer_key_passes(match_df, window_seconds=15, include_set_pieces=False):
    """Reference per-shot implementation (unused; kept for provenance).
    Returns a dict player_id -> count.

    For each shot, look backwards (same match, same team, ordered by time) for
    the most recent completed pass within `window_seconds`; credit its passer
    with a key pass. Marks source as inferred (medium confidence)."""
    import pandas as pd
    if match_df.empty:
        return {}
    df = match_df.copy()
    # Build an absolute time in seconds for ordering within the match
    tmin = pd.to_numeric(df.get("time_min"), errors="coerce").fillna(0)
    tsec = pd.to_numeric(df.get("time_sec"), errors="coerce").fillna(0)
    df["_abs_sec"] = tmin * 60 + tsec
    df = df.sort_values("_abs_sec").reset_index(drop=True)

    counts = {}
    passes = df[df["event"] == "Pass"]
    if "outcome" in passes.columns:
        passes = passes[passes["outcome"] == 1]
    shots = df[df["event"].isin(SHOT_EVENTS_KP)]

    for _, shot in shots.iterrows():
        if not include_set_pieces:
            # skip shots that are clearly set-piece/penalty derived
            if _is_flag(shot.get("From corner")) or _is_flag(shot.get("Penalty")) \
               or _is_flag(shot.get("Free kick taken")):
                continue
        t_shot = shot["_abs_sec"]
        team = shot["team_name"]
        cand = passes[(passes["team_name"] == team) &
                      (passes["_abs_sec"] <= t_shot) &
                      (passes["_abs_sec"] >= t_shot - window_seconds)]
        if cand.empty:
            continue
        passer = cand.iloc[-1]  # most recent completed pass before the shot
        pid = passer.get("player_id")
        # don't credit the shooter passing to himself
        if pid is not None and pid == shot.get("player_id"):
            continue
        if pid is not None:
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def _is_flag(v):
    try:
        from components.definitions import is_flag
        return is_flag(v)
    except Exception:
        import pandas as pd
        return pd.notna(v) and str(v).strip().lower() not in ("", "0", "0.0", "nan", "none", "false")


_KP_TABLE_CACHE = {}


def build_inferred_key_pass_table(df):
    """Vectorized league-wide inferred key passes → {player_id: count}. Cached by
    dataframe identity/shape so it is built at most once per loaded season."""
    key = (id(df), getattr(df, "shape", (0,))[0])
    if key in _KP_TABLE_CACHE:
        return _KP_TABLE_CACHE[key]
    table = _vectorized_key_passes(df)
    _KP_TABLE_CACHE[key] = table
    return table


def _vectorized_key_passes(df, window_seconds=15):
    """Compute inferred key passes for ALL matches in ONE vectorized pass.

    For each open-play shot, find the most recent completed same-team pass within
    `window_seconds` before it via a per-(match, team) merge_asof. Credits the
    passer. No per-shot Python loop, no per-match full-dataframe rescans.
    """
    import pandas as pd
    if df is None or df.empty:
        return {}
    need = ["match_id", "team_name", "event", "player_id", "time_min", "time_sec"]
    if any(c not in df.columns for c in need):
        return {}

    extra = [c for c in ("outcome", "From corner", "Penalty", "Free kick taken") if c in df.columns]
    work = df[need + extra].copy()
    work["_abs"] = (pd.to_numeric(work["time_min"], errors="coerce").fillna(0) * 60
                    + pd.to_numeric(work["time_sec"], errors="coerce").fillna(0)).astype(float)

    passes = work[work["event"] == "Pass"]
    if "outcome" in passes.columns:
        passes = passes[passes["outcome"] == 1]
    passes = passes[["match_id", "team_name", "_abs", "player_id"]].rename(columns={"player_id": "passer_id"})
    passes = passes.dropna(subset=["_abs"]).sort_values("_abs")

    shots = work[work["event"].isin(SHOT_EVENTS_KP)].copy()
    from components.definitions import flag_mask
    for flagcol in ("From corner", "Penalty", "Free kick taken"):
        if flagcol in shots.columns:
            shots = shots[~flag_mask(shots[flagcol])]
    shots = shots[["match_id", "team_name", "_abs", "player_id"]].rename(columns={"player_id": "shooter_id"})
    shots = shots.dropna(subset=["_abs"]).sort_values("_abs")

    if passes.empty or shots.empty:
        return {}

    merged = pd.merge_asof(
        shots, passes, on="_abs", by=["match_id", "team_name"],
        direction="backward", tolerance=float(window_seconds),
    )
    merged = merged.dropna(subset=["passer_id"])
    merged = merged[merged["passer_id"] != merged["shooter_id"]]
    if merged.empty:
        return {}
    counts = merged.groupby("passer_id", observed=True).size()
    return {pid: int(c) for pid, c in counts.items()}


def infer_key_passes_for_team(df, league_folder=None, team_name=None, match_ids=None):
    """Aggregate inferred key passes → dict player_id -> count. Uses the fast
    cached league-wide table; filters by team/matches without rescanning."""
    if team_name is None and match_ids is None:
        return dict(build_inferred_key_pass_table(df))
    sub = df
    if match_ids is not None:
        sub = sub[sub["match_id"].isin(match_ids)]
    if team_name is not None:
        sub = sub[sub["team_name"] == team_name]
    if sub.empty:
        return {}
    mids = sub["match_id"].unique()
    counts = _vectorized_key_passes(df[df["match_id"].isin(mids)])
    if team_name is not None:
        team_pids = set(sub["player_id"].dropna().unique())
        counts = {pid: c for pid, c in counts.items() if pid in team_pids}
    return counts
