"""
tests/test_trust_fixes.py — strict trust-repair tests for the four user-proven
visible bugs. These tests are written against the ACTIVE code paths (the Dash
callbacks and the functions they actually call), not helper functions.

They are designed to FAIL on the buggy code and PASS once the fixes land:

  Phase 1 — Player Radar honesty (default = max-normalized; math is auditable;
            low-output players do not produce a full radar)
  Phase 3 — Report selected-team / stale-state (team is a live Input; the Goal
            Profile title follows the selected report team, never hardcoded)
  Phase 4 — H2H global filter (Match Results table obeys the scope filter; Last
            Meeting => exactly one row, same match_ids everywhere)
  Phase 5 — Pitch-Map count/dot trust (footer "Plotted" == dots drawn; Out and
            out-of-bounds excluded; zone counts sum to plotted)

Run:  python tests/test_trust_fixes.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

LF = "France_League_1_25-26"

# ─────────────────────────────────────────────────────────────────────────────
#  tiny test runner
# ─────────────────────────────────────────────────────────────────────────────
_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def _walk(node):
    """Yield every Dash component in a tree (children may be list/scalar/str)."""
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for c in children:
            if hasattr(c, "children") or hasattr(c, "to_plotly_json"):
                yield from _walk(c)
    elif hasattr(children, "children") or hasattr(children, "to_plotly_json"):
        yield from _walk(children)


def _find_by_id(tree, cid):
    for n in _walk(tree):
        if getattr(n, "id", None) == cid:
            return n
    return None


def _dots_in_touch_fig(fig):
    """Number of plotted marker points in a touch_heatmap figure (the real dots,
    excluding the 3 legend placeholder traces whose x is [None])."""
    total = 0
    for tr in fig.data:
        if getattr(tr, "mode", "") and "markers" in tr.mode:
            xs = tr.x if tr.x is not None else []
            real = [v for v in xs if v is not None]
            total += len(real)
    return total


# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 1 — PLAYER RADAR HONESTY
# ─────────────────────────────────────────────────────────────────────────────
def test_phase1_radar():
    print("\n── Phase 1: Player Radar honesty ──")
    import app as A
    from components.radar import compute_peer_percentiles
    import data_loader as dl

    # 1a. Active default scale must be max-normalized (not percentile).
    layout = A.page_players(LF)
    scale_dd = _find_by_id(layout, "pl-scale")
    check("Radar Scale dropdown default is max-normalized",
          scale_dd is not None and scale_dd.value == "max",
          f"value={getattr(scale_dd, 'value', None)}")

    # 1b. The callback's own fallback resolves a missing scale to 'max'.
    src = A.update_players.__wrapped__ if hasattr(A.update_players, "__wrapped__") else None
    # The fallback lives in the callback body; assert via source text on the module.
    import inspect
    body = inspect.getsource(A.update_players)
    check("Callback default scale fallback is 'max'",
          'scale = scale or "max"' in body or "scale = scale or 'max'" in body)

    # Pick a real player to audit the math.
    df = dl.load_league_data(LF)
    ps = dl.get_player_stats(LF)
    ps = ps[ps["matches"] >= 5]
    # an attacking-mid-ish high-minute player and a low-output player
    grp_col = "position_group" if "position_group" in ps.columns else "position"

    # 1c. Math invariant: round(raw / peer_max * 100) == maxnorm for every metric.
    audited = 0
    bad = []
    for _, row in ps.head(40).iterrows():
        grp = row.get(grp_col)
        if not isinstance(grp, str):
            continue
        peer = compute_peer_percentiles(df, row["player_id"], row["team_name"], grp)
        for k, mn in peer.get("maxnorm", {}).items():
            raw = peer["raw"].get(k); pmax = peer["peer_max"].get(k)
            if pmax and pmax > 0:
                expect = round(raw / pmax * 100)
                audited += 1
                if expect != mn:
                    bad.append((row["player_name"], k, raw, pmax, mn, expect))
    check("Max-normalized value == round(raw / peer_max * 100) for all metrics",
          audited > 0 and not bad,
          f"audited={audited}, mismatches={len(bad)}" + (f" e.g. {bad[0]}" if bad else ""))

    # 1d. A low-output player must NOT produce a full radar under max-norm,
    #     and max-norm must be visibly less inflated than percentile for them.
    #     Choose the lowest-output outfield player with >=5 matches.
    out = ps[ps[grp_col].isin(["AM", "CM", "Winger", "ST", "FB/WB", "DM", "CB"])].copy()
    out["_vol"] = out.get("goals", 0) + out.get("assists", 0) + out.get("shots", 0) \
        + out.get("tackles", 0) + out.get("interceptions", 0)
    low = out.sort_values("_vol").iloc[0]
    grp = low[grp_col]
    peer = compute_peer_percentiles(df, low["player_id"], low["team_name"], grp)
    mx = peer.get("maxnorm", {})
    pc = peer.get("percentiles", {})
    if mx:
        mean_max = sum(mx.values()) / len(mx)
        full_axes = sum(1 for v in mx.values() if v >= 90)
        check("Low-output player: max-norm radar is NOT full (mean < 60, few/no 90+ axes)",
              mean_max < 60 and full_axes <= 1,
              f"{low['player_name']} mean_maxnorm={mean_max:.0f}, axes>=90={full_axes}")
        if pc:
            mean_pct = sum(pc.values()) / len(pc)
            check("Max-norm is less inflated than percentile for low-output player",
                  mean_max <= mean_pct + 1,
                  f"mean_maxnorm={mean_max:.0f} <= mean_pctl={mean_pct:.0f}")
    else:
        check("Low-output player radar produced metrics", False, "no maxnorm metrics")

    # 1e. All-zero / zero-variance metrics are excluded (never shown as 100).
    #     If a metric is in maxnorm, its peer pool had variance and peer_max>0.
    zero_max_shown = [k for k, v in mx.items() if peer["peer_max"].get(k, 0) == 0]
    check("Zero-peer-max metrics are excluded from the radar",
          not zero_max_shown, f"offending={zero_max_shown}")


# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 3 — REPORT SELECTED-TEAM / STALE STATE
# ─────────────────────────────────────────────────────────────────────────────
def test_phase3_report():
    print("\n── Phase 3: Match Report selected-team / stale-state ──")
    import app as A
    from dash._callback import GLOBAL_CALLBACK_MAP as G
    import data_loader as dl

    spec = G["rp-content.children"]
    input_ids = {i["id"] for i in spec["inputs"]}

    # 3a. Team / opponent / sample / type are LIVE INPUTS (auto-regenerate),
    #     so changing the team can never leave a stale report on screen.
    for cid in ("rp-our-team", "rp-opponent", "rp-sample", "rp-type"):
        check(f"'{cid}' is a live Input of the report callback (Option A)",
              cid in input_ids, f"inputs={sorted(input_ids)}")

    # 3b. Pre-match Goal Profile title follows the SELECTED OPPONENT (scouting subject), never hardcoded.
    teams = dl.get_teams(LF)
    lens = dl.DEFAULT_CLUB
    psg = next((t for t in teams if "Paris" in t and "Paris FC" not in t), None) \
        or next(t for t in teams if t != lens)
    opp = next(t for t in teams if t not in (psg, lens))

    from components.report_pages import build_pre_match_report

    def _title_text(team):
        rep = build_pre_match_report(LF, team, opp, last_n=5)
        texts = []
        for n in _walk(rep):
            ch = getattr(n, "children", None)
            if isinstance(ch, str):
                texts.append(ch)
        return " | ".join(texts)

    t_psg = _title_text(psg)
    t_lens = _title_text(lens)
    check("Pre-match Goal Profile title says the selected opponent, not our/report team",
          ("How " + dl.short(opp) + " score" in t_psg) and ("How " + dl.short(psg) + " score" not in t_psg),
          f"contains opponent '{dl.short(opp)}': {'How ' + dl.short(opp) + ' score' in t_psg}")
    check("Selecting Lens as report team does NOT force Lens goal distribution unless Lens is opponent",
          "How " + dl.short(lens) + " score" not in t_lens)

    # 3c. PDF model uses the same selected team as the Dash report.
    from components.report_model import build_pre_match_report_model
    m = build_pre_match_report_model(LF, psg, opp, last_n=5)
    rep_team = (m.get("teams", {}) or {}).get("our")
    check("PDF report model carries the selected report team",
          rep_team == psg, f"model teams.our={rep_team}")
    check("PDF report model goal distribution carries the selected opponent",
          m.get("goal_profile_team") == opp, f"goal_profile_team={m.get('goal_profile_team')}")
    check("PDF model title names the selected team (PDF/Dash titles match)",
          dl.short(psg) in m.get("title", ""), f"title={m.get('title')}")


# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 4 — H2H GLOBAL FILTER
# ─────────────────────────────────────────────────────────────────────────────
def test_phase4_h2h():
    print("\n── Phase 4: H2H global filter ──")
    import data_loader as dl
    from components.h2h_metrics import resolve_h2h_match_ids
    from components.h2h_engine import build_h2h_page

    ml = dl.get_match_list(LF)
    teams = dl.get_teams(LF)
    pair = None
    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            sub = ml[((ml["home_team"] == a) & (ml["away_team"] == b)) |
                     ((ml["home_team"] == b) & (ml["away_team"] == a))]
            if len(sub) >= 2:
                pair = (a, b)
                break
        if pair:
            break
    a, b = pair

    ids_all, _ = resolve_h2h_match_ids(ml, a, b, "all")
    ids_last1, _ = resolve_h2h_match_ids(ml, a, b, "last1")

    # 4a. Last Meeting resolves to exactly one match id.
    check("Last Meeting resolves to exactly 1 match id",
          len(ids_last1) == 1, f"all={len(ids_all)}, last1={len(ids_last1)}")

    def _results_rows(scope):
        page = build_h2h_page(LF, a, b, scope=scope, selected_match_id=None)
        # find the Match Results table: a tbody under the card titled "Match Results"
        rows = None
        for n in _walk(page):
            if getattr(n, "__class__", None).__name__ == "Table":
                # count tbody rows
                for sub in _walk(n):
                    if sub.__class__.__name__ == "Tbody":
                        trs = [x for x in _walk(sub) if x.__class__.__name__ == "Tr"]
                        # header may not be in tbody; count Tr that contain a score cell
                        # heuristic: results rows contain a "W{n}" week cell
                        cnt = 0
                        for tr in trs:
                            txt = " ".join(str(getattr(c, "children", "")) for c in _walk(tr))
                            if "-" in txt:  # score like 2-1
                                cnt += 1
                        if cnt:
                            rows = cnt
        return rows

    n_all = _results_rows("all")
    n_last1 = _results_rows("last1")
    check("Match Results table shows ALL meetings under scope=all",
          n_all == len(ids_all), f"rows={n_all}, expected={len(ids_all)}")
    # 4b. The headline bug: results table must NOT show all games for Last Meeting.
    check("Match Results table obeys Last Meeting (exactly 1 row, not all)",
          n_last1 == 1, f"rows={n_last1}, expected=1")


# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 5 — PITCH-MAP COUNT / DOT / ZONE TRUST
# ─────────────────────────────────────────────────────────────────────────────
def test_phase5_maps():
    print("\n── Phase 5: Pitch-Map count/dot/zone trust ──")
    import re
    import data_loader as dl
    from components.definitions import filter_valid_touch_events
    from components.zone_model import zone_grid_counts, third_of
    import app as A

    ml = dl.get_match_list(LF)
    lens = dl.DEFAULT_CLUB
    lm = ml[(ml["home_team"] == lens) | (ml["away_team"] == lens)].iloc[0]
    mid = lm["match_id"]
    team = lens

    # Drive the REAL callback exactly as the UI does (Touch layer only).
    out = A.update_maps(mid, team, None, ["touch"], 2, "all",
                        ["def", "mid", "att"], "all", "auto", LF)

    # Extract the touch-map figure (dots) and the footer "Plotted: N" text from
    # the rendered component tree — i.e. the live, on-screen numbers.
    dots = None
    footer_plotted = None
    footer_excluded = None
    footer_thirds = None
    for n in _walk(out):
        fig = getattr(n, "figure", None)
        if fig is not None and dots is None:
            d = _dots_in_touch_fig(fig)
            if d:
                dots = d
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            mp = re.search(r"Plotted:\s*(\d+)", ch)
            if mp:
                footer_plotted = int(mp.group(1))
            me = re.search(r"Excluded:\s*(\d+)", ch)
            if me:
                footer_excluded = int(me.group(1))
            mt = re.search(r"Def/Mid/Att:\s*(\d+)/(\d+)/(\d+)", ch)
            if mt:
                footer_thirds = tuple(int(x) for x in mt.groups())

    # 5a. THE headline trust bug: footer "Plotted" must equal the dots drawn.
    check("LIVE footer Plotted count == dots drawn on the touch map",
          footer_plotted is not None and dots is not None and footer_plotted == dots,
          f"footer={footer_plotted}, dots={dots}")

    # 5b. Footer thirds sum to plotted (zone numbers reconcile with dots).
    check("LIVE footer Def/Mid/Att sums to Plotted",
          footer_thirds is not None and footer_plotted is not None
          and sum(footer_thirds) == footer_plotted,
          f"thirds={footer_thirds} sum={sum(footer_thirds) if footer_thirds else None}, plotted={footer_plotted}")

    # Underlying invariants on the same valid-touch frame the map/footer use.
    mdf = dl.get_match_data(LF, mid)
    src = mdf[mdf["team_name"] == team]
    plotted_df, n_excl = filter_valid_touch_events(src)

    # 5c. Out events are excluded.
    out_in_plotted = (plotted_df["event"].astype(str) == "Out").any()
    src_has_out = (src["event"].astype(str) == "Out").any()
    check("Out events excluded from plotted touches",
          (not out_in_plotted) and bool(src_has_out),
          f"src_has_Out={bool(src_has_out)}, in_plotted={bool(out_in_plotted)}")

    # 5d. Out-of-bounds coordinates excluded (never clamped).
    xs = pd.to_numeric(plotted_df["x"], errors="coerce")
    ys = pd.to_numeric(plotted_df["y"], errors="coerce")
    oob = ((xs < 0) | (xs > 100) | (ys < 0) | (ys > 100)).sum()
    src_oob = (((pd.to_numeric(src["x"], errors="coerce") < 0) |
                (pd.to_numeric(src["x"], errors="coerce") > 100))).sum()
    check("Out-of-bounds coordinates excluded (and existed in source)",
          oob == 0 and src_oob > 0, f"oob_in_plotted={int(oob)}, oob_in_src={int(src_oob)}")

    # 5e. 18-zone grid counts sum to plotted dots.
    grid = zone_grid_counts(plotted_df, x_col="x", y_col="y")
    zsum = sum(grid["cells"].values())
    check("18-zone grid counts sum to plotted dots",
          zsum == len(plotted_df), f"zone_sum={zsum}, plotted={len(plotted_df)}")

    # 5f. Third boundaries are exact (def<33.33, mid, att>=66.67).
    mism = 0
    for x in xs.dropna():
        t = third_of(x)
        if x < 33.33 and t != "def":
            mism += 1
        elif 33.33 <= x < 66.67 and t != "mid":
            mism += 1
        elif x >= 66.67 and t != "att":
            mism += 1
    check("Third assignment matches x bands (def<33.33, mid, att>=66.67)",
          mism == 0, f"mismatch={mism}")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("TRUST-REPAIR TEST SUITE — Phases 1, 3, 4, 5")
    print("=" * 70)
    test_phase1_radar()
    test_phase3_report()
    test_phase4_h2h()
    test_phase5_maps()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"RESULT: {passed}/{total} checks passed")
    print("=" * 70)
    failed = [(n, d) for n, ok, d in _RESULTS if not ok]
    if failed:
        print("FAILURES:")
        for n, d in failed:
            print(f"  ✗ {n}  — {d}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
