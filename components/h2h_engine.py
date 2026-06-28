"""
components/h2h_engine.py — Head-to-Head Analysis Engine & Page Builder
Implements the full H2H specification:
  1. Matchup Snapshot (record, xG, possession, PPDA, etc.)
  2. Style Clash (side-by-side tactical profiles)
  3. Attacking Comparison (shots, box entries, xG by zone)
  4. Defensive Comparison (xG conceded, regain zones)
  5. Transition Battle (fast-break xG, turnovers)
  6. Territory & Zone Maps (heatmaps, entry zones)
  7. Set-Piece H2H
  8. Key Player Influence (top 3 per team)
  9. Coaching Summary (edges, dangers, patterns)
"""

import pandas as pd
import numpy as np
from components.dash_compat import dcc, html
import plotly.graph_objects as go

from data_loader import (
    load_league_data, get_match_list, get_match_data, get_teams,
    get_head_to_head, get_team_results, compute_league_table,
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
    compute_team_profile, _xg_from_distance, _safe_pct, _safe_div,
    SHOT_EVENTS, FINAL_THIRD_X, MID_THIRD_X, BOX_X, BOX_Y_LO, BOX_Y_HI,
)
from components.heatmaps import defensive_action_zone_grid, attacking_zone_grid
from components.charts import (


    shot_map, defensive_map, pass_network,
    BG, CARD_BG, GRID, TEXT, MUTED, GOLD, GOLD_DIM,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, ACCENT_PURPLE, _tmpl,
)

# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════
def _logo(team, size=36):
    src = get_logo_base64(team)
    if src:
        return html.Img(src=src, style={"width": f"{size}px", "height": f"{size}px", "objectFit": "contain"})
    return html.Span(short(team)[:3], style={"fontWeight": "700"})

def _card(title, children, s=None):
    return html.Div(className="card", style=s or {}, children=[
        html.Div(title, className="card-t") if title else None,
        *(children if isinstance(children, list) else [children]),
    ])

def _kpi(val, label, color=GOLD, small=True):
    sz = "18px" if small else "24px"
    return html.Div(className="kpi", children=[
        html.Div(str(val), className="kpi-v", style={"color": color, "fontSize": sz}),
        html.Div(label, className="kpi-l"),
    ])

def compute_buildup_patterns(df, team_name, match_ids):
    """UI re-export — analytics live in components.h2h_metrics (Dash-free)."""
    from components.h2h_metrics import compute_buildup_patterns as _f
    return _f(df, team_name, match_ids)


def compute_passing_profile(df, team_name, match_ids):
    """UI re-export — analytics live in components.h2h_metrics (Dash-free)."""
    from components.h2h_metrics import compute_passing_profile as _f
    return _f(df, team_name, match_ids)


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

def _stat_line(label, value, color):
    """Single labelled stat row for build-up cards."""
    v = f"{value:.1f}" if isinstance(value, float) else str(value)
    return html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
                           "padding": "5px 8px", "borderBottom": f"1px solid {CARD_BG}"}, children=[
        html.Span(label, style={"fontSize": "11px", "color": MUTED}),
        html.Span(v, style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "13px"}),
    ])


def _vs_bar(label, va, vb, ca, cb, fmt="{:.0f}", higher_better=True):
    """Mirrored comparison bar — value A vs value B."""
    va_f = fmt.format(va) if isinstance(va, (int, float)) else str(va)
    vb_f = fmt.format(vb) if isinstance(vb, (int, float)) else str(vb)
    mx = max(abs(va), abs(vb), 0.01)
    pa = abs(va) / mx * 100
    pb = abs(vb) / mx * 100
    # Highlight winner
    a_better = (va > vb) if higher_better else (va < vb)
    b_better = not a_better and va != vb
    return html.Div(style={"marginBottom": "6px"}, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px", "fontSize": "11px"}, children=[
            html.Span(va_f, style={"width": "45px", "textAlign": "right", "fontWeight": "700" if a_better else "400",
                                    "color": ca if a_better else MUTED, "fontFamily": "Orbitron, monospace", "fontSize": "12px"}),
            html.Div(style={"flex": "1", "display": "flex", "height": "12px", "borderRadius": "3px", "overflow": "hidden", "gap": "2px"}, children=[
                html.Div(style={"flex": "1", "display": "flex", "justifyContent": "flex-end"}, children=[
                    html.Div(style={"width": f"{pa}%", "background": f"linear-gradient(90deg, transparent, {ca}{'cc' if a_better else '55'})", "borderRadius": "3px 0 0 3px", "minWidth": "2px"}),
                ]),
                html.Div(style={"flex": "1"}, children=[
                    html.Div(style={"width": f"{pb}%", "background": f"linear-gradient(90deg, {cb}{'cc' if b_better else '55'}, transparent)", "borderRadius": "0 3px 3px 0", "minWidth": "2px", "height": "100%"}),
                ]),
            ]),
            html.Span(vb_f, style={"width": "45px", "fontWeight": "700" if b_better else "400",
                                    "color": cb if b_better else MUTED, "fontFamily": "Orbitron, monospace", "fontSize": "12px"}),
        ]),
        html.Div(label, style={"textAlign": "center", "fontSize": "9px", "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
    ])

def _edge_badge(label, winner, color):
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "6px 10px",
                            "background": f"{color}10", "borderLeft": f"3px solid {color}", "borderRadius": "6px", "marginBottom": "4px"}, children=[
        html.Span(f"→ {winner}", style={"fontSize": "11px", "fontWeight": "700", "color": color}),
        html.Span(label, style={"fontSize": "10px", "color": MUTED}),
    ])


# ══════════════════════════════════════════════════════════════════════════
#  H2H MATCH STATS COMPUTATION
# ══════════════════════════════════════════════════════════════════════════
def _compute_h2h_team_stats(df, team_name, match_ids):
    """UI re-export — analytics live in components.h2h_metrics (Dash-free)."""
    from components.h2h_metrics import compute_h2h_team_stats as _f
    return _f(df, team_name, match_ids)


def _get_h2h_key_players(df, team_name, match_ids, top_n=3):
    """UI re-export — analytics live in components.h2h_metrics (Dash-free)."""
    from components.h2h_metrics import get_h2h_key_players as _f
    return _f(df, team_name, match_ids, top_n)


# ══════════════════════════════════════════════════════════════════════════
#  H2H PAGE BUILDER
# ══════════════════════════════════════════════════════════════════════════
def resolve_h2h_match_ids(ml, team_a, team_b, scope="all", selected_match_id=None):
    """UI re-export — analytics live in components.h2h_metrics (Dash-free)."""
    from components.h2h_metrics import resolve_h2h_match_ids as _f
    return _f(ml, team_a, team_b, scope, selected_match_id)


def build_h2h_page(lf, team_a, team_b, scope="all", selected_match_id=None):
    """Build the complete H2H page as Dash layout."""
    df = load_league_data(lf)
    ml = get_match_list(lf)
    h2h = get_head_to_head(lf, team_a, team_b)

    ca, cb = team_color(team_a), team_color(team_b)
    if ca == cb:
        cb = ACCENT_BLUE

    # Resolve match_ids via the scope filter (applies to the WHOLE page)
    match_ids, scope_label = resolve_h2h_match_ids(ml, team_a, team_b, scope, selected_match_id)

    has_h2h = len(match_ids) > 0

    # Scope-aware H2H record — when a sample (last meeting / last 3 / specific)
    # is selected, the header + snapshot reflect THAT sample, not all-time.
    if scope == "all" or not match_ids:
        rec = {"a_wins": h2h["a_wins"], "draws": h2h["draws"], "b_wins": h2h["b_wins"],
               "a_goals": h2h["a_goals"], "b_goals": h2h["b_goals"], "total": h2h["total"]}
    else:
        sub = ml[ml["match_id"].isin(match_ids)]
        aw = dw = bw = ag = bg = 0
        for _, r in sub.iterrows():
            home, away = r["home_team"], r["away_team"]
            hg, agl = int(r["home_goals"]), int(r["away_goals"])
            a_goals = hg if home == team_a else agl
            b_goals = hg if home == team_b else agl
            ag += a_goals; bg += b_goals
            if a_goals > b_goals: aw += 1
            elif a_goals < b_goals: bw += 1
            else: dw += 1
        rec = {"a_wins": aw, "draws": dw, "b_wins": bw, "a_goals": ag, "b_goals": bg,
               "total": len(sub)}

    # Get H2H match stats
    if has_h2h:
        sa = _compute_h2h_team_stats(df, team_a, match_ids)
        sb = _compute_h2h_team_stats(df, team_b, match_ids)
    else:
        sa = sb = None

    # Get season-wide profiles for style comparison
    pa = compute_team_profile(lf, team_a, last_n=50)
    pb = compute_team_profile(lf, team_b, last_n=50)

    # H2H match event data (combined)
    h2h_df = df[df["match_id"].isin(match_ids)] if match_ids else pd.DataFrame()

    sections = []

    # ════ HEADER ════
    sections.append(html.Div(className="score-ban", children=[
        html.Div(className="score-row", children=[
            html.Div(className="score-team", children=[_logo(team_a, 52), html.Div(short(team_a), className="score-team-name", style={"color": ca})]),
            html.Div("VS", style={"fontFamily": "Orbitron", "fontSize": "24px", "color": MUTED, "fontWeight": "900"}),
            html.Div(className="score-team", children=[_logo(team_b, 52), html.Div(short(team_b), className="score-team-name", style={"color": cb})]),
        ]),
        html.Div(f"Record (this sample): {rec['a_wins']}W - {rec['draws']}D - {rec['b_wins']}W  ·  Goals: {rec['a_goals']}-{rec['b_goals']}  ·  {rec['total']} match{'es' if rec['total'] != 1 else ''}",
                 className="score-meta"),
    ]))

    # ════ DATA-BASIS BANNER (reflects the active scope filter) ════
    sections.append(html.Div(style={"padding": "8px 14px", "marginBottom": "12px",
                                    "background": "#10151D", "borderRadius": "8px",
                                    "border": "1px solid #1E2733", "fontSize": "11px", "color": "#8A95A5"}, children=[
        html.Span("Data basis: ", style={"color": MUTED}),
        html.Span(f"{scope_label}", style={"color": GOLD, "fontWeight": "700"}),
        html.Span(f"  ·  {len(match_ids)} match{'es' if len(match_ids) != 1 else ''} in sample"
                  f"  ·  Aggregate xG/PPDA/Possession use Wyscout where available; entries/zones/maps are event-derived",
                  style={"marginLeft": "6px"}),
    ]))

    # ════ 1. MATCHUP SNAPSHOT ════
    sections.append(_section(1, "Matchup Snapshot", f"{'H2H data from ' + str(len(match_ids)) + ' matches' if has_h2h else 'Season averages (no H2H matches yet)'}"))

    # Use H2H stats if available, else season profiles
    if has_h2h:
        snap_kpis = html.Div(className="row", style={"gap": "8px"}, children=[
            _kpi(rec["a_wins"], f"Wins ({short(team_a)[:6]})", ca),
            _kpi(rec["draws"], "Draws", GOLD),
            _kpi(rec["b_wins"], f"Wins ({short(team_b)[:6]})", cb),
            _kpi(f"{sa['xg']:.1f}", f"xG ({short(team_a)[:5]})", ca),
            _kpi(f"{sb['xg']:.1f}", f"xG ({short(team_b)[:5]})", cb),
            _kpi(f"{sa['possession']:.0f}%", f"Poss ({short(team_a)[:4]})", ca),
            _kpi(f"{sb['possession']:.0f}%", f"Poss ({short(team_b)[:4]})", cb),
        ])
    else:
        snap_kpis = html.Div(className="row", style={"gap": "8px"}, children=[
            _kpi(f"{pa.get('xg_per_match',0):.1f}", f"xG/M ({short(team_a)[:5]})", ca),
            _kpi(f"{pb.get('xg_per_match',0):.1f}", f"xG/M ({short(team_b)[:5]})", cb),
            _kpi(f"{pa.get('possession_pct',50):.0f}%", f"Poss ({short(team_a)[:4]})", ca),
            _kpi(f"{pb.get('possession_pct',50):.0f}%", f"Poss ({short(team_b)[:4]})", cb),
            _kpi(f"{pa.get('ppda',10):.1f}", f"PPDA ({short(team_a)[:4]})", ca),
            _kpi(f"{pb.get('ppda',10):.1f}", f"PPDA ({short(team_b)[:4]})", cb),
        ])
    sections.append(snap_kpis)

    # H2H Match results table — obeys the active scope filter (Last Meeting,
    # Last 3, etc.). Only matches in the resolved sample are shown, so the table
    # never mixes all-time games into a filtered sample.
    _sample_matches = [m for m in h2h["matches"] if m.get("match_id") in set(match_ids)]
    if _sample_matches:
        rows = []
        for m in _sample_matches:
            rows.append(html.Tr([
                html.Td(f"W{m['week']}"),
                html.Td(html.Div(className="team-cell", children=[_logo(m["home"], 18), html.Span(short(m["home"]))]), style={"textAlign": "left"}),
                html.Td(f"{m['home_goals']}-{m['away_goals']}", style={"fontWeight": "700", "fontFamily": "Orbitron"}),
                html.Td(html.Div(className="team-cell", style={"justifyContent": "flex-end"}, children=[html.Span(short(m["away"])), _logo(m["away"], 18)]), style={"textAlign": "right"}),
                html.Td(m["date"]),
            ]))
        sections.append(_card(f"Match Results — {scope_label} · {len(_sample_matches)} match{'es' if len(_sample_matches) != 1 else ''}",
                              [html.Table(className="tbl", children=[
            html.Thead(html.Tr([html.Th("Wk"), html.Th("Home"), html.Th(""), html.Th("Away"), html.Th("Date")])),
            html.Tbody(rows),
        ])]))

    # ════ 2. STYLE CLASH ════
    sections.append(_section(2, "Style Clash", "Side-by-side tactical profiles · Season Context — NOT the filtered H2H sample"))

    sa_s = pa  # season profile A
    sb_s = pb  # season profile B
    style_bars = _card(f"{short(team_a)} vs {short(team_b)}", [
        _vs_bar("Possession %", sa_s.get("possession_pct", 50), sb_s.get("possession_pct", 50), ca, cb, "{:.1f}"),
        _vs_bar("xG / Match", sa_s.get("xg_per_match", 0), sb_s.get("xg_per_match", 0), ca, cb, "{:.2f}"),
        _vs_bar("PPDA (lower = more pressing)", sa_s.get("ppda", 10), sb_s.get("ppda", 10), ca, cb, "{:.1f}", higher_better=False),
        _vs_bar("Prog Passes / M", sa_s.get("prog_passes_pm", 0), sb_s.get("prog_passes_pm", 0), ca, cb, "{:.0f}"),
        _vs_bar("Final-Third Entries / M", sa_s.get("ft_entries_pm", 0), sb_s.get("ft_entries_pm", 0), ca, cb, "{:.0f}"),
        _vs_bar("Box Entries / M", sa_s.get("box_entries_pm", 0), sb_s.get("box_entries_pm", 0), ca, cb, "{:.0f}"),
        _vs_bar("Crosses / M", sa_s.get("crosses_pm", 0), sb_s.get("crosses_pm", 0), ca, cb, "{:.0f}"),
        _vs_bar("Through Balls / M", sa_s.get("through_balls_pm", 0), sb_s.get("through_balls_pm", 0), ca, cb, "{:.1f}"),
        _vs_bar("Big Chances / M", sa_s.get("big_chances_pm", 0), sb_s.get("big_chances_pm", 0), ca, cb, "{:.1f}"),
        _vs_bar("Def Action Height", sa_s.get("def_action_height", 45), sb_s.get("def_action_height", 45), ca, cb, "{:.0f}"),
        _vs_bar("High Regains / M", sa_s.get("high_regains_pm", 0), sb_s.get("high_regains_pm", 0), ca, cb, "{:.0f}"),
        _vs_bar("Fast-Break Shots / M", sa_s.get("fast_break_shots_pm", 0), sb_s.get("fast_break_shots_pm", 0), ca, cb, "{:.1f}"),
        _vs_bar("Set-Piece xG", sa_s.get("xg_set_piece", 0), sb_s.get("xg_set_piece", 0), ca, cb, "{:.2f}"),
    ])

    # Radar
    cats = ["Poss", "xG/M", "Pressing", "Prog", "FT Entry", "Box Entry", "Width", "Transition", "Set Piece", "Def Solidity"]
    def _norm(v, mx): return min(v / max(mx, 0.01) * 100, 100)
    va_r = [_norm(sa_s.get("possession_pct",50),70), _norm(sa_s.get("xg_per_match",0),3),
            _norm(18-min(sa_s.get("ppda",12),18),12), _norm(sa_s.get("prog_passes_pm",0),40),
            _norm(sa_s.get("ft_entries_pm",0),50), _norm(sa_s.get("box_entries_pm",0),15),
            _norm(max(sa_s.get("lane_distribution",{}).get("left",33),sa_s.get("lane_distribution",{}).get("right",33)),45),
            _norm(sa_s.get("fast_break_shots_pm",0),3), _norm(sa_s.get("xg_set_piece",0),3),
            _norm(50-min(sa_s.get("def_action_height",45),50),15)]
    vb_r = [_norm(sb_s.get("possession_pct",50),70), _norm(sb_s.get("xg_per_match",0),3),
            _norm(18-min(sb_s.get("ppda",12),18),12), _norm(sb_s.get("prog_passes_pm",0),40),
            _norm(sb_s.get("ft_entries_pm",0),50), _norm(sb_s.get("box_entries_pm",0),15),
            _norm(max(sb_s.get("lane_distribution",{}).get("left",33),sb_s.get("lane_distribution",{}).get("right",33)),45),
            _norm(sb_s.get("fast_break_shots_pm",0),3), _norm(sb_s.get("xg_set_piece",0),3),
            _norm(50-min(sb_s.get("def_action_height",45),50),15)]

    fig_radar = go.Figure()
    for vals, name, color in [(va_r, short(team_a), ca), (vb_r, short(team_b), cb)]:
        r, g, b = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
        fig_radar.add_trace(go.Scatterpolar(r=vals+[vals[0]], theta=cats+[cats[0]], fill="toself",
                                            fillcolor=f"rgba({r},{g},{b},0.15)", line=dict(color=color, width=2), name=name))
    fig_radar.update_layout(polar=dict(bgcolor=CARD_BG, radialaxis=dict(visible=True, gridcolor=GRID, tickfont=dict(color=MUTED, size=8), range=[0,110]),
                                       angularaxis=dict(tickfont=dict(color=TEXT, size=10), gridcolor=GRID)),
                            paper_bgcolor=CARD_BG, font=dict(color=TEXT), height=400, margin=dict(l=55,r=55,t=30,b=30),
                            legend=dict(orientation="h", y=1.05, xanchor="center", x=0.5))

    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[style_bars]),
        html.Div(className="c6", children=[_card("Tactical Radar", [dcc.Graph(figure=fig_radar, config={"displayModeBar": False})])]),
    ]))

    # ════ 3. ATTACKING COMPARISON ════
    if has_h2h:
        sections.append(_section(3, "Attacking Comparison", "Shots, box entries, xG — H2H data"))
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card(f"Attack — {short(team_a)} vs {short(team_b)}", [
                _vs_bar("Shots", sa["shots"], sb["shots"], ca, cb),
                _vs_bar("Shots on Target", sa["sot"], sb["sot"], ca, cb),
                _vs_bar("xG", sa["xg"], sb["xg"], ca, cb, "{:.2f}"),
                _vs_bar("Big Chances", sa["big_chances"], sb["big_chances"], ca, cb),
                _vs_bar("Box Entries", sa["box_entries"], sb["box_entries"], ca, cb),
                _vs_bar("FT Entries", sa["ft_entries"], sb["ft_entries"], ca, cb),
                _vs_bar("Crosses", sa["crosses"], sb["crosses"], ca, cb),
                _vs_bar("Through Balls", sa["through_balls"], sb["through_balls"], ca, cb),
            ])]),
            html.Div(className="c6", children=[_card("Shot Maps", [
                dcc.Graph(figure=shot_map(h2h_df), config={"displayModeBar": False}),
            ])]),
        ]))

        # ════ 4. DEFENSIVE COMPARISON ════
        sections.append(_section(4, "Defensive Comparison", "xG conceded, pressing, regains"))
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card("Defense Comparison", [
                _vs_bar("xG Conceded", sa["xg_against"], sb["xg_against"], ca, cb, "{:.2f}", higher_better=False),
                _vs_bar("Shots Conceded", sb["shots"], sa["shots"], ca, cb, higher_better=False),
                _vs_bar("PPDA", sa["ppda"], sb["ppda"], ca, cb, "{:.1f}", higher_better=False),
                _vs_bar("Def Height", sa["def_height"], sb["def_height"], ca, cb, "{:.0f}"),
                _vs_bar("High Regains", sa["high_regains"], sb["high_regains"], ca, cb),
                _vs_bar("Tackles", sa["tackles"], sb["tackles"], ca, cb),
                _vs_bar("Interceptions", sa["interceptions"], sb["interceptions"], ca, cb),
                _vs_bar("Recoveries", sa["recoveries"], sb["recoveries"], ca, cb),
                _vs_bar("Clearances", sa["clearances"], sb["clearances"], ca, cb),
            ])]),
            html.Div(className="c6", children=[_card(f"Defensive Action Zones — {short(team_a)}", [
                dcc.Graph(figure=defensive_action_zone_grid(h2h_df, team_a, height=520),
                          config={"displayModeBar": False}, style={"height": "520px", "width": "100%"}),
            ])]),
        ]))
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card(f"Defensive Action Zones — {short(team_b)}", [
                dcc.Graph(figure=defensive_action_zone_grid(h2h_df, team_b, height=520),
                          config={"displayModeBar": False}, style={"height": "520px", "width": "100%"}),
            ])]),
        ]))

        # ════ 5. TRANSITION BATTLE ════
        sections.append(_section(5, "Transition Battle", "Fast-break danger, turnovers, counterpress"))
        sections.append(_card("Transition Comparison", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(sa["fb_shots"], f"FB Shots ({short(team_a)[:5]})", ca),
                _kpi(sb["fb_shots"], f"FB Shots ({short(team_b)[:5]})", cb),
                _kpi(f"{sa['fb_xg']:.2f}", f"FB xG ({short(team_a)[:4]})", ca),
                _kpi(f"{sb['fb_xg']:.2f}", f"FB xG ({short(team_b)[:4]})", cb),
            ]),
            _vs_bar("Fast-Break Shots", sa["fb_shots"], sb["fb_shots"], ca, cb),
            _vs_bar("Fast-Break xG", sa["fb_xg"], sb["fb_xg"], ca, cb, "{:.2f}"),
            _vs_bar("High Turnovers Forced", sb["high_turnovers"], sa["high_turnovers"], ca, cb),
        ]))

        # ════ 6. TERRITORY & ZONES ════
        sections.append(_section(6, "Territory & Zone Maps", "Where each team attacks and defends"))
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card(f"Attacking Zones — {short(team_a)}", [
                dcc.Graph(figure=attacking_zone_grid(h2h_df, team_a, height=520),
                          config={"displayModeBar": False}, style={"height": "520px", "width": "100%"}),
            ])]),
            html.Div(className="c6", children=[_card(f"Attacking Zones — {short(team_b)}", [
                dcc.Graph(figure=attacking_zone_grid(h2h_df, team_b, height=520),
                          config={"displayModeBar": False}, style={"height": "520px", "width": "100%"}),
            ])]),
        ]))
        # Lane comparison
        sections.append(_card("Attacking Lane Distribution", [
            _vs_bar("Left Wing %", sa["lane_left"], sb["lane_left"], ca, cb, "{:.0f}"),
            _vs_bar("Central %", sa["lane_center"], sb["lane_center"], ca, cb, "{:.0f}"),
            _vs_bar("Right Wing %", sa["lane_right"], sb["lane_right"], ca, cb, "{:.0f}"),
        ]))

        # ════ 7. SET PIECES ════
        sections.append(_section(7, "Set-Piece Battle", "Corners, dead-ball xG, vulnerability"))
        sections.append(_card("Set-Piece Comparison", [
            _vs_bar("Corners Won", sa["corners"], sb["corners"], ca, cb),
            _vs_bar("SP Shots", sa["sp_shots"], sb["sp_shots"], ca, cb),
            _vs_bar("SP xG", sa["sp_xg"], sb["sp_xg"], ca, cb, "{:.2f}"),
            _vs_bar("SP Shots Conceded", sa["opp_sp_shots"], sb["opp_sp_shots"], ca, cb, higher_better=False),
        ]))

        # ════ 8. KEY PLAYERS ════
        sections.append(_section(8, "Key Player Influence", "Top 3 most influential per team in H2H"))
        kp_a = _get_h2h_key_players(df, team_a, match_ids)
        kp_b = _get_h2h_key_players(df, team_b, match_ids)

        def _player_row(p, color):
            return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                                    "borderLeft": f"3px solid {color}", "borderRadius": "6px", "marginBottom": "4px",
                                    "background": f"{color}08"}, children=[
                html.Span(str(p["jersey"]), style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "13px", "width": "24px"}),
                html.Div(style={"flex": "1"}, children=[
                    html.Div(p["name"], style={"fontWeight": "600", "fontSize": "12px"}),
                    html.Div(f"{p['position']} · {p['goals']}G {p['assists']}A {p['xg']:.1f}xG · {p['prog_passes']}pp {p['tackles']}tk",
                             style={"fontSize": "10px", "color": MUTED}),
                ]),
            ])

        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card(f"Key Players — {short(team_a)}", [_player_row(p, ca) for p in kp_a] if kp_a else [html.Div("No data", style={"color": MUTED})])]),
            html.Div(className="c6", children=[_card(f"Key Players — {short(team_b)}", [_player_row(p, cb) for p in kp_b] if kp_b else [html.Div("No data", style={"color": MUTED})])]),
        ]))

        # ════ 8b. BUILD-UP PATTERNS ════
        sections.append(_section("8b", "Build-Up Patterns", f"How each team progresses the ball — {scope_label}"))
        bu_a = compute_buildup_patterns(df, team_a, match_ids)
        bu_b = compute_buildup_patterns(df, team_b, match_ids)

        def _buildup_card(team, color, bu):
            return _card(f"Build-Up — {short(team)}", [
                html.Div(style={"display": "flex", "gap": "6px", "marginBottom": "10px"}, children=[
                    html.Div(style={"flex": "1", "textAlign": "center", "padding": "6px", "background": f"{color}10", "borderRadius": "6px"}, children=[
                        html.Div(f"{bu['lane_left_pct']:.0f}%", style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "15px"}),
                        html.Div("Left", style={"fontSize": "9px", "color": MUTED})]),
                    html.Div(style={"flex": "1", "textAlign": "center", "padding": "6px", "background": f"{color}10", "borderRadius": "6px"}, children=[
                        html.Div(f"{bu['lane_central_pct']:.0f}%", style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "15px"}),
                        html.Div("Central", style={"fontSize": "9px", "color": MUTED})]),
                    html.Div(style={"flex": "1", "textAlign": "center", "padding": "6px", "background": f"{color}10", "borderRadius": "6px"}, children=[
                        html.Div(f"{bu['lane_right_pct']:.0f}%", style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "15px"}),
                        html.Div("Right", style={"fontSize": "9px", "color": MUTED})]),
                ]),
                _stat_line("Progressive passes / match", bu["progressive_passes_pm"], color),
                _stat_line("First-third progression / match", bu["first_third_prog_pm"], color),
                _stat_line("Final-third entries / match", bu["ft_entries_pm"], color),
                _stat_line("Box entries / match", bu["box_entries_pm"], color),
                _stat_line("Switches of play / match", bu["switches_pm"], color),
                _stat_line("Long build-up passes / match", bu["long_buildup_pm"], color),
                _stat_line("Avg pass length (m)", bu["avg_pass_length"], color),
                _stat_line("Directness index", bu["directness"], color),
            ])
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_buildup_card(team_a, ca, bu_a)]),
            html.Div(className="c6", children=[_buildup_card(team_b, cb, bu_b)]),
        ]))

        # ════ 8c. PASSING PROFILE ════
        sections.append(_section("8c", "Passing Profile", f"Pass volume, accuracy and types — {scope_label} · Event-derived"))
        pp_a = compute_passing_profile(df, team_a, match_ids)
        pp_b = compute_passing_profile(df, team_b, match_ids)
        sections.append(html.Div(className="row", children=[
            html.Div(className="c12", children=[_card("Passing Comparison (per match)", [
                _vs_bar("Passes", pp_a["passes_pm"], pp_b["passes_pm"], ca, cb),
                _vs_bar("Accuracy %", pp_a["accuracy"], pp_b["accuracy"], ca, cb, "{:.1f}"),
                _vs_bar("Short passes", pp_a["short_pm"], pp_b["short_pm"], ca, cb),
                _vs_bar("Medium passes", pp_a["medium_pm"], pp_b["medium_pm"], ca, cb),
                _vs_bar("Long passes", pp_a["long_pm"], pp_b["long_pm"], ca, cb),
                _vs_bar("Forward passes", pp_a["forward_pm"], pp_b["forward_pm"], ca, cb),
                _vs_bar("Progressive passes", pp_a["progressive_pm"], pp_b["progressive_pm"], ca, cb),
                _vs_bar("Final-third passes", pp_a["final_third_pm"], pp_b["final_third_pm"], ca, cb),
                _vs_bar("Box-entry passes", pp_a["box_entry_pm"], pp_b["box_entry_pm"], ca, cb),
                _vs_bar("Crosses", pp_a["crosses_pm"], pp_b["crosses_pm"], ca, cb),
                _vs_bar("Through balls", pp_a["through_balls_pm"], pp_b["through_balls_pm"], ca, cb),
            ])]),
        ]))

        # ════ 8d. TACTICAL INTERPRETATION ════
        sections.append(_section("8d", "Tactical Interpretation", f"Patterns, edges and mismatches — {scope_label}"))
        from components.h2h_metrics import compute_h2h_tactical_interpretation
        ti = compute_h2h_tactical_interpretation(df, team_a, team_b, match_ids)

        def _adv_label(code, ta, tb):
            return {"A": (short(ta), ca), "B": (short(tb), cb),
                    "neutral": ("Neutral", MUTED), "small_sample": ("Small sample", MUTED)}.get(code, ("Neutral", MUTED))

        # Build-up pattern cards
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card(f"Build-Up — {short(team_a)}", [
                html.Div([html.Span("▸ ", style={"color": ca}), html.Span(p.title())],
                         style={"fontSize": "12px", "color": TEXT, "marginBottom": "4px"}) for p in ti["buildup_a"]])]),
            html.Div(className="c6", children=[_card(f"Build-Up — {short(team_b)}", [
                html.Div([html.Span("▸ ", style={"color": cb}), html.Span(p.title())],
                         style={"fontSize": "12px", "color": TEXT, "marginBottom": "4px"}) for p in ti["buildup_b"]])]),
        ]))

        # Advantage matrix
        adv_rows = []
        for dim, code in ti["advantages"].items():
            lbl, col = _adv_label(code, team_a, team_b)
            adv_rows.append(html.Div(style={"display": "flex", "justifyContent": "space-between",
                                            "padding": "5px 8px", "borderBottom": f"1px solid {CARD_BG}"}, children=[
                html.Span(dim.title(), style={"fontSize": "12px", "color": MUTED}),
                html.Span(lbl, style={"fontSize": "12px", "fontWeight": "700", "color": col}),
            ]))
        # Mismatch + overall cards
        mismatch_children = [html.Div([html.Span("⚠ ", style={"color": "#FEB019"}), html.Span(mm)],
                                      style={"fontSize": "11px", "color": TEXT, "marginBottom": "5px"}) for mm in ti["mismatches"]]
        if not mismatch_children:
            mismatch_children = [html.Div("No standout mismatches in this sample.", style={"fontSize": "11px", "color": MUTED})]
        sections.append(html.Div(className="row", children=[
            html.Div(className="c6", children=[_card("Advantage by Dimension", adv_rows)]),
            html.Div(className="c6", children=[_card("Tactical Mismatches", mismatch_children + [
                html.Div(style={"marginTop": "10px", "padding": "8px", "background": f"{GOLD}10", "borderRadius": "6px"}, children=[
                    html.Span("Overall: ", style={"fontSize": "11px", "color": MUTED}),
                    html.Span(ti["overall"], style={"fontSize": "12px", "fontWeight": "700", "color": GOLD})])])]),
        ]))

    # ════ 9. COACHING SUMMARY ════
    sections.append(_section(9, "Coaching Summary", "Edges, dangers, tactical takeaways"))
    edges = []
    # Determine edges from data
    if has_h2h:
        if sa["xg"] > sb["xg"] + 0.5: edges.append(_edge_badge("xG advantage in H2H", short(team_a), ca))
        elif sb["xg"] > sa["xg"] + 0.5: edges.append(_edge_badge("xG advantage in H2H", short(team_b), cb))
        if sa["possession"] > sb["possession"] + 5: edges.append(_edge_badge("Territory control", short(team_a), ca))
        elif sb["possession"] > sa["possession"] + 5: edges.append(_edge_badge("Territory control", short(team_b), cb))
        if sa["fb_xg"] > sb["fb_xg"] + 0.3: edges.append(_edge_badge("Transition threat", short(team_a), ca))
        elif sb["fb_xg"] > sa["fb_xg"] + 0.3: edges.append(_edge_badge("Transition threat", short(team_b), cb))
        if sa["sp_xg"] > sb["sp_xg"] + 0.3: edges.append(_edge_badge("Set-piece advantage", short(team_a), ca))
        elif sb["sp_xg"] > sa["sp_xg"] + 0.3: edges.append(_edge_badge("Set-piece advantage", short(team_b), cb))
    # Season-wide edges
    if pa.get("ppda", 12) < pb.get("ppda", 12) - 2: edges.append(_edge_badge("Better pressing intensity (season)", short(team_a), ca))
    elif pb.get("ppda", 12) < pa.get("ppda", 12) - 2: edges.append(_edge_badge("Better pressing intensity (season)", short(team_b), cb))
    if pa.get("xg_per_match", 0) > pb.get("xg_per_match", 0) + 0.3: edges.append(_edge_badge("Higher xG creation rate (season)", short(team_a), ca))
    elif pb.get("xg_per_match", 0) > pa.get("xg_per_match", 0) + 0.3: edges.append(_edge_badge("Higher xG creation rate (season)", short(team_b), cb))

    if not edges:
        edges.append(html.Div("Evenly matched — no clear tactical edge from data", style={"color": MUTED, "fontSize": "12px", "padding": "10px"}))

    sections.append(_card("Matchup Edges", edges))

    return html.Div(sections)
