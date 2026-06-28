"""
components/charts.py — All chart builders for the dashboard.
"""

import plotly.graph_objects as go
import numpy as np
import pandas as pd
from components.definitions import filter_valid_touch_events, filter_valid_pass_events, filter_valid_defensive_events
from scipy.ndimage import gaussian_filter

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


# ── Lens-inspired palette ──────────────────────────────────────────────────
BG = "#0B0E11"
CARD_BG = "#141920"
GRID = "rgba(255,255,255,0.05)"
TEXT = "#C8D0DA"
MUTED = "#5A6575"
GOLD = "#FFD700"
GOLD_DIM = "#B8960F"
ACCENT_GREEN = "#00E396"
ACCENT_BLUE = "#008FFB"
ACCENT_RED = "#FF4560"
ACCENT_PURPLE = "#775DD0"

TMPL = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(family="Inter, Segoe UI, sans-serif", color=TEXT, size=12),
    xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    margin=dict(l=50, r=20, t=40, b=40),
)

def _tmpl(fig, height=380, title=""):
    fig.update_layout(**TMPL, height=height,
                      title=dict(text=title, font=dict(size=14, color="#fff")) if title else {})
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  MATCH MOMENTUM & KEY EVENTS  (replaces the old crowded match_timeline)
# ══════════════════════════════════════════════════════════════════════════
def match_momentum_graph(match_data, home_team, away_team, window=1,
                         home_color=GOLD, away_color=ACCENT_BLUE, height=300):
    """
    NET-MOMENTUM BAR CHART (per the uploaded reference image).

    One signed value per minute bin: net = home_danger - away_danger.
    Positive -> home bar above baseline (home color); negative -> away bar
    below baseline (away color). A single net value per minute means both
    teams can NEVER appear dominant at the same minute. Goals are marked
    under the baseline; half-time is a dashed separator; details in hover.
    """
    from components.definitions import SHOT_EVENTS, BOX_X, BOX_Y_LO, BOX_Y_HI, FINAL_THIRD_X

    fig = go.Figure()
    if match_data is None or match_data.empty or "time_min" not in match_data.columns:
        return _tmpl(fig, height=height, title="")

    df = match_data.dropna(subset=["time_min"]).copy()
    df["time_min"] = df["time_min"].astype(int)
    max_min = max(int(df["time_min"].max()) if not df.empty else 90, 90)
    minutes = list(range(0, max_min + 1))

    def _danger_per_minute(team):
        tdf = df[df["team_name"] == team].copy()
        arr = np.zeros(len(minutes))
        if tdf.empty:
            return arr
        ev = tdf["event"].astype(str)
        w = pd.Series(0.0, index=tdf.index)
        w[ev == "Goal"] += 5.0
        w[ev.isin(SHOT_EVENTS) & ~(ev == "Goal")] += 2.0
        w[ev.isin(["Saved Shot"])] += 1.0          # on target bonus -> 3
        if "Big Chance" in tdf.columns:
            w[_flagmask(tdf["Big Chance"])] += 4.0
        is_pass = ev == "Pass"
        if "Pass End X" in tdf.columns:
            pe = pd.to_numeric(tdf["Pass End X"], errors="coerce")
            pey = pd.to_numeric(tdf.get("Pass End Y", pd.Series(index=tdf.index)), errors="coerce")
            px = pd.to_numeric(tdf.get("x", pd.Series(index=tdf.index)), errors="coerce")
            w[is_pass & (pe >= BOX_X) & (pey >= BOX_Y_LO) & (pey <= BOX_Y_HI)] += 1.5
            w[is_pass & (pe >= FINAL_THIRD_X)] += 1.0
            w[is_pass & ((pe - px) >= 15)] += 0.8
        if "Leading to attempt" in tdf.columns:
            w[is_pass & tdf["Leading to attempt"].notna()] += 2.0
        if "x" in tdf.columns:
            x = pd.to_numeric(tdf["x"], errors="coerce")
            w[(ev == "Ball recovery") & (x > 60)] += 0.8
        w[ev == "Corner Awarded"] += 0.5
        tdf["_w"] = w.values
        g = tdf.groupby("time_min", observed=True)["_w"].sum()
        for mn, v in g.items():
            if 0 <= int(mn) < len(arr):
                arr[int(mn)] = v
        return arr

    home_d = _danger_per_minute(home_team)
    away_d = _danger_per_minute(away_team)

    # Light rolling smoothing (3-min) so single events don't spike alone
    def _smooth(a):
        if len(a) < 3:
            return a
        return np.convolve(a, np.array([0.25, 0.5, 0.25]), mode="same")
    net = _smooth(home_d) - _smooth(away_d)

    pos = np.where(net > 0, net, 0.0)
    neg = np.where(net < 0, net, 0.0)
    dominant = [home_team if v > 0 else (away_team if v < 0 else "Even") for v in net]

    # Home bars (up) and away bars (down) — discrete vertical bars
    fig.add_trace(go.Bar(
        x=minutes, y=pos, name=home_team, marker_color=home_color,
        marker_line_width=0, width=0.9,
        customdata=np.array(dominant),
        hovertemplate="Min %{x}'<br>"+home_team+" edge: %{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=minutes, y=neg, name=away_team, marker_color=away_color,
        marker_line_width=0, width=0.9,
        customdata=np.array(dominant),
        hovertemplate="Min %{x}'<br>"+away_team+" edge: %{y:.1f}<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.35)", line_width=1.2)
    fig.add_vline(x=45, line_dash="dot", line_color="rgba(255,255,255,0.20)")
    fig.add_annotation(x=45, y=1.06, yref="paper", text="HT", showarrow=False, font=dict(color=MUTED, size=9))

    ymax = max(np.abs(net).max(), 1.0) * 1.2
    # Goal markers under baseline
    for _, g in df[df["event"] == "Goal"].iterrows():
        is_home = g["team_name"] == home_team
        gx = int(g["time_min"])
        fig.add_annotation(x=gx, y=-ymax * 0.92, text="⚽", showarrow=False, font=dict(size=14),
                           hovertext=f"GOAL {g.get('player_name','')} {gx}'")
    if "Red Card" in df.columns:
        for _, r in df[(df["event"] == "Card") & _flagmask(df["Red Card"])].iterrows():
            rx = int(r["time_min"])
            fig.add_vline(x=rx, line_color="#FF3030", line_width=1.4, opacity=0.6, line_dash="dash")
            fig.add_annotation(x=rx, y=ymax*0.9, text="🟥", showarrow=False, font=dict(size=12),
                               hovertext=f"Red card {rx}'")

    fig = _tmpl(fig, height=height)
    fig.update_layout(
        barmode="relative", bargap=0.15,
        xaxis=dict(title="Minute", range=[0, max_min + 1], tickmode="array",
                   tickvals=[15, 30, 45, 60, 75, 90], gridcolor="rgba(255,255,255,0.04)"),
        yaxis=dict(title="◄ "+away_team[:12]+"   net   "+home_team[:12]+" ►",
                   showticklabels=False, range=[-ymax, ymax], zeroline=False),
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center", font=dict(size=11)),
        margin=dict(l=60, r=20, t=44, b=42),
    )
    return fig



# ══════════════════════════════════════════════════════════════════════════
#  MATCH STATISTICS — per-row independent scaling (readable HTML, not Plotly)
# ══════════════════════════════════════════════════════════════════════════
def match_stats_comparison_component(stats, home_color=GOLD, away_color=ACCENT_BLUE):
    """
    Readable match-statistics comparison where EACH ROW scales independently.
    Row split = value / (home+away), so Corners 28 vs 2 gives a 93%/7% bar even
    though Passes are in the hundreds. Big numbers, full labels, team colors.
    Returns a Dash html.Div (import dash here to keep charts importable headless).
    """
    from dash import html

    h, a = stats["home"], stats["away"]
    home_name = h.get("team", "Home"); away_name = a.get("team", "Away")

    # (label, home_key, lower_is_better, is_pct)
    groups = [
        ("Attacking", [
            ("Shots", "shots", False, False),
            ("On Target", "shots_on_target", False, False),
            ("Big Chances", "big_chances", False, False),
            ("Corners", "corners", False, False),
        ]),
        ("Passing & Control", [
            ("Passes", "passes", False, False),
            ("Pass Accuracy", "pass_accuracy", False, True),
            ("Long Balls", "long_balls", False, False),
            ("Crosses", "crosses", False, False),
        ]),
        ("Defending", [
            ("Tackles", "tackles", False, False),
            ("Interceptions", "interceptions", False, False),
            ("Recoveries", "recoveries", False, False),
            ("Clearances", "clearances", False, False),
            ("Aerials Won", "aerials_won", False, False),
        ]),
        ("Discipline", [
            ("Fouls", "fouls", True, False),
        ]),
    ]

    def _row(label, hkey, lower_better, is_pct):
        hv = h.get(hkey, 0) or 0
        av = a.get(hkey, 0) or 0
        total = hv + av
        # Independent per-row split
        if total == 0:
            hpct = apct = 50
        else:
            hpct = hv / total * 100
            apct = av / total * 100
        hv_disp = f"{hv:.1f}".rstrip("0").rstrip(".") + ("%" if is_pct else "")
        av_disp = f"{av:.1f}".rstrip("0").rstrip(".") + ("%" if is_pct else "")
        # Edge highlight
        if lower_better:
            h_better = hv < av
        else:
            h_better = hv > av
        h_weight = "800" if (h_better and total > 0) else "600"
        a_weight = "800" if (not h_better and total > 0 and hv != av) else "600"

        return html.Div(style={"marginBottom": "10px"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "3px"}, children=[
                html.Span(hv_disp, style={"fontSize": "19px", "fontWeight": h_weight, "color": home_color, "minWidth": "52px"}),
                html.Span(label + (" ▼" if lower_better else ""), style={"fontSize": "12px", "color": TEXT, "fontWeight": "500", "textAlign": "center", "flex": "1"}),
                html.Span(av_disp, style={"fontSize": "19px", "fontWeight": a_weight, "color": away_color, "minWidth": "52px", "textAlign": "right"}),
            ]),
            html.Div(style={"display": "flex", "height": "7px", "borderRadius": "4px", "overflow": "hidden", "background": "rgba(255,255,255,0.05)"}, children=[
                html.Div(style={"width": f"{hpct}%", "background": home_color, "opacity": "0.85"}),
                html.Div(style={"width": f"{apct}%", "background": away_color, "opacity": "0.85"}),
            ]),
        ])

    children = [
        # Header with team names
        html.Div(style={"display": "flex", "justifyContent": "space-between", "marginBottom": "12px", "paddingBottom": "8px", "borderBottom": "1px solid rgba(255,255,255,0.08)"}, children=[
            html.Span(home_name, style={"fontSize": "13px", "fontWeight": "700", "color": home_color}),
            html.Span(away_name, style={"fontSize": "13px", "fontWeight": "700", "color": away_color, "textAlign": "right"}),
        ]),
    ]
    for gname, rows in groups:
        children.append(html.Div(gname.upper(), style={"fontSize": "10px", "fontWeight": "700", "color": MUTED, "letterSpacing": "1px", "margin": "12px 0 8px"}))
        for label, hkey, lb, pct in rows:
            children.append(_row(label, hkey, lb, pct))

    return html.Div(children, style={"padding": "4px 8px"})


# ══════════════════════════════════════════════════════════════════════════
#  MATCH STATS BARS (legacy mirrored horizontal — kept for any other callers)
# ══════════════════════════════════════════════════════════════════════════
def match_stats_bars(stats: dict, home_color=GOLD, away_color=ACCENT_BLUE):
    metrics = [
        ("Shots", "shots"), ("On Target", "shots_on_target"),
        ("Big Chances", "big_chances"),
        ("Passes", "passes"), ("Pass Acc %", "pass_accuracy"),
        ("Long Balls", "long_balls"), ("Crosses", "crosses"),
        ("Tackles", "tackles"), ("Interceptions", "interceptions"),
        ("Recoveries", "recoveries"), ("Clearances", "clearances"),
        ("Corners", "corners"), ("Fouls", "fouls"),
        ("Aerials Won", "aerials_won"),
    ]
    labels = [m[0] for m in metrics]
    hv = [stats["home"].get(m[1], 0) for m in metrics]
    av = [stats["away"].get(m[1], 0) for m in metrics]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=[-v for v in hv], orientation="h",
        name=stats["home"]["team"][:15], marker_color=home_color,
        text=[str(v) for v in hv], textposition="inside",
        textfont=dict(color="#000" if home_color == GOLD else "#fff", size=11, family="Inter"),
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=labels, x=av, orientation="h",
        name=stats["away"]["team"][:15], marker_color=away_color,
        text=[str(v) for v in av], textposition="inside",
        textfont=dict(color="#fff", size=11, family="Inter"),
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    mx = max(max(hv, default=1), max(av, default=1)) * 1.3
    fig = _tmpl(fig, height=520)
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(range=[-mx, mx], showticklabels=False, showgrid=False),
        yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5),
        bargap=0.22,
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  SHOT MAP
# ══════════════════════════════════════════════════════════════════════════
def shot_map(match_data, team_name=None):
    from components.pitch import draw_half_pitch
    fig = draw_half_pitch(side="right")

    shot_types = ["Goal", "Miss", "Post", "Saved Shot"]
    shots = match_data[match_data["event"].isin(shot_types)].copy()
    if team_name:
        shots = shots[shots["team_name"] == team_name]

    cmap = {"Goal": ACCENT_GREEN, "Saved Shot": GOLD, "Miss": ACCENT_RED, "Post": ACCENT_PURPLE}
    smap = {"Goal": "star", "Saved Shot": "circle", "Miss": "x", "Post": "diamond"}
    sizes = {"Goal": 14, "Saved Shot": 10, "Miss": 9, "Post": 10}

    for evt in shot_types:
        edf = shots[shots["event"] == evt]
        if edf.empty:
            continue
        fig.add_trace(go.Scatter(
            x=edf["x"], y=edf["y"], mode="markers",
            marker=dict(size=sizes[evt], color=cmap[evt], symbol=smap[evt],
                        line=dict(width=1, color="#fff")),
            name=evt, text=edf["player_name"],
            hovertemplate="<b>%{text}</b><br>%{fullData.name}<br>Min: %{customdata}'<extra></extra>",
            customdata=edf["time_min"],
        ))
    fig.update_layout(height=420,
                      legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5, font=dict(color=TEXT)))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  PASS MAP
# ══════════════════════════════════════════════════════════════════════════
def pass_map(match_data, team_name):
    from components.pitch import draw_pitch
    fig = draw_pitch()

    passes = match_data[(match_data["event"] == "Pass") & (match_data["team_name"] == team_name)].copy()
    passes, _excluded = filter_valid_pass_events(passes, x_col="x", y_col="y")
    passes = passes.dropna(subset=["Pass End X", "Pass End Y"])

    for outcome, color, name in [(1, "rgba(255,215,0,0.2)", "Successful"),
                                  (0, "rgba(255,69,96,0.3)", "Failed")]:
        sub = passes[passes["outcome"] == outcome]
        for _, p in sub.iterrows():
            fig.add_trace(go.Scatter(
                x=[p["x"], p["Pass End X"]], y=[p["y"], p["Pass End Y"]],
                mode="lines", line=dict(color=color, width=0.8),
                showlegend=False, hoverinfo="skip",
            ))
    fig.update_layout(height=460)
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  HEATMAP (KDE) — FIXED: higher intensity, better colorscale
# ══════════════════════════════════════════════════════════════════════════
def action_heatmap(match_data, team_name=None, event_types=None):
    from components.pitch import draw_pitch
    fig = draw_pitch(line_col="rgba(255,255,255,0.35)")

    df, _excluded = filter_valid_touch_events(match_data, x_col="x", y_col="y")
    df = df.copy()
    if team_name:
        df = df[df["team_name"] == team_name]
    if event_types:
        df = df[df["event"].isin(event_types)]
    if df.empty:
        fig.update_layout(height=460)
        return fig

    # Fewer bins + higher sigma = smoother, more visible heatmap
    n_bins = 32
    xb = np.linspace(0, 100, n_bins + 1)
    yb = np.linspace(0, 100, n_bins + 1)
    H, _, _ = np.histogram2d(df["x"].values, df["y"].values, bins=[xb, yb])
    H = gaussian_filter(H.astype(float), sigma=4.0)

    # Normalize to 0-1 for consistent colorscale
    hmax = H.max()
    if hmax > 0:
        H = H / hmax

    # High-contrast colorscale: transparent at 0, then visible colors
    fig.add_trace(go.Heatmap(
        z=H.T,
        x0=0, dx=100 / n_bins, y0=0, dy=100 / n_bins,
        colorscale=[
            [0.0, "rgba(0,0,0,0)"],
            [0.05, "rgba(0,40,120,0.15)"],
            [0.15, "rgba(0,80,200,0.40)"],
            [0.30, "rgba(0,200,160,0.55)"],
            [0.50, "rgba(255,230,0,0.70)"],
            [0.70, "rgba(255,160,0,0.82)"],
            [0.85, "rgba(255,80,20,0.90)"],
            [1.0, "rgba(255,20,20,0.95)"],
        ],
        showscale=True, zmin=0, zmax=1,
        colorbar=dict(
            title="Intensity", tickfont=dict(color=TEXT, size=9),
            titlefont=dict(color=TEXT, size=10), len=0.5,
            tickvals=[0, 0.25, 0.5, 0.75, 1.0],
            ticktext=["Low", "", "Med", "", "High"],
        ),
        hovertemplate="x=%{x:.0f}, y=%{y:.0f}<br>Intensity: %{z:.2f}<extra></extra>",
    ))
    fig.update_layout(height=460)
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  DEFENSIVE ACTIONS MAP
# ══════════════════════════════════════════════════════════════════════════
def defensive_map(match_data, team_name):
    from components.pitch import draw_pitch
    fig = draw_pitch()

    actions = {
        "Tackle": {"color": ACCENT_GREEN, "symbol": "circle", "size": 9},
        "Interception": {"color": ACCENT_BLUE, "symbol": "diamond", "size": 9},
        "Clearance": {"color": GOLD, "symbol": "triangle-up", "size": 8},
        "Ball recovery": {"color": ACCENT_PURPLE, "symbol": "pentagon", "size": 8},
    }
    for evt, st in actions.items():
        edf = match_data[(match_data["event"] == evt) & (match_data["team_name"] == team_name)]
        edf, _excluded = filter_valid_defensive_events(edf, x_col="x", y_col="y")
        if edf.empty:
            continue
        fig.add_trace(go.Scatter(
            x=edf["x"], y=edf["y"], mode="markers",
            marker=dict(size=st["size"], color=st["color"], symbol=st["symbol"],
                        line=dict(width=0.5, color="#fff"), opacity=0.85),
            name=evt, text=edf["player_name"],
            hovertemplate="<b>%{text}</b><br>%{fullData.name}<br>%{customdata}'<extra></extra>",
            customdata=edf["time_min"],
        ))
    fig.update_layout(height=460,
                      legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5, font=dict(color=TEXT)))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  PASS NETWORK — with connection lines (thickness = pass count)
# ══════════════════════════════════════════════════════════════════════════
def pass_network(match_data, team_name, min_passes=2):
    """
    Draw pass network: nodes = player avg positions, lines = pass connections.
    Line thickness proportional to pass count between players.
    min_passes: minimum passes between two players to show a connection.
    """
    from components.pitch import draw_pitch
    fig = draw_pitch()

    # Get all events for this team, sorted by time
    team_events = match_data[match_data["team_name"] == team_name].copy()
    team_events = team_events.sort_values(["time_min", "time_sec"]).reset_index(drop=True)

    if team_events.empty:
        fig.update_layout(height=460)
        return fig

    # Build player average positions from all touches
    avg_pos = {}
    for _, e in team_events.iterrows():
        pn = e.get("player_name")
        if pd.notna(pn) and pd.notna(e.get("x")) and pd.notna(e.get("y")):
            if pn not in avg_pos:
                avg_pos[pn] = {"xs": [], "ys": [], "cnt": 0}
            avg_pos[pn]["xs"].append(e["x"])
            avg_pos[pn]["ys"].append(e["y"])
            avg_pos[pn]["cnt"] += 1

    # Build pass connections: passer → next team event player = receiver
    connections = {}
    for i in range(len(team_events) - 1):
        e = team_events.iloc[i]
        nxt = team_events.iloc[i + 1]
        if (e["event"] == "Pass" and e.get("outcome") == 1 and
                pd.notna(e.get("player_name")) and pd.notna(nxt.get("player_name"))):
            passer = e["player_name"]
            receiver = nxt["player_name"]
            if passer != receiver:
                pair = (passer, receiver)
                connections[pair] = connections.get(pair, 0) + 1

    # Filter by minimum passes
    connections = {k: v for k, v in connections.items() if v >= min_passes}

    if not connections:
        fig.update_layout(height=460)
        return fig

    # Compute avg positions
    positions = {}
    for pn, data in avg_pos.items():
        if data["cnt"] >= 3:
            positions[pn] = (np.mean(data["xs"]), np.mean(data["ys"]), data["cnt"])

    # Draw connection lines (FIRST — so they appear behind nodes)
    max_passes = max(connections.values()) if connections else 1
    for (passer, receiver), cnt in sorted(connections.items(), key=lambda x: x[1]):
        if passer in positions and receiver in positions:
            px, py, _ = positions[passer]
            rx, ry, _ = positions[receiver]
            # Width: 1 to 6 based on pass count
            width = max(1, cnt / max_passes * 6)
            opacity = min(0.25 + cnt / max_passes * 0.55, 0.8)
            fig.add_trace(go.Scatter(
                x=[px, rx], y=[py, ry], mode="lines",
                line=dict(color=f"rgba(255,215,0,{opacity})", width=width),
                showlegend=False, hoverinfo="skip",
            ))

    # Draw player nodes (on top)
    if positions:
        names = list(positions.keys())
        xs = [positions[n][0] for n in names]
        ys = [positions[n][1] for n in names]
        cnts = [positions[n][2] for n in names]
        max_cnt = max(cnts) if cnts else 1

        # Node sizes proportional to involvement
        sizes = [max(12, c / max_cnt * 30 + 8) for c in cnts]

        # Short names for labels
        labels = [n.split()[-1][:10] for n in names]

        # Total passes for each player (sent + received)
        pass_totals = {}
        for (p, r), cnt in connections.items():
            pass_totals[p] = pass_totals.get(p, 0) + cnt
            pass_totals[r] = pass_totals.get(r, 0) + cnt

        hover_texts = []
        for n in names:
            pt = pass_totals.get(n, 0)
            hover_texts.append(f"<b>{n}</b><br>Touches: {positions[n][2]}<br>Network passes: {pt}")

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            marker=dict(size=sizes, color=GOLD,
                        line=dict(width=2, color="#fff"), opacity=0.95),
            text=labels, textposition="top center",
            textfont=dict(size=9, color="#fff", family="Inter"),
            name="Players",
            hovertext=hover_texts, hoverinfo="text",
        ))

    fig.update_layout(height=460)
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  MATCH TIMELINE
# ══════════════════════════════════════════════════════════════════════════
def match_timeline(match_data):
    key = match_data[match_data["event"].isin(["Goal", "Card", "Player Off", "Player on"])].copy()
    key = key.sort_values("time_min")

    cmap = {"Goal": ACCENT_GREEN, "Card": GOLD, "Player Off": ACCENT_RED, "Player on": ACCENT_BLUE}
    icons = {"Goal": "⚽", "Card": "🟨", "Player Off": "🔴", "Player on": "🟢"}

    fig = go.Figure()
    for _, r in key.iterrows():
        evt = r["event"]
        side = 1 if r.get("team_position") == "home" else -1
        icon = icons.get(evt, "•")
        c = cmap.get(evt, "#fff")
        if evt == "Card" and _FLAGVAL(r.get("Red Card")):
            icon = "🟥"; c = ACCENT_RED
        elif evt == "Card" and _FLAGVAL(r.get("Second yellow")):
            icon = "🟥"; c = ACCENT_RED

        label = f"{icon} {r.get('player_name', '')}"
        fig.add_trace(go.Scatter(
            x=[r["time_min"]], y=[side * 0.5],
            mode="markers+text",
            marker=dict(size=10, color=c),
            text=[label],
            textposition="top center" if side > 0 else "bottom center",
            textfont=dict(size=10, color=TEXT),
            showlegend=False,
            hovertemplate=f"<b>{r.get('player_name','')}</b><br>{evt} {r['time_min']}'<extra></extra>",
        ))

    fig.add_vline(x=45, line_dash="dash", line_color="rgba(255,255,255,0.2)")
    fig.add_annotation(x=45, y=0, text="HT", font=dict(color=MUTED, size=10), showarrow=False)

    fig = _tmpl(fig, height=180)
    fig.update_layout(
        xaxis=dict(title="Minute", range=[0, 100], gridcolor=GRID, dtick=15),
        yaxis=dict(range=[-1.5, 1.5], showticklabels=False, showgrid=False),
        margin=dict(l=20, r=20, t=15, b=35),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  PLAYER RADAR
# ══════════════════════════════════════════════════════════════════════════
def player_radar(pstats: dict, name: str, color=GOLD):
    cats = ["Goals", "Assists", "Shots", "Key Passes", "Pass Acc",
            "Tackles", "Interceptions", "Recoveries", "Aerials", "Dribbles"]
    keys = ["goals", "assists", "shots", "key_passes", "pass_accuracy",
            "tackles", "interceptions", "recoveries", "aerials_won", "take_ons"]
    vals = [pstats.get(k, 0) for k in keys]

    fig = go.Figure()
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig.add_trace(go.Scatterpolar(
        r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
        fillcolor=f"rgba({r},{g},{b},0.2)",
        line=dict(color=color, width=2), name=name,
    ))
    fig.update_layout(
        polar=dict(bgcolor=CARD_BG,
                   radialaxis=dict(visible=True, gridcolor=GRID, tickfont=dict(color=MUTED, size=9)),
                   angularaxis=dict(tickfont=dict(color=TEXT, size=11), gridcolor=GRID)),
        paper_bgcolor=CARD_BG, font=dict(color=TEXT),
        showlegend=True, height=400, margin=dict(l=60, r=60, t=40, b=40),
    )
    return fig


def player_comparison_radar(pstats_a: dict, name_a: str, color_a: str,
                            pstats_b: dict, name_b: str, color_b: str):
    cats = ["Goals", "Assists", "Shots", "Key Passes", "Pass Acc",
            "Tackles", "Interceptions", "Recoveries", "Aerials", "Dribbles"]
    keys = ["goals", "assists", "shots", "key_passes", "pass_accuracy",
            "tackles", "interceptions", "recoveries", "aerials_won", "take_ons"]

    va = [pstats_a.get(k, 0) for k in keys]
    vb = [pstats_b.get(k, 0) for k in keys]

    # Normalise to max
    maxv = [max(a, b, 1) for a, b in zip(va, vb)]
    va_n = [v / m * 100 for v, m in zip(va, maxv)]
    vb_n = [v / m * 100 for v, m in zip(vb, maxv)]

    fig = go.Figure()
    for vals, name, color in [(va_n, name_a, color_a), (vb_n, name_b, color_b)]:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
            fillcolor=f"rgba({r},{g},{b},0.15)",
            line=dict(color=color, width=2), name=name,
        ))
    fig.update_layout(
        polar=dict(bgcolor=CARD_BG,
                   radialaxis=dict(visible=True, gridcolor=GRID,
                                   tickfont=dict(color=MUTED, size=9), range=[0, 110]),
                   angularaxis=dict(tickfont=dict(color=TEXT, size=11), gridcolor=GRID)),
        paper_bgcolor=CARD_BG, font=dict(color=TEXT),
        height=420, margin=dict(l=60, r=60, t=40, b=40),
        legend=dict(orientation="h", y=1.05, xanchor="center", x=0.5),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  POSSESSION ZONES
# ══════════════════════════════════════════════════════════════════════════
def possession_zones(match_data, home_team, away_team):
    zones = {"Def 3rd": (0, 33.3), "Mid 3rd": (33.3, 66.6), "Att 3rd": (66.6, 100)}
    hp = match_data[(match_data["team_name"] == home_team) & (match_data["event"] == "Pass")]
    ap = match_data[(match_data["team_name"] == away_team) & (match_data["event"] == "Pass")]

    labels, hv, av = [], [], []
    for zn, (lo, hi) in zones.items():
        labels.append(zn)
        hv.append(len(hp[(hp["x"] >= lo) & (hp["x"] < hi)]))
        av.append(len(ap[(ap["x"] >= lo) & (ap["x"] < hi)]))

    th = sum(hv) or 1; ta = sum(av) or 1
    hp_pct = [round(v / th * 100, 1) for v in hv]
    ap_pct = [round(v / ta * 100, 1) for v in av]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=hp_pct, name=home_team[:12], marker_color=GOLD,
                         text=[f"{v}%" for v in hp_pct], textposition="auto",
                         textfont=dict(color="#000")))
    fig.add_trace(go.Bar(x=labels, y=ap_pct, name=away_team[:12], marker_color=ACCENT_BLUE,
                         text=[f"{v}%" for v in ap_pct], textposition="auto"))
    return _tmpl(fig, height=320, title="Possession by Zone")


# ══════════════════════════════════════════════════════════════════════════
#  TEAM FORM CHART
# ══════════════════════════════════════════════════════════════════════════
def team_form_chart(match_list_df, team_name, color=GOLD):
    tm = match_list_df[(match_list_df["home_team"] == team_name) |
                       (match_list_df["away_team"] == team_name)].sort_values("week")
    pts, cum = [], 0
    for _, r in tm.iterrows():
        if r["home_team"] == team_name:
            if r["home_goals"] > r["away_goals"]: cum += 3
            elif r["home_goals"] == r["away_goals"]: cum += 1
        else:
            if r["away_goals"] > r["home_goals"]: cum += 3
            elif r["away_goals"] == r["home_goals"]: cum += 1
        pts.append(cum)

    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=tm["week"].tolist(), y=pts, mode="lines+markers",
        line=dict(color=color, width=2.5), marker=dict(size=7, color=color),
        fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.1)",
        hovertemplate="Week %{x}<br>Points: %{y}<extra></extra>",
    ))
    return _tmpl(fig, height=300, title="Points Progression")


# ══════════════════════════════════════════════════════════════════════════
#  xG SHOT QUALITY
# ══════════════════════════════════════════════════════════════════════════
def shot_quality_scatter(match_data, team_name=None):
    shots = match_data[match_data["event"].isin(["Goal", "Miss", "Post", "Saved Shot"])].copy()
    if team_name:
        shots = shots[shots["team_name"] == team_name]
    if shots.empty:
        return _tmpl(go.Figure(), title="Shot Quality")

    # Calibrated xG model (distance + angle)
    shots["dist"] = np.sqrt((100 - shots["x"])**2 + (50 - shots["y"])**2)
    shots["angle"] = np.arctan2(7.32, np.maximum(shots["dist"], 1))
    shots["xG"] = np.exp(-shots["dist"] / 16) * 0.55 * np.minimum(shots["angle"] / 0.30, 1.0)
    shots["xG"] = shots["xG"].clip(0.02, 0.85)
    shots.loc[_flagmask(shots["Head"]), "xG"] *= 0.7
    bc_mask = _flagmask(shots["Big Chance"])
    shots.loc[bc_mask, "xG"] = np.maximum(shots.loc[bc_mask, "xG"] * 1.5, 0.35).clip(upper=0.90)

    cmap = {"Goal": ACCENT_GREEN, "Saved Shot": GOLD, "Miss": ACCENT_RED, "Post": ACCENT_PURPLE}
    fig = go.Figure()
    for evt, color in cmap.items():
        edf = shots[shots["event"] == evt]
        if edf.empty:
            continue
        fig.add_trace(go.Scatter(
            x=edf["time_min"], y=edf["xG"], mode="markers",
            marker=dict(size=edf["xG"] * 25 + 5, color=color, opacity=0.8,
                        line=dict(width=1, color="#fff")),
            name=evt, text=edf["player_name"],
            hovertemplate="<b>%{text}</b><br>Min: %{x}'<br>xG: %{y:.2f}<extra></extra>",
        ))

    fig = _tmpl(fig, height=350, title="Shot Quality Timeline (xG)")
    fig.update_layout(
        xaxis_title="Minute", yaxis_title="xG",
        yaxis=dict(range=[0, 1.05]),
        legend=dict(orientation="h", y=1.05, xanchor="center", x=0.5),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  FORMATION PITCH DIAGRAM — players positioned on a pitch by formation string
# ══════════════════════════════════════════════════════════════════════════
def _parse_formation(formation_str):
    """Turn a formation string like '4231', '433', '352' into a list of band
    sizes from defence → attack, e.g. '4231' → [4, 2, 3, 1]. Supports any valid
    outfield-10 string including 4-3-1-2, 4-2-2-2, 3-4-2-1, etc."""
    s = str(formation_str or "").replace("-", "").replace(".0", "").strip()
    if not s.isdigit() or len(s) < 3:
        return [4, 4, 2]  # sensible default
    bands = [int(c) for c in s]
    if sum(bands) != 10:
        return [4, 4, 2]
    return bands


def infer_formation_from_positions(starters):
    """Infer an approximate formation from the starters' position codes when the
    formation string is unavailable. Returns (formation_str, confidence:bool)."""
    def band_of(pos):
        p = str(pos or "").upper()
        if p == "GK":
            return None
        if p.startswith("D") or p in ("LB", "RB", "CB", "LWB", "RWB"):
            return "def"
        if p.startswith("A") or p in ("LW", "RW", "ST", "CF", "FW", "SS"):
            return "att"
        return "mid"
    counts = {"def": 0, "mid": 0, "att": 0}
    for p in starters:
        b = band_of(p.get("position"))
        if b:
            counts[b] += 1
    total = counts["def"] + counts["mid"] + counts["att"]
    if total != 10:
        return "442", False  # low confidence fallback
    return f"{counts['def']}{counts['mid']}{counts['att']}", True


def formation_pitch_figure(team, formation, starters, color, side="home",
                           coach=None, photos=None):
    """Vertical pitch with the 11 starters placed by formation band.

    `starters` is a list of dicts with name/jersey/position. The pitch is drawn
    vertically (GK at bottom, attack at top) for the home side; away is mirrored
    so the two diagrams can sit side by side facing each other.

    `photos` optionally maps player_id/jersey → local image path. When a photo is
    missing a clean numbered token (silhouette equivalent) is drawn instead, so
    the layout never breaks. `coach` shows on the touchline if provided."""
    import plotly.graph_objects as go

    inferred = False
    if not formation or not str(formation).replace("-", "").replace(".0", "").strip().isdigit():
        formation, conf = infer_formation_from_positions(starters)
        inferred = True
    bands = _parse_formation(formation)
    fig = go.Figure()

    # Pitch background (vertical: width 0-100 on x, length 0-100 on y)
    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=100,
                  fillcolor="#16341f", line=dict(color="rgba(255,255,255,0.35)", width=1.5), layer="below")
    fig.add_shape(type="line", x0=0, y0=50, x1=100, y1=50, line=dict(color="rgba(255,255,255,0.25)", width=1), layer="below")
    fig.add_shape(type="circle", x0=38, y0=40, x1=62, y1=60, line=dict(color="rgba(255,255,255,0.20)", width=1), layer="below")
    fig.add_shape(type="rect", x0=22, y0=0, x1=78, y1=16, line=dict(color="rgba(255,255,255,0.22)", width=1), layer="below")
    fig.add_shape(type="rect", x0=22, y0=84, x1=78, y1=100, line=dict(color="rgba(255,255,255,0.22)", width=1), layer="below")

    # Separate GK from outfield by position code
    gk = [p for p in starters if str(p.get("position", "")).upper() in ("GK",)]
    outfield = [p for p in starters if p not in gk]

    n_bands = len(bands)
    band_ys = [16 + i * (74 / max(n_bands, 1)) for i in range(n_bands)]

    placed = []  # (x, y, player)
    if gk:
        placed.append((50, 7, gk[0]))

    idx = 0
    for bi, count in enumerate(bands):
        y = band_ys[bi]
        band_players = outfield[idx: idx + count]
        idx += count
        if count == 1:
            xs = [50]
        else:
            xs = [12 + j * (76 / (count - 1)) for j in range(count)]
        for x, p in zip(xs, band_players):
            placed.append((x, y, p))

    if side == "away":
        placed = [(x, 100 - y, p) for x, y, p in placed]

    # Plot player tokens (photo if available, else numbered token = silhouette)
    photos = photos or {}
    for x, y, p in placed:
        photo = photos.get(p.get("player_id")) or photos.get(str(p.get("jersey")))
        if photo:
            try:
                fig.add_layout_image(dict(source=photo, x=x, y=y, xref="x", yref="y",
                                          sizex=11, sizey=11, xanchor="center", yanchor="middle", layer="above"))
                fig.add_shape(type="circle", x0=x-5.7, y0=y-5.7, x1=x+5.7, y1=y+5.7,
                              line=dict(color=color, width=2))
            except Exception:
                photo = None
        if not photo:
            fig.add_trace(go.Scatter(
                x=[x], y=[y], mode="markers+text",
                marker=dict(size=26, color=color, line=dict(color="white", width=1.5)),
                text=[str(p.get("jersey", ""))],
                textfont=dict(color="white", size=12, family="Orbitron"),
                textposition="middle center",
                hovertemplate=f"#{p.get('jersey','')} {p.get('name','')}<br>{p.get('position','')}<extra></extra>",
                showlegend=False,
            ))
        surname = str(p.get("name", "")).split()[-1] if p.get("name") else ""
        fig.add_annotation(x=x, y=y - 5, text=surname, showarrow=False,
                           font=dict(color="rgba(245,248,252,0.95)", size=10),
                           bgcolor="rgba(0,0,0,0.45)", borderpad=1)

    # Coach label on the touchline
    if coach:
        cy = 1 if side == "home" else 99
        fig.add_annotation(x=50, y=cy, text=f"Coach: {coach}", showarrow=False,
                           font=dict(color="rgba(230,236,244,0.8)", size=9), bgcolor="rgba(0,0,0,0.4)", borderpad=2)

    # Confidence warning if formation was inferred
    if inferred:
        fig.add_annotation(x=50, y=50, text="⚠ formation inferred from positions",
                           showarrow=False, font=dict(color="#FEB019", size=9),
                           bgcolor="rgba(0,0,0,0.5)", borderpad=2)

    fig.update_layout(
        height=440, margin=dict(l=4, r=4, t=4, b=4),
        xaxis=dict(range=[-2, 102], visible=False, fixedrange=True),
        yaxis=dict(range=[-2, 102], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1.45),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        uirevision="formation",
    )
    return fig
