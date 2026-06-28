"""
components/pitch.py — Football pitch drawing with Plotly shapes.
"""

import plotly.graph_objects as go
import numpy as np

PITCH_GREEN = "#1a472a"
LINE_COLOR = "rgba(200,215,220,0.55)"


def _arc(cx, cy, a, b, s, e, N=40):
    t = np.linspace(s, e, N)
    return cx + a * np.cos(t), cy + b * np.sin(t)


def draw_pitch(fig=None, bg="#0B0E11", pitch_color=PITCH_GREEN,
               line_col=LINE_COLOR, lw=1.5):
    if fig is None:
        fig = go.Figure()

    shapes = []
    def R(x0, y0, x1, y1):
        shapes.append(dict(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                           line=dict(color=line_col, width=lw),
                           fillcolor="rgba(0,0,0,0)", layer="below"))
    def L(x0, y0, x1, y1):
        shapes.append(dict(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                           line=dict(color=line_col, width=lw), layer="below"))
    def C(xc, yc, r):
        shapes.append(dict(type="circle", x0=xc-r, y0=yc-r, x1=xc+r, y1=yc+r,
                           line=dict(color=line_col, width=lw),
                           fillcolor="rgba(0,0,0,0)", layer="below"))
    def Dot(xc, yc, r=0.6):
        shapes.append(dict(type="circle", x0=xc-r, y0=yc-r, x1=xc+r, y1=yc+r,
                           line=dict(color=line_col, width=0),
                           fillcolor=line_col, layer="below"))

    # Green pitch as a BOUNDED rectangle (not plot_bgcolor) so it never bleeds
    # across the wide plot area. Everything outside [0,100]x[0,100] stays dark.
    shapes.insert(0, dict(type="rect", x0=0, y0=0, x1=100, y1=100,
                          line=dict(width=0), fillcolor=pitch_color, layer="below"))

    R(0, 0, 100, 100)
    L(50, 0, 50, 100)
    C(50, 50, 9.15)
    Dot(50, 50)
    R(0, 21.1, 16.5, 78.9)
    R(0, 36.8, 5.5, 63.2)
    Dot(11.3, 50)
    R(83.5, 21.1, 100, 78.9)
    R(94.5, 36.8, 100, 63.2)
    Dot(88.7, 50)
    R(-2, 44.2, 0, 55.8)
    R(100, 44.2, 102, 55.8)

    # Penalty arcs
    for cx, side in [(11.3, "left"), (88.7, "right")]:
        s, e = (-0.65, 0.65) if side == "left" else (np.pi-0.65, np.pi+0.65)
        ax, ay = _arc(cx, 50, 8.5, 8.5, s, e)
        fig.add_trace(go.Scatter(x=ax.tolist(), y=ay.tolist(), mode="lines",
                                 line=dict(color=line_col, width=lw),
                                 showlegend=False, hoverinfo="skip"))
    # Corner arcs
    for cx, cy, s, e in [(0,0,0,np.pi/2), (0,100,-np.pi/2,0),
                          (100,0,np.pi/2,np.pi), (100,100,np.pi,3*np.pi/2)]:
        ax, ay = _arc(cx, cy, 2, 2, s, e, 20)
        fig.add_trace(go.Scatter(x=ax.tolist(), y=ay.tolist(), mode="lines",
                                 line=dict(color=line_col, width=lw),
                                 showlegend=False, hoverinfo="skip"))

    fig.update_layout(
        shapes=shapes, plot_bgcolor=bg, paper_bgcolor=bg,
        xaxis=dict(range=[-3, 103], showgrid=False, zeroline=False, visible=False,
                   scaleanchor="y", scaleratio=1, constrain="domain", fixedrange=True),
        yaxis=dict(range=[-3, 103], showgrid=False, zeroline=False, visible=False,
                   constrain="domain", fixedrange=True),
        margin=dict(l=5, r=5, t=5, b=5),
        autosize=True, uirevision="pitch",
    )
    return fig


def draw_half_pitch(fig=None, bg="#0B0E11", pitch_color=PITCH_GREEN,
                    line_col=LINE_COLOR, lw=1.5, side="right"):
    if fig is None:
        fig = go.Figure()

    shapes = []
    def R(x0, y0, x1, y1):
        shapes.append(dict(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                           line=dict(color=line_col, width=lw),
                           fillcolor="rgba(0,0,0,0)", layer="below"))
    def Dot(xc, yc, r=0.6):
        shapes.append(dict(type="circle", x0=xc-r, y0=yc-r, x1=xc+r, y1=yc+r,
                           line=dict(color=line_col, width=0),
                           fillcolor=line_col, layer="below"))

    if side == "right":
        shapes.insert(0, dict(type="rect", x0=50, y0=0, x1=100, y1=100,
                              line=dict(width=0), fillcolor=pitch_color, layer="below"))
        R(50, 0, 100, 100)
        R(83.5, 21.1, 100, 78.9)
        R(94.5, 36.8, 100, 63.2)
        R(100, 44.2, 102, 55.8)
        Dot(88.7, 50)
        ax, ay = _arc(88.7, 50, 8.5, 8.5, np.pi-0.65, np.pi+0.65)
        fig.add_trace(go.Scatter(x=ax.tolist(), y=ay.tolist(), mode="lines",
                                 line=dict(color=line_col, width=lw),
                                 showlegend=False, hoverinfo="skip"))
        xrange = [48, 102]
    else:
        shapes.insert(0, dict(type="rect", x0=0, y0=0, x1=50, y1=100,
                              line=dict(width=0), fillcolor=pitch_color, layer="below"))
        R(0, 0, 50, 100)
        R(0, 21.1, 16.5, 78.9)
        R(0, 36.8, 5.5, 63.2)
        R(-2, 44.2, 0, 55.8)
        Dot(11.3, 50)
        xrange = [-2, 52]

    fig.update_layout(
        shapes=shapes, plot_bgcolor=bg, paper_bgcolor=bg,
        xaxis=dict(range=xrange, showgrid=False, zeroline=False, visible=False,
                   scaleanchor="y", scaleratio=1, constrain="domain"),
        yaxis=dict(range=[-3, 103], showgrid=False, zeroline=False, visible=False,
                   constrain="domain"),
        margin=dict(l=5, r=5, t=5, b=5),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
#  SPLIT HELPERS — correct heatmap layering (background below, lines above)
#  Coordinate system: 0–100 x 0–100 (matches event data), but the figure is
#  given a true football aspect ratio via scaleratio so it is NOT a square.
# ══════════════════════════════════════════════════════════════════════════
# Real pitch is 105x68 → width/length = 0.6476. Applied as y:x scaleratio so the
# 0–100 box renders with football proportions instead of a square.
_PITCH_ASPECT = 68.0 / 105.0


def draw_pitch_background_only(fig, bg="#0B0E11", pitch_color=PITCH_GREEN):
    """Add ONLY the green pitch rectangle (below everything). Call before heatmap."""
    fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=100,
                  line=dict(width=0), fillcolor=pitch_color, layer="below")
    fig.update_layout(paper_bgcolor=bg, plot_bgcolor=bg)
    return fig


def draw_pitch_lines_only(fig, line_col=LINE_COLOR, lw=1.5, height=820,
                          aspect=True):
    """Draw ONLY pitch markings ABOVE the heatmap, then set football-ratio axes.
    All line shapes use layer='above' so they sit on top of the density."""
    shapes = list(fig.layout.shapes) if fig.layout.shapes else []

    def R(x0, y0, x1, y1):
        shapes.append(dict(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                           line=dict(color=line_col, width=lw),
                           fillcolor="rgba(0,0,0,0)", layer="above"))
    def L(x0, y0, x1, y1):
        shapes.append(dict(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                           line=dict(color=line_col, width=lw), layer="above"))
    def C(xc, yc, r):
        shapes.append(dict(type="circle", x0=xc-r, y0=yc-r, x1=xc+r, y1=yc+r,
                           line=dict(color=line_col, width=lw),
                           fillcolor="rgba(0,0,0,0)", layer="above"))
    def Dot(xc, yc, r=0.6):
        shapes.append(dict(type="circle", x0=xc-r, y0=yc-r, x1=xc+r, y1=yc+r,
                           line=dict(color=line_col, width=0),
                           fillcolor=line_col, layer="above"))

    R(0, 0, 100, 100)
    L(50, 0, 50, 100)
    C(50, 50, 9.15)
    Dot(50, 50)
    R(0, 21.1, 16.5, 78.9)
    R(0, 36.8, 5.5, 63.2)
    Dot(11.3, 50)
    R(83.5, 21.1, 100, 78.9)
    R(94.5, 36.8, 100, 63.2)
    Dot(88.7, 50)
    R(-2, 44.2, 0, 55.8)
    R(100, 44.2, 102, 55.8)

    # Penalty + corner arcs as scatter traces (drawn after heatmap = above it)
    for cx, side in [(11.3, "left"), (88.7, "right")]:
        s, e = (-0.65, 0.65) if side == "left" else (np.pi-0.65, np.pi+0.65)
        ax, ay = _arc(cx, 50, 8.5, 8.5, s, e)
        fig.add_trace(go.Scatter(x=ax.tolist(), y=ay.tolist(), mode="lines",
                                 line=dict(color=line_col, width=lw),
                                 showlegend=False, hoverinfo="skip"))
    for cx, cy, s, e in [(0,0,0,np.pi/2), (0,100,-np.pi/2,0),
                          (100,0,np.pi/2,np.pi), (100,100,np.pi,3*np.pi/2)]:
        ax, ay = _arc(cx, cy, 2, 2, s, e, 20)
        fig.add_trace(go.Scatter(x=ax.tolist(), y=ay.tolist(), mode="lines",
                                 line=dict(color=line_col, width=lw),
                                 showlegend=False, hoverinfo="skip"))

    fig.update_layout(
        shapes=shapes, height=height,
        xaxis=dict(range=[-3, 103], showgrid=False, zeroline=False, visible=False,
                   constrain="domain"),
        yaxis=dict(range=[-8, 108], showgrid=False, zeroline=False, visible=False,
                   scaleanchor="x", scaleratio=(_PITCH_ASPECT if aspect else 1.0),
                   constrain="domain"),
        margin=dict(l=20, r=70, t=20, b=30),
    )
    return fig
