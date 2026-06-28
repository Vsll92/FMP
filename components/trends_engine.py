"""
components/trends_engine.py — Season Trends Page Builder
8 blocks: Form, Attacking, Defensive, Transition, Territory,
Chance Patterns, Set Pieces, Coaching Takeaways
All with rolling 3/5-match averages + season baseline.
"""

import pandas as pd
import numpy as np
from components.dash_compat import dcc, html
import plotly.graph_objects as go

from data_loader import (
    load_league_data, get_match_list, get_match_data, get_teams,
    get_team_results, compute_league_table,
    short, team_color, get_logo_base64, DEFAULT_CLUB,
)

# ── Unified flag detection (single source of truth) ──────────────────
try:
    from components.definitions import is_flag as _FLAGVAL
except Exception:
    _FLAG_TRUE = {"si","sí","yes","y","1","true","t","x","✓"}
    def _FLAGVAL(v):
        if v is None: return False
        if isinstance(v, bool): return v
        if isinstance(v,(int,float)): return (v==1) and not (isinstance(v,float) and v!=v)
        if isinstance(v,str): return v.strip().lower() in _FLAG_TRUE
        return False
def _flagmask(series):
    """Vectorised flag mask for a Series; safe on missing/typed columns."""
    import pandas as _pd
    if series is None or len(series)==0: return _pd.Series([], dtype=bool)
    return series.apply(_FLAGVAL)

from components.report_engine import (
    _xg_from_distance, _safe_pct, _safe_div,
    SHOT_EVENTS, FINAL_THIRD_X, MID_THIRD_X, BOX_X, BOX_Y_LO, BOX_Y_HI,
)
from components.charts import (


    BG, CARD_BG, GRID, TEXT, MUTED, GOLD,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, ACCENT_PURPLE, _tmpl,
)

# ══════════════════════════════════════════════════════════════════════════
#  TREND COLOR MAP — one distinct hue per metric so traces never collide.
#  Raw vs rolling-average of the SAME metric share a hue but differ by
#  line-style/opacity (handled in _rolling_chart), while DIFFERENT metrics
#  use clearly different hues (e.g. Pass Share ≠ Pass Accuracy).
# ══════════════════════════════════════════════════════════════════════════
ACCENT_CYAN = "#00D8D8"
TREND_COLOR_MAP = {
    "Pass Share %": ACCENT_BLUE,
    "Field Tilt %": ACCENT_GREEN,
    "Pass Acc %": GOLD,
    "Shots": ACCENT_BLUE,
    "SOT": ACCENT_GREEN,
    "Big Chances": ACCENT_RED,
    "Prog Passes": ACCENT_PURPLE,
    "Box Entries": ACCENT_CYAN,
    "FT Entries": ACCENT_CYAN,
    "xG": GOLD,
    "xGA": ACCENT_RED,
    "Open Play xG": GOLD,
    "Set Piece xG": ACCENT_PURPLE,
    "Central %": ACCENT_GREEN,
    "Left %": ACCENT_BLUE,
    "Right %": ACCENT_PURPLE,
}


def _trend_color(label, fallback=GOLD):
    return TREND_COLOR_MAP.get(label, fallback)


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════
def _card(title, children, s=None):
    return html.Div(className="card", style=s or {}, children=[
        html.Div(title, className="card-t") if title else None,
        *(children if isinstance(children, list) else [children]),
    ])

def _section(num, title, sub=""):
    return html.Div(style={"marginBottom": "14px", "paddingBottom": "8px", "borderBottom": f"1px solid {GOLD}33"}, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px"}, children=[
            html.Span(str(num), style={"fontFamily": "Orbitron", "fontWeight": "900", "fontSize": "18px", "color": GOLD,
                                        "background": f"{GOLD}15", "borderRadius": "8px", "width": "32px", "height": "32px",
                                        "display": "inline-flex", "alignItems": "center", "justifyContent": "center"}),
            html.Div([html.Div(title, style={"fontWeight": "700", "fontSize": "15px", "color": "#fff"}),
                       html.Div(sub, style={"fontSize": "11px", "color": MUTED}) if sub else None]),
        ]),
    ])

def _trend_arrow(current, avg, higher_better=True):
    if current > avg * 1.05:
        return ("↑", ACCENT_GREEN if higher_better else ACCENT_RED, "Improving" if higher_better else "Worsening")
    elif current < avg * 0.95:
        return ("↓", ACCENT_RED if higher_better else ACCENT_GREEN, "Declining" if higher_better else "Improving")
    return ("→", MUTED, "Stable")

def _trend_kpi(val, label, avg=None, color=GOLD, higher_better=True):
    children = [
        html.Div(str(val) if isinstance(val, int) else f"{val:.2f}" if isinstance(val, float) else val,
                 className="kpi-v", style={"color": color, "fontSize": "18px"}),
        html.Div(label, className="kpi-l"),
    ]
    if avg is not None:
        arrow, ac, tip = _trend_arrow(float(val) if isinstance(val, (int, float)) else 0, avg, higher_better)
        children.append(html.Div(f"{arrow} vs avg {avg:.1f}", style={"fontSize": "9px", "color": ac, "marginTop": "2px"}))
    return html.Div(className="kpi", children=children)


def _rolling_line(fig, weeks, values, name, color, dash=None, width=2.5):
    """Add a line trace."""
    fig.add_trace(go.Scatter(
        x=weeks, y=values, mode="lines+markers", name=name,
        line=dict(color=color, width=width, dash=dash),
        marker=dict(size=5, color=color),
    ))

def _rolling_avg(values, window):
    """Compute rolling average."""
    s = pd.Series(values)
    return s.rolling(window, min_periods=1).mean().tolist()


# ══════════════════════════════════════════════════════════════════════════
#  MATCH-BY-MATCH STATS COMPUTATION
# ══════════════════════════════════════════════════════════════════════════
def _compute_match_metrics(df, team_name, match_id):
    """Compute key metrics for a single match for one team."""
    mdf = df[df["match_id"] == match_id]
    tdf = mdf[mdf["team_name"] == team_name]
    odf = mdf[mdf["team_name"] != team_name]

    passes = tdf[tdf["event"] == "Pass"]
    passes_end = passes.dropna(subset=["Pass End X", "Pass End Y"])
    opp_passes = odf[odf["event"] == "Pass"]
    shots = tdf[tdf["event"].isin(SHOT_EVENTS)]
    opp_shots = odf[odf["event"].isin(SHOT_EVENTS)]
    goals = tdf[tdf["event"] == "Goal"]
    opp_goals = odf[odf["event"] == "Goal"]

    # xG
    xg = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance"))) for _, s in shots.iterrows())
    xg_against = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance"))) for _, s in opp_shots.iterrows())

    # xG by context
    xg_op = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if not _FLAGVAL(s.get("Set piece")) and not _FLAGVAL(s.get("From corner")) and not _FLAGVAL(s.get("Fast break")))
    xg_sp = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if _FLAGVAL(s.get("Set piece")) or _FLAGVAL(s.get("From corner")))
    xg_fb = sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
                for _, s in shots.iterrows() if _FLAGVAL(s.get("Fast break")))

    # Progression — central metric engine (single source of truth)
    from components.metric_engine import (final_third_entries as _fte,
                                          box_entries as _bxe, progressive_passes as _pgp,
                                          field_tilt as _ftilt)
    prog = _pgp(tdf)
    ft_entries = _fte(tdf)
    box_entries = _bxe(tdf)

    # Possession (Pass Share), PPDA
    possession = _safe_pct(len(passes), len(passes) + len(opp_passes))
    opp_own = len(opp_passes[opp_passes["x"] < 50])
    our_def = len(tdf[(tdf["event"].isin(["Tackle", "Interception", "Foul"])) & (tdf["x"] > 50)])
    ppda = _safe_div(opp_own, our_def)

    # Field tilt = team FT touches / both teams' FT touches (territorial share)
    field_tilt = _ftilt(tdf, odf)

    # Defensive
    def_actions = tdf[tdf["event"].isin(["Tackle", "Interception", "Ball recovery"])]
    def_height = def_actions["x"].mean() if len(def_actions) > 0 else 50
    high_regains = len(tdf[(tdf["event"] == "Ball recovery") & (tdf["x"] > 50)])

    # Lanes
    left = len(passes_end[passes_end["Pass End Y"] >= 66.6]) if len(passes_end) > 0 else 0
    center = len(passes_end[(passes_end["Pass End Y"] >= 33.3) & (passes_end["Pass End Y"] < 66.6)]) if len(passes_end) > 0 else 0
    right = len(passes_end[passes_end["Pass End Y"] < 33.3]) if len(passes_end) > 0 else 0
    total_lane = max(left + center + right, 1)

    # Set pieces
    sp_shots = len(shots[(_flagmask(shots["Set piece"])) | (_flagmask(shots["From corner"]))])
    opp_sp_shots = len(opp_shots[(_flagmask(opp_shots["Set piece"])) | (_flagmask(opp_shots["From corner"]))])

    return {
        "goals": len(goals), "goals_against": len(opp_goals),
        "xg": round(xg, 3), "xg_against": round(xg_against, 3), "xg_diff": round(xg - xg_against, 3),
        "xg_open": round(xg_op, 3), "xg_sp": round(xg_sp, 3), "xg_fb": round(xg_fb, 3),
        "shots": len(shots), "sot": len(tdf[tdf["event"].isin(["Goal", "Saved Shot"])]),
        "opp_shots": len(opp_shots), "big_chances": len(shots[_flagmask(shots["Big Chance"])]),
        "passes": len(passes), "pass_acc": _safe_pct((passes["outcome"] == 1).sum(), len(passes)),
        "possession": possession, "field_tilt": field_tilt,
        "prog_passes": len(prog), "ft_entries": len(ft_entries), "box_entries": len(box_entries),
        "crosses": len(passes[_flagmask(passes["Cross"])]) if "Cross" in passes.columns else 0,
        "through_balls": len(passes[_flagmask(passes["Through ball"])]) if "Through ball" in passes.columns else 0,
        "ppda": ppda, "def_height": round(def_height, 1), "high_regains": high_regains,
        "tackles": len(tdf[tdf["event"] == "Tackle"]), "interceptions": len(tdf[tdf["event"] == "Interception"]),
        "recoveries": len(tdf[tdf["event"] == "Ball recovery"]), "clearances": len(tdf[tdf["event"] == "Clearance"]),
        "fb_shots": len(shots[_flagmask(shots["Fast break"])]), "fb_xg": round(xg_fb, 3),
        "opp_fb_shots": len(opp_shots[_flagmask(opp_shots["Fast break"])]),
        "transition_xg_against": round(sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
            for _, s in opp_shots[_flagmask(opp_shots["Fast break"])].iterrows()), 3),
        "sp_shots": sp_shots, "sp_xg": round(xg_sp, 3),
        "opp_sp_shots": opp_sp_shots, "opp_sp_xg": round(sum(_xg_from_distance(s["x"], s["y"], _FLAGVAL(s.get("Head")), _FLAGVAL(s.get("Big Chance")))
            for _, s in opp_shots[(_flagmask(opp_shots["Set piece"])) | (_flagmask(opp_shots["From corner"]))].iterrows()), 3),
        "lane_left": _safe_pct(left, total_lane), "lane_center": _safe_pct(center, total_lane), "lane_right": _safe_pct(right, total_lane),
    }


# ══════════════════════════════════════════════════════════════════════════
#  TRENDS PAGE BUILDER
# ══════════════════════════════════════════════════════════════════════════
def build_trends_page(lf, team_name, rolling_window=5, venue="all", opp_strength="all"):
    """Build the 8-block Trends page. Filters: venue (all/home/away),
    opp_strength (all/top6/mid/bottom6)."""
    df = load_league_data(lf)
    ml = get_match_list(lf)
    tc = team_color(team_name)

    # Get match list for this team, sorted by week
    tr = get_team_results(lf, team_name)
    if tr.empty:
        return html.Div("No data", style={"color": MUTED, "textAlign": "center", "padding": "60px"})

    tr = tr.sort_values("week")
    # ── Venue filter ──
    if venue == "home":
        tr = tr[tr["venue"] == "H"]
    elif venue == "away":
        tr = tr[tr["venue"] == "A"]
    # ── Opponent-strength filter (by final league position) ──
    if opp_strength != "all":
        from data_loader import compute_league_table
        lt = compute_league_table(lf)
        pos = {row["Team"]: i + 1 for i, (_, row) in enumerate(lt.iterrows())}
        if opp_strength == "top6":
            keep = lambda o: pos.get(o, 99) <= 6
        elif opp_strength == "bottom6":
            keep = lambda o: pos.get(o, 0) >= 13
        else:
            keep = lambda o: 7 <= pos.get(o, 0) <= 12
        tr = tr[tr["opponent"].apply(keep)]
    if tr.empty:
        return html.Div("No matches for the selected filters", style={"color": MUTED, "textAlign": "center", "padding": "60px"})

    match_ids = tr["match_id"].tolist()
    weeks = tr["week"].tolist()

    # Compute per-match metrics
    metrics = [_compute_match_metrics(df, team_name, mid) for mid in match_ids]
    n = len(metrics)

    def _get(key):
        return [m[key] for m in metrics]

    def _avg(key):
        vals = _get(key)
        return sum(vals) / max(len(vals), 1)

    rw = rolling_window

    def _rolling_chart(title, series_list, height=340, y_title=""):
        """Build a rolling average chart with multiple series. Raw = dotted/thin
        (lower opacity), rolling avg = solid/thick — so raw and avg of the same
        metric share a hue but stay distinguishable, and different metrics use
        distinct hues from TREND_COLOR_MAP."""
        fig = go.Figure()
        for name, values, color, dash in series_list:
            _rolling_line(fig, weeks, values, f"{name} (raw)", color, dash="dot", width=1)
            _rolling_line(fig, weeks, _rolling_avg(values, rw), f"{name} ({rw}m avg)", color, width=2.5)
        fig = _tmpl(fig, height=height)
        # Extra top margin so the horizontal legend never overflows the card;
        # legend wraps within the plot width.
        fig.update_layout(xaxis_title="Matchweek", yaxis_title=y_title,
                          margin=dict(l=55, r=25, t=64, b=44),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                      xanchor="center", x=0.5, font=dict(size=9),
                                      itemwidth=30))
        return fig

    sections = []

    # ════ 1. FORM SUMMARY ════
    sections.append(_section(1, "Form & Result Trends", f"Rolling {rw}-match averages"))
    xg_vals = _get("xg"); xga_vals = _get("xg_against")
    xg_diff = _get("xg_diff")
    fig_xg = _rolling_chart("xG Balance", [
        ("xG For", xg_vals, ACCENT_GREEN, None),
        ("xG Against", xga_vals, ACCENT_RED, None),
    ], y_title="xG")

    fig_xg_diff = _rolling_chart("xG Difference", [
        ("xG Diff", xg_diff, GOLD, None),
    ], height=260, y_title="xG Diff")
    # Add zero line
    fig_xg_diff.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.15)")

    last5 = metrics[-5:] if n >= 5 else metrics
    avg_xg = _avg("xg"); avg_xga = _avg("xg_against")
    l5_xg = sum(m["xg"] for m in last5) / max(len(last5), 1)
    l5_xga = sum(m["xg_against"] for m in last5) / max(len(last5), 1)

    sections.append(html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
        _trend_kpi(f"{l5_xg:.2f}", f"xG/M (L{len(last5)})", avg_xg, ACCENT_GREEN),
        _trend_kpi(f"{l5_xga:.2f}", f"xGA/M (L{len(last5)})", avg_xga, ACCENT_RED, higher_better=False),
        _trend_kpi(f"{_avg('possession'):.0f}%", "Avg Pass Share", color=tc),
        _trend_kpi(f"{_avg('ppda'):.1f}", "Avg PPDA", color=tc),
        _trend_kpi(f"{_avg('ft_entries'):.0f}", "Avg FT Entry", color=tc),
    ]))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("xG For vs Against", [dcc.Graph(figure=fig_xg, config={"displayModeBar": False})])]),
        html.Div(className="c6", children=[_card("xG Difference Trend", [dcc.Graph(figure=fig_xg_diff, config={"displayModeBar": False})])]),
    ]))

    # ════ 2. ATTACKING TRENDS ════
    sections.append(_section(2, "Attacking Trends", "Shots, chances, entries — are we creating more?"))
    fig_att = _rolling_chart("Attacking Output", [
        ("Shots", _get("shots"), ACCENT_BLUE, None),
        ("SOT", _get("sot"), ACCENT_GREEN, None),
        ("Big Chances", _get("big_chances"), GOLD, None),
    ], y_title="Count")
    fig_entries = _rolling_chart("Progression", [
        ("FT Entries", _get("ft_entries"), ACCENT_BLUE, None),
        ("Box Entries", _get("box_entries"), ACCENT_GREEN, None),
        ("Prog Passes", _get("prog_passes"), GOLD, None),
    ], y_title="Count")
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Shot Volume", [dcc.Graph(figure=fig_att, config={"displayModeBar": False})])]),
        html.Div(className="c6", children=[_card("Progression", [dcc.Graph(figure=fig_entries, config={"displayModeBar": False})])]),
    ]))

    # ════ 3. DEFENSIVE TRENDS ════
    sections.append(_section(3, "Defensive Trends", "Becoming harder to beat?"))
    fig_def = _rolling_chart("Defensive Metrics", [
        ("xG Against", _get("xg_against"), ACCENT_RED, None),
        ("Shots Conceded", _get("opp_shots"), "#FEB019", None),
    ], y_title="Count / xG")
    fig_press = _rolling_chart("Pressing & Regains", [
        ("PPDA", _get("ppda"), ACCENT_RED, None),
        ("High Regains", _get("high_regains"), ACCENT_GREEN, None),
    ], y_title="Value")
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Concession Trends", [dcc.Graph(figure=fig_def, config={"displayModeBar": False})])]),
        html.Div(className="c6", children=[_card("Pressing Trends", [dcc.Graph(figure=fig_press, config={"displayModeBar": False})])]),
    ]))

    # ════ 4. TRANSITION TRENDS ════
    sections.append(_section(4, "Transition Trends", "Fast-break danger for and against"))
    fig_trans = _rolling_chart("Transition xG", [
        ("Trans xG For", _get("fb_xg"), ACCENT_GREEN, None),
        ("Trans xG Against", _get("transition_xg_against"), ACCENT_RED, None),
    ], y_title="xG")
    sections.append(_card("Transition Balance", [dcc.Graph(figure=fig_trans, config={"displayModeBar": False})]))

    # ════ 5. TERRITORY & CONTROL ════
    sections.append(_section(5, "Territory & Control", "Pass share (event-derived), field tilt, pass accuracy"))
    fig_terr = _rolling_chart("Control Metrics", [
        ("Pass Share %", _get("possession"), _trend_color("Pass Share %"), None),
        ("Field Tilt %", _get("field_tilt"), _trend_color("Field Tilt %"), None),
        ("Pass Acc %", _get("pass_acc"), _trend_color("Pass Acc %"), None),
    ], y_title="%")
    sections.append(_card("Territory Trends", [
        dcc.Graph(figure=fig_terr, config={"displayModeBar": False}),
        html.Div("Pass Share is event-derived (share of total passes), not Wyscout true possession. "
                 "Field tilt = share of final-third touches.",
                 style={"fontSize": "10px", "color": MUTED, "marginTop": "6px", "fontStyle": "italic"}),
    ]))

    # ════ 6. CHANCE CREATION PATTERNS ════
    sections.append(_section(6, "Chance Creation Patterns", "How are goals being created?"))
    fig_xg_ctx = _rolling_chart("xG by Context", [
        ("Open Play xG", _get("xg_open"), GOLD, None),
        ("Set-Piece xG", _get("xg_sp"), ACCENT_BLUE, None),
        ("Fast-Break xG", _get("xg_fb"), ACCENT_GREEN, None),
    ], y_title="xG")
    fig_lanes = _rolling_chart("Attacking Lanes", [
        ("Left %", _get("lane_left"), ACCENT_BLUE, None),
        ("Central %", _get("lane_center"), GOLD, None),
        ("Right %", _get("lane_right"), ACCENT_GREEN, None),
    ], y_title="%")
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("xG by Source", [dcc.Graph(figure=fig_xg_ctx, config={"displayModeBar": False})])]),
        html.Div(className="c6", children=[_card("Lane Distribution", [dcc.Graph(figure=fig_lanes, config={"displayModeBar": False})])]),
    ]))

    # ════ 7. SET-PIECE TRENDS ════
    sections.append(_section(7, "Set-Piece Trends", "Dead-ball output for and against"))
    fig_sp = _rolling_chart("Set-Piece xG", [
        ("SP xG For", _get("sp_xg"), ACCENT_GREEN, None),
        ("SP xG Against", _get("opp_sp_xg"), ACCENT_RED, None),
    ], y_title="xG")
    sections.append(_card("Set-Piece Trends", [dcc.Graph(figure=fig_sp, config={"displayModeBar": False})]))

    # ════ 8. COACHING TAKEAWAYS ════
    sections.append(_section(8, "Coaching Takeaways", "Auto-generated from trend analysis"))

    # Analyze trends: compare last 5 vs season average
    takeaways = []
    l5_metrics = {k: sum(m[k] for m in last5) / max(len(last5), 1) for k in metrics[0].keys() if isinstance(metrics[0][k], (int, float))}
    season_metrics = {k: sum(m[k] for m in metrics) / n for k in metrics[0].keys() if isinstance(metrics[0][k], (int, float))}

    def _ta(icon, title, desc, status):
        color = {"up": ACCENT_GREEN, "down": ACCENT_RED, "stable": MUTED, "warn": "#FEB019"}.get(status, MUTED)
        return html.Div(style={"display": "flex", "gap": "10px", "padding": "8px 12px", "background": f"{color}08",
                                "borderLeft": f"3px solid {color}", "borderRadius": "6px", "marginBottom": "4px"}, children=[
            html.Span(icon, style={"fontSize": "16px"}),
            html.Div([html.Div(title, style={"fontWeight": "600", "fontSize": "12px"}),
                       html.Div(desc, style={"fontSize": "11px", "color": MUTED})]),
        ])

    # xG trend
    if l5_metrics.get("xg", 0) > season_metrics.get("xg", 0) * 1.1:
        takeaways.append(_ta("📈", "Improving: xG Creation", f"Last 5 avg {l5_metrics['xg']:.2f} vs season {season_metrics['xg']:.2f}", "up"))
    elif l5_metrics.get("xg", 0) < season_metrics.get("xg", 0) * 0.9:
        takeaways.append(_ta("📉", "Declining: xG Creation", f"Last 5 avg {l5_metrics['xg']:.2f} vs season {season_metrics['xg']:.2f}", "down"))

    if l5_metrics.get("xg_against", 0) > season_metrics.get("xg_against", 0) * 1.1:
        takeaways.append(_ta("⚠️", "Worsening: xG Conceded", f"Last 5 avg {l5_metrics['xg_against']:.2f} vs season {season_metrics['xg_against']:.2f}", "warn"))
    elif l5_metrics.get("xg_against", 0) < season_metrics.get("xg_against", 0) * 0.9:
        takeaways.append(_ta("🛡️", "Improving: Defensive Solidity", f"Last 5 avg {l5_metrics['xg_against']:.2f} vs season {season_metrics['xg_against']:.2f}", "up"))

    if l5_metrics.get("ppda", 12) < season_metrics.get("ppda", 12) * 0.85:
        takeaways.append(_ta("💨", "Improving: Press Intensity", f"PPDA down to {l5_metrics['ppda']:.1f} from {season_metrics['ppda']:.1f}", "up"))

    if l5_metrics.get("box_entries", 0) > season_metrics.get("box_entries", 0) * 1.15:
        takeaways.append(_ta("🎯", "Improving: Box Entries", f"Last 5 avg {l5_metrics['box_entries']:.0f} vs season {season_metrics['box_entries']:.0f}", "up"))
    elif l5_metrics.get("box_entries", 0) < season_metrics.get("box_entries", 0) * 0.85:
        takeaways.append(_ta("⚠️", "Declining: Box Penetration", f"Last 5 avg {l5_metrics['box_entries']:.0f} vs season {season_metrics['box_entries']:.0f}", "warn"))

    if l5_metrics.get("transition_xg_against", 0) > season_metrics.get("transition_xg_against", 0) * 1.2:
        takeaways.append(_ta("⚡", "Warning: Transition Vulnerability", f"Trans xG against rising — rest defense needs work", "warn"))

    if not takeaways:
        takeaways.append(_ta("✅", "Consistent Performance", "All key metrics within normal range of season averages", "stable"))

    sections.append(_card("Trend Analysis", takeaways))

    return html.Div(sections)
