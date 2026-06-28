"""
components/report_pages.py — Match Reports UI (Pre-Match & Post-Match)
Implements all 20 report sections from the tactical document:
  PRE-MATCH:  10 pages (Executive Summary → Recommended Game Plan)
  POST-MATCH: 10 pages (Match Summary → Training Recommendations)
"""

from components.dash_compat import dcc, html
import plotly.graph_objects as go
import numpy as np
import pandas as pd

from data_loader import (
    load_league_data, get_match_list, get_match_data, get_teams,
    get_match_lineup, get_team_results, short, team_color,
    get_logo_base64, filter_by_period,
)
from components.heatmaps import action_heatmap
from components.charts import (
    shot_map, pass_map, defensive_map, pass_network,
    shot_quality_scatter, team_form_chart, possession_zones,
    BG, CARD_BG, GRID, TEXT, MUTED, GOLD, GOLD_DIM,
    ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, ACCENT_PURPLE, _tmpl,
)
from components.report_engine import (
    compute_team_profile, compute_post_match_report, compute_player_roles,
    _safe_pct, _safe_div,
    SHOT_EVENTS, FINAL_THIRD_X, MID_THIRD_X, BOX_X, BOX_Y_LO, BOX_Y_HI,
)

# ══════════════════════════════════════════════════════════════════════════
#  SHARED UI COMPONENTS
# ══════════════════════════════════════════════════════════════════════════
def _report_state_badge(our_team, opponent, sample_label, report_type):
    """Visible report-state badge shown at the top of every report so the
    report's subject is unambiguous and provably driven by the selected filters.
    Renders: Report Team · Opponent · Sample · Report Type."""
    mc = team_color(our_team)
    oc = team_color(opponent) if opponent else MUTED
    rt_label = "Pre-Match" if str(report_type).lower().startswith("pre") else "Post-Match"
    children = [
        html.Span("Report Team: ", style={"fontSize": "12px", "color": MUTED}),
        html.Span(short(our_team), style={"fontSize": "14px", "fontWeight": "800", "color": mc}),
    ]
    if opponent:
        children += [
            html.Span("  ·  Opponent: ", style={"fontSize": "12px", "color": MUTED}),
            html.Span(short(opponent), style={"fontSize": "13px", "fontWeight": "700", "color": oc}),
        ]
    children += [
        html.Span(f"  ·  Sample: {sample_label}", style={"fontSize": "11px", "color": MUTED}),
        html.Span("  ·  Report Type: ", style={"fontSize": "11px", "color": MUTED}),
        html.Span(rt_label, style={"fontSize": "12px", "fontWeight": "700", "color": GOLD}),
        html.Span("  ·  Generated from selected filters", style={
            "fontSize": "10px", "color": MUTED, "fontStyle": "italic", "marginLeft": "auto"}),
    ]
    return html.Div(style={"padding": "10px 16px", "marginBottom": "10px",
                           "background": f"{mc}14", "borderRadius": "8px",
                           "border": f"1px solid {mc}55", "display": "flex",
                           "alignItems": "center", "gap": "8px", "flexWrap": "wrap"},
                    children=children)


def _goal_card(title, gp, color):
    """Render one goal-distribution card: total, per-match, 1st/2nd split,
    method breakdown and timing bars. Pure function of the goal-profile dict."""
    methods = {k: v for k, v in gp.get("methods", {}).items() if v > 0}
    timing = {k: v for k, v in gp.get("timing", {}).items() if v > 0}
    method_rows = [html.Div(style={"display": "flex", "justifyContent": "space-between",
                                   "padding": "4px 8px", "borderBottom": f"1px solid {CARD_BG}"}, children=[
        html.Span(k.title(), style={"fontSize": "12px", "color": TEXT}),
        html.Span(str(v), style={"fontFamily": "Orbitron", "fontWeight": "700", "color": color, "fontSize": "13px"}),
    ]) for k, v in sorted(methods.items(), key=lambda kv: -kv[1])]
    timing_bars = []
    mx = max(timing.values()) if timing else 1
    for band in ["0-15", "16-30", "31-45+", "46-60", "61-75", "76-90+"]:
        v = gp.get("timing", {}).get(band, 0)
        timing_bars.append(html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "3px"}, children=[
            html.Span(band, style={"fontSize": "10px", "color": MUTED, "width": "46px"}),
            html.Div(style={"flex": "1", "height": "12px", "background": "#1A2030", "borderRadius": "3px", "overflow": "hidden"}, children=[
                html.Div(style={"width": f"{v/mx*100:.0f}%", "height": "100%", "background": color})]),
            html.Span(str(v), style={"fontSize": "11px", "color": TEXT, "width": "18px", "textAlign": "right"}),
        ]))
    return _card(title, [
        html.Div(style={"display": "flex", "gap": "12px", "marginBottom": "10px"}, children=[
            html.Div(style={"textAlign": "center", "flex": "1"}, children=[
                html.Div(f"{gp['total']}", style={"fontFamily": "Orbitron", "fontSize": "28px", "fontWeight": "900", "color": color}),
                html.Div("Total", style={"fontSize": "9px", "color": MUTED})]),
            html.Div(style={"textAlign": "center", "flex": "1"}, children=[
                html.Div(f"{gp['per_match']}", style={"fontFamily": "Orbitron", "fontSize": "28px", "fontWeight": "900", "color": color}),
                html.Div("Per Match", style={"fontSize": "9px", "color": MUTED})]),
            html.Div(style={"textAlign": "center", "flex": "1"}, children=[
                html.Div(f"{gp['first_half']}/{gp['second_half']}", style={"fontFamily": "Orbitron", "fontSize": "22px", "fontWeight": "900", "color": color}),
                html.Div("1st / 2nd", style={"fontSize": "9px", "color": MUTED})]),
        ]),
        html.Div("Method", style={"fontSize": "10px", "color": MUTED, "textTransform": "uppercase", "marginBottom": "4px"}),
        html.Div(method_rows or [html.Div("No goals in this scope", style={"fontSize": "11px", "color": MUTED})]),
        html.Div("Timing", style={"fontSize": "10px", "color": MUTED, "textTransform": "uppercase", "margin": "10px 0 4px"}),
        html.Div(timing_bars),
    ])


def _goal_distribution_cards(df, team, match_ids, scored_title="Goals Scored",
                             conceded_title="Goals Conceded"):
    """Build the [Goals Scored | Goals Conceded] distribution cards for a team
    over the given match_ids (total, per-match, 1st/2nd split, method, timing).
    Used by BOTH pre-match (sample) and post-match (single match) so the
    distribution always derives from the active selected scope."""
    from components.goal_profile import compute_goal_profile
    gf = compute_goal_profile(df, team, match_ids, side="for")
    ga = compute_goal_profile(df, team, match_ids, side="against")
    return html.Div(className="row", children=[
        html.Div(className="c6", children=[_goal_card(scored_title, gf, ACCENT_GREEN)]),
        html.Div(className="c6", children=[_goal_card(conceded_title, ga, ACCENT_RED)]),
    ]), gf, ga


def _logo(team, size=36):
    src = get_logo_base64(team)
    if src:
        return html.Img(src=src, style={"width": f"{size}px", "height": f"{size}px", "objectFit": "contain"})
    return html.Span(short(team)[:3], style={"fontWeight": "700", "fontSize": f"{size//3}px"})

def _card(title, children, style_extra=None):
    s = {}
    if style_extra:
        s = style_extra
    return html.Div(className="card", style=s, children=[
        html.Div(title, className="card-t") if title else None,
        *(children if isinstance(children, list) else [children]),
    ])

def _kpi(val, label, color=GOLD, small=False):
    sz = "18px" if small else "24px"
    return html.Div(className="kpi", children=[
        html.Div(str(val), className="kpi-v", style={"color": color, "fontSize": sz}),
        html.Div(label, className="kpi-l"),
    ])

def _section_header(num, title, subtitle=""):
    return html.Div(style={
        "marginBottom": "16px", "paddingBottom": "10px",
        "borderBottom": f"1px solid {GOLD}33",
    }, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"}, children=[
            html.Span(str(num), style={
                "fontFamily": "Orbitron, monospace", "fontWeight": "900", "fontSize": "20px",
                "color": GOLD, "background": f"{GOLD}15", "borderRadius": "8px",
                "width": "36px", "height": "36px", "display": "inline-flex",
                "alignItems": "center", "justifyContent": "center",
            }),
            html.Div([
                html.Div(title, style={"fontWeight": "700", "fontSize": "16px", "color": "#fff"}),
                html.Div(subtitle, style={"fontSize": "11px", "color": MUTED}) if subtitle else None,
            ]),
        ]),
    ])

def _traffic_light(status, label, value):
    """Green/amber/red indicator dot + label."""
    color = {"green": ACCENT_GREEN, "amber": "#FEB019", "red": ACCENT_RED}.get(status, MUTED)
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "5px 0"}, children=[
        html.Span(style={"width": "10px", "height": "10px", "borderRadius": "50%", "background": color, "flexShrink": "0"}),
        html.Span(label, style={"fontSize": "12px", "color": TEXT, "flex": "1"}),
        html.Span(str(value), style={"fontSize": "12px", "fontWeight": "600", "color": color, "fontFamily": "Orbitron, monospace"}),
    ])

def _tag(text, color=GOLD):
    return html.Span(text, style={
        "display": "inline-block", "padding": "3px 12px", "borderRadius": "16px",
        "fontSize": "10px", "fontWeight": "700", "letterSpacing": "0.5px",
        "background": f"{color}18", "color": color, "border": f"1px solid {color}40",
        "marginRight": "6px", "marginBottom": "4px",
    })

def _pct_bar(label, value, max_val=100, color=GOLD, show_val=True):
    pct = min(value / max(max_val, 1) * 100, 100)
    return html.Div(style={"marginBottom": "8px"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between", "fontSize": "11px", "marginBottom": "3px"}, children=[
            html.Span(label, style={"color": TEXT}),
            html.Span(f"{value}" + ("%" if max_val == 100 else ""), style={"color": color, "fontWeight": "600"}) if show_val else None,
        ]),
        html.Div(style={"height": "6px", "background": f"rgba(255,255,255,0.05)", "borderRadius": "3px", "overflow": "hidden"}, children=[
            html.Div(style={"width": f"{pct}%", "height": "100%", "background": f"linear-gradient(90deg, {color}60, {color})", "borderRadius": "3px", "transition": "width 0.8s ease"}),
        ]),
    ])

def _post_kpi_context_card(ctx):
    """Small card explaining one post-match KPI vs team season average and
    league average. Uses neutral logic for contextual defensive workload metrics.
    """
    if not ctx:
        return None
    label = ctx.get("label", ctx.get("metric", "Metric"))
    mv = ctx.get("match_value")
    tavg = ctx.get("team_season_avg")
    lavg = ctx.get("league_avg")
    interp = ctx.get("interpretation", "")
    direction = ctx.get("direction", "contextual")
    diff = ctx.get("difference_vs_team_avg")
    pct = ctx.get("percentile")
    conf = ctx.get("confidence", "")
    source = ctx.get("source", "")
    sample = ctx.get("sample_size", "")
    # Colour reflects good/bad for directional metrics, and neutral/amber for contextual workload.
    color = MUTED
    if mv is not None and diff is not None:
        if direction == "higher_good":
            color = ACCENT_GREEN if diff > 0 else (ACCENT_RED if diff < 0 else GOLD)
        elif direction == "lower_good":
            color = ACCENT_GREEN if diff < 0 else (ACCENT_RED if diff > 0 else GOLD)
        else:
            color = GOLD if abs(float(diff)) > max(abs(float(tavg or 0))*0.10, 1) else MUTED
    def _fmt(v):
        if v is None:
            return "—"
        try:
            return f"{float(v):.1f}" if abs(float(v)) >= 10 else f"{float(v):.2f}"
        except Exception:
            return str(v)
    return html.Div(className="kpi", style={"minWidth": "210px", "flex": "1 1 210px", "position": "relative"}, children=[
        html.Div(_fmt(mv), className="kpi-v", style={"color": color, "fontSize": "22px"}),
        html.Div(label, className="kpi-l"),
        html.Div(f"Team avg: {_fmt(tavg)} · League avg: {_fmt(lavg)}", style={"fontSize": "9px", "color": MUTED, "marginTop": "4px"}),
        html.Div(f"Δ team avg: {_fmt(diff)}" + (f" · Pctl {pct}" if pct is not None else ""), style={"fontSize": "9px", "color": color, "marginTop": "2px", "fontWeight": "600"}),
        html.Div(interp, style={"fontSize": "9px", "color": TEXT, "marginTop": "4px", "lineHeight": "1.25"}),
        html.Div(f"{source} · baseline N={sample} · {conf}", style={"fontSize": "8px", "color": MUTED, "marginTop": "4px"}),
    ])


def _post_context_grid(contexts, metrics=None):
    """Render a mini-grid of post-match KPI context rows by metric key."""
    if not contexts:
        return html.Div("Season-average context unavailable", style={"fontSize": "11px", "color": MUTED})
    wanted = set(metrics or [])
    cards = []
    for ctx in contexts:
        if wanted and ctx.get("metric") not in wanted:
            continue
        c = _post_kpi_context_card(ctx)
        if c is not None:
            cards.append(c)
    return html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "8px"}, children=cards or [html.Div("No contextual metrics available", style={"fontSize": "11px", "color": MUTED})])

def _lane_bar(left, center, right):
    """Three-section horizontal bar for lane distribution."""
    return html.Div(style={"display": "flex", "borderRadius": "4px", "overflow": "hidden", "height": "28px", "marginBottom": "8px"}, children=[
        html.Div(style={"flex": left, "background": ACCENT_BLUE, "display": "flex", "alignItems": "center", "justifyContent": "center", "fontSize": "10px", "fontWeight": "700", "color": "#fff"}, children=[f"L {left}%"]) if left > 5 else None,
        html.Div(style={"flex": center, "background": GOLD, "display": "flex", "alignItems": "center", "justifyContent": "center", "fontSize": "10px", "fontWeight": "700", "color": "#000"}, children=[f"C {center}%"]) if center > 5 else None,
        html.Div(style={"flex": right, "background": ACCENT_GREEN, "display": "flex", "alignItems": "center", "justifyContent": "center", "fontSize": "10px", "fontWeight": "700", "color": "#000"}, children=[f"R {right}%"]) if right > 5 else None,
    ])

def _plan_target_row(t):
    """Row for plan vs actual table — supports the new rich status vocabulary."""
    st = t.get("status", "Partial")
    color = {"Hit": ACCENT_GREEN, "Strategically Acceptable": "#00D0C0",
             "Partial": "#FEB019", "Missed": ACCENT_RED,
             "Not Applicable": MUTED}.get(st, MUTED)
    icon = {"Hit": "✅", "Strategically Acceptable": "◑", "Partial": "⚠️",
            "Missed": "❌", "Not Applicable": "—"}.get(st, "•")
    actual_val = t.get("actual", "N/A")
    if isinstance(actual_val, float):
        actual_val = f"{actual_val:.1f}"
    weight = t.get("weight", "")
    return html.Tr(style={"borderBottom": f"1px solid {CARD_BG}"}, children=[
        html.Td(t["metric"], style={"padding": "8px 10px", "fontWeight": "600", "color": TEXT, "textAlign": "left", "fontSize": "12px"}),
        html.Td(str(t.get("target", "")), style={"padding": "8px 10px", "color": MUTED, "textAlign": "center", "fontSize": "12px", "fontFamily": "Orbitron, monospace"}),
        html.Td(str(actual_val), style={"padding": "8px 10px", "fontWeight": "700", "color": color, "textAlign": "center", "fontSize": "13px", "fontFamily": "Orbitron, monospace"}),
        html.Td(f"{icon} {st}", style={"padding": "8px 10px", "textAlign": "center", "fontSize": "11px", "color": color, "fontWeight": "600"}),
        html.Td(weight, style={"padding": "8px 10px", "textAlign": "center", "fontSize": "10px", "color": MUTED}),
        html.Td(t.get("interpretation", t.get("rationale", "")), style={"padding": "8px 10px", "color": MUTED, "fontSize": "11px", "textAlign": "left"}),
    ])


# ══════════════════════════════════════════════════════════════════════════
#  REPORT CHART BUILDERS
# ══════════════════════════════════════════════════════════════════════════
def _archetype_radar(profile, color=GOLD):
    """Spider chart showing tactical archetype dimensions."""
    cats = ["Possession", "Pressing", "Directness", "Width", "Transition", "Set-Piece", "Creativity", "Def Solidity"]
    vals = [
        min(profile.get("possession_pct", 50) / 65 * 100, 100),
        min((18 - min(profile.get("ppda", 12), 18)) / 12 * 100, 100),  # lower PPDA = more pressing
        min(profile.get("long_balls_pm", 0) / 25 * 100, 100),
        max(profile.get("lane_distribution", {}).get("left", 33), profile.get("lane_distribution", {}).get("right", 33)) / 45 * 100,
        min(profile.get("fast_break_shots_pm", 0) / 3 * 100, 100),
        min(profile.get("sp_shots_pm", 0) / 4 * 100, 100),
        min(profile.get("big_chances_pm", 0) / 4 * 100, 100),
        min((50 - min(profile.get("def_action_height", 45), 50)) / 15 * 100, 100),
    ]
    vals = [min(v, 100) for v in vals]

    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
        fillcolor=f"rgba({r},{g},{b},0.2)", line=dict(color=color, width=2.5),
    ))
    fig.update_layout(
        polar=dict(bgcolor=CARD_BG,
                   radialaxis=dict(visible=True, gridcolor=GRID, tickfont=dict(color=MUTED, size=8), range=[0, 110]),
                   angularaxis=dict(tickfont=dict(color=TEXT, size=10), gridcolor=GRID)),
        paper_bgcolor=CARD_BG, font=dict(color=TEXT),
        height=340, margin=dict(l=55, r=55, t=25, b=25), showlegend=False,
    )
    return fig

def _xg_context_bars(xg_open, xg_sp, xg_fb, height=260):
    cats = ["Open Play", "Set Piece", "Fast Break"]
    vals = [xg_open, xg_sp, xg_fb]
    colors = [GOLD, ACCENT_BLUE, ACCENT_GREEN]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cats, y=vals, marker_color=colors, text=[f"{v:.2f}" for v in vals],
                         textposition="auto", textfont=dict(color="#fff", size=12, family="Orbitron")))
    fig = _tmpl(fig, height=height)
    fig.update_layout(xaxis_title="", yaxis_title="xG", bargap=0.4)
    return fig

def _hex_to_rgba(hex_color, alpha=0.06):
    """Convert hex color to Plotly-safe rgba string."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) >= 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return f"rgba(128,128,128,{alpha})"

def _xg_rolling_timeline(home_tl, away_tl, home_name, away_name, home_color, away_color, height=320):
    fig = go.Figure()
    # Home
    hm = [0] + [s["minute"] for s in home_tl]
    hx = [0] + [s["cum_xg"] for s in home_tl]
    fig.add_trace(go.Scatter(x=hm, y=hx, mode="lines+markers", name=short(home_name),
                             line=dict(color=home_color, width=2.5), marker=dict(size=7, color=home_color),
                             fill="tozeroy", fillcolor=_hex_to_rgba(home_color, 0.06)))
    # Away
    am = [0] + [s["minute"] for s in away_tl]
    ax = [0] + [s["cum_xg"] for s in away_tl]
    fig.add_trace(go.Scatter(x=am, y=ax, mode="lines+markers", name=short(away_name),
                             line=dict(color=away_color, width=2.5), marker=dict(size=7, color=away_color),
                             fill="tozeroy", fillcolor=_hex_to_rgba(away_color, 0.06)))
    fig.add_vline(x=45, line_dash="dot", line_color="rgba(255,255,255,0.15)")
    fig.add_annotation(x=45, y=0, text="HT", font=dict(color=MUTED, size=9), showarrow=False, yshift=-12)
    fig = _tmpl(fig, height=height)
    fig.update_layout(xaxis_title="Minute", yaxis_title="Cumulative xG",
                      legend=dict(orientation="h", y=1.05, xanchor="center", x=0.5))
    return fig

def _player_role_card(p, color=GOLD):
    """Structured, readable player role card (no cramped decayed stat strings)."""
    infl = p.get("influence", 0)
    infl_color = ACCENT_GREEN if infl >= 60 else (GOLD if infl >= 35 else MUTED)

    def stat_col(value, label, vcolor=TEXT):
        return html.Div(style={"textAlign": "center", "flex": "1", "minWidth": "48px"}, children=[
            html.Div(str(value), style={"fontFamily": "Orbitron", "fontWeight": "700", "fontSize": "15px", "color": vcolor}),
            html.Div(label, style={"fontSize": "9px", "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.5px", "marginTop": "1px"}),
        ])

    return html.Div(style={
        "background": CARD_BG, "border": "1px solid rgba(255,255,255,0.06)",
        "borderRadius": "10px", "padding": "14px", "marginBottom": "10px",
        "borderLeft": f"3px solid {color}",
    }, children=[
        # Header: jersey, name, role badge, influence
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px"}, children=[
                html.Span(str(p["jersey"]), style={"fontFamily": "Orbitron", "fontWeight": "700", "fontSize": "14px", "color": color,
                                                    "background": f"{color}15", "borderRadius": "4px", "padding": "3px 9px"}),
                html.Div(children=[
                    html.Div(p["name"], style={"fontWeight": "700", "fontSize": "14px", "color": TEXT}),
                    html.Div([
                        html.Span(p["position"], style={"color": MUTED, "fontSize": "10px", "textTransform": "uppercase", "letterSpacing": "1px"}),
                        html.Span(" · ", style={"color": MUTED, "fontSize": "10px"}),
                        html.Span(p.get("role", ""), style={"color": color, "fontSize": "10px", "fontWeight": "700"}),
                    ]),
                ]),
            ]),
            html.Div(style={"textAlign": "center"}, children=[
                html.Div(str(infl), style={"fontFamily": "Orbitron", "fontWeight": "900", "fontSize": "20px", "color": infl_color}),
                html.Div("Influence", style={"fontSize": "8px", "color": MUTED, "textTransform": "uppercase"}),
            ]),
        ]),
        # Stat row — structured columns, readable sizes
        html.Div(style={"display": "flex", "gap": "4px", "marginBottom": "10px"}, children=[
            stat_col(p["goals"], "Goals", ACCENT_GREEN if p["goals"] else TEXT),
            stat_col(p["assists"], "Assists", ACCENT_GREEN if p["assists"] else TEXT),
            stat_col(f"{p['xg']:.1f}", "xG", MUTED),
            stat_col(p["key_passes"], "Key P", ACCENT_BLUE if p["key_passes"] else TEXT),
            stat_col(p["prog_passes"], "Prog P", color),
            stat_col(p["tackles_won"] + p["interceptions"], "Tkl+Int", ACCENT_PURPLE),
        ]),
        # Touch distribution — labelled bar, readable percentages
        html.Div(style={"fontSize": "9px", "color": MUTED, "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "3px"}, children="Touch Distribution"),
        html.Div(style={"display": "flex", "borderRadius": "3px", "overflow": "hidden", "height": "16px"}, children=[
            html.Div(style={"flex": max(p["touch_def_pct"], 1), "background": ACCENT_BLUE,
                            "display": "flex", "alignItems": "center", "justifyContent": "center"},
                     children=html.Span(f"{p['touch_def_pct']}%", style={"fontSize": "9px", "color": "white", "fontWeight": "700"}) if p["touch_def_pct"] >= 12 else None),
            html.Div(style={"flex": max(p["touch_mid_pct"], 1), "background": "#8A7A20",
                            "display": "flex", "alignItems": "center", "justifyContent": "center"},
                     children=html.Span(f"{p['touch_mid_pct']}%", style={"fontSize": "9px", "color": "white", "fontWeight": "700"}) if p["touch_mid_pct"] >= 12 else None),
            html.Div(style={"flex": max(p["touch_att_pct"], 1), "background": ACCENT_GREEN,
                            "display": "flex", "alignItems": "center", "justifyContent": "center"},
                     children=html.Span(f"{p['touch_att_pct']}%", style={"fontSize": "9px", "color": "white", "fontWeight": "700"}) if p["touch_att_pct"] >= 12 else None),
        ]),
        html.Div(style={"display": "flex", "justifyContent": "space-between", "marginTop": "3px"}, children=[
            html.Span("Def 3rd", style={"fontSize": "8px", "color": MUTED}),
            html.Span("Mid 3rd", style={"fontSize": "8px", "color": MUTED}),
            html.Span("Att 3rd", style={"fontSize": "8px", "color": MUTED}),
        ]),
    ])

def _micro_stat(val, label, color):
    return html.Span(style={
        "display": "inline-flex", "alignItems": "center", "gap": "3px",
        "padding": "2px 7px", "borderRadius": "4px",
        "background": f"{color}10", "fontSize": "10px",
    }, children=[
        html.Span(val, style={"color": color, "fontWeight": "600"}),
        html.Span(label, style={"color": MUTED}),
    ])

def _training_item(icon, title, desc, priority="medium"):
    pcolor = {"high": ACCENT_RED, "medium": "#FEB019", "low": ACCENT_GREEN}.get(priority, MUTED)
    return html.Div(style={
        "display": "flex", "gap": "12px", "padding": "10px 12px",
        "background": CARD_BG, "borderRadius": "8px", "marginBottom": "6px",
        "borderLeft": f"3px solid {pcolor}",
    }, children=[
        html.Span(icon, style={"fontSize": "18px", "lineHeight": "1"}),
        html.Div([
            html.Div(title, style={"fontWeight": "600", "fontSize": "12px", "color": TEXT}),
            html.Div(desc, style={"fontSize": "11px", "color": MUTED, "marginTop": "2px"}),
        ]),
        html.Span(priority.upper(), style={"marginLeft": "auto", "fontSize": "9px", "fontWeight": "700",
                                            "color": pcolor, "letterSpacing": "1px", "alignSelf": "center"}),
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  PRE-MATCH REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════
def build_pre_match_report(league_folder: str, our_team: str, opp_team: str, last_n: int = 5) -> html.Div:
    """Build the full 10-page Pre-Match Report as Dash layout."""

    opp_profile = compute_team_profile(league_folder, opp_team, last_n)
    our_profile = compute_team_profile(league_folder, our_team, last_n)
    opp_roles = compute_player_roles(league_folder, opp_team, last_n)
    our_roles = compute_player_roles(league_folder, our_team, last_n)
    from components.target_engine import generate_targets as _gen_targets
    _pre_sample = our_profile.get("matches_analyzed", 0) if our_profile else 0
    _pre_plan = _gen_targets(our_profile or {}, opp_profile or {}, sample_size=_pre_sample,
                             wyscout_available=bool((our_profile or {}).get("wyscout_available")))
    plan_targets = _pre_plan["targets"]
    ml = get_match_list(league_folder)
    opp_results = get_team_results(league_folder, opp_team)

    if not opp_profile:
        return html.Div("No data available for opponent", style={"color": MUTED, "textAlign": "center", "padding": "60px"})

    oc = team_color(opp_team)
    mc = team_color(our_team)
    opp_form = opp_results.sort_values("week", ascending=False).head(5)

    # Get opponent match data for heatmaps
    df = load_league_data(league_folder)
    opp_mids = opp_profile.get("match_ids", [])
    opp_match_df = df[(df["match_id"].isin(opp_mids)) & (df["team_name"] == opp_team)]

    sections = []

    # ── Opponent sample resolution via the SAME central resolver as the model/PDF ──
    # Pre-match reports scout the opponent. Goal Profile / Goal Distribution
    # must describe the selected opponent's scoring and conceding patterns.
    from components.goal_profile import compute_goal_profile
    from components.report_sample import resolve_report_sample
    _samp = resolve_report_sample(league_folder, opp_team,
                                  sample_mode=(last_n if last_n else "season"))
    _sample_ids = _samp["match_ids"]
    _n_sample = _samp["n_matches"]

    # ── Report-state badge (Team · Opponent · Sample · Report Type) ──
    sections.append(_report_state_badge(our_team, opp_team, _samp["sample_label"], "pre"))

    # Sample badge (top of report)
    sections.append(html.Div(style={"padding": "8px 14px", "marginBottom": "12px", "background": "#10151D",
                                    "borderRadius": "8px", "border": "1px solid #1E2733", "fontSize": "11px",
                                    "color": "#8A95A5"}, children=[
        html.Span("Sample: ", style={"color": MUTED}),
        html.Span(f"{_samp['sample_label']} · N={_n_sample}", style={"color": GOLD, "fontWeight": "700"}),
        html.Span("  ·  opponent goal distribution uses this opponent sample", style={"marginLeft": "6px"}),
    ] + ([html.Span(f"  ·  ⚠ small sample", style={"color": "#FEB019", "marginLeft": "6px"})] if _n_sample < 3 else [])))
    # Determine top threat / weakness / exploit
    threats = opp_profile.get("threats", [])
    weaknesses = opp_profile.get("weaknesses", [])
    top_threat = threats[0] if threats else "No major threat identified"
    top_weakness = weaknesses[0] if weaknesses else "No clear weakness"

    # Exploit logic
    if "Deep defensive line" in top_weakness or "deep" in top_weakness.lower():
        exploit = "Use pace in behind through early forward balls"
    elif "Passive pressing" in top_weakness or "passive" in top_weakness.lower():
        exploit = "Build confidently; draw press then switch to open side"
    elif "Turnover" in top_weakness:
        exploit = "Press high and exploit turnovers in advanced areas"
    elif "Predictable" in top_weakness:
        exploit = f"Overload their {opp_profile.get('buildup_side', 'strong')} side to force errors"
    else:
        exploit = "Target wide areas and cut-backs into box"

    sections.append(_section_header(1, "Executive Summary", f"30-second coaching brief · scouting {short(opp_team)} (opponent)"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card(None, [
            # Opponent identity
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "14px", "marginBottom": "16px"}, children=[
                _logo(opp_team, 48),
                html.Div([
                    html.Div([
                        html.Span("SCOUTING OPPONENT", style={"fontSize": "9px", "color": oc, "fontWeight": "700",
                                                               "letterSpacing": "0.5px", "padding": "1px 6px",
                                                               "border": f"1px solid {oc}66", "borderRadius": "3px"}),
                    ], style={"marginBottom": "4px"}),
                    html.Div(short(opp_team), style={"fontFamily": "Orbitron", "fontSize": "22px", "fontWeight": "900", "color": oc}),
                    html.Div(f"Last {last_n} matches analyzed", style={"color": MUTED, "fontSize": "11px"}),
                ]),
            ]),
            # Style tags
            html.Div(style={"marginBottom": "14px"}, children=[
                _tag(t, oc) for t in opp_profile.get("style_tags", [])
            ]),
            # Formation & form
            html.Div(style={"marginBottom": "12px", "fontSize": "12px", "color": TEXT}, children=[
                html.Span("Formations: ", style={"color": MUTED}),
                html.Span(" / ".join(opp_profile.get("formations", ["?"])), style={"fontWeight": "600"}),
            ]),
            html.Div(style={"marginBottom": "8px", "fontSize": "12px", "color": TEXT}, children=[
                html.Span("Primary Buildup: ", style={"color": MUTED}),
                html.Span(opp_profile.get("buildup_side", "?"), style={"fontWeight": "600"}),
            ]),
            # Recent form
            html.Div(style={"marginTop": "10px"}, children=[
                html.Span("Form: ", style={"color": MUTED, "fontSize": "12px"}),
                html.Span([html.Span(r["result"], className=f"form-dot form-{r['result']}") for _, r in opp_form.iterrows()]),
            ]),
        ])]),
        html.Div(className="c6", children=[_card(None, [
            # Traffic light indicators
            html.Div(style={"marginBottom": "16px"}, children=[
                html.Div("KEY INDICATORS", style={"fontSize": "10px", "color": MUTED, "fontWeight": "700", "letterSpacing": "1px", "marginBottom": "8px"}),
                _traffic_light("red" if opp_profile.get("xg_per_match", 0) > 1.5 else "amber" if opp_profile.get("xg_per_match", 0) > 1 else "green",
                              "xG / Match", f"{opp_profile.get('xg_per_match', 0):.2f}"),
                _traffic_light("red" if opp_profile.get("ppda", 12) < 8 else "green" if opp_profile.get("ppda", 12) > 12 else "amber",
                              "PPDA (pressing)", f"{opp_profile.get('ppda', 0):.1f}"),
                _traffic_light("red" if opp_profile.get("big_chances_pm", 0) > 2.5 else "amber",
                              "Big Chances / Match", f"{opp_profile.get('big_chances_pm', 0):.1f}"),
                _traffic_light("amber" if opp_profile.get("sp_shots_pm", 0) > 1.5 else "green",
                              "Set-Piece Threat", f"{opp_profile.get('sp_shots_pm', 0):.1f} shots/m"),
                _traffic_light("red" if opp_profile.get("fast_break_shots_pm", 0) > 1.5 else "green",
                              "Transition Danger", f"{opp_profile.get('fast_break_shots_pm', 0):.1f} fb shots/m"),
            ]),
            # Top 3 boxes
            html.Div(style={"background": f"{ACCENT_RED}10", "borderLeft": f"3px solid {ACCENT_RED}", "borderRadius": "6px", "padding": "10px 14px", "marginBottom": "8px"}, children=[
                html.Div("🔴 TOP THREAT", style={"fontSize": "9px", "fontWeight": "700", "color": ACCENT_RED, "letterSpacing": "1px", "marginBottom": "3px"}),
                html.Div(top_threat, style={"fontSize": "12px", "fontWeight": "600"}),
            ]),
            html.Div(style={"background": f"{ACCENT_GREEN}10", "borderLeft": f"3px solid {ACCENT_GREEN}", "borderRadius": "6px", "padding": "10px 14px", "marginBottom": "8px"}, children=[
                html.Div("🟢 TOP WEAKNESS", style={"fontSize": "9px", "fontWeight": "700", "color": ACCENT_GREEN, "letterSpacing": "1px", "marginBottom": "3px"}),
                html.Div(top_weakness, style={"fontSize": "12px", "fontWeight": "600"}),
            ]),
            html.Div(style={"background": f"{GOLD}10", "borderLeft": f"3px solid {GOLD}", "borderRadius": "6px", "padding": "10px 14px"}, children=[
                html.Div("⚡ BEST EXPLOIT", style={"fontSize": "9px", "fontWeight": "700", "color": GOLD, "letterSpacing": "1px", "marginBottom": "3px"}),
                html.Div(exploit, style={"fontSize": "12px", "fontWeight": "600"}),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  OPPONENT GOAL PROFILE — attacking & defensive output (opponent sample)
    #  Derived from the SAME opponent sample as the model/PDF.
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header("G", "Opponent Goal Profile",
                                    f"How {short(opp_team)} score and concede · {_samp['sample_label']}"))
    _goal_block, _gf, _ga = _goal_distribution_cards(
        df, opp_team, _sample_ids,
        scored_title=f"{short(opp_team)} Goals Scored",
        conceded_title=f"{short(opp_team)} Goals Conceded",
    )
    sections.append(_goal_block)

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 2 — TACTICAL IDENTITY
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(2, "Opponent Tactical Identity", "Style archetype, shape & control metrics"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c4", children=[_card("Archetype Radar", [
            dcc.Graph(figure=_archetype_radar(opp_profile, oc), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c4", children=[_card("Game Control", [
            _pct_bar("Possession", opp_profile.get("possession_pct", 50), color=oc),
            _pct_bar("Field Tilt", opp_profile.get("field_tilt", 25), color=oc),
            _pct_bar("Pass Accuracy", opp_profile.get("pass_accuracy", 75), color=oc),
            html.Div(style={"marginTop": "14px"}, children=[
                html.Div("KEY METRICS / MATCH", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginBottom": "8px"}),
                _traffic_light("amber", "PPDA", f"{opp_profile.get('ppda', 0):.1f}"),
                _traffic_light("amber", "Passes / Match", f"{opp_profile.get('passes_per_match', 0):.0f}"),
                _traffic_light("amber", "Prog Passes / M", f"{opp_profile.get('prog_passes_pm', 0):.0f}"),
                _traffic_light("amber", "Switches / M", f"{opp_profile.get('switches_pm', 0):.0f}"),
            ]),
        ])]),
        html.Div(className="c4", children=[_card("Attacking Lanes", [
            html.Div("Pass Distribution by Zone", style={"fontSize": "11px", "color": MUTED, "marginBottom": "8px"}),
            _lane_bar(
                opp_profile.get("lane_distribution", {}).get("left", 33),
                opp_profile.get("lane_distribution", {}).get("center", 34),
                opp_profile.get("lane_distribution", {}).get("right", 33),
            ),
            html.Div(style={"marginTop": "14px"}, children=[
                _traffic_light("amber", "Long Balls / M", f"{opp_profile.get('long_balls_pm', 0):.0f}"),
                _traffic_light("amber", "Crosses / M", f"{opp_profile.get('crosses_pm', 0):.0f}"),
                _traffic_light("amber", "Through Balls / M", f"{opp_profile.get('through_balls_pm', 0):.1f}"),
                _traffic_light("amber", "Cutbacks / M", f"{opp_profile.get('cutbacks_pm', 0):.1f}"),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 3 — BUILDUP & PROGRESSION
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(3, "Buildup & Progression Model", "How they advance the ball · routes, lanes, tendencies"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Progression Heatmap", [
            dcc.Graph(figure=action_heatmap(opp_match_df, event_types=["Pass"]), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Progression Metrics", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(f"{opp_profile.get('prog_passes_pm', 0):.0f}", "Prog Pass/M", oc, True),
                _kpi(f"{opp_profile.get('line_breaks_pm', 0):.0f}", "Line Breaks/M", oc, True),
                _kpi(f"{opp_profile.get('ft_entries_pm', 0):.0f}", "FT Entries/M", oc, True),
                _kpi(f"{opp_profile.get('box_entries_pm', 0):.0f}", "Box Entries/M", ACCENT_GREEN, True),
            ]),
            _card("Buildup Profile", [
                _traffic_light("amber", "Primary Buildup Side", opp_profile.get("buildup_side", "?")),
                _pct_bar("Left Flank", opp_profile.get("lane_distribution", {}).get("left", 33), color=ACCENT_BLUE),
                _pct_bar("Central", opp_profile.get("lane_distribution", {}).get("center", 34), color=GOLD),
                _pct_bar("Right Flank", opp_profile.get("lane_distribution", {}).get("right", 33), color=ACCENT_GREEN),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 4 — CHANCE CREATION
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(4, "Chance Creation & Final Third", "Where they hurt teams · xG sources · patterns"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Shot Map (Last 5)", [
            dcc.Graph(figure=shot_map(opp_match_df, opp_team), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[
            _card("xG by Context", [
                dcc.Graph(figure=_xg_context_bars(
                    opp_profile.get("xg_open_play", 0),
                    opp_profile.get("xg_set_piece", 0),
                    opp_profile.get("xg_fast_break", 0),
                ), config={"displayModeBar": False}),
            ]),
            html.Div(className="row", style={"gap": "8px"}, children=[
                _kpi(f"{opp_profile.get('xg_per_match', 0):.2f}", "xG / Match", ACCENT_GREEN, True),
                _kpi(f"{opp_profile.get('shots_pm', 0):.0f}", "Shots / M", oc, True),
                _kpi(f"{opp_profile.get('big_chances_pm', 0):.1f}", "Big Ch / M", ACCENT_RED, True),
                _kpi(f"{opp_profile.get('goals_pm', 0):.1f}", "Goals / M", GOLD, True),
            ]),
        ]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 5 — DEFENSIVE STRUCTURE & PRESSING
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(5, "Defensive Structure & Pressing", "PPDA, press triggers, weak zones"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Defensive Actions Map", [
            dcc.Graph(figure=defensive_map(opp_match_df, opp_team), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Pressing Profile", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(f"{opp_profile.get('ppda', 0):.1f}", "PPDA", ACCENT_RED if opp_profile.get("ppda", 12) < 9 else ACCENT_GREEN, True),
                _kpi(f"{opp_profile.get('def_action_height', 0):.0f}", "Def Height", oc, True),
                _kpi(f"{opp_profile.get('high_regains_pm', 0):.0f}", "High Reg/M", oc, True),
            ]),
            _pct_bar("Opp Pass Acc Under Press", opp_profile.get("opp_pass_acc", 80), color=ACCENT_RED),
            _pct_bar("Tackles / M", opp_profile.get("tackles_pm", 15), max_val=30, color=oc),
            _pct_bar("Interceptions / M", opp_profile.get("interceptions_pm", 8), max_val=20, color=oc),
            _pct_bar("Recoveries / M", opp_profile.get("recoveries_pm", 40), max_val=60, color=oc),
            html.Div(style={"marginTop": "14px", "padding": "10px", "background": f"rgba(255,255,255,0.02)", "borderRadius": "8px"}, children=[
                html.Div("COACHING ANSWERS", style={"fontSize": "10px", "color": GOLD, "fontWeight": "700", "letterSpacing": "1px", "marginBottom": "8px"}),
                html.Div(f"• {'High press — play through or go over' if opp_profile.get('ppda', 12) < 9 else 'Mid/low block — patient buildup safe'}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
                html.Div(f"• Def line at {opp_profile.get('def_action_height', 45):.0f} — {'space in behind to exploit' if opp_profile.get('def_action_height', 45) > 45 else 'need combination play to unlock'}", style={"fontSize": "11px", "color": TEXT}),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 6 — TRANSITIONS
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(6, "Transition Profile", "What happens when they win/lose the ball"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Transition Metrics", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(f"{opp_profile.get('fast_break_shots_pm', 0):.1f}", "FB Shots/M", ACCENT_RED, True),
                _kpi(f"{opp_profile.get('fast_break_xg', 0):.2f}", "FB xG Total", ACCENT_RED, True),
                _kpi(f"{opp_profile.get('high_turnovers_pm', 0):.1f}", "High TO/M", ACCENT_GREEN, True),
            ]),
            html.Div(style={"marginTop": "10px", "padding": "10px", "background": f"rgba(255,255,255,0.02)", "borderRadius": "8px"}, children=[
                html.Div("TRANSITION SCOUTING", style={"fontSize": "10px", "color": GOLD, "fontWeight": "700", "letterSpacing": "1px", "marginBottom": "8px"}),
                html.Div(f"• Fast-break threat: {'HIGH — set rest defense' if opp_profile.get('fast_break_shots_pm', 0) > 1.5 else 'MODERATE — standard balance' if opp_profile.get('fast_break_shots_pm', 0) > 0.5 else 'LOW — press confidently'}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
                html.Div(f"• Turnovers in advanced areas: {opp_profile.get('high_turnovers_pm', 0):.1f}/match — {'pressable target' if opp_profile.get('high_turnovers_pm', 0) > 5 else 'reasonably secure'}", style={"fontSize": "11px", "color": TEXT}),
            ]),
        ])]),
        html.Div(className="c6", children=[_card("Ball Recovery Zones", [
            dcc.Graph(figure=action_heatmap(opp_match_df, opp_team, event_types=["Ball recovery"]), config={"displayModeBar": False}),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 7 — SET PIECES
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(7, "Set-Piece Intelligence", "Corners, free kicks, delivery patterns"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Offensive Set Pieces", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(f"{opp_profile.get('corners_pm', 0):.1f}", "Corners/M", oc, True),
                _kpi(f"{opp_profile.get('fk_pm', 0):.1f}", "Free Kicks/M", oc, True),
                _kpi(f"{opp_profile.get('sp_shots_pm', 0):.1f}", "SP Shots/M", ACCENT_RED, True),
                _kpi(f"{opp_profile.get('sp_goals', 0)}", f"SP Goals ({last_n}m)", ACCENT_GREEN, True),
            ]),
            _pct_bar("Set-Piece xG", opp_profile.get("xg_set_piece", 0), max_val=max(opp_profile.get("xg_total", 1), 1), color=ACCENT_BLUE),
        ])]),
        html.Div(className="c6", children=[_card("Defensive Set Pieces", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                _kpi(f"{opp_profile.get('opp_sp_shots_pm', 0):.1f}", "SP Shots Conc/M", ACCENT_RED, True),
            ]),
            html.Div(style={"padding": "10px", "background": f"rgba(255,255,255,0.02)", "borderRadius": "8px"}, children=[
                html.Div("SET-PIECE SCOUTING", style={"fontSize": "10px", "color": GOLD, "fontWeight": "700", "letterSpacing": "1px", "marginBottom": "8px"}),
                html.Div(f"• Offensive SP level: {'STRONG — expect rehearsed routines' if opp_profile.get('sp_goals', 0) >= 2 else 'Average — standard organization needed'}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
                html.Div(f"• Defensive SP vulnerability: {'HIGH — target from corners/FKs' if opp_profile.get('opp_sp_shots_pm', 0) > 2 else 'LOW — focus on open play'}", style={"fontSize": "11px", "color": TEXT}),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 8 — PLAYER ROLE PROFILES
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(8, "Key Player Roles", "Role-based profiles · who to press, deny, isolate"))
    # Group players by role
    gk = [p for p in opp_roles if p["position"] == "GK"]
    defenders = [p for p in opp_roles if p["position"] in ["CB", "LB", "RB", "LWB", "RWB"]]
    midfield = [p for p in opp_roles if p["position"] in ["CDM", "CM", "MC", "CAM"]]
    forwards = [p for p in opp_roles if p["position"] in ["CF", "SS", "LW", "RW", "LM", "RM"]]

    role_cols = []
    for group, label, limit in [(defenders, "Defenders", 5), (midfield, "Midfield", 4), (forwards, "Forwards", 4)]:
        role_cols.append(html.Div(className="c4", children=[
            html.Div(label, style={"fontSize": "11px", "fontWeight": "700", "color": GOLD, "textTransform": "uppercase", "letterSpacing": "1px", "marginBottom": "8px"}),
            *[_player_role_card(p, oc) for p in group[:limit]],
        ]))
    sections.append(html.Div(className="row", children=role_cols))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 9 — MATCH-UP / EXPLOITATION
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(9, "Match-Up & Exploitation", "Opponent weakness × Our strength = Tactical edge"))

    exploits = []
    # Generate smart exploits based on actual data
    opp_lane = opp_profile.get("lane_distribution", {})
    our_lane = our_profile.get("lane_distribution", {})

    if opp_profile.get("def_action_height", 45) > 48:
        exploits.append(("🔴 PRIMARY", "Space behind high line", f"Opponent defends at {opp_profile.get('def_action_height', 45):.0f} avg height. Use through balls ({our_profile.get('through_balls_pm', 0):.1f}/m) and pace in behind.", ACCENT_RED))
    if opp_profile.get("ppda", 12) > 11:
        exploits.append(("🔴 PRIMARY", "Build through passive press", f"Opponent PPDA {opp_profile.get('ppda', 0):.1f} — low intensity. We can build with confidence and draw them out.", ACCENT_RED))
    if opp_profile.get("high_turnovers_pm", 0) > 5:
        exploits.append(("🟠 SECONDARY", "Press their turnovers", f"Opponent loses ball {opp_profile.get('high_turnovers_pm', 0):.1f}×/match in advanced areas. High press can create chances.", "#FEB019"))
    if opp_lane.get("left", 33) > 38 or opp_lane.get("right", 33) > 38:
        weak_side = "left" if opp_lane.get("left", 33) < opp_lane.get("right", 33) else "right"
        exploits.append(("🟠 SECONDARY", f"Attack weak {weak_side} side", f"Opponent concentrates {max(opp_lane.get('left',33), opp_lane.get('right',33))}% on strong side. Overload their {weak_side}.", "#FEB019"))
    if opp_profile.get("opp_sp_shots_pm", 0) > 1.5:
        exploits.append(("🟢 TERTIARY", "Target set pieces", f"Opponent concedes {opp_profile.get('opp_sp_shots_pm', 0):.1f} SP shots/match. Use our corners/FKs.", ACCENT_GREEN))

    if not exploits:
        exploits.append(("🟠 PRIMARY", "Balanced approach", "No major exploitable weakness — focus on disciplined execution of our game model.", "#FEB019"))

    # Risk to manage
    risk = f"Opponent creates {opp_profile.get('xg_per_match', 0):.2f} xG/match" if opp_profile.get("xg_per_match", 0) > 1.3 else "Transition defense: prevent fast-break chances"

    exploit_items = []
    for priority, title, desc, color in exploits:
        exploit_items.append(html.Div(style={
            "background": f"{color}08", "borderLeft": f"3px solid {color}",
            "borderRadius": "8px", "padding": "12px 16px", "marginBottom": "8px",
        }, children=[
            html.Div(priority, style={"fontSize": "9px", "fontWeight": "700", "color": color, "letterSpacing": "1px", "marginBottom": "4px"}),
            html.Div(title, style={"fontWeight": "700", "fontSize": "13px", "marginBottom": "3px"}),
            html.Div(desc, style={"fontSize": "11px", "color": MUTED}),
        ]))

    exploit_items.append(html.Div(style={
        "background": f"{ACCENT_PURPLE}08", "borderLeft": f"3px solid {ACCENT_PURPLE}",
        "borderRadius": "8px", "padding": "12px 16px", "marginTop": "12px",
    }, children=[
        html.Div("⚠️ RISK TO MANAGE", style={"fontSize": "9px", "fontWeight": "700", "color": ACCENT_PURPLE, "letterSpacing": "1px", "marginBottom": "4px"}),
        html.Div(risk, style={"fontSize": "12px", "fontWeight": "600"}),
    ]))

    sections.append(_card(None, exploit_items))

    # ══════════════════════════════════════════════════════════════════
    #  PAGE 10 — RECOMMENDED GAME PLAN
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(10, "Recommended Game Plan", "Tactical targets · measurable objectives"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c8", children=[_card("Tactical Targets", [
            html.Table(style={"width": "100%", "borderCollapse": "collapse"}, children=[
                html.Thead(html.Tr([
                    html.Th("Metric", style={"textAlign": "left", "padding": "8px 10px", "background": "#1A2030", "color": MUTED, "fontSize": "10px", "fontWeight": "600", "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                    html.Th("Target", style={"textAlign": "center", "padding": "8px 10px", "background": "#1A2030", "color": MUTED, "fontSize": "10px", "fontWeight": "600", "textTransform": "uppercase"}),
                    html.Th("Rationale", style={"textAlign": "left", "padding": "8px 10px", "background": "#1A2030", "color": MUTED, "fontSize": "10px", "fontWeight": "600", "textTransform": "uppercase"}),
                ])),
                html.Tbody([
                    html.Tr([
                        html.Td(t["label"], style={"padding": "10px", "fontWeight": "600", "fontSize": "12px", "color": TEXT, "borderBottom": f"1px solid {CARD_BG}"}),
                        html.Td((f"{t['low']}–{t['high']}" if t.get("kind") == "range" else f"≤ {t['high']}"), style={"padding": "10px", "textAlign": "center", "fontFamily": "Orbitron", "fontWeight": "700", "fontSize": "13px", "color": GOLD, "borderBottom": f"1px solid {CARD_BG}"}),
                        html.Td(t.get("note", "") or t["label"], style={"padding": "10px", "fontSize": "11px", "color": MUTED, "borderBottom": f"1px solid {CARD_BG}"}),
                    ]) for t in plan_targets
                ]),
            ]),
        ])]),
        html.Div(className="c4", children=[_card("Structure & Setup", [
            html.Div("OUR EXPECTED FORMATION", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginBottom": "8px"}),
            html.Div(" / ".join(our_profile.get("formations", ["?"])), style={"fontFamily": "Orbitron", "fontSize": "22px", "color": mc, "fontWeight": "700", "marginBottom": "14px"}),
            html.Div("KEY INSTRUCTIONS", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginBottom": "8px"}),
            html.Div(f"• {'Press high (PPDA < 9)' if opp_profile.get('ppda', 12) > 11 else 'Mid-block press'}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
            html.Div(f"• {'Attack in behind' if opp_profile.get('def_action_height', 45) > 46 else 'Combination play in final third'}", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
            html.Div(f"• Target {opp_profile.get('buildup_side', 'their').lower()} side for pressing traps", style={"fontSize": "11px", "color": TEXT, "marginBottom": "4px"}),
            html.Div(f"• Set rest defense: {'2-3 back' if opp_profile.get('fast_break_shots_pm', 0) > 1 else 'standard balance'}", style={"fontSize": "11px", "color": TEXT}),
        ])]),
    ]))

    return html.Div(sections)


# ══════════════════════════════════════════════════════════════════════════════
#  POST-MATCH REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════
def build_post_match_report(league_folder: str, match_id: str, our_team: str) -> html.Div:
    """Build the full 10-page Post-Match Report."""

    report = compute_post_match_report(league_folder, match_id)
    if not report or "meta" not in report or "home" not in report or "away" not in report:
        return html.Div(style={"textAlign": "center", "padding": "60px"}, children=[
            html.Div("⚠️ Match data not available", style={"color": "#FF4560", "fontWeight": "700", "fontSize": "16px", "marginBottom": "10px"}),
            html.Div("This match may belong to a different season or the data is incomplete. Try selecting a match from the current league/season.",
                     style={"color": "#5A6575", "fontSize": "13px", "maxWidth": "450px", "margin": "0 auto"}),
        ])

    meta = report["meta"]
    home = report["home"]
    away = report["away"]

    # Determine our side
    if meta["home_team"] == our_team:
        us, them = home, away
        our_side, opp_side = "home", "away"
    else:
        us, them = away, home
        our_side, opp_side = "away", "home"

    oc = team_color(them["team"])
    mc = team_color(us["team"])
    if oc == mc:
        oc = ACCENT_BLUE

    # Get match data for visualizations
    mdf = get_match_data(league_folder, match_id)
    ml = get_match_list(league_folder)

    # Plan targets — built ONLY from matches BEFORE this one (no data leakage).
    _mw = meta.get("week")
    our_profile = compute_team_profile(league_folder, our_team, 5,
                                       before_matchweek=_mw, exclude_match_id=match_id)
    opp_profile = compute_team_profile(league_folder, them["team"], 5,
                                       before_matchweek=_mw, exclude_match_id=match_id)
    # Fallback if the cutoff leaves no prior matches (e.g. week 1)
    if not our_profile:
        our_profile = compute_team_profile(league_folder, our_team, 5)
    if not opp_profile:
        opp_profile = compute_team_profile(league_folder, them["team"], 5)
    print(f"[REPORT_QA] Pre-match targets built from {our_profile.get('matches_analyzed', 0)} matches before W{_mw}.")

    # ── Use the NEW target_engine (Wyscout-aware, range-based) ──
    from components.target_engine import generate_targets, evaluate_targets, infer_plan_template
    _sample = our_profile.get("matches_analyzed", 0) if our_profile else 0
    _plan = generate_targets(our_profile or {}, opp_profile or {},
                             sample_size=_sample, wyscout_available=(us.get("xg_source") == "Wyscout"))
    # Build actuals dict from the (Wyscout-overlaid) report
    _actuals = {
        "xg": us.get("xg"), "xga": us.get("xga"), "ppda": us.get("ppda"),
        "possession": us.get("possession"), "field_tilt": us.get("field_tilt"),
        "box_entries": us.get("box_entries"),
        "transition_xga": us.get("transition_xg_against"),
        "set_piece_shots": us.get("sp_shots"),
        "set_piece_conceded": us.get("opp_sp_shots"),
    }
    _ctx = {"won": us.get("goals", 0) > them.get("goals", 0),
            "goal_diff": us.get("goals", 0) - them.get("goals", 0),
            "xga": us.get("xga"), "big_chances_against": them.get("big_chances", 0)}
    _teval = evaluate_targets(_plan, _actuals, _ctx)

    # ── Match KPI context: every key post-match number gets team-season and league baselines.
    # This is intentionally built once and reused across defensive/attacking/pressing sections.
    try:
        from components.kpi_context import build_post_match_kpi_contexts
        _match_values = {
            "tackles_won": us.get("tackles_won"), "tackles": us.get("tackles"),
            "tackle_success_pct": (round(us.get("tackles_won", 0) / max(us.get("tackles", 0), 1) * 100, 1) if us.get("tackles") is not None else None),
            "interceptions": us.get("interceptions"), "recoveries": us.get("recoveries"), "clearances": us.get("clearances"),
            "duels_won": us.get("tackles_won", 0) + us.get("aerials_won", 0), "aerials_won": us.get("aerials_won"),
            "ppda": us.get("ppda"), "xg": us.get("xg"), "xga": us.get("xga"),
            "shots": us.get("shots_wyscout", us.get("shots")), "shots_on_target": us.get("sot_wyscout", us.get("shots_on_target")),
            "big_chances": us.get("big_chances"), "sp_shots": us.get("sp_shots"),
            "ft_entries": us.get("ft_entries"), "box_entries": us.get("box_entries"), "prog_passes": us.get("prog_passes"),
            "possession": us.get("possession"), "field_tilt": us.get("field_tilt"), "corners": us.get("corners_wyscout", us.get("corners")),
            "fouls_committed": us.get("fouls_committed"), "yellow_cards": us.get("yellow_cards"), "red_cards": us.get("red_cards"),
        }
        _post_ctx_metrics = [
            "xg", "xga", "shots", "shots_on_target", "big_chances",
            "tackles_won", "tackles", "tackle_success_pct", "interceptions", "recoveries", "clearances",
            "duels_won", "aerials_won", "ppda", "possession", "field_tilt",
            "ft_entries", "box_entries", "prog_passes", "sp_shots", "corners",
            "fouls_committed", "yellow_cards", "red_cards",
        ]
        _post_contexts = build_post_match_kpi_contexts(league_folder, our_team, match_id, _match_values, _post_ctx_metrics)
    except Exception as _e:
        print(f"[REPORT_QA] Post-match KPI context unavailable: {_e}")
        _post_contexts = []

    sections = []

    # ── Report-state badge (Team · Opponent · Sample · Report Type) ──
    sections.append(_report_state_badge(
        our_team, them["team"],
        f"This match (W{meta['week']} {short(meta['home_team'])} {meta['home_goals']}-{meta['away_goals']} {short(meta['away_team'])})",
        "post"))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 1 — MATCH EXECUTIVE SUMMARY
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(1, "Match Executive Summary", f"Matchweek {meta['week']} · {meta['date']}"))

    # Score banner
    sections.append(html.Div(style={
        "background": "linear-gradient(135deg, #070A0D 0%, #151208 50%, #070A0D 100%)",
        "border": f"1px solid rgba(255,255,255,0.06)", "borderRadius": "12px",
        "padding": "22px 36px", "textAlign": "center", "marginBottom": "16px",
    }, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "center", "gap": "36px"}, children=[
            html.Div(style={"textAlign": "center"}, children=[_logo(meta["home_team"], 48), html.Div(short(meta["home_team"]), style={"fontWeight": "600", "fontSize": "14px", "marginTop": "4px"})]),
            html.Div(f"{meta['home_goals']}  —  {meta['away_goals']}", style={"fontFamily": "Orbitron", "fontSize": "42px", "fontWeight": "900", "color": "#fff", "letterSpacing": "4px"}),
            html.Div(style={"textAlign": "center"}, children=[_logo(meta["away_team"], 48), html.Div(short(meta["away_team"]), style={"fontWeight": "600", "fontSize": "14px", "marginTop": "4px"})]),
        ]),
        # Game story tag
        html.Div(style={"marginTop": "10px"}, children=[
            _tag(report.get("game_story", ""), GOLD),
        ]),
    ]))

    # Key KPIs — Wyscout-sourced where available (labels reflect source)
    _xg_lbl = "Wyscout xG" if us.get("xg_source") == "Wyscout" else "Estimated xG"
    _oxg_lbl = "Wyscout xGA" if us.get("xga_source") == "Wyscout" else "Estimated xGA"
    _poss_lbl = "Wyscout Poss%" if us.get("possession_source") == "Wyscout" else "Pass Share%"
    _ppda_lbl = "Wyscout PPDA" if us.get("ppda_source") == "Wyscout" else "Estimated PPDA"
    sections.append(html.Div(className="row", style={"gap": "8px"}, children=[
        _kpi(f"{us['xg']:.2f}", _xg_lbl, mc, True),
        _kpi(f"{us.get('xga', them['xg']):.2f}", _oxg_lbl, oc, True),
        _kpi(f"{us['possession']:.0f}%", _poss_lbl, mc, True),
        _kpi(f"{us['field_tilt']:.0f}%", "Est. Field Tilt", mc, True),
        _kpi(f"{us['ppda']:.1f}", _ppda_lbl, mc, True),
        _kpi(f"{us['ft_entries']}", "FT Entries", mc, True),
        _kpi(f"{us.get('shots_wyscout', us['shots'])}", "Shots", mc, True),
        _kpi(f"{us['big_chances']}", "Big Chances", ACCENT_GREEN, True),
    ]))

    # Match-vs-season context so raw post-match KPIs become interpretable.
    sections.append(_section_header("C", "KPI Context", "Match value vs team season average and league average"))
    sections.append(_card("Key Match Metrics in Context", [
        html.Div("Season/team and league baselines exclude this match. Defensive workload metrics are contextual: higher volume can mean strong ball-winning or more defending.",
                 style={"fontSize": "10px", "color": MUTED, "marginBottom": "8px"}),
        _post_context_grid(_post_contexts, ["xg", "xga", "shots", "shots_on_target", "big_chances", "ppda", "possession", "field_tilt", "ft_entries", "box_entries", "prog_passes"]),
    ]))

    # ── Goal Distribution (THIS MATCH ONLY) — how our team scored & conceded ──
    sections.append(_section_header("G", "Goal Distribution",
                                    f"How {short(our_team)} scored & conceded · this match only"))
    _post_goal_block, _pgf, _pga = _goal_distribution_cards(
        mdf, our_team, [match_id],
        scored_title="Goals Scored (this match)",
        conceded_title="Goals Conceded (this match)")
    sections.append(_post_goal_block)

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 2 — PLAN VS EXECUTION  (target_engine, Wyscout-aware)
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(2, "Plan vs Execution", "Pre-match targets vs actual outcome"))

    adherence = _teval["score"]
    counts = _teval["counts"]
    adh_color = ACCENT_GREEN if adherence >= 65 else ("#FEB019" if adherence >= 45 else ACCENT_RED)
    _conf = _plan.get("confidence", "High")

    gm_banner = [html.Div(style={"marginBottom": "10px", "padding": "8px 12px",
                                 "background": "#161C2A", "borderRadius": "8px",
                                 "border": f"1px solid {GOLD}33"}, children=[
        html.Span("Tactical Plan: ", style={"color": MUTED, "fontSize": "11px"}),
        html.Span(_plan["template"].replace("_", " ").title(), style={"color": GOLD, "fontWeight": "700", "fontSize": "12px"}),
        html.Span(f"  ·  Confidence: {_conf}", style={"color": MUTED, "fontSize": "10px"}),
        html.Div(_plan.get("rationale", ""), style={"color": MUTED, "fontSize": "10px", "marginTop": "2px"}),
    ])]
    if _conf == "Low":
        gm_banner.append(html.Div("⚠ Small pre-match sample — targets are low confidence.",
                                  style={"color": "#FEB019", "fontSize": "11px", "marginBottom": "8px"}))

    def _trow(r):
        st = r["status"]
        color = {"Hit": ACCENT_GREEN, "Strategically Acceptable": "#00D0C0", "Partial": "#FEB019",
                 "Missed": ACCENT_RED, "Not Applicable": MUTED, "Low Confidence": MUTED,
                 "Unavailable": MUTED}.get(st, MUTED)
        tgt = (f"{r['low']}–{r['high']}" if r.get("kind") == "range" else f"≤ {r['high']}")
        actual = r.get("actual")
        actual = f"{actual:.2f}" if isinstance(actual, float) else (str(actual) if actual is not None else "—")
        return html.Tr(style={"borderBottom": f"1px solid {CARD_BG}"}, children=[
            html.Td(r["label"], style={"padding": "8px 10px", "fontWeight": "600", "color": TEXT, "fontSize": "12px"}),
            html.Td(tgt, style={"padding": "8px 10px", "color": MUTED, "textAlign": "center", "fontSize": "12px", "fontFamily": "Orbitron, monospace"}),
            html.Td(actual, style={"padding": "8px 10px", "fontWeight": "700", "color": color, "textAlign": "center", "fontSize": "13px", "fontFamily": "Orbitron, monospace"}),
            html.Td(st, style={"padding": "8px 10px", "textAlign": "center", "fontSize": "11px", "color": color, "fontWeight": "600"}),
            html.Td(f"{r.get('weight', 1):.1f}", style={"padding": "8px 10px", "textAlign": "center", "fontSize": "10px", "color": MUTED}),
            html.Td(r.get("interpretation", ""), style={"padding": "8px 10px", "color": MUTED, "fontSize": "11px"}),
        ])

    sections.append(html.Div(gm_banner + [html.Div(className="row", children=[
        html.Div(className="c8", children=[_card("Target vs Actual", [
            html.Table(style={"width": "100%", "borderCollapse": "collapse"}, children=[
                html.Thead(html.Tr([
                    html.Th(h, style={"textAlign": "left" if h in ("Metric", "Interpretation") else "center", "padding": "8px 10px", "background": "#1A2030", "color": MUTED, "fontSize": "10px", "fontWeight": "600", "textTransform": "uppercase"})
                    for h in ["Metric", "Target", "Actual", "Status", "Weight", "Interpretation"]
                ])),
                html.Tbody([_trow(r) for r in _teval["results"]]),
            ]),
        ])]),
        html.Div(className="c4", children=[_card("Tactical Execution Score", [
            html.Div(style={"textAlign": "center", "padding": "16px"}, children=[
                html.Div(f"{adherence}%", style={"fontFamily": "Orbitron", "fontSize": "48px", "fontWeight": "900", "color": adh_color}),
                html.Div("Weighted Execution Score", style={"fontSize": "11px", "color": MUTED, "textTransform": "uppercase", "letterSpacing": "1px", "marginTop": "4px"}),
                html.Div(_teval["label"], style={"fontSize": "13px", "color": adh_color, "fontWeight": "700", "marginTop": "6px"}),
                html.Div(f"Result: {meta['home_goals']}–{meta['away_goals']}", style={"fontSize": "11px", "color": MUTED, "marginTop": "4px"}),
            ]),
            html.Div(style={"marginTop": "10px"}, children=[
                _traffic_light("green", "Hit", f"{counts.get('Hit',0)}"),
                _traffic_light("green", "Strategically OK", f"{counts.get('Strategically Acceptable',0)}"),
                _traffic_light("amber", "Partial", f"{counts.get('Partial',0)}"),
                _traffic_light("red", "Missed", f"{counts.get('Missed',0)}"),
                _traffic_light("amber", "N/A or Unavailable", f"{counts.get('Not Applicable',0)+counts.get('Unavailable',0)}"),
            ]),
        ])]),
    ])]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 3 — IN-POSSESSION PERFORMANCE
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(3, "In-Possession Performance", "How we used the ball — control, penetration, creation"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Pass Network & Heatmap", [
            dcc.Graph(figure=action_heatmap(mdf, us["team"], event_types=["Pass"]), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[
            _card("Possession Quality", [
                html.Div(className="row", style={"gap": "8px", "marginBottom": "10px"}, children=[
                    _kpi(us["passes"], "Passes", mc, True),
                    _kpi(f"{us['pass_accuracy']}%", "Pass Acc", mc, True),
                    _kpi(us["prog_passes"], "Prog Pass", GOLD, True),
                    _kpi(us["line_breaks"], "Line Breaks", GOLD, True),
                ]),
                _pct_bar("Final Third Entries", us["ft_entries"], max_val=max(us["ft_entries"], them["ft_entries"], 1), color=mc),
                _pct_bar("Box Entries", us["box_entries"], max_val=max(us["box_entries"], them["box_entries"], 1), color=mc),
                _pct_bar("Switches", us["switches"], max_val=max(us["switches"], 10), color=mc),
                html.Div("LANE DISTRIBUTION", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginTop": "10px", "marginBottom": "6px"}),
                _lane_bar(us["lane_left"], us["lane_center"], us["lane_right"]),
            ]),
        ]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 4 — OUT-OF-POSSESSION PERFORMANCE
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(4, "Out-of-Possession Performance", "Defensive model, pressing, space control"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Our Defensive Actions", [
            dcc.Graph(figure=defensive_map(mdf, us["team"]), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Defensive Metrics", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "10px"}, children=[
                _kpi(f"{us['ppda']:.1f}", "PPDA", mc, True),
                _kpi(f"{us['def_height']:.0f}", "Def Height", mc, True),
                _kpi(us["high_regains"], "High Regains", ACCENT_GREEN, True),
                _kpi(us["counterpress"], "Counterpress", ACCENT_BLUE, True),
            ]),
            html.Div("DEFENSIVE OUTPUT VS SEASON AVERAGES", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "margin": "8px 0 6px"}),
            _post_context_grid(_post_contexts, ["tackles_won", "tackles", "tackle_success_pct", "interceptions", "recoveries", "clearances", "duels_won", "aerials_won"]),
            html.Div(style={"marginTop": "10px"}, children=[
                _traffic_light("green" if them["shots"] < 10 else "amber" if them["shots"] < 15 else "red", "Opp Shots", them["shots"]),
                _traffic_light("green" if them["xg"] < 1.0 else "amber" if them["xg"] < 1.5 else "red", "Opp xG", f"{them['xg']:.2f}"),
                _traffic_light("green" if them["big_chances"] < 2 else "red", "Opp Big Chances", them["big_chances"]),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 5 — TRANSITIONS
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(5, "Transition Performance", "Attack/defend in transition moments"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Transition Balance", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "10px"}, children=[
                _kpi(us["fast_break_shots"], "Our FB Shots", mc, True),
                _kpi(f"{us['transition_xg_for']:.2f}", "Trans xG For", ACCENT_GREEN, True),
                _kpi(them["fast_break_shots"], "Opp FB Shots", oc, True),
                _kpi(f"{us['transition_xg_against']:.2f}", "Trans xG Against", ACCENT_RED, True),
            ]),
            html.Div(style={"marginTop": "10px", "padding": "10px", "background": f"rgba(255,255,255,0.02)", "borderRadius": "8px"}, children=[
                html.Div("TRANSITION VERDICT", style={"fontSize": "10px", "color": GOLD, "fontWeight": "700", "letterSpacing": "1px", "marginBottom": "6px"}),
                html.Div(
                    f"{'✅ Transition advantage' if us['transition_xg_for'] > us['transition_xg_against'] + 0.2 else '⚠️ Transition balanced' if abs(us['transition_xg_for'] - us['transition_xg_against']) < 0.2 else '❌ Transition deficit — rest defense issue'}",
                    style={"fontSize": "12px", "fontWeight": "600"}),
            ]),
        ])]),
        html.Div(className="c6", children=[_card("Recovery Zones", [
            dcc.Graph(figure=action_heatmap(mdf, us["team"], event_types=["Ball recovery"]), config={"displayModeBar": False}),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 6 — CHANCE QUALITY & xG
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(6, "Chance Quality & Finishing", "Volume vs quality, xG timeline, shot analysis"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Shot Map", [
            dcc.Graph(figure=shot_map(mdf), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Rolling xG Timeline", [
            dcc.Graph(figure=_xg_rolling_timeline(
                us["xg_timeline"], them["xg_timeline"],
                us["team"], them["team"], mc, oc,
            ), config={"displayModeBar": False}),
        ])]),
    ]))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("xG by Context", [
            dcc.Graph(figure=_xg_context_bars(
                us["xg_by_context"]["Open Play"],
                us["xg_by_context"]["Set Piece"],
                us["xg_by_context"]["Fast Break"],
            ), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Half Comparison", [
            html.Div(className="row", style={"gap": "8px"}, children=[
                _kpi(f"{us['h1_xg']:.2f}", "1st Half xG", mc, True),
                _kpi(f"{us['h2_xg']:.2f}", "2nd Half xG", mc, True),
                _kpi(us["h1_shots"], "1H Shots", mc, True),
                _kpi(us["h2_shots"], "2H Shots", mc, True),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 7 — SET PIECE REVIEW
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(7, "Set-Piece Review", "Dead-ball performance for/against"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("Our Set Pieces", [
            html.Div(className="row", style={"gap": "8px"}, children=[
                _kpi(us["corners"], "Corners", mc, True),
                _kpi(us["sp_shots"], "SP Shots", mc, True),
                _kpi(us["sp_goals"], "SP Goals", ACCENT_GREEN, True),
            ]),
        ])]),
        html.Div(className="c6", children=[_card("Set Pieces Conceded", [
            html.Div(className="row", style={"gap": "8px"}, children=[
                _kpi(them["corners"], "Opp Corners", oc, True),
                _kpi(us["opp_sp_shots"], "SP Shots Conc", ACCENT_RED, True),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 8 — INDIVIDUAL PERFORMANCE
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(8, "Individual Performance", "Role-based player evaluation"))
    our_match_roles = compute_player_roles(league_folder, our_team, last_n=1)
    # Use only match players by filtering roles to those in the latest match
    starter_roles = [p for p in our_match_roles if p["touches"] > 10][:11]
    role_cards = [_player_role_card(p, mc) for p in starter_roles]
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=role_cards[:6] if role_cards else [html.Div("No data", style={"color": MUTED})]),
        html.Div(className="c6", children=role_cards[6:] if len(role_cards) > 6 else []),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 9 — MOMENTUM / GAME-STATE ANALYSIS
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(9, "Timeline & Momentum", "How the match evolved over 90 minutes"))
    sections.append(html.Div(className="row", children=[
        html.Div(className="c6", children=[_card("xG Race", [
            dcc.Graph(figure=_xg_rolling_timeline(
                us["xg_timeline"], them["xg_timeline"],
                us["team"], them["team"], mc, oc, height=280,
            ), config={"displayModeBar": False}),
        ])]),
        html.Div(className="c6", children=[_card("Half Performance Split", [
            html.Div(className="row", style={"gap": "8px", "marginBottom": "12px"}, children=[
                html.Div(style={"flex": "1", "textAlign": "center"}, children=[
                    html.Div("1ST HALF", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginBottom": "6px"}),
                    _kpi(f"{us['h1_xg']:.2f}", "xG", mc, True),
                    html.Div(style={"marginTop": "6px"}, children=[_kpi(us["h1_shots"], "Shots", mc, True)]),
                ]),
                html.Div(style={"width": "1px", "background": f"rgba(255,255,255,0.06)", "alignSelf": "stretch"}),
                html.Div(style={"flex": "1", "textAlign": "center"}, children=[
                    html.Div("2ND HALF", style={"fontSize": "10px", "color": MUTED, "fontWeight": "600", "letterSpacing": "1px", "marginBottom": "6px"}),
                    _kpi(f"{us['h2_xg']:.2f}", "xG", mc, True),
                    html.Div(style={"marginTop": "6px"}, children=[_kpi(us["h2_shots"], "Shots", mc, True)]),
                ]),
            ]),
            html.Div(style={"padding": "10px", "background": f"rgba(255,255,255,0.02)", "borderRadius": "8px", "marginTop": "8px"}, children=[
                html.Div(f"{'Second half improvement' if us['h2_xg'] > us['h1_xg'] + 0.3 else 'First half stronger' if us['h1_xg'] > us['h2_xg'] + 0.3 else 'Consistent across halves'}",
                         style={"fontSize": "12px", "fontWeight": "600", "color": TEXT}),
            ]),
        ])]),
    ]))

    # ══════════════════════════════════════════════════════════════════
    #  POST PAGE 10 — TRAINING RECOMMENDATIONS
    # ══════════════════════════════════════════════════════════════════
    sections.append(_section_header(10, "Training Recommendations", "Auto-generated coaching actions from weak metrics"))

    recs = []
    # Generate from actual data
    if them["xg"] > 1.5:
        recs.append(("🛡️", "Defensive Compactness Drill", f"Conceded {them['xg']:.2f} xG — work on midfield shape and central access denial.", "high"))
    if us["transition_xg_against"] > 0.4:
        recs.append(("⚡", "Transition Defense Rehearsal", f"Opponent created {us['transition_xg_against']:.2f} xG from fast breaks — practice rest-defense recovery.", "high"))
    if us["box_entries"] < 8:
        recs.append(("🎯", "Final-Third Penetration", f"Only {us['box_entries']} box entries — practice combination play into the box.", "high"))
    if us["xg"] > 1.5 and us["goals"] < us["xg"] - 0.5:
        recs.append(("⚽", "Finishing Session", f"Created {us['xg']:.2f} xG but scored {us['goals']} — focus on composure in front of goal.", "medium"))
    if us["sp_shots"] == 0 and us["corners"] > 3:
        recs.append(("🏁", "Set-Piece Rehearsal", f"Had {us['corners']} corners but 0 SP shots — review delivery and movement patterns.", "medium"))
    if us["pass_accuracy"] < 78:
        recs.append(("📐", "Possession Under Pressure", f"Pass accuracy {us['pass_accuracy']}% — work on ball security in tight spaces.", "medium"))
    if them["lane_center"] > 40:
        recs.append(("🔒", "Central Compactness", f"Opponent had {them['lane_center']:.0f}% central access — drill midfield compactness.", "medium"))
    if us["high_regains"] < 5:
        recs.append(("💨", "Press Trigger Work", f"Only {us['high_regains']} high regains — rehearse coordinated pressing traps.", "low"))
    if us["crosses"] > 10 and us["goals"] == 0:
        recs.append(("✈️", "Crossing Quality", f"{us['crosses']} crosses delivered but no goals — work on delivery timing and movement.", "low"))

    # Always add at least one if empty
    if not recs:
        recs.append(("✅", "Review & Maintain", "All metrics within targets — focus on consolidation and tactical repetition.", "low"))

    sections.append(_card("Next Week Training Focus", [
        *[_training_item(icon, title, desc, pri) for icon, title, desc, pri in recs],
    ]))

    return html.Div(sections)
