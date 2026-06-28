"""
components/heatmaps.py — Professional Football Pitch Map System v2
Maps:
  1. Touch Map — dot-based with zone grid overlay
  2. Zone Occupancy — zone-segmented with intensity fill + counts
  3. Pass Origins — density with directional context
  4. Reception Map — where team receives, with zone breakdown
  5. Shot Map — xG-sized markers with clear legend
  6. Defensive Map — action-typed scatter with zone structure
  7. Player Season Heatmap — KDE with proper intensity
  8. action_heatmap — backward-compatible KDE
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.ndimage import gaussian_filter

from components.pitch import draw_pitch, draw_half_pitch
from components.charts import CARD_BG, TEXT, MUTED, GOLD, ACCENT_GREEN, ACCENT_BLUE, ACCENT_RED, ACCENT_PURPLE

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


# ── Zone definitions (6 columns × 3 rows = 18 zones) ─────────────────
# Derived from the central zone model (single source of truth). Local copies
# use the display upper edge (100) for grid drawing; the central model uses an
# inclusive 100.01 top edge for counting so no boundary points are lost.
from components.zone_model import ZONE_GRID_COLS as _ZGC, ZONE_GRID_ROWS as _ZGR
ZONE_COLS = [(lo, min(hi, 100)) for lo, hi in _ZGC]
ZONE_ROWS = [(lo, min(hi, 100)) for lo, hi in _ZGR]
ZONE_NAMES = [
    ["Def L", "Def-Mid L", "Mid L", "Mid-Att L", "Att L", "Box L"],
    ["Def C", "Def-Mid C", "Mid C", "Mid-Att C", "Att C", "Box C"],
    ["Def R", "Def-Mid R", "Mid R", "Mid-Att R", "Att R", "Box R"],
]

# ── Colorscales ───────────────────────────────────────────────────────
CS_HEAT = [
    [0.00, "rgba(10,14,20,0)"], [0.08, "rgba(0,50,140,0.25)"],
    [0.20, "rgba(0,100,210,0.45)"], [0.35, "rgba(0,190,150,0.58)"],
    [0.50, "rgba(200,220,0,0.68)"], [0.65, "rgba(255,180,0,0.78)"],
    [0.80, "rgba(255,100,20,0.88)"], [0.92, "rgba(255,40,20,0.94)"],
    [1.00, "rgba(200,0,0,0.98)"],
]


def _add_zone_grid(fig, line_color="rgba(255,255,255,0.12)", lw=0.8):
    """Add 18-zone grid lines to a pitch figure."""
    for x0, x1 in ZONE_COLS:
        if x0 > 0:
            fig.add_shape(type="line", x0=x0, y0=0, x1=x0, y1=100,
                          line=dict(color=line_color, width=lw, dash="dot"), layer="above")
    for y0, y1 in ZONE_ROWS:
        if y0 > 0:
            fig.add_shape(type="line", x0=0, y0=y0, x1=100, y1=y0,
                          line=dict(color=line_color, width=lw, dash="dot"), layer="above")


def _zone_of(x, y):
    """Return (col_idx, row_idx) for a coordinate, or None."""
    ci = ri = None
    for i, (a, b) in enumerate(ZONE_COLS):
        if a <= x < b or (i == len(ZONE_COLS) - 1 and x == 100):
            ci = i; break
    for j, (a, b) in enumerate(ZONE_ROWS):
        if a <= y < b or (j == len(ZONE_ROWS) - 1 and y == 100):
            ri = j; break
    return (ci, ri) if ci is not None and ri is not None else None


def _zone_grid_figure(counts, title_metric, height, colorscale_pos="green",
                      subtitle_stats=None):
    """
    Shared 18-zone grid renderer. `counts` is a 3x6 matrix [row][col].
    Draws pitch + filled zones with the count inside each + % share.
    """
    from components.pitch import draw_pitch
    fig = draw_pitch(line_col="rgba(255,255,255,0.45)")

    total = sum(sum(r) for r in counts) or 1
    flat = [counts[r][c] for r in range(3) for c in range(6)]
    mx = max(flat) or 1

    base = {"green": (0, 227, 150), "blue": (0, 143, 251), "gold": (255, 180, 0)}.get(colorscale_pos, (0, 227, 150))
    for ci, (x0, x1) in enumerate(ZONE_COLS):
        for ri, (y0, y1) in enumerate(ZONE_ROWS):
            cnt = counts[ri][ci]
            inten = cnt / mx
            r, g, b = base
            fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                          fillcolor=f"rgba({r},{g},{b},{0.06 + inten * 0.62:.3f})",
                          line=dict(color="rgba(255,255,255,0.10)", width=0.6), layer="below")
            if cnt > 0:
                pct = round(cnt / total * 100)
                fig.add_annotation(
                    x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                    text=f"<b>{cnt}</b><br><span style='font-size:11px'>{pct}%</span>",
                    showarrow=False, align="center",
                    bgcolor="rgba(0,0,0,0.40)", borderpad=2,
                    font=dict(color="rgba(245,248,252,0.97)" if inten > 0.25 else "rgba(230,236,244,0.85)", size=15),
                )
    _add_zone_grid(fig, "rgba(255,255,255,0.16)", 1.0)

    # Attack-direction arrow
    fig.add_annotation(x=50, y=104, text="Attacking direction →", showarrow=False,
                       font=dict(color=MUTED, size=9), xref="x", yref="y")
    if subtitle_stats:
        fig.add_annotation(x=50, y=-7, text=subtitle_stats, showarrow=False,
                           font=dict(color=TEXT, size=10), xref="x", yref="y")

    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=40),
                      yaxis=dict(range=[-12, 108]))
    return fig


def defensive_action_zone_grid(match_data, team_name, height=560):
    """18-zone grid of defensive actions (tackle/interception/recovery/clearance/block).
    Readable counts per zone; replaces the old KDE heatmap for H2H."""
    from components.definitions import filter_valid_defensive_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    df, n_excluded = filter_valid_defensive_events(src, x_col="x", y_col="y")

    counts = [[0] * 6 for _ in range(3)]
    for x, y in zip(df["x"].values, df["y"].values):
        z = _zone_of(x, y)
        if z: counts[z[1]][z[0]] += 1

    total = sum(sum(r) for r in counts)
    if total == 0:
        from components.pitch import draw_pitch
        fig = draw_pitch(); fig.update_layout(height=height)
        fig.add_annotation(x=50, y=50, text="No defensive actions in sample",
                           showarrow=False, font=dict(color=MUTED, size=12))
        return fig

    # Tactical stats
    own_half = sum(counts[r][c] for r in range(3) for c in range(3))
    opp_half = total - own_half
    # Average defensive action height (x weighted)
    avg_x = df["x"].mean()
    block = "High press" if avg_x >= 55 else ("Mid block" if avg_x >= 40 else "Low block")
    sub = (f"Own half {round(own_half/total*100)}% · Opp half {round(opp_half/total*100)}% · "
           f"Avg height {avg_x:.0f} · {block} · excluded {n_excluded} invalid rows")
    return _zone_grid_figure(counts, "Defensive actions", height, "blue", sub)


def attacking_zone_grid(match_data, team_name, height=560):
    """18-zone grid of attacking involvement using valid football events only."""
    from components.definitions import filter_valid_touch_events, filter_valid_reception_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    touches, excl_touch = filter_valid_touch_events(src, x_col="x", y_col="y")
    rec, excl_rec = filter_valid_reception_events(src, x_col="Pass End X", y_col="Pass End Y")
    pts = []
    if not touches.empty:
        pts.extend(zip(touches["x"].values, touches["y"].values))
    if not rec.empty:
        pts.extend(zip(rec["Pass End X"].values, rec["Pass End Y"].values))

    counts = [[0] * 6 for _ in range(3)]
    for x, y in pts:
        z = _zone_of(x, y)
        if z: counts[z[1]][z[0]] += 1

    total = sum(sum(r) for r in counts)
    if total == 0:
        from components.pitch import draw_pitch
        fig = draw_pitch(); fig.update_layout(height=height)
        fig.add_annotation(x=50, y=50, text="No attacking actions in sample",
                           showarrow=False, font=dict(color=MUTED, size=12))
        return fig

    att_third = sum(counts[r][c] for r in range(3) for c in range(4, 6))
    left = sum(counts[2][c] for c in range(6))     # row index 2 = right? keep lane mapping consistent
    # Lanes: ZONE_ROWS row0=0-33 (right side y low), row2=66-100. Use share by row.
    row_share = [sum(counts[r]) for r in range(3)]
    rs = sum(row_share) or 1
    sub = (f"Att third {round(att_third/total*100)}% · "
           f"Lanes L/C/R {round(row_share[2]/rs*100)}/{round(row_share[1]/rs*100)}/{round(row_share[0]/rs*100)}% · "
           f"excluded {excl_touch + excl_rec} invalid rows")
    return _zone_grid_figure(counts, "Attacking involvement", height, "green", sub)


def _kde(x, y, n_bins=28, sigma=3.5):
    """Compute normalized KDE."""
    if len(x) == 0:
        return np.zeros((n_bins, n_bins))
    xc = np.clip(x, 0, 100); yc = np.clip(y, 0, 100)
    H, _, _ = np.histogram2d(xc, yc, bins=[np.linspace(0, 100, n_bins+1), np.linspace(0, 100, n_bins+1)])
    H = gaussian_filter(H.astype(float), sigma=sigma)
    if H.max() > 0:
        H = H / H.max()
    return H


def _add_kde_trace(fig, H, colorscale=CS_HEAT, bar_title="Intensity", show_bar=True):
    n = H.shape[0]
    fig.add_trace(go.Heatmap(
        z=H.T, x0=0, dx=100/n, y0=0, dy=100/n,
        colorscale=colorscale, showscale=show_bar, zmin=0, zmax=1,
        colorbar=dict(title=bar_title, tickfont=dict(color=TEXT, size=8),
                      titlefont=dict(color=TEXT, size=9), len=0.4,
                      tickvals=[0, 0.5, 1], ticktext=["Low", "Med", "High"]) if show_bar else None,
        hovertemplate="x=%{x:.0f}, y=%{y:.0f}<br>%{z:.2f}<extra></extra>",
    ))


# ══════════════════════════════════════════════════════════════════════════
#  1. TOUCH MAP — Dot-based with zone grid
# ══════════════════════════════════════════════════════════════════════════
def touch_heatmap(match_data, team_name=None, height=460):
    """Each VALID touch as a dot on pitch with zone grid overlay. Out-of-play,
    admin, and out-of-bounds rows are excluded (not counted as touches)."""
    fig = draw_pitch(line_col="rgba(255,255,255,0.40)")
    _add_zone_grid(fig, "rgba(255,255,255,0.10)")

    from components.definitions import filter_valid_touch_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    n_before = len(src)
    df, n_excluded = filter_valid_touch_events(src)
    if df.empty:
        fig.update_layout(height=height)
        return fig

    # Color by zone (x-based thirds)
    def _zone_color(x):
        if x < 33.3: return "rgba(0,143,251,0.55)"      # Defensive — blue
        elif x < 66.6: return "rgba(255,215,0,0.50)"     # Middle — gold
        else: return "rgba(0,227,150,0.55)"               # Attacking — green

    colors = [_zone_color(x) for x in df["x"].values]

    fig.add_trace(go.Scatter(
        x=df["x"], y=df["y"], mode="markers",
        marker=dict(size=4, color=colors, opacity=0.6,
                    line=dict(width=0)),
        showlegend=False,
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} %{customdata[2]}'<extra></extra>",
        customdata=list(zip(
            df["player_name"].fillna("").values,
            df["event"].values,
            df["time_min"].fillna(0).astype(int).values,
        )),
    ))

    # Zone count annotations — computed from the SAME df that is plotted, using
    # the central 18-zone grid with inclusive upper edges so the displayed counts
    # sum EXACTLY to the number of plotted dots (no boundary loss).
    from components.zone_model import zone_grid_counts, ZONE_GRID_COLS, ZONE_GRID_ROWS
    grid = zone_grid_counts(df, x_col="x", y_col="y")
    plotted = len(df)
    shown = 0
    for (cx, cy), cnt in grid["cells"].items():
        if cnt > 0:
            x0, x1 = ZONE_GRID_COLS[cx]; y0, y1 = ZONE_GRID_ROWS[cy]
            x1 = min(x1, 100); y1 = min(y1, 100)
            shown += cnt
            fig.add_annotation(
                x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=f"<b>{cnt}</b>",
                font=dict(color="rgba(245,248,252,0.95)", size=15, family="Inter"),
                bgcolor="rgba(0,0,0,0.40)", borderpad=2, showarrow=False,
            )
    # Validation footer: counts must equal plotted VALID touches, with the
    # excluded (Out/admin/out-of-bounds) count shown for transparency.
    note = f"{plotted} valid touches plotted · zone counts sum to {shown}"
    if shown == plotted:
        note += " ✓"
    if n_excluded:
        note += f" · {n_excluded} excluded (Out/admin/out-of-bounds)"
    fig.add_annotation(x=50, y=-4, text=note, showarrow=False,
                       font=dict(color=MUTED, size=10), yref="y")

    # Legend
    for label, color in [("Def Third", "rgba(0,143,251,0.7)"), ("Mid Third", "rgba(255,215,0,0.7)"), ("Att Third", "rgba(0,227,150,0.7)")]:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                  marker=dict(size=7, color=color), name=label))

    fig.add_annotation(x=50, y=-4, text=f"Pass origins plotted: {len(df)} · excluded: {n_excluded} invalid/admin/out-of-bounds rows",
                       showarrow=False, font=dict(color=MUTED, size=9))
    fig.update_layout(height=height, legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center", font=dict(size=11, color=TEXT)), yaxis=dict(range=[-8, 105]))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  2. ZONE OCCUPANCY — Zone-segmented with tactical context
# ══════════════════════════════════════════════════════════════════════════
def zone_occupancy_heatmap(match_data, team_name=None, height=480):
    """Zone occupancy with intensity fill, counts, labels, and third-split summary."""
    fig = draw_pitch(line_col="rgba(255,255,255,0.40)")

    from components.definitions import filter_valid_touch_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    df, n_excluded = filter_valid_touch_events(src)
    if df.empty:
        fig.add_annotation(x=50, y=50, text="No valid touch events after filtering",
                           showarrow=False, font=dict(color=MUTED, size=12))
        fig.update_layout(height=height)
        return fig

    weights = df["event"].map({
        "Pass": 2.0, "Ball touch": 2.0, "Ball recovery": 1.0,
        "Take On": 1.5, "Tackle": 0.5, "Interception": 0.5,
    }).fillna(0.3)

    total_weight = weights.sum()
    zone_vals = []
    max_val = 1
    for ci, (x0, x1) in enumerate(ZONE_COLS):
        for ri, (y0, y1) in enumerate(ZONE_ROWS):
            mask = (df["x"] >= x0) & (df["x"] < x1) & (df["y"] >= y0) & (df["y"] < y1)
            val = weights[mask].sum()
            raw = mask.sum()
            zone_vals.append((x0, y0, x1, y1, val, raw, ci, ri))
            max_val = max(max_val, val)

    # Draw zones
    for x0, y0, x1, y1, val, raw, ci, ri in zone_vals:
        intensity = val / max_val
        if intensity < 0.2:
            c = f"rgba(0,60,140,{max(intensity * 2, 0.02)})"
        elif intensity < 0.4:
            c = f"rgba(0,150,200,{0.15 + intensity * 0.5})"
        elif intensity < 0.6:
            c = f"rgba(200,200,0,{0.25 + intensity * 0.4})"
        elif intensity < 0.8:
            c = f"rgba(255,150,0,{0.35 + intensity * 0.3})"
        else:
            c = f"rgba(255,50,20,{0.45 + intensity * 0.3})"

        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=c, line=dict(color="rgba(255,255,255,0.10)", width=0.6), layer="below")

        pct = round(val / total_weight * 100) if total_weight > 0 else 0
        label = ZONE_NAMES[ri][ci]
        if pct >= 1:
            fig.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2,
                               text=f"<b>{pct}%</b><br><span style='font-size:7px'>{label}</span>",
                               font=dict(color="rgba(255,255,255,0.55)" if intensity > 0.12 else "rgba(255,255,255,0.2)",
                                         size=9, family="Inter"),
                               showarrow=False, align="center")

    _add_zone_grid(fig, "rgba(255,255,255,0.15)", 1.0)

    # Third splits summary
    def_w = sum(v[4] for v in zone_vals if v[6] < 2)
    mid_w = sum(v[4] for v in zone_vals if 2 <= v[6] < 4)
    att_w = sum(v[4] for v in zone_vals if v[6] >= 4)
    tw = max(def_w + mid_w + att_w, 1)
    # Left / Center / Right
    left_w = sum(v[4] for v in zone_vals if v[7] == 2)
    cent_w = sum(v[4] for v in zone_vals if v[7] == 1)
    right_w = sum(v[4] for v in zone_vals if v[7] == 0)
    lw = max(left_w + cent_w + right_w, 1)

    fig.add_annotation(x=50, y=-6,
                       text=(f"Thirds → Def: {round(def_w/tw*100)}%  Mid: {round(mid_w/tw*100)}%  Att: {round(att_w/tw*100)}%"
                             f"   |   Lanes → L: {round(left_w/lw*100)}%  C: {round(cent_w/lw*100)}%  R: {round(right_w/lw*100)}%"),
                       font=dict(color=MUTED, size=8), showarrow=False)

    # Top 3 zones
    sorted_zones = sorted(zone_vals, key=lambda z: -z[4])[:3]
    top_names = [ZONE_NAMES[z[7]][z[6]] for z in sorted_zones]
    fig.add_annotation(x=50, y=-10,
                       text=f"Top zones: {', '.join(top_names)}",
                       font=dict(color="rgba(255,215,0,0.5)", size=8), showarrow=False)
    fig.add_annotation(x=50, y=-13,
                       text=f"Valid occupancy events: {len(df)} · excluded: {n_excluded} out/admin/out-of-bounds rows",
                       font=dict(color=MUTED, size=8), showarrow=False)

    fig.update_layout(height=height, yaxis=dict(range=[-16, 105]))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  3. PASS ORIGINS — Where passes start, with success overlay
# ══════════════════════════════════════════════════════════════════════════
def pass_origin_heatmap(match_data, team_name=None, height=460):
    """Pass origin map with success/fail distinction and zone grid."""
    fig = draw_pitch(line_col="rgba(255,255,255,0.40)")
    _add_zone_grid(fig, "rgba(255,255,255,0.08)")

    from components.definitions import filter_valid_pass_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    df, n_excluded = filter_valid_pass_events(src, x_col="x", y_col="y")
    if df.empty:
        fig.add_annotation(x=50, y=50, text="No valid pass-origin events after filtering",
                           showarrow=False, font=dict(color=MUTED, size=12))
        fig.update_layout(height=height)
        return fig

    # Successful passes
    succ = df[df["outcome"] == 1]
    fail = df[df["outcome"] == 0]

    # Successful = green, Failed = red (legend matches plotted colors)
    fig.add_trace(go.Scatter(
        x=succ["x"], y=succ["y"], mode="markers", name=f"Successful ({len(succ)})",
        marker=dict(size=5, color="rgba(0,208,132,0.75)", symbol="circle", line=dict(width=0)),
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}'<extra>✓ Successful</extra>",
        customdata=list(zip(succ["player_name"].fillna("").values, succ["time_min"].fillna(0).astype(int).values)),
    ))
    fig.add_trace(go.Scatter(
        x=fail["x"], y=fail["y"], mode="markers", name=f"Failed ({len(fail)})",
        marker=dict(size=5, color="rgba(255,77,109,0.8)", symbol="x", line=dict(width=0)),
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}'<extra>✗ Failed</extra>",
        customdata=list(zip(fail["player_name"].fillna("").values, fail["time_min"].fillna(0).astype(int).values)),
    ))

    # Pass accuracy by zone — readable label (>=15px, near-white, shadow)
    for ci, (x0, x1) in enumerate(ZONE_COLS):
        for ri, (y0, y1) in enumerate(ZONE_ROWS):
            zone_p = df[(df["x"]>=x0)&(df["x"]<x1)&(df["y"]>=y0)&(df["y"]<y1)]
            if len(zone_p) >= 5:
                acc = round(zone_p["outcome"].mean() * 100)
                fig.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=f"<b>{acc}%</b>",
                                   font=dict(color="rgba(245,248,252,0.95)", size=15, family="Inter"),
                                   bgcolor="rgba(0,0,0,0.45)", borderpad=2, showarrow=False)

    fig.update_layout(height=height, legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center", font=dict(size=11, color=TEXT)))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  4. RECEPTION MAP — Zone-structured with lane/third analysis
# ══════════════════════════════════════════════════════════════════════════
def reception_heatmap(match_data, team_name=None, height=480):
    """Where the team receives passes — zone-segmented with tactical labels."""
    fig = draw_pitch(line_col="rgba(255,255,255,0.40)")

    from components.definitions import filter_valid_reception_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    df, n_excluded = filter_valid_reception_events(src, x_col="Pass End X", y_col="Pass End Y")
    if df.empty:
        fig.add_annotation(x=50, y=50, text="No valid completed pass receptions after filtering",
                           showarrow=False, font=dict(color=MUTED, size=12))
        fig.update_layout(height=height)
        return fig

    total = len(df)

    # Define 5 attacking lanes (y-based) × 3 thirds (x-based) — from the central
    # zone model (single source of truth, consistent L/R convention).
    from components.zone_model import LANES as _ZL
    lanes = [(name.replace("Wide Left", "Wide L").replace("Wide Right", "Wide R")
                  .replace("Left Half-Space", "Half-Space L").replace("Right Half-Space", "Half-Space R"),
              lo, hi) for name, lo, hi in reversed(_ZL)]
    thirds = [("Def 3rd", 0, 33.33), ("Mid 3rd", 33.33, 66.67), ("Att 3rd", 66.67, 100)]

    # Compute zone intensities and draw filled rectangles
    zone_data = []
    max_cnt = 1
    for tname, tx0, tx1 in thirds:
        for lname, ly0, ly1 in lanes:
            mask = ((df["Pass End X"] >= tx0) & (df["Pass End X"] < tx1) &
                    (df["Pass End Y"] >= ly0) & (df["Pass End Y"] < ly1))
            cnt = mask.sum()
            zone_data.append((tx0, ly0, tx1, ly1, cnt, tname, lname))
            max_cnt = max(max_cnt, cnt)

    for tx0, ly0, tx1, ly1, cnt, tname, lname in zone_data:
        intensity = cnt / max_cnt
        if intensity < 0.15:
            c = f"rgba(0,60,140,{max(intensity * 1.5, 0.02)})"
        elif intensity < 0.35:
            c = f"rgba(0,150,220,{0.12 + intensity * 0.6})"
        elif intensity < 0.55:
            c = f"rgba(180,210,0,{0.20 + intensity * 0.4})"
        elif intensity < 0.75:
            c = f"rgba(255,160,0,{0.30 + intensity * 0.35})"
        else:
            c = f"rgba(255,50,20,{0.40 + intensity * 0.3})"

        fig.add_shape(type="rect", x0=tx0, y0=ly0, x1=tx1, y1=ly1,
                      fillcolor=c, line=dict(color="rgba(255,255,255,0.10)", width=0.6), layer="below")

        # Zone count + percentage
        pct = round(cnt / total * 100) if total > 0 else 0
        if cnt > 0:
            fig.add_annotation(x=(tx0+tx1)/2, y=(ly0+ly1)/2,
                               text=f"<b>{cnt}</b><br><span style='font-size:11px'>{pct}%</span>",
                               font=dict(color="rgba(245,248,252,0.95)" if intensity > 0.1 else "rgba(230,236,244,0.82)",
                                         size=15, family="Inter"),
                               bgcolor="rgba(0,0,0,0.40)", borderpad=2,
                               showarrow=False, align="center")

    # Lane labels on right edge
    for lname, ly0, ly1 in lanes:
        fig.add_annotation(x=102, y=(ly0+ly1)/2, text=lname, font=dict(color=TEXT, size=10), showarrow=False, xanchor="left")

    # Third labels on top
    for tname, tx0, tx1 in thirds:
        fig.add_annotation(x=(tx0+tx1)/2, y=103, text=tname, font=dict(color=TEXT, size=11), showarrow=False)

    # Summary stats
    ft = len(df[df["Pass End X"] >= 66.6])
    central = len(df[(df["Pass End Y"] >= 33.3) & (df["Pass End Y"] < 66.6)])
    wide = total - central
    fig.add_annotation(x=50, y=-6,
                       text=f"Total receptions plotted: {total}  |  Att 3rd: {ft} ({round(ft/total*100)}%)  |  Central: {round(central/total*100)}%  |  Wide: {round(wide/total*100)}%  |  Excluded: {n_excluded}",
                       font=dict(color=TEXT, size=10), showarrow=False)

    # Zone grid
    _add_zone_grid(fig, "rgba(255,255,255,0.08)")

    fig.update_layout(height=height, xaxis=dict(range=[-5, 108]), yaxis=dict(range=[-10, 108]))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  5. SHOT ZONE PROFILE — aggregate spatial shooting pattern (NOT event-level)
# ══════════════════════════════════════════════════════════════════════════
def shot_heatmap(match_data, team_name=None, height=460):
    """
    Zone-based shot profile — shows WHERE shots come from with zone counts,
    conversion rates, and xG totals. Distinct from the event-level shot map.
    """
    from components.report_engine import _xg_from_distance

    fig = draw_half_pitch(side="right")

    from components.definitions import filter_valid_shot_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    shots, n_excluded = filter_valid_shot_events(src, x_col="x", y_col="y")
    if shots.empty:
        fig.add_annotation(x=82, y=50, text="No valid shots after filtering",
                           showarrow=False, font=dict(color=MUTED, size=12))
        fig.update_layout(height=height)
        return fig

    # Compute xG
    xg_list = []
    for _, s in shots.iterrows():
        xg_list.append(_xg_from_distance(s["x"], s["y"],
                        _FLAGVAL(s.get("Head")) if "Head" in s.index else False,
                        _FLAGVAL(s.get("Big Chance")) if "Big Chance" in s.index else False))
    shots = shots.copy()
    shots["xg"] = xg_list

    # Define shot zones (relative to goal at x=100)
    shot_zones = [
        ("6-yard box", 94.5, 100, 36.8, 63.2),
        ("Penalty area C", 83.5, 94.5, 30, 70),
        ("Penalty area L", 83.5, 94.5, 70, 80),
        ("Penalty area R", 83.5, 94.5, 20, 30),
        ("Edge of box", 75, 83.5, 21, 79),
        ("Outside box", 60, 75, 15, 85),
        ("Long range", 50, 60, 10, 90),
    ]

    total_shots = len(shots)
    total_goals = len(shots[shots["event"] == "Goal"])
    total_xg = shots["xg"].sum()

    for zname, x0, x1, y0, y1 in shot_zones:
        zdf = shots[(shots["x"] >= x0) & (shots["x"] < x1) & (shots["y"] >= y0) & (shots["y"] < y1)]
        cnt = len(zdf)
        goals = len(zdf[zdf["event"] == "Goal"])
        xg_sum = zdf["xg"].sum()

        if cnt == 0:
            continue

        # Intensity by shot count
        intensity = min(cnt / max(total_shots * 0.4, 1), 1.0)
        if goals > 0:
            c = f"rgba(0,227,150,{0.20 + intensity * 0.5})"
        elif cnt >= 3:
            c = f"rgba(255,180,0,{0.15 + intensity * 0.4})"
        else:
            c = f"rgba(0,143,251,{0.10 + intensity * 0.3})"

        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=c, line=dict(color="rgba(255,255,255,0.15)", width=0.8), layer="below")

        # Annotation: compact for small zones, detailed for large zones
        zone_width = x1 - x0
        zone_height = y1 - y0
        conv = round(goals / cnt * 100) if cnt > 0 else 0

        if zone_width < 12 or zone_height < 15:
            # Small zone — compact label, detail in hover
            label = f"<b>{cnt}</b>"
            fig.add_trace(go.Scatter(
                x=[(x0+x1)/2], y=[(y0+y1)/2], mode="markers",
                marker=dict(size=1, color="rgba(0,0,0,0)"), showlegend=False,
                hovertemplate=f"<b>{zname}</b><br>{cnt} shots · {goals}G<br>{xg_sum:.1f} xG · {conv}% conv<extra></extra>",
            ))
        else:
            label = f"<b>{cnt}</b> · {goals}G · {xg_sum:.1f}xG"

        fig.add_annotation(
            x=(x0+x1)/2, y=(y0+y1)/2, text=label,
            font=dict(color="rgba(245,248,252,0.95)" if cnt >= 2 else "rgba(230,236,244,0.8)",
                      size=13, family="Inter"),
            bgcolor="rgba(0,0,0,0.4)", borderpad=2,
            showarrow=False, align="center",
        )

    # Summary
    conv_rate = round(total_goals / max(total_shots, 1) * 100)
    fig.add_annotation(x=75, y=-6,
                       text=f"Total: {total_shots} valid shots · {total_goals} goals · {total_xg:.1f} estimated xG · {conv_rate}% conversion · excluded: {n_excluded}",
                       font=dict(color=TEXT, size=9), showarrow=False)

    fig.update_layout(height=height, yaxis=dict(range=[-10, 105]))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  6. DEFENSIVE MAP — Action-typed scatter with zone structure
# ══════════════════════════════════════════════════════════════════════════
def defensive_heatmap(match_data, team_name=None, height=460):
    """Defensive actions by type with zone grid overlay."""
    fig = draw_pitch(line_col="rgba(255,255,255,0.40)")
    _add_zone_grid(fig, "rgba(255,255,255,0.08)")

    actions = {
        "Tackle":        {"color": ACCENT_GREEN, "symbol": "circle",       "size": 8},
        "Interception":  {"color": ACCENT_BLUE,  "symbol": "diamond",      "size": 8},
        "Ball recovery": {"color": GOLD,         "symbol": "triangle-up",  "size": 7},
        "Clearance":     {"color": ACCENT_PURPLE, "symbol": "square",      "size": 6},
    }

    from components.definitions import filter_valid_defensive_events
    src = match_data[match_data["team_name"] == team_name] if team_name else match_data
    df, n_excluded = filter_valid_defensive_events(src, x_col="x", y_col="y")

    total = 0
    for evt, style in actions.items():
        edf = df[df["event"] == evt]
        if edf.empty:
            continue
        total += len(edf)

        # Won vs lost
        won = edf[edf["outcome"] == 1]
        lost = edf[edf["outcome"] == 0]

        if not won.empty:
            fig.add_trace(go.Scatter(
                x=won["x"], y=won["y"], mode="markers",
                marker=dict(size=style["size"], color=style["color"], symbol=style["symbol"],
                            line=dict(width=0.8, color="#fff"), opacity=0.8),
                name=f"{evt} Won ({len(won)})",
                customdata=list(zip(won["player_name"].fillna("").values, won["time_min"].fillna(0).astype(int).values)),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}'<extra>%{fullData.name}</extra>",
            ))
        if not lost.empty:
            fig.add_trace(go.Scatter(
                x=lost["x"], y=lost["y"], mode="markers",
                marker=dict(size=style["size"] - 1, color=style["color"], symbol=style["symbol"],
                            line=dict(width=0.8, color=style["color"]), opacity=0.3),
                name=f"{evt} Lost ({len(lost)})",
                customdata=list(zip(lost["player_name"].fillna("").values, lost["time_min"].fillna(0).astype(int).values)),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}'<extra>%{fullData.name}</extra>",
            ))

    # Defensive line annotation
    def_events = df[df["event"].isin(["Tackle", "Interception", "Ball recovery"])]
    if not def_events.empty:
        avg_x = def_events["x"].mean()
        fig.add_vline(x=avg_x, line_dash="dash", line_color="rgba(255,69,96,0.4)", line_width=1.5)
        fig.add_annotation(x=avg_x, y=102, text=f"Avg Def Line: {avg_x:.0f}",
                           font=dict(color=ACCENT_RED, size=9), showarrow=False)

    fig.add_annotation(x=50, y=-4, text=f"Defensive actions plotted: {total} · excluded: {n_excluded} invalid/admin/out-of-bounds rows",
                       showarrow=False, font=dict(color=MUTED, size=9))
    fig.update_layout(height=height,
                      legend=dict(orientation="h", y=1.06, x=0.5, xanchor="center", font=dict(size=8, color=TEXT),
                                  itemsizing="constant"), yaxis=dict(range=[-8, 105]))
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  7. PLAYER SEASON HEATMAP — KDE with proper intensity
# ══════════════════════════════════════════════════════════════════════════
def player_season_heatmap(df, player_id, height=760):
    """ACTIVE Player Hub heatmap — now a true smooth Gaussian render with
    open-play coordinate cleaning (no more 28-bin blocks, no ghost hotspots)."""
    return smooth_gaussian_pitch_heatmap(
        df, player_id=player_id, title="Player Activity Heatmap",
        open_play_only=True, include_set_pieces=False,
        height=height, grid_x=180, grid_y=140, sigma=6.0,
    )


# ══════════════════════════════════════════════════════════════════════════
#  CLEAN COORDINATES + SMOOTH GAUSSIAN HEATMAP  (replaces the 28-bin renderer)
# ══════════════════════════════════════════════════════════════════════════
# Event names / qualifier columns that mark a non-open-play restart.
_SET_PIECE_EVENTS = {"Corner Awarded", "Goal Kick", "Throw-in", "Foul throw-in"}
_SET_PIECE_FLAGS = ["Set piece", "From corner", "Corner taken", "Free kick taken",
                    "Throw-in", "Goal Kick", "Penalty", "Direct free kick"]


def clean_heatmap_events(df, x_col="x", y_col="y", open_play_only=True,
                         include_set_pieces=False, allow_boundary_actions=False,
                         pitch_length=100, pitch_width=100):
    """Clean event data before heatmap rendering. Returns (clean_df, qa).

    Removes (in order): missing xy, out-of-bounds, administrative/non-spatial
    events (Card, Player Off/on, Start/End delay, Deleted event, Formation
    change, ...), (0,0) artifacts, and set-pieces when open_play_only."""
    from components.definitions import VALID_SPATIAL_EVENTS, NON_SPATIAL_EVENTS

    qa = {"before": len(df) if df is not None else 0, "after": 0,
          "excluded_missing_xy": 0, "excluded_out_of_bounds": 0,
          "excluded_admin_events": 0, "excluded_zero_zero": 0,
          "excluded_set_pieces": 0, "open_play_only": open_play_only}
    if df is None or df.empty:
        return (df.iloc[0:0] if df is not None else df), qa

    work = df.copy()
    work[x_col] = pd.to_numeric(work[x_col], errors="coerce")
    work[y_col] = pd.to_numeric(work[y_col], errors="coerce")

    before_xy = len(work)
    work = work.dropna(subset=[x_col, y_col])
    qa["excluded_missing_xy"] = before_xy - len(work)

    # Out-of-bounds
    inb = work[x_col].between(0, pitch_length) & work[y_col].between(0, pitch_width)
    qa["excluded_out_of_bounds"] = int((~inb).sum())
    work = work[inb]

    # Administrative / non-spatial events (the real ghost-hotspot cause)
    if "event" in work.columns:
        evs = work["event"].astype(str)
        admin_mask = evs.isin(NON_SPATIAL_EVENTS) | ~evs.isin(VALID_SPATIAL_EVENTS)
        qa["excluded_admin_events"] = int(admin_mask.sum())
        work = work[~admin_mask]

    # (0,0) artifacts — any remaining exact-origin rows are data artifacts
    if not allow_boundary_actions:
        zz = (work[x_col] == 0) & (work[y_col] == 0)
        qa["excluded_zero_zero"] = int(zz.sum())
        work = work[~zz]

    # Set-piece / restart exclusion (open-play heatmaps)
    if open_play_only and not include_set_pieces:
        mask_sp = pd.Series(False, index=work.index)
        if "event" in work.columns:
            mask_sp |= work["event"].astype(str).isin(_SET_PIECE_EVENTS)
        for col in _SET_PIECE_FLAGS:
            if col in work.columns:
                mask_sp |= work[col].apply(_FLAGVAL)
        qa["excluded_set_pieces"] = int(mask_sp.sum())
        work = work[~mask_sp]

    qa["after"] = len(work)
    return work, qa


def smooth_gaussian_pitch_heatmap(df, team=None, player_id=None, event_types=None,
                                  x_col="x", y_col="y", title="Activity Heatmap",
                                  open_play_only=True, include_set_pieces=False,
                                  pitch_length=100, pitch_width=100,
                                  grid_x=210, grid_y=136, sigma=5.0,
                                  height=820, show_points=False, showscale=True):
    """True smooth football heatmap with CORRECT layering:
       1) green pitch background (below)  2) Gaussian density (middle)
       3) pitch lines (above)  4) caveat. Football aspect ratio, not a square."""
    from components.pitch import draw_pitch_background_only, draw_pitch_lines_only

    # Build figure in the right order — background FIRST (stays below heat)
    fig = go.Figure()
    draw_pitch_background_only(fig)

    work = df
    if player_id is not None and "player_id" in work.columns:
        work = work[work["player_id"] == player_id]
    if team is not None and "team_name" in work.columns:
        work = work[work["team_name"] == team]
    if event_types and "event" in work.columns:
        work = work[work["event"].isin(event_types)]

    clean, qa = clean_heatmap_events(
        work,
        x_col=x_col,
        y_col=y_col,
        open_play_only=open_play_only,
        include_set_pieces=include_set_pieces,
        allow_boundary_actions=False,
        pitch_length=100,
        pitch_width=100,
    )

    if clean is None or clean.empty:
        draw_pitch_lines_only(fig, height=height)
        fig.add_annotation(x=50, y=50, text="No open-play events in sample",
                           showarrow=False, font=dict(color=MUTED, size=13))
        return fig

    x = clean[x_col].values.astype(float)
    y = clean[y_col].values.astype(float)
    n_valid = len(x)

    # Small-sample guard: a handful of events normalised to [0,1] makes tiny
    # clusters look like dominant hotspots. Below 25 valid events, fall back to
    # an 18-zone activity grid (honest counts) instead of a smooth density.
    if n_valid < 25:
        draw_pitch_background_only(fig)
        zx = [0, 100/6, 200/6, 300/6, 400/6, 500/6, 100]
        zy = [0, 100/3, 200/3, 100]
        for ci in range(6):
            for ri in range(3):
                x0, x1 = zx[ci], zx[ci+1]; y0, y1 = zy[ri], zy[ri+1]
                cnt = int(((x >= x0) & (x < x1) & (y >= y0) & (y < y1)).sum())
                inten = cnt / max(n_valid, 1)
                fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                              fillcolor=f"rgba(0,227,150,{min(0.10 + inten*0.5, 0.6):.2f})",
                              line=dict(color="rgba(255,255,255,0.10)", width=0.6), layer="below")
                if cnt > 0:
                    fig.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=f"<b>{cnt}</b>",
                                       font=dict(color="rgba(245,248,252,0.95)", size=15),
                                       bgcolor="rgba(0,0,0,0.4)", borderpad=2, showarrow=False)
        draw_pitch_lines_only(fig, line_col="rgba(255,255,255,0.55)", height=height)
        fig.add_annotation(x=50, y=-5, showarrow=False, font=dict(color="#FEB019", size=11),
                           text=f"⚠ Small sample ({n_valid} open-play events) — showing 18-zone activity grid, not a density map.")
        fig.add_annotation(x=50, y=104, text="Attacking direction →", showarrow=False,
                           font=dict(color=MUTED, size=10))
        fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=40),
                          xaxis=dict(range=[-5, 108], visible=False),
                          yaxis=dict(range=[-12, 110], visible=False),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        return fig

    # High-resolution density grid (NOT 28 bins) on the 0–100 coordinate box
    xedges = np.linspace(0, 100, grid_x + 1)
    yedges = np.linspace(0, 100, grid_y + 1)
    H, _, _ = np.histogram2d(x, y, bins=[xedges, yedges])
    H = gaussian_filter(H.astype(float), sigma=sigma)
    # Density cap: clip the top 2% of cells before normalising so a single dense
    # spot doesn't wash out the rest of the map (exaggerated-hotspot fix).
    if H.max() > 0:
        cap = np.percentile(H[H > 0], 98)
        if cap > 0:
            H = np.clip(H, 0, cap)
        H = H / H.max()
    xc = (xedges[:-1] + xedges[1:]) / 2
    yc = (yedges[:-1] + yedges[1:]) / 2

    # Heatmap density — added AFTER background, BEFORE lines → visible
    fig.add_trace(go.Heatmap(
        z=H.T, x=xc, y=yc, colorscale=CS_HEAT, zsmooth="best",
        zmin=0, zmax=1, opacity=0.85, showscale=showscale,
        colorbar=dict(title=dict(text="Activity", font=dict(color=TEXT, size=11)),
                      tickfont=dict(color=TEXT, size=10), len=0.55, thickness=14,
                      tickvals=[0, 0.5, 1], ticktext=["Low", "Med", "High"]) if showscale else None,
        hovertemplate="x=%{x:.0f}, y=%{y:.0f}<br>intensity=%{z:.2f}<extra></extra>",
    ))

    if show_points:
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="markers",
            marker=dict(size=4, color="rgba(255,255,255,0.35)", line=dict(width=0)),
            hoverinfo="skip", showlegend=False))

    # Pitch lines LAST → above the density (football aspect ratio applied here)
    draw_pitch_lines_only(fig, line_col="rgba(255,255,255,0.55)", height=height)

    # QA caveat — shows the admin/(0,0) events that were correctly excluded
    excluded = qa["before"] - qa["after"]
    cav = (f"Open-play heatmap: {qa['after']:,} valid events used; "
           f"{excluded:,} administrative/zero-coordinate/set-piece events excluded.")
    fig.add_annotation(x=50, y=-5, text=cav, showarrow=False,
                       font=dict(color=MUTED, size=10), xref="x", yref="y")
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  8. action_heatmap — now delegates to the smooth renderer (no 28-bin path)
# ══════════════════════════════════════════════════════════════════════════
def action_heatmap(match_data, team_name=None, event_types=None, height=760):
    """Backward-compatible signature, now backed by smooth_gaussian_pitch_heatmap."""
    return smooth_gaussian_pitch_heatmap(
        match_data, team=team_name, event_types=event_types,
        title="Activity Heatmap", open_play_only=True,
        height=height, grid_x=180, grid_y=140, sigma=6.0,
    )


def _legacy_action_heatmap(match_data, team_name=None, event_types=None, height=460):
    fig = draw_pitch(line_col="rgba(255,255,255,0.35)")
    df = match_data.dropna(subset=["x", "y"]).copy()
    if team_name:
        df = df[df["team_name"] == team_name]
    if event_types:
        df = df[df["event"].isin(event_types)]
    if df.empty:
        fig.update_layout(height=height)
        return fig
    H = _kde(df["x"].values, df["y"].values)
    _add_kde_trace(fig, H, CS_HEAT)
    fig.update_layout(height=height)
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  PITCH-THIRD FILTERING (used by Touch Map filters)
# ══════════════════════════════════════════════════════════════════════════
def filter_events_by_pitch_third(df, selected_thirds, x_col="x"):
    """Filter events to the selected pitch third(s).

    For a 0-100 left-to-right pitch (selected team attacking towards x=100):
      defensive third : x < 33.33
      middle third    : 33.33 <= x < 66.67
      attacking third : x >= 66.67

    `selected_thirds` is a list drawn from {"def", "mid", "att"}. Empty list or
    None means no filtering (all thirds)."""
    if not selected_thirds or set(selected_thirds) >= {"def", "mid", "att"}:
        return df
    if df.empty or x_col not in df.columns:
        return df
    x = pd.to_numeric(df[x_col], errors="coerce")
    mask = pd.Series(False, index=df.index)
    if "def" in selected_thirds:
        mask |= (x < 33.33)
    if "mid" in selected_thirds:
        mask |= ((x >= 33.33) & (x < 66.67))
    if "att" in selected_thirds:
        mask |= (x >= 66.67)
    return df[mask]


# ══════════════════════════════════════════════════════════════════════════
#  PASS-TYPE FILTERING (for Pass Origins / Reception maps)
# ══════════════════════════════════════════════════════════════════════════
def filter_passes_by_type(df, pass_type):
    """Filter PASS events to a tactical sub-type. Non-pass events pass through
    unchanged so this is safe to apply to a mixed event frame. pass_type ∈
    {all, short, long, progressive, final_third, box_entry, cross, switch,
     through, key, failed, successful}."""
    if not pass_type or pass_type == "all":
        return df
    if df.empty:
        return df
    import numpy as np
    passes = df[df["event"] == "Pass"].copy()
    if passes.empty:
        return passes
    sx = pd.to_numeric(passes.get("x"), errors="coerce")
    ex = pd.to_numeric(passes.get("Pass End X"), errors="coerce")
    sy = pd.to_numeric(passes.get("y"), errors="coerce")
    ey = pd.to_numeric(passes.get("Pass End Y"), errors="coerce")
    lng = pd.to_numeric(passes.get("Length"), errors="coerce") if "Length" in passes.columns else pd.Series(np.nan, index=passes.index)
    out = passes["outcome"] if "outcome" in passes.columns else pd.Series(1, index=passes.index)

    if pass_type == "short":
        mask = lng < 15
    elif pass_type == "long":
        mask = lng > 30
    elif pass_type == "progressive":
        mask = (ex - sx) > 10
    elif pass_type == "final_third":
        mask = ex >= 66.6
    elif pass_type == "box_entry":
        mask = (ex >= 83) & (ey >= 21) & (ey <= 79) & (sx < 83)
    elif pass_type == "cross":
        mask = ((sy < 21) | (sy > 79)) & (ex > 83) & (ey >= 21) & (ey <= 79)
    elif pass_type == "switch":
        mask = (ey - sy).abs() > 35
    elif pass_type == "through":
        mask = (ex > 66.6) & ((ex - sx) > 15)
    elif pass_type == "key":
        from components.definitions import flag_mask
        mask = flag_mask(passes["Key pass"]) if "Key pass" in passes.columns else pd.Series(False, index=passes.index)
    elif pass_type == "failed":
        mask = out == 0
    elif pass_type == "successful":
        mask = out == 1
    else:
        mask = pd.Series(True, index=passes.index)
    return passes[mask.fillna(False)]
