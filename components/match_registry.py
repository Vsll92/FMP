"""
components/match_registry.py — ONE canonical source of truth for match scores.

The bug this fixes: own goals were credited to the scoring player's team, so
event-derived scores were wrong for 26/305 matches (e.g. Lens 2-1 Marseille was
shown as 1-2 because Pavard's own goal at x=7.0 counted for Marseille).

Score source priority:
  1. Wyscout official team-match score (authoritative) — when the fixture matches.
  2. Own-goal-aware event count                       — when Wyscout unavailable.
  3. Naive event count                                — last resort.
Conflicts are recorded (score_conflict + qa_warnings), never silently resolved.

Home is ALWAYS the left side of a scoreline; away is ALWAYS the right side.
A team-focused view may say "our team", but the scoreline stays home–away.
"""
import pandas as pd

# A goal scored from deep in the scorer's OWN half is an own goal: the ball went
# into their own net (x→0). Attribute it to the opponent. 35 is a safe threshold
# (real goals are taken from x>50, almost all from x>75).
_OWN_GOAL_MAX_X = 35.0


def compute_score_from_events(match_df, home_team, away_team):
    """Own-goal-aware event goal count → (home_goals, away_goals, n_own_goals).

    A 'Goal' event whose x-coordinate is in the scorer's own half (< 35) is an
    own goal and is credited to the opponent. Disallowed/VAR-deleted goals are
    not 'Goal' events in this provider (they become 'Deleted event'), so they're
    already excluded by filtering event == 'Goal'."""
    g = match_df[match_df["event"] == "Goal"].copy()
    if g.empty:
        return 0, 0, 0
    g["x"] = pd.to_numeric(g["x"], errors="coerce")
    hg = ag = og = 0
    for _, row in g.iterrows():
        team = row["team_name"]
        is_og = pd.notna(row["x"]) and row["x"] < _OWN_GOAL_MAX_X
        if is_og:
            og += 1
            credited = away_team if team == home_team else home_team
        else:
            credited = team
        if credited == home_team:
            hg += 1
        else:
            ag += 1
    return hg, ag, og


def _wyscout_score(wy_df, date, home_canon, away_canon):
    """Return (home_goals, away_goals) from Wyscout, oriented to home/away."""
    if wy_df is None or wy_df.empty:
        return None, None
    sub = wy_df[wy_df["date"] == str(date)[:10]]
    hrow = sub[sub["team_name_canon"] == home_canon]
    arow = sub[sub["team_name_canon"] == away_canon]
    if hrow.empty or arow.empty:
        return None, None
    h = hrow.iloc[0]
    # team_goals is the row-team's goals; for the home row that's home_goals.
    hg = h.get("team_goals")
    ag = h.get("opponent_goals")
    if pd.isna(hg) or pd.isna(ag):
        # fall back to parsed home/away goals on the row
        hg = h.get("home_goals"); ag = h.get("away_goals")
    if pd.isna(hg) or pd.isna(ag):
        return None, None
    return int(hg), int(ag)


def _vectorized_event_scores(df, home_map, away_map):
    """Own-goal-aware event goals for ALL matches in one pass.
    Returns dicts: ev_home[mid], ev_away[mid], n_og[mid]."""
    goals = df[df["event"] == "Goal"][["match_id", "team_name", "x"]].copy()
    if goals.empty:
        return {}, {}, {}
    goals["x"] = pd.to_numeric(goals["x"], errors="coerce")
    goals["home"] = goals["match_id"].map(home_map)
    goals["away"] = goals["match_id"].map(away_map)
    goals["is_og"] = goals["x"].notna() & (goals["x"] < _OWN_GOAL_MAX_X)
    is_home_scorer = goals["team_name"] == goals["home"]
    goals["credited_home"] = (is_home_scorer & ~goals["is_og"]) | (~is_home_scorer & goals["is_og"])
    ev_home = goals[goals["credited_home"]].groupby("match_id", observed=True).size().to_dict()
    ev_away = goals[~goals["credited_home"]].groupby("match_id", observed=True).size().to_dict()
    n_og = goals[goals["is_og"]].groupby("match_id", observed=True).size().to_dict()
    return ev_home, ev_away, n_og


def build_match_registry(league_folder, df=None, wy_df=None):
    """Build the canonical match table DIRECTLY from event + Wyscout data.

    This is the TRUE single source of truth: it derives match metadata (teams,
    dates, weeks) and resolves scores (own-goal aware + Wyscout authoritative)
    itself. It does NOT call get_match_list — get_match_list reads from here.
    One row per match_id. Vectorized + cached."""
    from data_loader import load_league_data, normalize_team
    if df is None:
        df = load_league_data(league_folder)
    if wy_df is None:
        try:
            from components.metric_engine import get_wyscout_df
            wy_df = get_wyscout_df()
        except Exception:
            wy_df = None

    # ── Match metadata directly from event data (one groupby pass) ──
    _agg = {
        "date": ("local_date", "first"),
        "week": ("week", "first"),
        "source_file": ("description", "first"),
    }
    # Cup/knockout metadata added by data_loader for files whose Opta week is NaN.
    for _c in ["round_name", "round_order", "competition_type", "source_file_name", "competition_name"]:
        if _c in df.columns:
            _agg[_c] = (_c, "first")
    meta = df.groupby("match_id", observed=True).agg(**_agg).reset_index()

    # ── Home/away teams per match (vectorized) ──
    hd = df[df["team_position"] == "home"].groupby("match_id", observed=True)["team_name"].first()
    ad = df[df["team_position"] == "away"].groupby("match_id", observed=True)["team_name"].first()
    hd_raw = (df[df["team_position"] == "home"].groupby("match_id", observed=True)["team_name_raw"].first()
              if "team_name_raw" in df.columns else hd)
    ad_raw = (df[df["team_position"] == "away"].groupby("match_id", observed=True)["team_name_raw"].first()
              if "team_name_raw" in df.columns else ad)
    home_map = {mid: normalize_team(v) for mid, v in hd.items()}
    away_map = {mid: normalize_team(v) for mid, v in ad.items()}
    home_raw_map = dict(hd_raw.items()); away_raw_map = dict(ad_raw.items())

    # ── Own-goal-aware event scores (one vectorized pass over all goals) ──
    ev_home, ev_away, n_og_map = _vectorized_event_scores(df, home_map, away_map)
    naive = df[df["event"] == "Goal"].groupby(["match_id", "team_name"], observed=True).size()

    # ── Wyscout score lookup dict (authoritative) ──
    wy_lookup = {}
    if wy_df is not None:
        for _, w in wy_df.iterrows():
            if pd.notna(w.get("team_goals")) and pd.notna(w.get("opponent_goals")):
                wy_lookup[(str(w["date"])[:10], w["team_name_canon"])] = (int(w["team_goals"]), int(w["opponent_goals"]))

    rows = []
    for _, m in meta.sort_values(["round_order" if "round_order" in meta.columns else "week", "date"]).iterrows():
        mid = m["match_id"]
        home = home_map.get(mid, "Unknown"); away = away_map.get(mid, "Unknown")
        ev_h = int(ev_home.get(mid, 0)); ev_a = int(ev_away.get(mid, 0)); n_og = int(n_og_map.get(mid, 0))
        wy_pair = wy_lookup.get((str(m.get("date"))[:10], home))
        wy_h, wy_a = (wy_pair if wy_pair else (None, None))
        try:
            naive_h = int(naive.get((mid, home), 0)); naive_a = int(naive.get((mid, away), 0))
        except Exception:
            naive_h = naive_a = 0

        # ── Safe stage metadata (league week or knockout round order) ──
        import pandas as _pd
        _week_raw = m.get("week", None)
        _round_order_raw = m.get("round_order", _week_raw)
        try:
            _round_order = int(0 if _pd.isna(_round_order_raw) else _round_order_raw)
        except Exception:
            _round_order = 0
        try:
            _matchweek = int(0 if _pd.isna(_week_raw) else _week_raw)
        except Exception:
            _matchweek = _round_order
        if not _matchweek:
            _matchweek = _round_order
        _round_name = m.get("round_name", f"Matchweek {_matchweek}")
        if _pd.isna(_round_name) or not str(_round_name).strip():
            _round_name = f"Matchweek {_matchweek}"
        _competition_type = m.get("competition_type", "league")
        if _pd.isna(_competition_type):
            _competition_type = "league"

        # ── Score source priority: Wyscout → event(own-goal aware) → naive ──
        qa = []
        if wy_h is not None:
            home_score, away_score, src = wy_h, wy_a, "Wyscout"
            if (ev_h, ev_a) != (wy_h, wy_a):
                qa.append(f"Event score {ev_h}-{ev_a} differs from Wyscout {wy_h}-{wy_a} (using Wyscout).")
        else:
            home_score, away_score, src = ev_h, ev_a, "Event (own-goal aware)"
        conflict = (wy_h is not None and (ev_h, ev_a) != (wy_h, wy_a))
        if (naive_h, naive_a) != (home_score, away_score) and n_og > 0:
            qa.append(f"{n_og} own goal(s) re-attributed to the opponent.")

        rows.append({
            "match_id": mid, "source_file": m.get("source_file"),
            "source_file_name": m.get("source_file_name"),
            "date": m.get("date"), "matchweek": _matchweek,
            "round_order": _round_order, "round_name": _round_name,
            "competition_type": str(_competition_type),
            "competition_name": m.get("competition_name"),
            "home_team_canon": home, "away_team_canon": away,
            "home_team_raw": home_raw_map.get(mid, home), "away_team_raw": away_raw_map.get(mid, away),
            "home_score": home_score, "away_score": away_score, "score_source": src,
            "event_home_goals": ev_h, "event_away_goals": ev_a,
            "naive_home_goals": naive_h, "naive_away_goals": naive_a,
            "wyscout_home_goals": wy_h, "wyscout_away_goals": wy_a,
            "filename_home_goals": None, "filename_away_goals": None,
            "n_own_goals": n_og, "score_conflict": conflict, "qa_warnings": qa,
        })
    return pd.DataFrame(rows)


# Module-level cache + accessors
_REGISTRY = {}


def get_registry(league_folder):
    if league_folder not in _REGISTRY:
        _REGISTRY[league_folder] = build_match_registry(league_folder)
    return _REGISTRY[league_folder]


def get_match_score(league_folder, match_id):
    """Canonical (home_score, away_score, source) for one match."""
    reg = get_registry(league_folder)
    row = reg[reg["match_id"] == match_id]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"home_score": int(r["home_score"]), "away_score": int(r["away_score"]),
            "source": r["score_source"], "conflict": bool(r["score_conflict"]),
            "qa_warnings": r["qa_warnings"]}


def validate_lens_marseille(league_folder):
    """Mandatory test: the W9 Lens vs Marseille fixture must be Lens 2-1."""
    reg = get_registry(league_folder)
    row = reg[(reg["home_team_canon"] == "Racing Club de Lens") &
              (reg["away_team_canon"] == "Olympique de Marseille") &
              (reg["matchweek"] == 9)]
    if row.empty:
        return {"ok": False, "detail": "W9 Lens-Marseille fixture not found"}
    r = row.iloc[0]
    ok = (int(r["home_score"]), int(r["away_score"])) == (2, 1)
    return {"ok": ok, "detail": f"Lens {r['home_score']}-{r['away_score']} Marseille (source: {r['score_source']})",
            "n_own_goals": int(r["n_own_goals"])}


# ── Tests (Phase 2 acceptance) ──────────────────────────────────────────
def test_lens_marseille_score_registry(league_folder="France_League_1_25-26"):
    """Lens vs Marseille (W9) must resolve to Lens 2-1 in the registry."""
    v = validate_lens_marseille(league_folder)
    assert v["ok"], f"Expected Lens 2-1, got {v['detail']}"
    return True


def test_get_match_list_reads_registry():
    """get_match_list must NOT contain independent score logic; it reads the
    registry. Verified by source inspection (no own-goal / Wyscout score code)."""
    import os
    dl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_loader.py")
    src = open(dl, encoding="utf-8").read()
    gml = src[src.find("def get_match_list"): src.find("def get_teams")]
    for forbidden in ("is_og", "x < 35", "wy_score"):
        assert forbidden not in gml, f"get_match_list still contains score logic: {forbidden}"
    assert "get_registry" in gml, "get_match_list must read from the registry"
    return True
