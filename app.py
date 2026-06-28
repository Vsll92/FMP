"""
═══════════════════════════════════════════════════════════════════════════════
  FOOTBALL ANALYTICS PRO — Multi-League Match Intelligence Dashboard
  Stack: Dash 2.x + Plotly + Flask
  Default: RC Lens (Sang et Or)
  Data: Auto-discovers league-season folders in data/
═══════════════════════════════════════════════════════════════════════════════
"""

from components.dash_compat import dash, dcc, html, Input, Output, State, callback, no_update
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import os, sys

from data_loader import (
    discover_leagues, load_league_data, get_match_list, get_teams,
    get_match_data, filter_by_period, filter_by_minutes,
    compute_league_table, compute_match_stats, get_player_stats,
    get_match_lineup, get_head_to_head, get_top_scorers, get_top_assists,
    get_week_fixtures, get_team_results, get_rounds, is_knockout_lf, compute_cup_progress_table,
    get_logo_base64, short, team_color, TEAM_COLORS,
    DEFAULT_CLUB, LENS_GOLD, LENS_RED,
)
from components.charts import (
    match_stats_bars, match_stats_comparison_component, shot_map, pass_map,
    defensive_map, pass_network, match_momentum_graph, player_radar,
    player_comparison_radar, possession_zones, team_form_chart,
    shot_quality_scatter, BG, CARD_BG, GRID, TEXT, MUTED, GOLD,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, ACCENT_PURPLE, _tmpl,
)
from components.heatmaps import (
    action_heatmap, touch_heatmap, pass_origin_heatmap,
    reception_heatmap, defensive_heatmap, shot_heatmap,
    zone_occupancy_heatmap, player_season_heatmap,
)
from components.report_pages import build_pre_match_report, build_post_match_report

# ═══════════════════════════════════════════════════════════════════════════
#  INIT
# ═══════════════════════════════════════════════════════════════════════════
print("⚽ Discovering leagues...")
leagues = discover_leagues()
if not leagues:
    print("❌ No data found in data/ folder. Add league-season subfolders with CSVs.")
    sys.exit(1)

DEFAULT_LEAGUE = next((lg["folder"] for lg in leagues if "League_1" in lg["folder"] or "Ligue" in lg["display_name"]), leagues[0]["folder"])
for lg in leagues:
    print(f"  📂 {lg['display_name']} — {lg['csv_count']} matches")

print(f"\n⚽ Loading default league: {DEFAULT_LEAGUE}")
_ = load_league_data(DEFAULT_LEAGUE)
ml = get_match_list(DEFAULT_LEAGUE)
teams = get_teams(DEFAULT_LEAGUE)
print(f"✅ {len(ml)} matches, {len(teams)} teams loaded")

app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="Football Analytics Pro",
    update_title="Loading…",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server

# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def logo_img(team, size=40):
    src = get_logo_base64(team)
    if src:
        return html.Img(src=src, style={"width": f"{size}px", "height": f"{size}px", "objectFit": "contain"})
    return html.Span(short(team)[:3], style={"fontWeight": "700", "fontSize": f"{size//3}px"})

def kpi(val, label, color=GOLD):
    return html.Div(className="kpi", children=[
        html.Div(str(val), className="kpi-v", style={"color": color}),
        html.Div(label, className="kpi-l"),
    ])

def card(title, children, **kwargs):
    return html.Div(className="card", children=[
        html.Div(title, className="card-t") if title else None,
        *(children if isinstance(children, list) else [children]),
    ], **kwargs)

def form_dots(form_list):
    return html.Span([html.Span(r, className=f"form-dot form-{r}") for r in form_list])

def empty_fig(h=380):
    fig = go.Figure()
    fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG, height=h,
                      font=dict(color=TEXT), xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig

def match_opts(lf):
    ml = get_match_list(lf)
    opts = []
    is_cup = is_knockout_lf(lf)
    sort_cols = ["round_order", "local_date"] if "round_order" in ml.columns else ["week", "local_date"]
    for _, r in ml.sort_values(sort_cols).iterrows():
        stage = r.get("round_name", f"W{r['week']}") if is_cup else f"W{r['week']}"
        label = f"{stage}  {short(r['home_team'])} {r['home_goals']}-{r['away_goals']} {short(r['away_team'])}  ({r['local_date']})"
        opts.append({"label": label, "value": r["match_id"]})
    return opts

def team_opts(lf):
    return [{"label": short(t), "value": t} for t in get_teams(lf)]

def week_opts(lf):
    if is_knockout_lf(lf):
        return get_rounds(lf)
    ml = get_match_list(lf)
    return [{"label": f"Matchweek {int(w)}", "value": int(w)} for w in sorted(ml["week"].unique())]

def round_label(lf, value):
    if value is None:
        return "Latest"
    for r in get_rounds(lf):
        if int(r["value"]) == int(value):
            return r["label"]
    return f"Matchweek {value}"

def find_default_team(lf):
    """Return Lens if in this league, else first team."""
    teams = get_teams(lf)
    if DEFAULT_CLUB in teams:
        return DEFAULT_CLUB
    return teams[0] if teams else None


# ═══════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════════════
lens_logo_b64 = get_logo_base64(DEFAULT_CLUB)

app.layout = html.Div(style={"backgroundColor": "#0B0E11", "minHeight": "100vh"}, children=[
    # Store for current league
    dcc.Store(id="store-league", data=DEFAULT_LEAGUE),

    # ── Header ─────────────────────────────────────────────────────────
    html.Div(className="hdr", children=[
        html.Img(src=lens_logo_b64, className="hdr-logo") if lens_logo_b64 else html.Span("⚽", style={"fontSize": "24px"}),
        html.Div("Football Analytics Pro", className="hdr-title"),
        html.Div(className="hdr-sub", children=[
            html.Span(className="pulse"),
            html.Span("Multi-League · Eventing Data Engine"),
        ]),
        html.Div(className="hdr-league-sel", children=[
            dcc.Dropdown(
                id="league-selector",
                options=[{"label": lg["display_name"], "value": lg["folder"]} for lg in leagues],
                value=DEFAULT_LEAGUE,
                clearable=False, className="dd",
            ),
        ]),
    ]),

    # ── Tabs ───────────────────────────────────────────────────────────
    dcc.Tabs(id="tabs", value="tab-overview", className="custom-tabs", children=[
        dcc.Tab(label="📊 Overview", value="tab-overview", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="⚽ Match Center", value="tab-match", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="⚔️ Head-to-Head", value="tab-h2h", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="👤 Player Hub", value="tab-players", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="🗺️ Pitch Maps", value="tab-maps", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="📈 Trends", value="tab-trends", className="tab", selected_className="tab tab--selected"),
        dcc.Tab(label="📋 Match Reports", value="tab-reports", className="tab", selected_className="tab tab--selected"),
    ]),

    html.Div(id="tab-content", className="content"),
])


# ═══════════════════════════════════════════════════════════════════════════
#  TAB ROUTER
# ═══════════════════════════════════════════════════════════════════════════
@callback(Output("tab-content", "children"),
          Input("tabs", "value"), Input("league-selector", "value"))
def route(tab, lf):
    # Clear league-context metrics cache when switching seasons
    ctx_key = f"league_metrics_{lf}"
    from data_loader import _CACHE, get_match_list
    stale = [k for k in _CACHE if k.startswith("league_metrics_") and k != ctx_key]
    for k in stale:
        del _CACHE[k]

    # ── Season-safe guard: no season selected or no data on disk ──
    if not lf:
        return _empty_state("No season selected",
                            "Choose a competition / season from the selector above.")
    try:
        ml = get_match_list(lf)
    except Exception:
        ml = None
    if ml is None or ml.empty:
        return _empty_state(
            "Data for this season is not available",
            f"No converted match CSV files were found for “{lf.replace('_',' ')}”. "
            f"Add CSV files to data/{lf}/ and reload.")

    try:
        if tab == "tab-overview": return page_overview(lf)
        if tab == "tab-match": return page_match(lf)
        if tab == "tab-h2h": return page_h2h(lf)
        if tab == "tab-players": return page_players(lf)
        if tab == "tab-maps": return page_maps(lf)
        if tab == "tab-trends": return page_trends(lf)
        if tab == "tab-reports": return page_reports(lf)
    except Exception as e:
        import traceback; traceback.print_exc()
        return _empty_state("This page could not be loaded",
                            f"An error occurred while building this page for the selected season. ({str(e)[:160]})")
    return html.Div("Select a tab")


def _empty_state(title, subtitle):
    """Professional empty/fallback state for missing season data or load errors."""
    return html.Div(style={"textAlign": "center", "padding": "80px 30px"}, children=[
        html.Div("⚠️", style={"fontSize": "40px", "marginBottom": "14px", "opacity": "0.6"}),
        html.Div(title, style={"fontSize": "18px", "fontWeight": "700", "color": "#C8D0DA", "marginBottom": "8px"}),
        html.Div(subtitle, style={"fontSize": "13px", "color": "#5A6575", "maxWidth": "460px", "margin": "0 auto", "lineHeight": "1.6"}),
    ])


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 1: OVERVIEW (with sub-tabs: Home Page + General Stats)
# ═══════════════════════════════════════════════════════════════════════════
def _wyscout_banner(lf):
    """Data-completeness banner: Wyscout coverage vs project matches."""
    try:
        from components.metric_engine import get_wyscout_df, get_wyscout_qa
        from components.wyscout_loader import wyscout_lookup
        from data_loader import get_match_list
        wy = get_wyscout_df()
        if wy is None or wy.empty:
            return html.Div()
        qa = get_wyscout_qa()
        ml = get_match_list(lf)
        matched = sum(1 for _, m in ml.iterrows()
                      if all(wyscout_lookup(wy, m["local_date"], m["home_team"], m["away_team"])))
        cov = round(matched / len(ml) * 100) if len(ml) else 0
        return html.Div(style={"display": "flex", "gap": "18px", "padding": "10px 16px",
                               "background": "#10151D", "borderRadius": "10px", "marginBottom": "12px",
                               "border": "1px solid #1E2733", "fontSize": "11px", "color": "#8A95A5",
                               "alignItems": "center", "flexWrap": "wrap"}, children=[
            html.Span([html.Span("● ", style={"color": "#00E396"}), f"Wyscout official: {matched}/{len(ml)} matches ({cov}%)"]),
            html.Span(f"Team-matches loaded: {qa.get('team_matches', 0)}"),
            html.Span(f"Teams: {qa.get('teams', 0)}"),
            html.Span("Wyscout xG/PPDA/Possession used where available; entries & maps are event-derived",
                      style={"color": "#5A6575", "fontStyle": "italic"}),
        ])
    except Exception:
        return html.Div()


def _wyscout_match_kpis(lf, mid, h, a):
    """Horizontal strip of Wyscout official team metrics for the selected match.
    Falls back to a clear note when the fixture isn't matched to Wyscout."""
    try:
        from components.metric_engine import get_wyscout_df, source_badge
        from components.wyscout_loader import wyscout_lookup
        from data_loader import get_match_list, short as _short
        wy = get_wyscout_df()
        if wy is None:
            return html.Div()
        ml = get_match_list(lf)
        row = ml[ml["match_id"] == mid]
        if row.empty:
            return html.Div()
        r = row.iloc[0]
        hw, aw = wyscout_lookup(wy, r["local_date"], r["home_team"], r["away_team"])
        if not hw or not aw:
            return html.Div(style={"padding": "8px 14px", "marginBottom": "10px", "background": "#10151D",
                                   "borderRadius": "8px", "fontSize": "11px", "color": "#8A95A5"},
                            children="Wyscout data unavailable for this match — using event-derived estimates.")

        def metric_block(label, hv, av, fmt="{:.2f}"):
            return html.Div(style={"flex": "1", "textAlign": "center", "padding": "4px"}, children=[
                html.Div(label, style={"fontSize": "9px", "color": "#5A6575", "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                html.Div(style={"display": "flex", "justifyContent": "center", "gap": "10px", "marginTop": "3px"}, children=[
                    html.Span(fmt.format(hv) if hv is not None else "—", style={"color": "#008FFB", "fontWeight": "700", "fontSize": "14px", "fontFamily": "Orbitron, monospace"}),
                    html.Span("vs", style={"color": "#3A4555", "fontSize": "9px", "alignSelf": "center"}),
                    html.Span(fmt.format(av) if av is not None else "—", style={"color": "#FFD700", "fontWeight": "700", "fontSize": "14px", "fontFamily": "Orbitron, monospace"}),
                ]),
            ])

        return html.Div(style={"marginBottom": "12px"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "marginBottom": "6px"}, children=[
                html.Span("WYSCOUT OFFICIAL", style={"fontSize": "10px", "fontWeight": "700", "color": "#00E396", "letterSpacing": "1px"}),
                html.Span(f"{_short(r['home_team'])} (blue) vs {_short(r['away_team'])} (gold)", style={"fontSize": "10px", "color": "#5A6575"}),
            ]),
            html.Div(style={"display": "flex", "gap": "6px", "padding": "10px", "background": "#10151D",
                            "borderRadius": "10px", "border": "1px solid #1E2733"}, children=[
                metric_block("Wyscout xG", hw.get("wyscout_xg"), aw.get("wyscout_xg")),
                metric_block("Wyscout PPDA", hw.get("wyscout_ppda"), aw.get("wyscout_ppda"), "{:.1f}"),
                metric_block("Possession %", hw.get("wyscout_possession_pct"), aw.get("wyscout_possession_pct"), "{:.1f}"),
                metric_block("Shots", hw.get("wyscout_shots"), aw.get("wyscout_shots"), "{:.0f}"),
                metric_block("Corners", hw.get("wyscout_corners"), aw.get("wyscout_corners"), "{:.0f}"),
                metric_block("Passes", hw.get("wyscout_passes"), aw.get("wyscout_passes"), "{:.0f}"),
            ]),
        ])
    except Exception as e:
        print(f"[WYSCOUT_KPI] {e}")
        return html.Div()


def page_overview(lf):
    dt = find_default_team(lf)
    mxw = int(get_match_list(lf)["week"].max()) if not get_match_list(lf).empty else 34
    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("My Club", className="fl"),
                dcc.Dropdown(id="ov-team", options=team_opts(lf), value=dt, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("View", className="fl"),
                dcc.Dropdown(id="ov-sub", options=[
                    {"label": "🏠 Home Page", "value": "home"},
                    {"label": "📊 General Stats", "value": "stats"},
                ], value="home", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Cup Round" if is_knockout_lf(lf) else "Table After Week", className="fl"),
                dcc.Dropdown(id="ov-week", options=([{"label": "Final / Current", "value": 0}] +
                             ([{"label": f"After MW {w}", "value": w} for w in range(1, mxw + 1)] if not is_knockout_lf(lf) else get_rounds(lf))),
                             value=0, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Table Mode" if not is_knockout_lf(lf) else "Cup View", className="fl"),
                dcc.Dropdown(id="ov-mode", options=[
                    {"label": "Overall", "value": "all"},
                    {"label": "Home only", "value": "home"},
                    {"label": "Away only", "value": "away"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Results Round" if is_knockout_lf(lf) else "Results Week", className="fl"),
                dcc.Dropdown(id="ov-results-week", options=([{"label": f"MW {w}", "value": w} for w in range(1, mxw + 1)] if not is_knockout_lf(lf) else get_rounds(lf)),
                             value=None, placeholder="Latest", clearable=True, className="dd"),
            ]),
        ]),
        _wyscout_banner(lf),
        html.Div(id="ov-content"),
    ])


@callback(Output("ov-content", "children"),
          Input("ov-team", "value"), Input("ov-sub", "value"),
          Input("ov-week", "value"), Input("ov-mode", "value"),
          Input("ov-results-week", "value"), Input("league-selector", "value"))
def update_overview(team, sub, week, mode, results_week, lf):
    if not team:
        return html.Div()
    if sub == "home":
        return _overview_home(lf, team)
    return _overview_stats(lf, team, up_to_week=(week or None), table_mode=(mode or "all"),
                           results_week=results_week)



def _safe_sort_cup_df(df):
    """Sort cup/league match tables without assuming every helper returns the same date column.

    get_match_list() returns local_date + home_team/away_team, while
    get_team_results() returns date + opponent/gf/ga. The cup overview uses both,
    so this helper prevents KeyError: local_date and keeps knockout rounds ordered.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    sort_cols = []
    for c in ("round_order", "week"):
        if c in out.columns:
            sort_cols.append(c)
            break
    if "local_date" in out.columns:
        sort_cols.append("local_date")
    elif "date" in out.columns:
        sort_cols.append("date")
    if not sort_cols:
        return out
    return out.sort_values(sort_cols, na_position="last").reset_index(drop=True)

def _cup_match_table(df, title="Cup Matches"):
    if df is None or df.empty:
        return card(title, [html.Div("No matches found", style={"color": MUTED, "padding": "14px"})])
    df = _safe_sort_cup_df(df)

    # Team-run tables produced by get_team_results(): round/date/opponent/gf/ga/result.
    if {"opponent", "gf", "ga"}.issubset(set(df.columns)):
        rows = []
        for _, r in df.iterrows():
            date_value = r.get("local_date", r.get("date", ""))
            score = f"{int(r.get('gf', 0))}-{int(r.get('ga', 0))}"
            result = str(r.get("result", "—"))
            badge_cls = "pts-hl"
            rows.append(html.Tr([
                html.Td(str(r.get("round_name", f"Round {r.get('round_order', r.get('week',''))}")).replace("nan", "—")),
                html.Td(str(date_value)[:10]),
                html.Td(str(r.get("venue", "—"))),
                html.Td(html.Div(className="team-cell", children=[logo_img(r.get("opponent", ""), 18), html.Span(short(r.get("opponent", "")))]), style={"textAlign": "left"}),
                html.Td(html.Span(score, className=badge_cls)),
                html.Td(result),
            ]))
        return card(title, [html.Table(className="tbl", children=[
            html.Thead(html.Tr([html.Th("Round"), html.Th("Date"), html.Th("Venue"), html.Th("Opponent"), html.Th("Score"), html.Th("Result")])),
            html.Tbody(rows),
        ])])

    # Full match tables produced by get_match_list(): home_team/away_team/home_goals/away_goals.
    rows = []
    for _, r in df.iterrows():
        date_value = r.get("local_date", r.get("date", ""))
        home = r.get("home_team", "Unknown")
        away = r.get("away_team", "Unknown")
        hg = int(r.get("home_goals", 0)) if str(r.get("home_goals", "")).strip() != "" else 0
        ag = int(r.get("away_goals", 0)) if str(r.get("away_goals", "")).strip() != "" else 0
        rows.append(html.Tr([
            html.Td(str(r.get("round_name", f"Round {r.get('round_order', r.get('week',''))}")).replace("nan", "—")),
            html.Td(str(date_value)[:10]),
            html.Td(html.Div(className="team-cell", children=[logo_img(home, 18), html.Span(short(home))]), style={"textAlign": "left"}),
            html.Td(html.Span(f"{hg}-{ag}", className="pts-hl")),
            html.Td(html.Div(className="team-cell", children=[logo_img(away, 18), html.Span(short(away))]), style={"textAlign": "left"}),
            html.Td(str(r.get("score_source", "Event")), style={"fontSize": "10px", "color": MUTED}),
        ]))
    return card(title, [html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th("Round"), html.Th("Date"), html.Th("Home"), html.Th("Score"), html.Th("Away"), html.Th("Source")])),
        html.Tbody(rows),
    ])])

def _cup_progress_table_component(lf, title="Knockout Progress"):
    cp = compute_cup_progress_table(lf)
    if cp.empty:
        return card(title, [html.Div("No cup progress data", style={"color": MUTED})])
    rows = []
    for _, r in cp.head(32).iterrows():
        rows.append(html.Tr([
            html.Td(html.Div(className="team-cell", children=[logo_img(r["Team"], 18), html.Span(short(r["Team"]))]), style={"textAlign": "left"}),
            html.Td(r["Reached"]), html.Td(r["P"]), html.Td(r["W"]), html.Td(r["L"]),
            html.Td(f"{r['GF']}-{r['GA']}"), html.Td(r["Last"]),
        ]))
    return card(title, [html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th("Team"), html.Th("Reached"), html.Th("P"), html.Th("W"), html.Th("L"), html.Th("GF-GA"), html.Th("Last")])),
        html.Tbody(rows),
    ]), html.Div("Cup mode: no league table/points. Progress is ordered by knockout round reached and result summary.",
                 style={"fontSize": "10px", "color": MUTED, "marginTop": "8px"})])

def _cup_overview_home(lf, team):
    ml = get_match_list(lf)
    tr = get_team_results(lf, team)
    tc = team_color(team)
    cp = compute_cup_progress_table(lf)
    row = cp[cp["Team"] == team].iloc[0] if (not cp.empty and team in cp["Team"].values) else {}
    header = html.Div(className="score-ban", children=[
        html.Div(className="score-row", children=[
            logo_img(team, 64),
            html.Div([
                html.Div(short(team), style={"fontFamily": "Orbitron", "fontSize": "28px", "fontWeight": "900", "color": tc}),
                html.Div(f"Coupe de France · Reached: {row.get('Reached','—')} · {row.get('W',0)}W {row.get('L',0)}L · Goals {row.get('GF',0)}-{row.get('GA',0)}", className="score-meta"),
            ]),
        ]),
    ])
    kpis = html.Div(className="row", children=[
        html.Div(className="c3", children=[kpi(row.get("Reached", "—"), "Round Reached", GOLD)]),
        html.Div(className="c3", children=[kpi(row.get("P", 0), "Cup Matches", ACCENT_BLUE)]),
        html.Div(className="c3", children=[kpi(row.get("GF", 0), "Goals For", ACCENT_GREEN)]),
        html.Div(className="c3", children=[kpi(row.get("GA", 0), "Goals Against", ACCENT_RED)]),
    ])
    return html.Div([
        header, kpis,
        html.Div(className="row", children=[
            html.Div(className="c6", children=[_cup_match_table(tr, f"{short(team)} Cup Run")]),
            html.Div(className="c6", children=[_cup_progress_table_component(lf, "Competition Progress")]),
        ]),
        _cup_match_table(ml, "All Coupe de France Matches"),
    ])

def _cup_overview_stats(lf, team, selected_round=None):
    ml = get_match_list(lf)
    if selected_round:
        shown = ml[ml["round_order"] == int(selected_round)] if "round_order" in ml.columns else ml[ml["week"] == int(selected_round)]
        title = f"{round_label(lf, selected_round)} Results"
    else:
        shown = ml
        title = "All Cup Results"
    return html.Div([
        html.Div(className="row", children=[
            html.Div(className="c6", children=[_cup_progress_table_component(lf)]),
            html.Div(className="c6", children=[_cup_match_table(shown, title)]),
        ]),
        html.Div(style={"fontSize": "11px", "color": MUTED, "marginTop": "10px"}, children=
                 "Knockout adaptation: rounds replace matchweeks, no league table is shown, and match filters operate by cup stage."),
    ])

def _overview_home(lf, team):
    """Home Page: club header, club summary (API-powered), recent form, key stats."""
    ml = get_match_list(lf)
    if is_knockout_lf(lf):
        return _cup_overview_home(lf, team)
    lt = compute_league_table(lf)
    tr = get_team_results(lf, team)
    tc = team_color(team)

    pos = lt[lt["Team"] == team].index[0] + 1 if team in lt["Team"].values else "?"
    row = lt[lt["Team"] == team].iloc[0] if team in lt["Team"].values else {}

    # Club header
    header = html.Div(className="score-ban", children=[
        html.Div(className="score-row", children=[
            logo_img(team, 64),
            html.Div([
                html.Div(short(team), style={"fontFamily": "Orbitron", "fontSize": "28px", "fontWeight": "900", "color": tc}),
                html.Div(f"#{pos} · {row.get('Pts',0)} pts · {row.get('W',0)}W {row.get('D',0)}D {row.get('L',0)}L · GD {row.get('GD',0):+d}", className="score-meta"),
            ]),
        ]),
    ])

    # KPIs
    kpis = html.Div(className="row", children=[
        html.Div(className="c3", children=[kpi(row.get("Pts", 0), "Points", GOLD)]),
        html.Div(className="c3", children=[kpi(row.get("W", 0), "Wins", ACCENT_GREEN)]),
        html.Div(className="c3", children=[kpi(row.get("GF", 0), "Goals For", ACCENT_BLUE)]),
        html.Div(className="c3", children=[kpi(f"{row.get('GD', 0):+d}", "Goal Diff",
                                                ACCENT_GREEN if row.get("GD", 0) > 0 else ACCENT_RED)]),
    ])

    # Club summary — AI-generated or fallback
    summary_card = _club_summary_card(team, lf)

    # Recent form
    recent = _results_table(tr.sort_values("week", ascending=False).head(5), team)
    form = team_form_chart(ml, team, tc)

    # Team Situation Summary (analytical context)
    situation_card = _team_situation_card(team, lf)

    return html.Div([
        header, kpis,
        situation_card,
        html.Div(className="row", children=[
            html.Div(className="c6", children=[summary_card]),
            html.Div(className="c6", children=[
                card("Points Progression", [dcc.Graph(figure=form, config={"displayModeBar": False})]),
            ]),
        ]),
        card("Recent Results", [recent]),
    ])


def _team_situation_card(team, lf):
    """Analytical Team Situation Summary: trends, strengths/risks, league rank."""
    try:
        from components.overview_metrics import compute_team_situation
        s = compute_team_situation(lf, team)
    except Exception:
        return html.Div()

    tc = team_color(team)
    _dir_color = {"improving": ACCENT_GREEN, "declining": ACCENT_RED, "steady": MUTED, "n/a": MUTED}
    _dir_arrow = {"improving": "▲", "declining": "▼", "steady": "▶", "n/a": "·"}

    def _trend_chip(label, t, fmt="{:.2f}"):
        d = t.get("direction", "steady")
        rec = t.get("recent")
        rec_s = fmt.format(rec) if isinstance(rec, (int, float)) else "—"
        return html.Div(style={"flex": "1", "textAlign": "center", "padding": "8px", "background": "#10151D", "borderRadius": "8px"}, children=[
            html.Div([html.Span(_dir_arrow[d] + " ", style={"color": _dir_color[d]}), html.Span(rec_s, style={"fontFamily": "Orbitron", "fontWeight": "700", "color": TEXT})],
                     style={"fontSize": "15px"}),
            html.Div(label, style={"fontSize": "9px", "color": MUTED, "textTransform": "uppercase", "marginTop": "2px"}),
            html.Div(d, style={"fontSize": "9px", "color": _dir_color[d], "fontWeight": "700"}),
        ])

    trends = s["trends"]
    trend_row = html.Div(style={"display": "flex", "gap": "8px", "marginBottom": "12px"}, children=[
        _trend_chip("Form (PPG)", trends["form"]),
        _trend_chip("xG/Match", trends["xg"]),
        _trend_chip("Goals/Match", trends["goals"]),
        _trend_chip("Conceded/Match", trends["defense"]),
    ])

    rank = s.get("league_rank") or {}
    rank_txt = (f"#{rank['xg_rank']}/{rank['of']} for xG ({rank['xg']}/match)" if rank else "league rank n/a")
    eff = s.get("efficiency")
    eff_txt = (f"{'+' if eff and eff > 0 else ''}{eff} goals vs xG ({'over' if eff and eff > 0 else 'under'}-performing)" if eff is not None else "")

    strengths = [html.Div([html.Span("▲ ", style={"color": ACCENT_GREEN}), s_], style={"fontSize": "11px", "color": TEXT, "marginBottom": "3px"}) for s_ in s["strengths"]]
    risks = [html.Div([html.Span("▼ ", style={"color": ACCENT_RED}), r_], style={"fontSize": "11px", "color": TEXT, "marginBottom": "3px"}) for r_ in s["risks"]]
    watch = [html.Div([html.Span("👁 ", ), w_], style={"fontSize": "11px", "color": GOLD, "marginBottom": "3px"}) for w_ in s["watch"]]

    return card("Team Situation Summary", [
        trend_row,
        html.Div(style={"fontSize": "11px", "color": MUTED, "marginBottom": "10px"}, children=[
            html.Span(f"League standing: {rank_txt}", style={"color": tc, "fontWeight": "700"}),
            html.Span(f"  ·  {eff_txt}" if eff_txt else ""),
            html.Span(f"  ·  Wyscout data {s['wyscout_completeness']}% complete" if s.get("wyscout_completeness") is not None else ""),
        ]),
        html.Div(className="row", children=[
            html.Div(className="c6", children=[html.Div("Top Strengths", style={"fontSize": "10px", "color": ACCENT_GREEN, "fontWeight": "700", "textTransform": "uppercase", "marginBottom": "4px"})] + (strengths or [html.Div("—", style={"color": MUTED})])),
            html.Div(className="c6", children=[html.Div("Key Risks", style={"fontSize": "10px", "color": ACCENT_RED, "fontWeight": "700", "textTransform": "uppercase", "marginBottom": "4px"})] + (risks or [html.Div("—", style={"color": MUTED})])),
        ]),
        html.Div(style={"marginTop": "10px", "padding": "8px", "background": f"{GOLD}10", "borderRadius": "6px"}, children=[
            html.Div("Watch Next", style={"fontSize": "10px", "color": GOLD, "fontWeight": "700", "textTransform": "uppercase", "marginBottom": "4px"})] + watch),
        html.Div("Trends compare last 5 vs prior 5 matches. xG uses Wyscout where available; form is points-per-game.",
                 style={"fontSize": "9px", "color": MUTED, "marginTop": "8px", "fontStyle": "italic"}),
    ])


def _club_summary_card(team, lf):
    """Club summary. Never blocks page render: uses cached AI text if present,
    otherwise shows an instant static card with a manual refresh option.
    The live API call is gated behind FAP_ENABLE_AI_PROFILE=1 to keep UI fast."""
    import os
    from data_loader import _CACHE

    # Return cached AI summary instantly if we already generated one this session
    ck = f"clubprofile_{lf}_{team}"
    if ck in _CACHE:
        return card("🏟️ Club Profile", [
            html.Div(_CACHE[ck], style={"fontSize": "13px", "lineHeight": "1.7", "color": TEXT}),
            html.Div("Generated by Claude AI", style={"fontSize": "9px", "color": MUTED, "marginTop": "8px", "fontStyle": "italic"}),
        ])

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    ai_enabled = os.environ.get("FAP_ENABLE_AI_PROFILE", "") == "1"

    # Only make the (slow) network call when explicitly enabled AND a key exists.
    # This prevents a 5–15s blocking request on every Home Page render.
    if api_key and ai_enabled:
        try:
            import requests
            league_display = lf.replace("_", " ")
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "content-type": "application/json", "anthropic-version": "2023-06-01"},
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content":
                        f"Write a concise 4-5 sentence club profile for {team} competing in {league_display}. "
                        f"Include: founded year, stadium name & capacity, city, nickname, "
                        f"historical highlights (major trophies), and current era identity. "
                        f"Be factual and professional. No markdown formatting."}],
                },
                timeout=15,
            )
            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"]
                _CACHE[ck] = text  # cache so we never call again this session
                return card("🏟️ Club Profile", [
                    html.Div(text, style={"fontSize": "13px", "lineHeight": "1.7", "color": TEXT}),
                    html.Div("Generated by Claude AI", style={"fontSize": "9px", "color": MUTED, "marginTop": "8px", "fontStyle": "italic"}),
                ])
        except Exception:
            pass

    # Instant fallback (default path — no network call)
    return card("🏟️ Club Profile", [
        html.Div(f"{short(team)} — {lf.replace('_', ' ')}", style={"fontSize": "14px", "fontWeight": "600", "marginBottom": "8px"}),
        html.Div("Set ANTHROPIC_API_KEY and FAP_ENABLE_AI_PROFILE=1 to auto-generate detailed club profiles. "
                 "AI generation is disabled by default so page navigation stays fast.",
                 style={"fontSize": "12px", "color": MUTED, "lineHeight": "1.6"}),
    ])


def _overview_stats(lf, team, up_to_week=None, table_mode="all", results_week=None):
    """General Stats: league table or knockout competition summary."""
    ml = get_match_list(lf)
    if is_knockout_lf(lf):
        return _cup_overview_stats(lf, team, selected_round=(up_to_week or results_week))
    lt = compute_league_table(lf, up_to_week=up_to_week, venue=table_mode)
    tr = get_team_results(lf, team)
    tc = team_color(team)
    max_week = int(ml["week"].max())
    _table_title = "League Table"
    if up_to_week:
        _table_title += f" after Matchweek {up_to_week}"
    if table_mode == "home":
        _table_title += " (Home)"
    elif table_mode == "away":
        _table_title += " (Away)"

    # Club header (compact)
    pos = lt[lt["Team"] == team].index[0] + 1 if team in lt["Team"].values else "?"
    row = lt[lt["Team"] == team].iloc[0] if team in lt["Team"].values else {}

    header = html.Div(className="score-ban", style={"padding": "16px 30px"}, children=[
        html.Div(className="score-row", children=[
            logo_img(team, 48),
            html.Div([
                html.Div(short(team), style={"fontFamily": "Orbitron", "fontSize": "22px", "fontWeight": "900", "color": tc}),
                html.Div(f"#{pos} · {row.get('Pts',0)} pts · {row.get('W',0)}W {row.get('D',0)}D {row.get('L',0)}L", className="score-meta"),
            ]),
        ]),
    ])

    # KPIs + league context
    from components.kpi_context import get_kpi_context, kpi_with_context_html
    kpi_keys = [("xg_per_match", "xG/M"), ("ppda", "PPDA"),
                ("possession_pct", "Poss%"), ("prog_passes_pm", "Prog/M"),
                ("box_entries_pm", "Box/M"), ("def_action_height", "Def Ht")]
    ctx_kpis = [html.Div(className="c3", children=[kpi_with_context_html(lbl, get_kpi_context(lf, team, k))]) for k, lbl in kpi_keys]

    kpis = html.Div(className="row", children=[
        html.Div(className="c3", children=[kpi(row.get("Pts", 0), "Points", GOLD)]),
        html.Div(className="c3", children=[kpi(row.get("W", 0), "Wins", ACCENT_GREEN)]),
        html.Div(className="c3", children=[kpi(row.get("GF", 0), "Goals For", ACCENT_BLUE)]),
        html.Div(className="c3", children=[kpi(f"{row.get('GD', 0):+d}", "Goal Diff",
                                                ACCENT_GREEN if row.get("GD", 0) > 0 else ACCENT_RED)]),
    ])
    kpis_ctx = html.Div(className="row", children=ctx_kpis)

    # League table
    league_table = _league_mini_table(lt, _table_title)

    # Top scorers + assists
    scorers = get_top_scorers(lf)
    assists = get_top_assists(lf)

    def _top_table(df, col, title, emoji):
        rows = []
        for i, (_, r) in enumerate(df.head(10).iterrows()):
            rows.append(html.Tr([
                html.Td(str(i+1), style={"color": GOLD, "fontWeight": "700"}),
                html.Td(html.Div(className="team-cell", children=[logo_img(r["team_name"], 18), html.Span(r["player_name"])]),
                         style={"textAlign": "left"}),
                html.Td(r["team_short"]),
                html.Td(r["matches"]),
                html.Td(html.Span(str(r[col]), className="pts-hl")),
            ]))
        return card(f"{emoji} {title}", [html.Table(className="tbl", children=[
            html.Thead(html.Tr([html.Th("#"), html.Th("Player"), html.Th("Team"), html.Th("MP"), html.Th(col.title())])),
            html.Tbody(rows),
        ])])

    sc = _top_table(scorers, "goals", "Top Scorers", "🏅") if not scorers.empty else html.Div()
    ac = _top_table(assists, "assists", "Top Assists", "🎯") if not assists.empty else html.Div()

    # Recent results + form chart
    recent = _results_table(tr.sort_values("week", ascending=False).head(5), team)
    form = team_form_chart(ml, team, tc)

    # Fixtures — results week is user-selectable (defaults to last played)
    last_played_week = int(tr["week"].max()) if not tr.empty else max_week
    shown_results_week = results_week if results_week else last_played_week
    last_fixtures = _fixtures_card(lf, shown_results_week, f"Matchweek {shown_results_week} Results")
    next_week = shown_results_week + 1
    next_wk_data = get_week_fixtures(lf, next_week)
    if not next_wk_data.empty:
        next_fixtures = _fixtures_card(lf, next_week, f"Matchweek {next_week} Fixtures")
    else:
        next_fixtures = card("Upcoming Fixtures", [html.Div("No upcoming fixtures found", style={"color": MUTED, "textAlign": "center", "padding": "20px"})])

    return html.Div([
        header, kpis, kpis_ctx,
        html.Div(className="row", children=[
            html.Div(className="c6", children=[league_table]),
            html.Div(className="c6", children=[
                card("Points Progression", [dcc.Graph(figure=form, config={"displayModeBar": False})]),
            ]),
        ]),
        html.Div(className="row", children=[
            html.Div(className="c6", children=[sc]),
            html.Div(className="c6", children=[ac]),
        ]),
        html.Div(className="row", children=[
            html.Div(className="c6", children=[card("Recent Results", [recent])]),
            html.Div(className="c6", children=[
                html.Div(className="row", style={"flexDirection": "column", "gap": "14px"}, children=[
                    last_fixtures, next_fixtures,
                ]),
            ]),
        ]),
    ])


def _results_table(tr_df, team):
    rows = []
    for _, r in tr_df.iterrows():
        badge = html.Span(r["result"], className=f"badge badge-{r['result']}")
        rows.append(html.Tr([
            html.Td(r.get("round_name", f"W{int(r['week'])}")),
            html.Td(html.Div(className="team-cell", children=[logo_img(r["opponent"], 20), html.Span(short(r["opponent"]))]),
                     style={"textAlign": "left"}),
            html.Td(r["venue"]),
            html.Td(f"{r['gf']}-{r['ga']}", style={"fontWeight": "700"}),
            html.Td(badge),
        ]))
    return html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th("Round"), html.Th("Opponent"), html.Th("H/A"), html.Th("Score"), html.Th("")])),
        html.Tbody(rows),
    ])


def _league_mini_table(lt, title="League Table"):
    rows = []
    for i, r in lt.iterrows():
        rank = i + 1
        cls = "rk-1" if rank == 1 else "rk-2" if rank == 2 else "rk-3" if rank == 3 else "rk-ucl" if rank <= 5 else "rk-rel" if rank >= 17 else ""
        rows.append(html.Tr([
            html.Td(html.Span(str(rank), className=f"rk {cls}")),
            html.Td(html.Div(className="team-cell", children=[logo_img(r["Team"], 20), html.Span(r["Short"])]),
                     style={"textAlign": "left"}),
            html.Td(r["P"]),
            html.Td(f"{r['GD']:+d}", style={"color": ACCENT_GREEN if r["GD"] > 0 else (ACCENT_RED if r["GD"] < 0 else TEXT)}),
            html.Td(html.Span(r["Pts"], className="pts-hl")),
            html.Td(form_dots(r["Form"]) if isinstance(r.get("Form"), list) else ""),
        ]))
    return card(title, [html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th("#"), html.Th("Team"), html.Th("P"), html.Th("GD"), html.Th("Pts"), html.Th("Form")])),
        html.Tbody(rows),
    ])])


def _fixtures_card(lf, week, title):
    fx = get_week_fixtures(lf, week)
    rows = []
    for _, r in fx.iterrows():
        rows.append(html.Tr([
            html.Td(html.Div(className="team-cell", children=[logo_img(r["home_team"], 18), html.Span(short(r["home_team"]))]),
                     style={"textAlign": "left"}),
            html.Td(f"{r['home_goals']}-{r['away_goals']}", style={"fontWeight": "700", "fontFamily": "Orbitron", "fontSize": "14px"}),
            html.Td(html.Div(className="team-cell", style={"justifyContent": "flex-end"},
                             children=[html.Span(short(r["away_team"])), logo_img(r["away_team"], 18)]),
                     style={"textAlign": "right"}),
        ]))
    return card(title, [html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th("Home"), html.Th(""), html.Th("Away")])),
        html.Tbody(rows),
    ])])


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 2: MATCH CENTER
# ═══════════════════════════════════════════════════════════════════════════
def page_match(lf):
    dt = find_default_team(lf)
    ml = get_match_list(lf)
    # Default: last Lens match
    tm = ml[(ml["home_team"] == dt) | (ml["away_team"] == dt)] if dt else ml
    default_mid = tm.iloc[-1]["match_id"] if not tm.empty else (ml.iloc[-1]["match_id"] if not ml.empty else None)

    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("Filter Week", className="fl"),
                dcc.Dropdown(id="mc-week", options=week_opts(lf), placeholder="All", className="dd"),
            ]),
            html.Div(className="fg-wide", children=[
                html.Div("Select Match", className="fl"),
                dcc.Dropdown(id="mc-match", options=match_opts(lf), value=default_mid, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Half", className="fl"),
                dcc.Dropdown(id="mc-half", options=[
                    {"label": "Full Match", "value": "all"},
                    {"label": "1st Half", "value": "1st"},
                    {"label": "2nd Half", "value": "2nd"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Minutes Range", className="fl"),
                dcc.RangeSlider(id="mc-minutes", min=0, max=100, step=1, value=[0, 100],
                                marks={0: "0'", 15: "15'", 30: "30'", 45: "45'", 60: "60'", 75: "75'", 90: "90'", 100: "90+"},
                                tooltip={"placement": "bottom"}),
            ]),
        ]),
        html.Div(id="mc-content"),
    ])


@callback(Output("mc-match", "options"), Output("mc-match", "value"),
          Input("mc-week", "value"), Input("league-selector", "value"),
          State("mc-match", "value"))
def filter_mc_matches(week, lf, current):
    ml = get_match_list(lf)
    if ml is None or ml.empty:
        return [], None
    if week and week in ml["week"].values:
        fml = ml[ml["week"] == week]
        opts = [{"label": f"W{r['week']}  {short(r['home_team'])} {r['home_goals']}-{r['away_goals']} {short(r['away_team'])}", "value": r["match_id"]} for _, r in fml.iterrows()]
    else:
        opts = match_opts(lf)
    valid_ids = {o["value"] for o in opts}
    # Keep current selection only if still valid for this season/week, else default to first
    value = current if current in valid_ids else (opts[0]["value"] if opts else None)
    return opts, value


@callback(Output("mc-content", "children"),
          Input("mc-match", "value"), Input("mc-half", "value"),
          Input("mc-minutes", "value"), Input("league-selector", "value"))
def update_match(mid, half, mins, lf):
    if not mid:
        return html.Div()

    stats = compute_match_stats(lf, mid, period=half, min_from=mins[0], min_to=mins[1])
    if not stats:
        return html.Div("No data for this match", style={"color": MUTED, "textAlign": "center", "padding": "40px"})

    h, a = stats["home"], stats["away"]
    hc, ac = team_color(h["team"]), team_color(a["team"])
    if hc == ac:
        ac = ACCENT_BLUE

    ml = get_match_list(lf)
    info_df = ml[ml["match_id"] == mid]
    if info_df.empty:
        return html.Div("Match not found in current season", style={"color": MUTED, "textAlign": "center", "padding": "40px"})
    info = info_df.iloc[0]

    # Full match data (for charts)
    mdf = get_match_data(lf, mid)
    mdf_filtered = filter_by_period(mdf, half)
    mdf_filtered = filter_by_minutes(mdf_filtered, mins[0], mins[1])

    # Score
    banner = html.Div(className="score-ban", children=[
        html.Div(className="score-row", children=[
            html.Div(className="score-team", children=[logo_img(h["team"], 56), html.Div(short(h["team"]), className="score-team-name")]),
            html.Div(f"{h['goals']}  —  {a['goals']}", className="score-num"),
            html.Div(className="score-team", children=[logo_img(a["team"], 56), html.Div(short(a["team"]), className="score-team-name")]),
        ]),
        html.Div(f"Matchweek {info['week']}  ·  {info['local_date']}  ·  {info.get('venue','')}", className="score-meta"),
    ])

    # Score-source provenance + conflict/QA banner (from the registry)
    source_banner = None
    try:
        from components.match_registry import get_registry
        reg = get_registry(lf)
        rrow = reg[reg["match_id"] == mid]
        if not rrow.empty:
            rr = rrow.iloc[0]
            chips = [html.Span(f"Score source: {rr['score_source']}",
                               style={"fontSize": "11px", "color": GOLD, "fontWeight": "700"})]
            if rr.get("wyscout_home_goals") is not None and \
               (int(rr["event_home_goals"]), int(rr["event_away_goals"])) != (int(rr["wyscout_home_goals"]), int(rr["wyscout_away_goals"])):
                chips.append(html.Span(
                    f"  ·  Event score {int(rr['event_home_goals'])}-{int(rr['event_away_goals'])} differs from Wyscout "
                    f"{int(rr['wyscout_home_goals'])}-{int(rr['wyscout_away_goals'])} (showing Wyscout)",
                    style={"fontSize": "11px", "color": "#FEB019"}))
            for w in (rr.get("qa_warnings") or []):
                chips.append(html.Span(f"  ·  ⚠ {w}", style={"fontSize": "11px", "color": MUTED}))
            source_banner = html.Div(chips, style={"padding": "6px 14px", "marginBottom": "10px",
                                                    "background": "#10151D", "borderRadius": "8px",
                                                    "border": "1px solid #1E2733"})
    except Exception:
        source_banner = None

    # KPIs
    kpis = html.Div(className="row", style={"gap": "10px"}, children=[
        html.Div(className="c3", children=[kpi(h["shots"], f"Shots ({short(h['team'])})", hc)]),
        html.Div(className="c3", children=[kpi(a["shots"], f"Shots ({short(a['team'])})", ac)]),
        html.Div(className="c3", children=[kpi(f"{h['pass_accuracy']}%", f"Pass% ({short(h['team'])})", hc)]),
        html.Div(className="c3", children=[kpi(f"{a['pass_accuracy']}%", f"Pass% ({short(a['team'])})", ac)]),
    ])

    # Match Momentum & Key Events — net-momentum bar chart (one signed value/min)
    momentum = card("Match Momentum & Key Events", [dcc.Graph(
        figure=match_momentum_graph(mdf_filtered, h["team"], a["team"], home_color=hc, away_color=ac, height=300),
        config={"displayModeBar": False, "responsive": True},
        style={"height": "300px", "width": "100%"})])

    # Wyscout official team-level metrics (where matched) — source of truth
    wyscout_strip = _wyscout_match_kpis(lf, mid, h, a)

    # Stats + Pass Origins (event-derived detail; Wyscout summary above)
    stats_chart = card("Match Statistics", [match_stats_comparison_component(stats, hc, ac)])
    poss = card("Pass Origin Zones", [dcc.Graph(figure=possession_zones(mdf_filtered, h["team"], a["team"]), config={"displayModeBar": False})])

    # Shots + xG (event-derived estimated shot quality — NOT official shot xG)
    shots = card("Shot Map", [dcc.Graph(figure=shot_map(mdf_filtered), config={"displayModeBar": False})])
    xg = card("Estimated Shot Quality", [dcc.Graph(figure=shot_quality_scatter(mdf_filtered), config={"displayModeBar": False})])

    # Lineups
    lineup_data = get_match_lineup(lf, mid)
    lineup_card = _lineup_card(lineup_data)

    # Tactical insights
    from components.insights import (insight_shot_profile, insight_defensive_zone,
                                       insight_pass_network, insight_zone_occupancy,
                                       insight_card_html)

    home_team_name = h["team"]
    away_team_name = a["team"]

    # Build insights for both teams
    home_insights = [
        insight_card_html(f"{short(home_team_name)} shot profile: {insight_shot_profile(mdf_filtered, home_team_name)}"),
        insight_card_html(f"{short(home_team_name)} defensive shape: {insight_defensive_zone(mdf_filtered, home_team_name)}"),
        insight_card_html(f"{short(home_team_name)} buildup: {insight_pass_network(mdf_filtered, home_team_name)}"),
    ]
    away_insights = [
        insight_card_html(f"{short(away_team_name)} shot profile: {insight_shot_profile(mdf_filtered, away_team_name)}"),
        insight_card_html(f"{short(away_team_name)} defensive shape: {insight_defensive_zone(mdf_filtered, away_team_name)}"),
        insight_card_html(f"{short(away_team_name)} buildup: {insight_pass_network(mdf_filtered, away_team_name)}"),
    ]

    insights_card = card("📋 Tactical Insights", [
        html.Div(className="row", children=[
            html.Div(className="c6", children=[
                html.Div(short(home_team_name), style={"fontWeight": "700", "color": hc, "marginBottom": "4px", "fontSize": "12px"}),
                *[i for i in home_insights if i is not None],
            ]),
            html.Div(className="c6", children=[
                html.Div(short(away_team_name), style={"fontWeight": "700", "color": ac, "marginBottom": "4px", "fontSize": "12px"}),
                *[i for i in away_insights if i is not None],
            ]),
        ]),
    ])

    # Data availability banner — never show misleading zeroes
    from components.definitions import big_chance_availability
    bc_avail = big_chance_availability(mdf)
    avail_banner = None
    if not bc_avail["available"]:
        avail_banner = html.Div(style={
            "padding": "8px 14px", "background": "rgba(255,69,96,0.08)",
            "borderLeft": "3px solid #FF4560", "borderRadius": "6px",
            "marginBottom": "10px", "fontSize": "11px", "color": "#C8D0DA"},
            children=[html.Span("⚠️ ", style={"marginRight": "6px"}),
                      html.Span(f"Big Chance data not captured for this match ({bc_avail['reason']}). "
                                f"Big-chance metrics will show 'Not captured' rather than 0.")])

    return html.Div([
        banner, source_banner, kpis, wyscout_strip, momentum,
        avail_banner,
        html.Div(className="row", children=[html.Div(className="c6", children=[stats_chart]), html.Div(className="c6", children=[poss])]),
        html.Div(className="row", children=[html.Div(className="c6", children=[shots]), html.Div(className="c6", children=[xg])]),
        insights_card,
        lineup_card,
    ])


def _lineup_card(data):
    from components.charts import formation_pitch_figure
    cols = []
    for side in ["home", "away"]:
        sd = data.get(side, {})
        if not sd:
            continue
        team = sd.get("team", "")
        formation = sd.get("formation", "?")
        players = sd.get("players", [])
        starters = [p for p in players if p.get("starter")]
        subs = [p for p in players if not p.get("starter")]
        tc = team_color(team)

        # Pretty formation label (3421 → 3-4-2-1)
        f_label = "-".join(list(str(formation))) if str(formation).isdigit() else str(formation)

        items = [html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "marginBottom": "6px"}, children=[
            logo_img(team, 22), html.Span(short(team), style={"fontWeight": "700", "fontSize": "14px"}),
            html.Span(f_label, style={"marginLeft": "auto", "fontFamily": "Orbitron", "color": tc, "fontWeight": "700", "fontSize": "13px"}),
        ])]
        # Formation pitch diagram
        if len(starters) >= 11:
            # Look up local player photos (jersey-keyed); missing → numbered token
            import os
            photo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "photos")
            photos = {}
            for p in starters:
                for key in (str(p.get("player_id", "")), str(p.get("jersey", ""))):
                    if key and os.path.exists(os.path.join(photo_dir, f"{key}.png")):
                        photos[key] = f"/assets/photos/{key}.png"
                        break
            fig = formation_pitch_figure(team, formation, starters, tc, side, photos=photos)
            items.append(dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                                   style={"height": "440px", "width": "100%"}))
        else:
            # Fallback: list starters if lineup incomplete
            for p in starters:
                items.append(html.Div(className="lineup-player", children=[
                    html.Span(str(p["jersey"]), className="lineup-jersey"),
                    html.Span(p["position"], className="lineup-pos"), html.Span(p["name"])]))

        # Substitutes as a compact list
        if subs:
            items.append(html.Div("Substitutes", style={"fontSize": "10px", "color": MUTED, "textTransform": "uppercase",
                                                          "letterSpacing": "1px", "marginTop": "8px", "marginBottom": "4px"}))
            sub_chips = [html.Span(f"{p['jersey']} {p['name'].split()[-1] if p['name'] else ''}",
                                   style={"fontSize": "10px", "color": TEXT, "background": "#1A2030",
                                          "borderRadius": "4px", "padding": "2px 6px", "marginRight": "4px",
                                          "marginBottom": "4px", "display": "inline-block"}) for p in subs[:7]]
            items.append(html.Div(sub_chips))
        cols.append(html.Div(className="c6", children=[html.Div(items, style={"padding": "4px"})]))

    return card("Lineups & Formation", [html.Div(className="row", children=cols)])


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 4: HEAD-TO-HEAD (comprehensive rewrite)
# ═══════════════════════════════════════════════════════════════════════════
def page_h2h(lf):
    dt = find_default_team(lf)
    teams = get_teams(lf)
    team_b = [t for t in teams if t != dt]
    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("Team A", className="fl"),
                dcc.Dropdown(id="h2h-a", options=team_opts(lf), value=dt, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Team B", className="fl"),
                dcc.Dropdown(id="h2h-b", options=team_opts(lf), value=team_b[0] if team_b else None, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Sample", className="fl"),
                dcc.Dropdown(id="h2h-scope", options=[
                    {"label": "All H2H", "value": "all"},
                    {"label": "Last meeting", "value": "last1"},
                    {"label": "Last 3", "value": "last3"},
                    {"label": "Last 5", "value": "last5"},
                    {"label": "Specific match", "value": "specific"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg-wide", children=[
                html.Div("Specific Match", className="fl"),
                dcc.Dropdown(id="h2h-match", options=[], placeholder="(when Specific selected)", className="dd"),
            ]),
        ]),
        dcc.Loading(type="circle", color=GOLD, children=[
            html.Div(id="h2h-content"),
        ]),
    ])


@callback(Output("h2h-match", "options"),
          Input("h2h-a", "value"), Input("h2h-b", "value"), Input("league-selector", "value"))
def h2h_match_options(ta, tb, lf):
    if not ta or not tb or ta == tb:
        return []
    ml = get_match_list(lf)
    h2h_ml = ml[((ml["home_team"] == ta) & (ml["away_team"] == tb)) |
                ((ml["home_team"] == tb) & (ml["away_team"] == ta))].sort_values("week")
    return [{"label": f"W{int(r['week'])} · {r['local_date']} · {short(r['home_team'])} {r['home_goals']}-{r['away_goals']} {short(r['away_team'])}",
             "value": r["match_id"]} for _, r in h2h_ml.iterrows()]


@callback(Output("h2h-content", "children"),
          Input("h2h-a", "value"), Input("h2h-b", "value"),
          Input("h2h-scope", "value"), Input("h2h-match", "value"),
          Input("league-selector", "value"))
def update_h2h(ta, tb, scope, match_id, lf):
    if not ta or not tb or ta == tb:
        return html.Div("Select two different teams", style={"color": MUTED, "textAlign": "center", "padding": "40px"})
    from components.h2h_engine import build_h2h_page
    return build_h2h_page(lf, ta, tb, scope=(scope or "all"), selected_match_id=match_id)


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 5: PLAYER HUB (with position-based radar)
# ═══════════════════════════════════════════════════════════════════════════
def page_players(lf):
    dt = find_default_team(lf)
    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("Team", className="fl"),
                dcc.Dropdown(id="pl-team", options=team_opts(lf), value=dt, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Position Filter", className="fl"),
                dcc.Dropdown(id="pl-pos", options=[{"label": p, "value": p} for p in
                    ["GK", "CB", "FB/WB", "DM", "CM", "AM", "Winger", "ST"]],
                    placeholder="All positions", className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Player A", className="fl"),
                dcc.Dropdown(id="pl-a", placeholder="Select player…", className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Compare vs", className="fl"),
                dcc.Dropdown(id="pl-b", placeholder="Optional player…", className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Radar Mode", className="fl"),
                dcc.Dropdown(id="pl-mode", options=[
                    {"label": "Full Template", "value": "full"},
                    {"label": "Offensive Only", "value": "offensive"},
                    {"label": "Defensive Only", "value": "defensive"},
                ], value="full", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Radar Scale", className="fl"),
                dcc.Dropdown(id="pl-scale", options=[
                    {"label": "Max-normalized (vs peer max)", "value": "max"},
                    {"label": "Percentile rank", "value": "percentile"},
                ], value="max", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Min Matches", className="fl"),
                dcc.Dropdown(id="pl-minutes", options=[
                    {"label": "Any", "value": 0}, {"label": "5+", "value": 5},
                    {"label": "10+", "value": 10}, {"label": "15+", "value": 15},
                    {"label": "20+", "value": 20},
                ], value=0, clearable=False, className="dd"),
            ]),
        ]),
        html.Div(id="pl-content"),
    ])


@callback(Output("pl-a", "options"), Output("pl-b", "options"),
          Input("pl-team", "value"), Input("pl-pos", "value"),
          Input("pl-minutes", "value"), Input("league-selector", "value"))
def update_player_opts(team, pos, min_matches, lf):
    ps = get_player_stats(lf, team)
    if ps.empty:
        return [], []
    if pos:
        _pcol = "position_group" if "position_group" in ps.columns else "position"
        ps = ps[ps[_pcol] == pos]
    if min_matches and "matches" in ps.columns:
        ps = ps[ps["matches"] >= min_matches]
    opts = [{"label": f"#{r['jersey']} {r['player_name']} ({r['team_short']}, {r['position']})", "value": r["player_id"]}
            for _, r in ps.iterrows()]
    return opts, opts


@callback(Output("pl-content", "children"),
          Input("pl-a", "value"), Input("pl-b", "value"),
          Input("pl-team", "value"), Input("pl-pos", "value"),
          Input("pl-mode", "value"), Input("pl-scale", "value"),
          Input("league-selector", "value"))
def update_players(pa, pb, team, pos, mode, scale, lf):
    from components.radar import (compute_player_radar_stats, get_position_group,
                                   RADAR_TEMPLATES)
    scale = scale or "max"
    ps = get_player_stats(lf, team)
    if ps.empty:
        return html.Div("No player data for this team", style={"color": MUTED, "textAlign": "center", "padding": "40px"})
    if pos:
        _pcol = "position_group" if "position_group" in ps.columns else "position"
        ps = ps[ps[_pcol] == pos]

    content = []
    mode = mode or "full"

    # Player A card + radar
    if pa:
        p = ps[ps["player_id"] == pa]
        if not p.empty:
            p = p.iloc[0]
            tc = team_color(p["team_name"])
            player_pos = p["position"]
            # Use the canonical position GROUP stored on the row (override-aware)
            pos_group = p.get("position_group") or get_position_group(player_pos)
            pos_source = p.get("position_source", "Event data fallback")
            pos_conf = p.get("position_confidence", "low")
            pos_mismatch = p.get("position_mismatch", False)
            event_pos = p.get("event_position", player_pos)

            _conf_color = {"high": ACCENT_GREEN, "medium": GOLD, "low": ACCENT_RED}.get(pos_conf, MUTED)
            badge_children = [
                html.Span(f"Position: {pos_group}", style={"color": tc, "fontWeight": "700"}),
                html.Span(f"  ·  Source: {pos_source}", style={"color": MUTED}),
                html.Span(f"  ·  Confidence: {pos_conf.title()}", style={"color": _conf_color, "fontWeight": "700"}),
            ]
            mismatch_note = []
            if pos_mismatch:
                mismatch_note = [html.Div(
                    f"⚠ Provider event position differs from canonical: event mode {event_pos}, canonical {player_pos} ({pos_group}).",
                    style={"fontSize": "10px", "color": "#FEB019", "marginTop": "4px"})]

            content.append(html.Div(className="score-ban", children=[
                html.Div(className="score-row", children=[
                    logo_img(p["team_name"], 44),
                    html.Div([
                        html.Div(f"#{p['jersey']} {p['player_name']}", style={"fontFamily": "Orbitron", "fontSize": "22px", "fontWeight": "700"}),
                        html.Div(f"{player_pos} ({pos_group}) · {p['team_short']} · {p['matches']} matches",
                                 className="score-meta"),
                        html.Div(badge_children, style={"fontSize": "10px", "marginTop": "4px"}),
                    ] + mismatch_note),
                ]),
                html.Div(className="row", style={"marginTop": "14px", "justifyContent": "center", "gap": "8px"}, children=[
                    kpi(p["goals"], "Goals", ACCENT_GREEN), kpi(p["assists"], "Assists", ACCENT_BLUE),
                    kpi(p["shots"], "Shots", GOLD), kpi(f"{p['pass_accuracy']}%", "Pass%", TEXT),
                    kpi(p["tackles"], "Tackles", ACCENT_GREEN), kpi(p["interceptions"], "Intercepts", ACCENT_BLUE),
                ]),
            ]))

            # Position-based radar
            df = load_league_data(lf)

            # Peer percentiles + group size (vs LEAGUE position peers) — computed
            # first so the radar plots REAL percentiles, not self-normalized values.
            from components.radar import compute_peer_percentiles, build_percentile_radar
            peer = compute_peer_percentiles(df, pa, p["team_name"], pos_group)

            # Optional comparison player (pl-b) → second radar trace on same axes
            peer_b = None; name_b = None; cross_pos_warning = None
            if pb and pb != pa:
                allps = get_player_stats(lf)
                p2 = allps[allps["player_id"] == pb]
                if not p2.empty:
                    p2 = p2.iloc[0]
                    b_group = p2.get("position_group") or get_position_group(p2["position"])
                    # compare within player A's peer group so axes are comparable
                    peer_b = compute_peer_percentiles(df, pb, p2["team_name"], pos_group)
                    name_b = p2["player_name"]
                    if b_group != pos_group:
                        cross_pos_warning = (
                            f"⚠ Cross-position comparison: {name_b} is a {b_group}, "
                            f"shown against {pos_group} peers — percentiles use the "
                            f"{pos_group} pool, so {name_b}'s ranks are indicative only.")

            fig_radar = build_percentile_radar(peer, p["player_name"], pos_group, color=tc,
                                               peer_b=peer_b, name_b=name_b, scale=scale)

            # Show which metrics are in the template
            template = RADAR_TEMPLATES.get(pos_group, RADAR_TEMPLATES["CM"])
            metric_labels = [m[0] for m in template["metrics"]]

            # Subtitle reflects the ACTIVE scale (never hardcoded to percentile).
            if scale == "max":
                _mode_txt = "Max-normalized peer scale (value ÷ peer max × 100)"
                _radar_txt = "radar shows % of peer max, hover for raw/match"
            else:
                _mode_txt = "Percentile rank vs peers"
                _radar_txt = "radar shows percentile rank, hover for raw/match"
            subtitle = (f"Radar Mode: {_mode_txt} · Peer Pool: {pos_group} · "
                        f"{peer['n_peers']} players (≥3 matches) · {_radar_txt}")

            # Honest data-availability notes (no hidden zeros)
            avail_notes = []
            if cross_pos_warning:
                avail_notes.append(html.Div(cross_pos_warning,
                    style={"fontSize": "11px", "color": "#FEB019", "fontWeight": "600",
                           "marginBottom": "4px"}))
            unavail = peer.get("unavailable", [])
            if unavail:
                avail_notes.append(html.Div(
                    f"Excluded (no peer variation): {', '.join(unavail)}.",
                    style={"fontSize": "10px", "color": MUTED, "fontStyle": "italic"}))
            # Key-pass provenance
            kp_src = p.get("key_pass_source", "inferred")
            if "key_passes" in peer.get("percentiles", {}):
                avail_notes.append(html.Div(
                    f"Key Passes are inferred (last completed same-team pass before a shot, ≤15s) — medium confidence; "
                    f"provider has no clean key-pass flag.",
                    style={"fontSize": "10px", "color": MUTED, "fontStyle": "italic"}))
            else:
                avail_notes.append(html.Div(
                    "Key Passes unavailable from provider schema; inferred key-pass model produced no peer variation.",
                    style={"fontSize": "10px", "color": MUTED, "fontStyle": "italic"}))

            # Strengths / weaknesses cards (with raw per-match values beside percentiles)
            _rawmap = peer.get("raw", {})
            _lbl2key = {v: k for k, v in peer.get("labels", {}).items()}
            def _raw_for(lbl):
                k = _lbl2key.get(lbl)
                return f" · {_rawmap[k]}/match" if k in _rawmap else ""
            sw_children = []
            if peer["strengths"]:
                sw_children.append(html.Div("Strengths (vs peers)", style={"fontSize": "11px", "color": ACCENT_GREEN, "fontWeight": "700", "marginBottom": "4px"}))
                for lbl, pct in peer["strengths"]:
                    sw_children.append(html.Div(f"▲ {lbl}: {pct}th pct{_raw_for(lbl)}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "2px"}))
            if peer["weaknesses"]:
                sw_children.append(html.Div("Development areas", style={"fontSize": "11px", "color": ACCENT_RED, "fontWeight": "700", "margin": "8px 0 4px"}))
                for lbl, pct in peer["weaknesses"]:
                    sw_children.append(html.Div(f"▼ {lbl}: {pct}th pct{_raw_for(lbl)}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "2px"}))
            if not sw_children:
                sw_children.append(html.Div("Around peer average across template metrics.", style={"fontSize": "11px", "color": MUTED}))

            # ── Raw values table (Metric | Raw | Peer max | Radar % | Pctl | Rank | Source | Conf) ──
            _SRC = {"goals": "Event", "xg": "Estimated", "shots": "Event/Wyscout",
                    "assists": "Event", "key_passes": "Inferred", "prog_passes": "Event",
                    "pass_accuracy": "Event", "tackles": "Event", "interceptions": "Event",
                    "recoveries": "Event", "clearances": "Event", "aerials": "Event",
                    "take_ons": "Event", "saves": "Event", "claims": "Event",
                    "sweeper_actions": "Event"}
            _CONF = {"key_passes": "Med", "xg": "Est"}
            radar_vals = peer.get("maxnorm" if scale == "max" else "percentiles", {})
            tbl_header = html.Tr([html.Th(h, style={"textAlign": "left", "padding": "3px 6px",
                "fontSize": "9px", "color": MUTED, "borderBottom": "1px solid #1E2733"})
                for h in ["Metric", "Raw/match", "Peer max", "Radar %", "Pctl", "Rank", "Leader", "Source", "Conf"]])
            tbl_rows = [tbl_header]

            def _fmt_metric_value(val, other=None, rank_val=None):
                try:
                    v = float(val)
                    o = float(other) if other is not None else None
                except Exception:
                    return "—"
                # If rounded 2dp values would look identical while the player is
                # not actually ranked first, show 4dp so the table explains why.
                try:
                    rv = str(rank_val or "")
                    not_first = rv not in ("1", "T-1")
                    if o is not None and not_first and round(v, 2) == round(o, 2):
                        return f"{v:.4f}"
                except Exception:
                    pass
                return f"{v:.2f}"

            def _fmt_radar_value(val, rank_val=None):
                try:
                    v = float(val)
                except Exception:
                    return "—"
                rv = str(rank_val or "")
                # Never hide a rank>1 player behind a rounded 100.
                if rv not in ("1", "T-1") and v >= 99.0:
                    return f"{v:.1f}"
                if abs(v - round(v)) < 0.05:
                    return f"{int(round(v))}"
                return f"{v:.1f}"

            for k in radar_vals:
                lbl = peer["labels"].get(k, k)
                raw_exact = peer.get("raw_exact", peer.get("raw", {})).get(k, 0)
                max_exact = peer.get("peer_max_exact", peer.get("peer_max", {})).get(k, 0)
                rank_disp = peer.get("rank_display", peer.get("rank", {})).get(k, "—")
                leader_txt = peer.get("leader", {}).get(k, "—")
                tie_txt = peer.get("tie_status", {}).get(k, "")
                hover_txt = (
                    f"Exact raw: {float(raw_exact):.6f}/match | "
                    f"Exact peer max: {float(max_exact):.6f}/match | "
                    f"Rank: {rank_disp} | Leader: {leader_txt} | {tie_txt} | "
                    "Formula: raw ÷ peer max × 100"
                )
                tbl_rows.append(html.Tr([
                    html.Td(lbl, title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": TEXT}),
                    html.Td(_fmt_metric_value(raw_exact, max_exact, rank_disp), title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": TEXT}),
                    html.Td(_fmt_metric_value(max_exact, raw_exact, rank_disp), title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": MUTED}),
                    html.Td(_fmt_radar_value(radar_vals.get(k, 0), rank_disp), title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": GOLD, "fontWeight": "700"}),
                    html.Td(f"{peer['percentiles'].get(k, 0)}", title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": TEXT}),
                    html.Td(f"{rank_disp}", title=hover_txt, style={"padding": "2px 6px", "fontSize": "10px", "color": MUTED}),
                    html.Td(leader_txt, title=hover_txt, style={"padding": "2px 6px", "fontSize": "9px", "color": MUTED, "maxWidth": "180px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
                    html.Td(_SRC.get(k, "Event"), style={"padding": "2px 6px", "fontSize": "9px", "color": MUTED}),
                    html.Td(_CONF.get(k, "High"), style={"padding": "2px 6px", "fontSize": "9px", "color": MUTED}),
                ]))
            raw_table = card("Radar Values (raw · peer-max · scaled)", [
                html.Div(f"Scale: {'Max-normalized (value ÷ peer max × 100)' if scale == 'max' else 'Percentile rank vs peers'}",
                         style={"fontSize": "10px", "color": MUTED, "marginBottom": "6px"}),
                html.Table(tbl_rows, style={"width": "100%", "borderCollapse": "collapse"}),
            ])

            content.append(html.Div(className="row", children=[
                html.Div(className="c8", children=[card(f"Player Radar — {pos_group} Template",
                    [html.Div(subtitle, style={"fontSize": "10px", "color": MUTED, "marginBottom": "6px"}),
                     dcc.Graph(figure=fig_radar, config={"displayModeBar": False, "responsive": True},
                               style={"height": "520px", "width": "100%"})] + avail_notes)]),
                html.Div(className="c4", children=[card("Peer Context", [
                    html.Div(f"{peer['n_peers']}", style={"fontFamily": "Orbitron", "fontSize": "30px", "fontWeight": "900", "color": GOLD}),
                    html.Div(f"league {pos_group}s in peer group", style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
                    # Scouting summary + confidence badge
                    html.Div(peer.get("scouting_summary", ""), style={"fontSize": "11px", "color": TEXT, "lineHeight": "1.5",
                                                                       "marginBottom": "8px", "padding": "8px", "background": f"{GOLD}10", "borderRadius": "6px"}),
                    html.Div([
                        html.Span("Confidence: ", style={"fontSize": "10px", "color": MUTED}),
                        html.Span(peer.get("confidence", "low").upper(),
                                  style={"fontSize": "10px", "fontWeight": "700",
                                         "color": {"high": ACCENT_GREEN, "medium": GOLD, "low": ACCENT_RED}.get(peer.get("confidence"), MUTED)}),
                        html.Span(f"  ({peer.get('matches_played', 0)} matches)", style={"fontSize": "10px", "color": MUTED}),
                    ], style={"marginBottom": "10px"}),
                    html.Div(sw_children),
                    html.Div("Percentiles compare this player to all league players in the same position group (≥3 matches). Raw values are per-match, event-derived/estimated.",
                             style={"fontSize": "9px", "color": MUTED, "marginTop": "10px", "fontStyle": "italic"}),
                ])]),
            ]))
            content.append(html.Div(className="row", children=[
                html.Div(className="c1", children=[raw_table])]))
            content.append(html.Div(className="row", children=[
                html.Div(className="c1 map-card-full", children=[card("Player Activity Heatmap",
                    [dcc.Graph(figure=_player_heatmap(lf, pa), config={"displayModeBar": True, "responsive": True},
                               style={"height": "820px", "width": "100%"})])]),
            ]))

    # Table
    tdf = ps.head(50)[["player_name", "team_short", "position", "jersey", "matches", "goals", "assists",
                        "shots", "shots_on_target", "pass_accuracy", "key_passes",
                        "tackles", "interceptions", "recoveries", "yellow_cards"]].copy()
    tdf.columns = ["Player", "Team", "Pos", "#", "MP", "G", "A", "Sh", "SOT", "Pass%", "KP", "Tkl", "Int", "Rec", "YC"]
    rows = [html.Tr([html.Td(r[c]) for c in tdf.columns]) for _, r in tdf.iterrows()]
    content.append(card("Player Statistics", [html.Div(style={"overflowX": "auto"}, children=[html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th(c) for c in tdf.columns])),
        html.Tbody(rows),
    ])])]))

    return html.Div(content)


def _player_heatmap(lf, pid):
    df = load_league_data(lf)
    return player_season_heatmap(df, pid)


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 6: PITCH MAPS
# ═══════════════════════════════════════════════════════════════════════════
def page_maps(lf):
    dt = find_default_team(lf)
    ml = get_match_list(lf)
    tm = ml[(ml["home_team"] == dt) | (ml["away_team"] == dt)] if dt else ml
    default_mid = tm.iloc[-1]["match_id"] if not tm.empty else (ml.iloc[-1]["match_id"] if not ml.empty else None)

    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg-wide", children=[
                html.Div("Match", className="fl"),
                dcc.Dropdown(id="pm-match", options=match_opts(lf), value=default_mid, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Team", className="fl"),
                dcc.Dropdown(id="pm-team", className="dd", placeholder="Both"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Half", className="fl"),
                dcc.Dropdown(id="pm-half", options=[
                    {"label": "Full Match", "value": "all"}, {"label": "1st Half", "value": "1st"}, {"label": "2nd Half", "value": "2nd"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg-wide", children=[
                html.Div("Layers", className="fl"),
                dcc.Checklist(id="pm-layers", options=[
                    {"label": " Touch Map", "value": "touch"}, {"label": " Pass Origins", "value": "passorg"},
                    {"label": " Receptions", "value": "recept"}, {"label": " Shot Zone Profile", "value": "shotzone"},
                    {"label": " Defensive", "value": "defheat"}, {"label": " Zone Occupancy", "value": "occupy"},
                    {"label": " Pass Network", "value": "net"}, {"label": " Shot Map (Events)", "value": "shotmap"},
                ], value=["touch"], inline=True, className="chk",
                   labelStyle={"display": "inline-block", "marginRight": "14px"}),
            ]),
            html.Div(className="fg", id="pm-minpass-wrap", children=[
                html.Div("Min Passes (Network)", className="fl"),
                dcc.Dropdown(id="pm-minpass", options=[
                    {"label": "1+", "value": 1}, {"label": "2+", "value": 2},
                    {"label": "3+", "value": 3}, {"label": "5+", "value": 5},
                    {"label": "8+", "value": 8}, {"label": "10+", "value": 10},
                ], value=2, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Touch Actions", className="fl"),
                dcc.Dropdown(id="pm-touch-actions", options=[
                    {"label": "All Actions", "value": "all"},
                    {"label": "Passes", "value": "Pass"},
                    {"label": "Tackles", "value": "Tackle"},
                    {"label": "Recoveries", "value": "Ball recovery"},
                    {"label": "Interceptions", "value": "Interception"},
                    {"label": "Take Ons", "value": "Take On"},
                    {"label": "Clearances", "value": "Clearance"},
                    {"label": "Shots", "value": "shots"},
                    {"label": "Aerials", "value": "Aerial"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Pitch Third", className="fl"),
                dcc.Checklist(id="pm-thirds", options=[
                    {"label": " Def", "value": "def"},
                    {"label": " Mid", "value": "mid"},
                    {"label": " Att", "value": "att"},
                ], value=["def", "mid", "att"], inline=True, className="chk",
                   labelStyle={"display": "inline-block", "marginRight": "10px"}),
            ]),
            html.Div(className="fg", children=[
                html.Div("Pass Type", className="fl"),
                dcc.Dropdown(id="pm-passtype", options=[
                    {"label": "All Passes", "value": "all"},
                    {"label": "Short (<15m)", "value": "short"},
                    {"label": "Long (>30m)", "value": "long"},
                    {"label": "Progressive", "value": "progressive"},
                    {"label": "Final Third", "value": "final_third"},
                    {"label": "Box Entry", "value": "box_entry"},
                    {"label": "Crosses", "value": "cross"},
                    {"label": "Switches", "value": "switch"},
                    {"label": "Through Balls", "value": "through"},
                    {"label": "Successful", "value": "successful"},
                    {"label": "Failed", "value": "failed"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Layout", className="fl"),
                dcc.Dropdown(id="pm-layout", options=[
                    {"label": "Auto", "value": "auto"},
                    {"label": "Focus (1 full-width)", "value": "focus"},
                    {"label": "Compare (2 side-by-side)", "value": "compare"},
                    {"label": "Stack (full-width rows)", "value": "stack"},
                ], value="auto", clearable=False, className="dd"),
            ]),
        ]),
        html.Div(id="pm-content"),
    ])


@callback(Output("pm-team", "options"), Output("pm-team", "value"),
          Input("pm-match", "value"), Input("league-selector", "value"))
def pm_team_opts(mid, lf):
    if not mid:
        return [], None
    mdf = get_match_data(lf, mid)
    teams = mdf["team_name"].dropna().unique().tolist()
    opts = [{"label": short(t), "value": t} for t in teams]
    # Default to Lens if present
    dt = find_default_team(lf)
    val = dt if dt in teams else (teams[0] if teams else None)
    return opts, val


def _map_insight_card(layer, plotted_df, team):
    """Render a multi-part tactical insight (primary/secondary/risk/coaching/
    evidence) for a map layer. Returns None when no insight applies."""
    from components.map_insights import INSIGHT_FOR_LAYER
    fn = INSIGHT_FOR_LAYER.get(layer)
    if fn is None:
        return None
    try:
        ins = fn(plotted_df, team)
    except Exception:
        return None
    if not ins.get("primary"):
        return None
    rows = [html.Div([html.Span("▸ Pattern: ", style={"color": GOLD, "fontWeight": "700"}), ins["primary"]],
                     style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"})]
    if ins.get("secondary"):
        rows.append(html.Div([html.Span("▸ Detail: ", style={"color": ACCENT_BLUE, "fontWeight": "700"}), ins["secondary"]],
                             style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}))
    if ins.get("risk"):
        rows.append(html.Div([html.Span("⚠ Risk: ", style={"color": "#FEB019", "fontWeight": "700"}), ins["risk"]],
                             style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}))
    if ins.get("coaching"):
        rows.append(html.Div([html.Span("✎ Coaching: ", style={"color": ACCENT_GREEN, "fontWeight": "700"}), ins["coaching"]],
                             style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}))
    if ins.get("evidence"):
        rows.append(html.Div(f"Evidence: {ins['evidence']}", style={"fontSize": "9px", "color": MUTED, "fontStyle": "italic", "marginTop": "4px"}))
    return html.Div(rows, style={"padding": "10px 12px", "marginTop": "6px", "background": "#0E1318",
                                 "borderRadius": "6px", "borderLeft": f"3px solid {GOLD}"})


def _map_summary(team, mdf_full, plotted_df, *, half, thirds, action=None, passtype=None,
                 coord_x="x", coord_y="y", source="Event data (Opta x,y∈[0,100], attack→x=100)"):
    """Build a per-map filter/validation summary line. Counts come straight from
    the plotted frame so displayed numbers always equal plotted points."""
    from components.zone_model import zone_breakdown
    team_full = mdf_full[mdf_full["team_name"] == team] if team else mdf_full
    before = len(team_full)
    plotted = len(plotted_df)
    excluded = max(before - plotted, 0)
    br = zone_breakdown(plotted_df, x_col=coord_x, y_col=coord_y)
    third_txt = "/".join(t for t in ["def", "mid", "att"] if t in (thirds or [])) or "all"
    bits = [f"Half: {half}", f"Third: {third_txt}"]
    if action and action != "all":
        bits.append(f"Action: {action}")
    if passtype and passtype != "all":
        bits.append(f"Pass type: {passtype}")
    bits += [f"Plotted: {plotted}", f"Excluded: {excluded}",
             f"Def/Mid/Att: {br['thirds'].get('def',0)}/{br['thirds'].get('mid',0)}/{br['thirds'].get('att',0)}"]
    return html.Div([
        html.Div("  ·  ".join(bits), style={"fontSize": "10px", "color": MUTED}),
        html.Div(f"Coordinates: {source}", style={"fontSize": "9px", "color": MUTED, "fontStyle": "italic", "marginTop": "2px"}),
    ], style={"padding": "6px 10px", "marginTop": "6px", "background": "#0E1318", "borderRadius": "6px"})


@callback(Output("pm-content", "children"),
          Input("pm-match", "value"), Input("pm-team", "value"),
          Input("pm-half", "value"), Input("pm-layers", "value"),
          Input("pm-minpass", "value"), Input("pm-touch-actions", "value"),
          Input("pm-thirds", "value"), Input("pm-passtype", "value"),
          Input("pm-layout", "value"),
          Input("league-selector", "value"))
def update_maps(mid, team, half, layers, min_passes, touch_action, thirds, passtype, layout_mode, lf):
    if not mid:
        return html.Div()

    mdf = get_match_data(lf, mid)
    if mdf.empty:
        return html.Div("Match data not found in current season", style={"color": MUTED, "textAlign": "center", "padding": "40px"})
    mdf = filter_by_period(mdf, half)
    layers = layers or []
    min_passes = min_passes or 2
    thirds = thirds if thirds else ["def", "mid", "att"]
    passtype = passtype or "all"
    layout_mode = layout_mode or "auto"

    from components.heatmaps import filter_events_by_pitch_third, filter_passes_by_type
    # Pitch-third filter applies to EVERY compatible layer (not just Touch Map)
    third_active = set(thirds) < {"def", "mid", "att"}
    third_label = "" if not third_active else " · " + "/".join(
        {"def": "Def", "mid": "Mid", "att": "Att"}[t] for t in ["def", "mid", "att"] if t in thirds)
    # A third-filtered frame shared by all point-based maps
    mdf_third = filter_events_by_pitch_third(mdf, thirds) if third_active else mdf
    pass_label = "" if passtype == "all" else f" · {passtype.replace('_', ' ').title()}"

    # Layout mode: focus=1 full-width, compare=2 side-by-side, stack=full-width rows, auto=responsive
    n_layers = len([l for l in layers if l in ("touch", "passorg", "recept", "shotzone", "defheat", "occupy", "net", "shotmap")])
    if layout_mode == "focus" or (layout_mode == "auto" and n_layers <= 1):
        col_cls, gh = "c1 map-card-full", 820
    elif layout_mode == "stack":
        col_cls, gh = "c1 map-card-full", 760
    elif layout_mode == "compare":
        col_cls, gh = "c6", 620
    elif n_layers == 2:
        col_cls, gh = "c6", 620
    else:
        col_cls, gh = "c6", 540
    gstyle = {"height": f"{gh}px", "width": "100%"}
    # Modebar OFF prevents focus-grab and zoom that visually "shrinks" the pitch.
    gcfg = {"displayModeBar": False, "responsive": True}
    cards = []

    if "touch" in layers:
        touch_df = mdf_third
        action_label = "All"
        if touch_action and touch_action != "all":
            if touch_action == "shots":
                touch_df = touch_df[touch_df["event"].isin(["Goal", "Miss", "Post", "Saved Shot"])]
                action_label = "Shots"
            else:
                touch_df = touch_df[touch_df["event"] == touch_action]
                action_label = touch_action
        # plotted = EXACTLY what the touch map draws. The map uses
        # filter_valid_touch_events (excludes Out/admin events and out-of-bounds
        # coordinates), so the footer must use the identical filter or the count
        # would over-report vs the dots on screen.
        from components.definitions import filter_valid_touch_events
        _touch_src = touch_df[touch_df["team_name"] == team] if team else touch_df
        touch_plotted, _ = filter_valid_touch_events(_touch_src)
        cards.append(html.Div(className=col_cls, children=[
            card(f"Touch Map — {short(team) if team else 'All'} ({action_label}{third_label})",
                 [dcc.Graph(figure=touch_heatmap(touch_df, team), config=gcfg, style=gstyle),
                  _map_summary(team, mdf, touch_plotted, half=half, thirds=thirds, action=action_label),
                  _map_insight_card("touch", touch_plotted, team)])]))
    if "passorg" in layers and team:
        # third + pass-type filters both apply to pass origins
        porg = filter_passes_by_type(mdf_third, passtype) if passtype != "all" else mdf_third
        from components.definitions import filter_valid_pass_events
        porg_plotted, _ = filter_valid_pass_events(porg[porg["team_name"] == team], x_col="x", y_col="y")
        cards.append(html.Div(className=col_cls, children=[
            card(f"Pass Origins — {short(team)}{third_label}{pass_label}",
                 [dcc.Graph(figure=pass_origin_heatmap(porg, team), config=gcfg, style=gstyle),
                  _map_summary(team, mdf, porg_plotted, half=half, thirds=thirds, passtype=passtype),
                  _map_insight_card("passorg", porg_plotted, team)])]))
    if "recept" in layers and team:
        from components.definitions import filter_valid_reception_events
        recept_plotted, _ = filter_valid_reception_events(mdf_third[mdf_third["team_name"] == team], x_col="Pass End X", y_col="Pass End Y")
        cards.append(html.Div(className=col_cls, children=[
            card(f"Reception Zones — {short(team)}{third_label}",
                 [dcc.Graph(figure=reception_heatmap(mdf_third, team), config=gcfg, style=gstyle),
                  _map_summary(team, mdf, recept_plotted, half=half, thirds=thirds, coord_x="Pass End X", coord_y="Pass End Y"),
                  _map_insight_card("recept", recept_plotted, team)])]))
    if "shotzone" in layers:
        cards.append(html.Div(className=col_cls, children=[
            card(f"Shot Zone Profile — {short(team) if team else 'All'}", [dcc.Graph(figure=shot_heatmap(mdf, team), config=gcfg, style=gstyle)])]))
    if "defheat" in layers and team:
        from components.definitions import filter_valid_defensive_events
        def_plotted, _ = filter_valid_defensive_events(mdf_third[mdf_third["team_name"] == team], x_col="x", y_col="y")
        cards.append(html.Div(className=col_cls, children=[
            card(f"Defensive Actions — {short(team)}{third_label}",
                 [dcc.Graph(figure=defensive_heatmap(mdf_third, team), config=gcfg, style=gstyle),
                  _map_summary(team, mdf, def_plotted, half=half, thirds=thirds),
                  _map_insight_card("defheat", def_plotted, team)])]))
    if "occupy" in layers and team:
        from components.definitions import filter_valid_touch_events
        occ_plotted, _ = filter_valid_touch_events(mdf_third[mdf_third["team_name"] == team])
        cards.append(html.Div(className=col_cls, children=[
            card(f"Event Zone Occupancy — {short(team)}{third_label}",
                 [dcc.Graph(figure=zone_occupancy_heatmap(mdf_third, team), config=gcfg, style=gstyle),
                  _map_summary(team, mdf, occ_plotted, half=half, thirds=thirds),
                  _map_insight_card("occupy", occ_plotted, team)])]))
    if "shotmap" in layers:
        cards.append(html.Div(className=col_cls, children=[
            card(f"Shot Map (Estimated Quality) — {short(team) if team else 'All'}", [dcc.Graph(figure=shot_map(mdf, team), config=gcfg, style=gstyle)])]))
    if "net" in layers and team:
        cards.append(html.Div(className=col_cls, children=[
            card(f"Pass Network — {short(team)} (min {min_passes} passes)", [dcc.Graph(figure=pass_network(mdf, team, min_passes=min_passes), config=gcfg, style=gstyle)])]))

    if not cards:
        cards = [html.Div(className="c1", style={"textAlign": "center", "padding": "50px", "color": MUTED},
                          children=["Select map layers above"])]

    # Insights summary for selected team
    insight_section = None
    if team:
        from components.insights import (insight_shot_profile, insight_defensive_zone,
                                          insight_pass_network, insight_zone_occupancy,
                                          insight_reception_zones, insight_card_html)
        insights = []
        if "touch" in layers or "occupy" in layers:
            insights.append(insight_card_html(f"Territory: {insight_zone_occupancy(mdf, team)}", "🗺️"))
        if "recept" in layers:
            insights.append(insight_card_html(f"Receptions: {insight_reception_zones(mdf, team)}", "🎯"))
        if "shotzone" in layers or "shotmap" in layers:
            insights.append(insight_card_html(f"Shot profile: {insight_shot_profile(mdf, team)}", "⚽"))
        if "defheat" in layers:
            insights.append(insight_card_html(f"Defensive shape: {insight_defensive_zone(mdf, team)}", "🛡️"))
        if "net" in layers or "passorg" in layers:
            insights.append(insight_card_html(f"Buildup: {insight_pass_network(mdf, team)}", "🔁"))
        if insights:
            insight_section = card(f"📋 Tactical Insights — {short(team)}", [i for i in insights if i is not None])

    # Sample-size caveat + filter summary banner
    n_events = len(mdf[mdf["team_name"] == team]) if team else len(mdf)
    half_label = {"all": "Full match", "1": "1st half", "2": "2nd half"}.get(str(half), str(half))
    caveat = []
    if n_events < 50:
        caveat.append(html.Span(f"⚠ Small sample ({n_events} events) — zone density may be unreliable.",
                                style={"color": "#FEB019", "marginRight": "12px"}))
    banner = html.Div(style={"padding": "8px 14px", "marginBottom": "10px", "background": "#10151D",
                             "borderRadius": "8px", "border": "1px solid #1E2733", "fontSize": "11px", "color": "#8A95A5"},
                      children=caveat + [
        html.Span(f"Filters: {short(team) if team else 'All teams'} · {half_label} · "
                  f"{n_events} events · Pass colours — Successful = green, Failed = red · "
                  f"xG on shot maps is Estimated (event-derived), not official Wyscout shot xG")])

    return html.Div([
        banner,
        html.Div(className="row", children=cards),
        insight_section,
    ])


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 7: SEASON TRENDS (comprehensive rewrite — 8 blocks)
# ═══════════════════════════════════════════════════════════════════════════
def page_trends(lf):
    dt = find_default_team(lf)
    return html.Div([
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("Team", className="fl"),
                dcc.Dropdown(id="tr-team", options=team_opts(lf), value=dt, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Rolling Window", className="fl"),
                dcc.Dropdown(id="tr-window", options=[
                    {"label": "3-match", "value": 3}, {"label": "5-match", "value": 5},
                    {"label": "10-match", "value": 10},
                ], value=5, clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Venue", className="fl"),
                dcc.Dropdown(id="tr-venue", options=[
                    {"label": "All", "value": "all"}, {"label": "Home", "value": "home"},
                    {"label": "Away", "value": "away"},
                ], value="all", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Opponent Strength", className="fl"),
                dcc.Dropdown(id="tr-oppstr", options=[
                    {"label": "All", "value": "all"}, {"label": "Top 6", "value": "top6"},
                    {"label": "Mid table", "value": "mid"}, {"label": "Bottom 6", "value": "bottom6"},
                ], value="all", clearable=False, className="dd"),
            ]),
        ]),
        dcc.Loading(type="circle", color=GOLD, children=[
            html.Div(id="tr-content"),
        ]),
    ])


@callback(Output("tr-content", "children"),
          Input("tr-team", "value"), Input("tr-window", "value"),
          Input("tr-venue", "value"), Input("tr-oppstr", "value"),
          Input("league-selector", "value"))
def update_trends(team, window, venue, oppstr, lf):
    if not team:
        return html.Div()
    from components.trends_engine import build_trends_page
    return build_trends_page(lf, team, rolling_window=window or 5,
                             venue=(venue or "all"), opp_strength=(oppstr or "all"))


# ═══════════════════════════════════════════════════════════════════════════
#  TAB 8: MATCH REPORTS (Pre-Match & Post-Match)
# ═══════════════════════════════════════════════════════════════════════════
def page_reports(lf):
    dt = find_default_team(lf)
    teams = get_teams(lf)
    opp_default = [t for t in teams if t != dt]

    return html.Div([
        # Report type selector
        html.Div(className="fbar", children=[
            html.Div(className="fg", children=[
                html.Div("Report Type", className="fl"),
                dcc.Dropdown(id="rp-type", options=[
                    {"label": "📋 Pre-Match Report", "value": "pre"},
                    {"label": "📊 Post-Match Report", "value": "post"},
                ], value="pre", clearable=False, className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Our Team", className="fl"),
                dcc.Dropdown(id="rp-our-team", options=team_opts(lf), value=dt, clearable=False, className="dd"),
            ]),
            # Pre-match: opponent selector / Post-match: match selector
            html.Div(className="fg", id="rp-opp-wrap", children=[
                html.Div("Opponent", className="fl"),
                dcc.Dropdown(id="rp-opponent", options=team_opts(lf),
                             value=opp_default[0] if opp_default else None, clearable=False, className="dd"),
            ]),
            html.Div(className="fg-wide", id="rp-match-wrap", children=[
                html.Div("Match", className="fl"),
                dcc.Dropdown(id="rp-match", options=match_opts(lf), className="dd"),
            ]),
            html.Div(className="fg", children=[
                html.Div("Sample Size", className="fl"),
                dcc.Dropdown(id="rp-sample", options=[
                    {"label": "Last 3", "value": 3}, {"label": "Last 5", "value": 5},
                    {"label": "Last 10", "value": 10}, {"label": "All", "value": 50},
                ], value=5, clearable=False, className="dd"),
            ]),
            html.Div(style={"display": "flex", "alignItems": "flex-end", "gap": "10px"}, children=[
                html.Button("Generate Report", id="rp-generate",
                    style={
                        "background": f"linear-gradient(135deg, {GOLD}, #B8960F)",
                        "color": "#000", "fontWeight": "700", "fontSize": "12px",
                        "padding": "10px 24px", "border": "none", "borderRadius": "8px",
                        "cursor": "pointer", "letterSpacing": "0.5px", "textTransform": "uppercase",
                        "fontFamily": "Inter, sans-serif",
                    }),
                html.Button("⬇ Export PDF", id="rp-export-pdf",
                    style={
                        "background": "transparent", "color": GOLD, "fontWeight": "700",
                        "fontSize": "12px", "padding": "10px 18px",
                        "border": f"1px solid {GOLD}", "borderRadius": "8px",
                        "cursor": "pointer", "letterSpacing": "0.5px", "textTransform": "uppercase",
                        "fontFamily": "Inter, sans-serif",
                    }),
            ]),
        ]),
        dcc.Download(id="rp-download-pdf"),
        # Loading indicator
        dcc.Loading(id="rp-loading", type="circle", color=GOLD, children=[
            html.Div(id="rp-content", style={"minHeight": "300px"}),
        ]),
    ])


@callback(
    Output("rp-opp-wrap", "style"),
    Output("rp-match-wrap", "style"),
    Input("rp-type", "value"),
)
def toggle_report_selectors(rtype):
    if rtype == "pre":
        return {"display": "block", "flex": "1", "minWidth": "150px"}, {"display": "none"}
    else:
        return {"display": "none"}, {"display": "block", "flex": "2", "minWidth": "250px"}


@callback(
    Output("rp-match", "options"),
    Output("rp-match", "value"),
    Input("rp-our-team", "value"),
    Input("league-selector", "value"),
)
def update_report_match_options(our_team, lf):
    if not our_team:
        return match_opts(lf), None
    ml = get_match_list(lf)
    tm = ml[(ml["home_team"] == our_team) | (ml["away_team"] == our_team)]
    tm = tm.sort_values("week", ascending=False)
    opts = []
    for _, r in tm.iterrows():
        label = f"W{r['week']}  {short(r['home_team'])} {r['home_goals']}-{r['away_goals']} {short(r['away_team'])}"
        opts.append({"label": label, "value": r["match_id"]})
    default = opts[0]["value"] if opts else None
    return opts, default


@callback(
    Output("rp-content", "children"),
    # Option A — every selector is a live INPUT, so changing the team/opponent/
    # sample/type/match regenerates the report immediately. A stale report (e.g.
    # "How Lens score" while PSG is selected) is therefore impossible.
    Input("rp-generate", "n_clicks"),
    Input("rp-type", "value"),
    Input("rp-our-team", "value"),
    Input("rp-opponent", "value"),
    Input("rp-match", "value"),
    Input("rp-sample", "value"),
    Input("league-selector", "value"),
)
def generate_report(n_clicks, rtype, our_team, opponent, match_id, sample, lf):
    if not our_team:
        return html.Div("Select our team", style={"color": MUTED, "textAlign": "center", "padding": "60px"})

    try:
        if rtype == "pre":
            if not opponent:
                return html.Div("Select opponent team", style={"color": MUTED, "textAlign": "center", "padding": "60px"})
            if opponent == our_team:
                return html.Div("Select a different opponent", style={"color": MUTED, "textAlign": "center", "padding": "60px"})
            return build_pre_match_report(lf, our_team, opponent, last_n=sample or 5)
        else:
            if not match_id:
                return html.Div("Select a match", style={"color": MUTED, "textAlign": "center", "padding": "60px"})
            return build_post_match_report(lf, match_id, our_team)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"Report generation error: {e}\n{tb}")
        return html.Div(style={"textAlign": "center", "padding": "60px"}, children=[
            html.Div("⚠️ Report Generation Error", style={"color": ACCENT_RED, "fontWeight": "700", "fontSize": "16px", "marginBottom": "12px"}),
            html.Div(f"Could not generate the report for this match. This may happen when switching seasons or selecting a match from a different dataset.",
                     style={"color": MUTED, "fontSize": "13px", "maxWidth": "500px", "margin": "0 auto", "lineHeight": "1.6"}),
            html.Div(f"Error: {str(e)[:200]}", style={"color": "#5A6575", "fontSize": "11px", "marginTop": "12px", "fontFamily": "monospace"}),
        ])


# ═══════════════════════════════════════════════════════════════════════════
#  PDF EXPORT (Pre-Match & Post-Match)
# ═══════════════════════════════════════════════════════════════════════════
@callback(
    Output("rp-download-pdf", "data"),
    Input("rp-export-pdf", "n_clicks"),
    State("rp-type", "value"),
    State("rp-our-team", "value"),
    State("rp-opponent", "value"),
    State("rp-match", "value"),
    State("rp-sample", "value"),
    State("league-selector", "value"),
    prevent_initial_call=True,
)
def export_report_pdf_cb(n_clicks, rtype, our_team, opponent, match_id, sample, lf):
    if not n_clicks or not our_team:
        return no_update
    try:
        from components.pdf_export import export_model_pdf, pdf_export_available
        from components.report_model import (build_post_match_report_model,
                                             build_pre_match_report_model)
        if not pdf_export_available():
            return dict(content="PDF export requires the 'reportlab' package. "
                                "Install with: pip install reportlab",
                        filename="pdf_export_unavailable.txt")

        # SHARED report model — identical to what the Dash report renders.
        if rtype == "post" and match_id:
            model = build_post_match_report_model(lf, match_id, our_team)
        else:
            model = build_pre_match_report_model(lf, our_team, opponent or our_team,
                                                 last_n=sample or 5)

        pdf_bytes, fname = export_model_pdf(model)
        if pdf_bytes is None:
            return dict(content=str(fname), filename="pdf_export_error.txt")
        return dcc.send_bytes(lambda b: b.write(pdf_bytes), fname)
    except Exception as e:
        import traceback; traceback.print_exc()
        return dict(content=f"PDF export failed: {e}", filename="pdf_export_error.txt")


# ═══════════════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n🚀 Dashboard running at http://127.0.0.1:8050\n")
    app.run(debug=True, host="0.0.0.0", port=8050)
