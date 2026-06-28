"""
PDF export for Pre-Match and Post-Match reports.

Uses ReportLab (pure-Python, no headless browser needed) so it works inside a
standard Dash deployment without extra system binaries. Produces a professional,
dark-themed PDF with title, teams, KPI cards, tactical summaries, data-source
badges, and caveats. Charts/maps are included as rasterised PNGs when Kaleido is
available; if not, the PDF still renders with all tables/summaries and a note.

If ReportLab is not installed, export_report_pdf returns (None, message) so the
caller can show a clean error instead of crashing.
"""
from io import BytesIO
import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable, Image)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    _HAVE_REPORTLAB = True
except Exception:
    _HAVE_REPORTLAB = False


def _figure_to_png_bytes(fig, width=900, height=520):
    """Render a Plotly figure to PNG bytes via kaleido. Returns None if image
    export is unavailable (no Chrome/kaleido) — the PDF then degrades to text."""
    try:
        import plotly.io as pio
        return pio.to_image(fig, format="png", width=width, height=height, scale=2)
    except Exception:
        return None


def charts_available_for_pdf():
    """True if Plotly figures can be rasterised for embedding in the PDF."""
    try:
        import plotly.graph_objects as go
        return _figure_to_png_bytes(go.Figure(), 200, 120) is not None
    except Exception:
        return False


def _build_report_charts(model):
    """Build a list of (title, png_bytes) charts from the model. Returns [] when
    image export is unavailable so the PDF cleanly degrades to text+tables."""
    if not charts_available_for_pdf():
        return []
    import plotly.graph_objects as go
    out = []
    GOLD = "#FFD700"; GREEN = "#00E396"; RED = "#FF4560"; BLUE = "#008FFB"

    def _style(fig, title):
        fig.update_layout(
            title=dict(text=title, font=dict(size=15, color="#1A1A1A")),
            paper_bgcolor="white", plot_bgcolor="#F7F8FA",
            font=dict(color="#222", size=12), margin=dict(l=40, r=20, t=40, b=36),
            showlegend=True, legend=dict(font=dict(size=11)),
        )
        fig.update_xaxes(gridcolor="#E2E6EC", color="#444")
        fig.update_yaxes(gridcolor="#E2E6EC", color="#444")
        return fig

    # 1) Goal timing distribution (scored vs conceded) — from goal profiles
    gf = model.get("goal_profile", {}); ga = model.get("goals_conceded_profile", {})
    bands = ["0-15", "16-30", "31-45+", "46-60", "61-75", "76-90+"]
    if gf.get("timing") or ga.get("timing"):
        fig = go.Figure()
        fig.add_bar(x=bands, y=[gf.get("timing", {}).get(b, 0) for b in bands], name="Scored", marker_color=GREEN)
        if ga.get("timing"):
            fig.add_bar(x=bands, y=[ga.get("timing", {}).get(b, 0) for b in bands], name="Conceded", marker_color=RED)
        fig.update_layout(barmode="group")
        png = _figure_to_png_bytes(_style(fig, "Goal Timing Distribution"), 900, 460)
        if png:
            out.append(("Goals by 15-minute band (scored vs conceded over the sample)", png))

    # 2) Goal method distribution — scored
    methods = {k: v for k, v in (gf.get("methods", {}) or {}).items() if v > 0}
    if methods:
        items = sorted(methods.items(), key=lambda kv: -kv[1])
        fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k.title() for k, _ in items],
                               orientation="h", marker_color=BLUE))
        png = _figure_to_png_bytes(_style(fig, "How Goals Were Scored"), 900, 420)
        if png:
            out.append(("Goal method distribution", png))

    # 3) Plan vs Execution (post-match) — target attainment bar
    pve = model.get("plan_vs_execution", {})
    rows = pve.get("rows", [])
    if rows and "actual" in (rows[0] if rows else {}):
        labels = [r["label"] for r in rows]
        statuses = [r.get("status", "") for r in rows]
        cmap = {"Hit": GREEN, "Strategically Acceptable": GOLD, "Missed": RED, "Partial": "#FEB019"}
        colors_ = [cmap.get(s, BLUE) for s in statuses]
        fig = go.Figure(go.Bar(x=[1]*len(labels), y=labels, orientation="h", marker_color=colors_,
                               text=statuses, textposition="inside", insidetextanchor="start"))
        fig.update_xaxes(visible=False, range=[0, 1])
        png = _figure_to_png_bytes(_style(fig, "Plan vs Execution — Target Attainment"), 900, 420)
        if png:
            out.append(("Each bar coloured by whether the pre-match target was met", png))

    # 4) Post-match: shot map + momentum from the actual match data
    if model.get("report_type") == "post":
        mid = model.get("match", {}).get("match_id") or model.get("match_id")
        league = model.get("league")
        our = model.get("teams", {}).get("our")
        if mid and league:
            try:
                from data_loader import get_match_data
                from components.charts import shot_map, match_momentum_graph
                mdf = get_match_data(league, mid)
                # Shot map (estimated quality) for our team
                try:
                    sfig = shot_map(mdf, our)
                    sfig.update_layout(paper_bgcolor="white", plot_bgcolor="#1a3d2a",
                                       font=dict(color="#222"), title=dict(text="Shot Map (Estimated Quality)", font=dict(size=15, color="#1A1A1A")))
                    png = _figure_to_png_bytes(sfig, 900, 560)
                    if png:
                        out.append(("Shot locations sized by estimated quality (event-derived xG)", png))
                except Exception:
                    pass
                # Momentum
                try:
                    home = model.get("match", {}).get("home"); away = model.get("match", {}).get("away")
                    mfig = match_momentum_graph(mdf, home, away)
                    png = _figure_to_png_bytes(_style(mfig, "Match Momentum"), 900, 420)
                    if png:
                        out.append(("Rolling territorial/threat momentum through the match", png))
                except Exception:
                    pass
            except Exception:
                pass

    return out

# Brand palette
_GOLD = colors.HexColor("#FFD700")
_BG = colors.HexColor("#0B0E11")
_CARD = colors.HexColor("#141920")
_TEXT = colors.HexColor("#C8D0DA")
_MUTED = colors.HexColor("#5A6575")
_GREEN = colors.HexColor("#00E396")
_BLUE = colors.HexColor("#008FFB")


def pdf_export_available() -> bool:
    return _HAVE_REPORTLAB


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("FAPTitle", parent=ss["Title"], textColor=_GOLD,
                          fontSize=20, spaceAfter=4, alignment=TA_LEFT))
    ss.add(ParagraphStyle("FAPSub", parent=ss["Normal"], textColor=_MUTED,
                          fontSize=10, spaceAfter=10))
    ss.add(ParagraphStyle("FAPH2", parent=ss["Heading2"], textColor=_GOLD,
                          fontSize=13, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("FAPBody", parent=ss["Normal"], textColor=colors.HexColor("#1A1A1A"),
                          fontSize=10.5, leading=15, spaceAfter=4))
    ss.add(ParagraphStyle("FAPCaveat", parent=ss["Normal"], textColor=_MUTED,
                          fontSize=8.5, leading=12, spaceBefore=8))
    return ss


def export_report_pdf(report_data: dict):
    """DEPRECATED legacy entry point. The official PDF path is export_model_pdf,
    which renders the shared report model (components/report_model.py). This shim
    remains only so any external caller keeps working: if given a full report
    model it delegates to export_model_pdf; otherwise it returns a clear message
    rather than running a divergent, unmaintained code path."""
    if not _HAVE_REPORTLAB:
        return None, "PDF export requires the 'reportlab' package."
    # A report model always carries report_type + kpis + caveats keys.
    if isinstance(report_data, dict) and "report_type" in report_data and "kpis" in report_data:
        return export_model_pdf(report_data)
    return None, ("export_report_pdf is deprecated. Build a report model with "
                  "report_model.build_pre/post_match_report_model and call "
                  "export_model_pdf(model).")


def export_model_pdf(model: dict):
    """Build a professional PDF from the SHARED report model (report_model.py).
    Both the Dash report and this PDF read the same model, so values match
    exactly. Returns (bytes, filename) or (None, error)."""
    if not _HAVE_REPORTLAB:
        return None, "PDF export requires the 'reportlab' package."
    try:
        rtype = model.get("report_type", "post")
        title = model.get("title", "Match Report")
        league = model.get("league", "")
        date = model.get("date", datetime.date.today().isoformat())
        our = model.get("teams", {}).get("our", "Team")

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
                                topMargin=14*mm, bottomMargin=14*mm, title=title)
        ss = _styles()
        story = []

        # ── Professional cover band (logos + fixture + score) ──
        try:
            from data_loader import short as _short
        except Exception:
            def _short(team):
                return str(team or "")

        def _logo_path(team):
            try:
                from data_loader import TEAM_LOGO_MAP, LOGOS_DIR, normalize_team
                import os
                fn = TEAM_LOGO_MAP.get(normalize_team(team))
                if fn:
                    p = os.path.join(LOGOS_DIR, fn)
                    if os.path.exists(p):
                        return p
            except Exception:
                pass
            return None

        story.append(Paragraph("FOOTBALL ANALYTICS PRO", ss["FAPSub"]))
        story.append(Paragraph(title, ss["FAPTitle"]))
        sc = model.get("score", {})
        m = model.get("match", {})
        home_t, away_t = m.get("home", ""), m.get("away", "")
        lp_home, lp_away = _logo_path(home_t), _logo_path(away_t)
        if home_t and away_t and (lp_home or lp_away):
            # Three-column fixture band: home logo | score | away logo
            score_txt = (f"{sc.get('home','')}–{sc.get('away','')}" if sc else "vs")
            hcell = Image(lp_home, width=16*mm, height=16*mm) if lp_home else Paragraph(_short(home_t), ss["FAPBody"])
            acell = Image(lp_away, width=16*mm, height=16*mm) if lp_away else Paragraph(_short(away_t), ss["FAPBody"])
            mid = Paragraph(f"<b>{_short(home_t)}</b>  <font color='#B8860B'><b>{score_txt}</b></font>  <b>{_short(away_t)}</b>", ss["FAPBody"])
            band = Table([[hcell, mid, acell]], colWidths=[24*mm, 100*mm, 24*mm])
            band.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                      ("ALIGN", (0, 0), (0, 0), "CENTER"),
                                      ("ALIGN", (1, 0), (1, 0), "CENTER"),
                                      ("ALIGN", (2, 0), (2, 0), "CENTER")]))
            story.append(band)
        if sc:
            winner = sc.get("winner", "")
            wtxt = f"Winner: {winner}" if winner and winner != "Draw" else "Draw"
            story.append(Paragraph(f"Score source: {sc.get('source','')}  ·  {wtxt}", ss["FAPSub"]))
        meta = "  ·  ".join([x for x in [league.replace("_", " ") if league else "", str(date)] if x])
        if meta:
            story.append(Paragraph(meta, ss["FAPSub"]))
        # Selected-team band (parity with the Dash report badge)
        teams = model.get("teams", {})
        samp = model.get("sample", {})
        if teams.get("our"):
            rt = (f"<b>Report Team:</b> {_short(teams.get('our',''))}"
                  f"  ·  <b>Opponent:</b> {_short(teams.get('opponent',''))}"
                  f"  ·  <b>Sample:</b> {samp.get('sample_label', '')}"
                  f"  ·  Generated from selected-team state")
            story.append(Paragraph(rt, ss["FAPSub"]))
        story.append(HRFlowable(width="100%", thickness=1.2, color=_GOLD, spaceAfter=10))

        # ── Executive summary ──
        ex = [s for s in model.get("executive_summary", []) if s]
        if ex:
            story.append(Paragraph("Executive Summary", ss["FAPH2"]))
            for s in ex:
                story.append(Paragraph(s, ss["FAPBody"]))

        # ── KPIs ──
        kpis = model.get("kpis", [])
        if kpis:
            story.append(Paragraph("Key Metrics", ss["FAPH2"]))
            rows = [["Metric", "Value", "Source", "Context"]]
            for k in kpis:
                rows.append([str(k.get("label", "")), str(k.get("value", "")),
                             str(k.get("source", "")), str(k.get("context", ""))])
            t = Table(rows, colWidths=[58*mm, 26*mm, 38*mm, 56*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _CARD),
                ("TEXTCOLOR", (0, 0), (-1, 0), _GOLD),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#222")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCD2DA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t)

        # ── Post-match KPI context (match vs team season avg vs league avg) ──
        pmctx = model.get("post_match_kpi_context", [])
        if model.get("report_type") == "post" and pmctx:
            story.append(Paragraph("Post-Match KPI Context", ss["FAPH2"]))
            story.append(Paragraph("Match values are compared with the team season average and league team-match average; the selected match is excluded from baselines.", ss["FAPCaveat"]))
            keep = {"xg", "xga", "shots", "shots_on_target", "big_chances", "ppda", "tackles_won", "interceptions", "recoveries", "clearances", "ft_entries", "box_entries", "prog_passes"}
            rows = [["Metric", "Match", "Team Avg", "League Avg", "Δ Team", "Pctl", "Interpretation"]]
            for c in pmctx:
                if c.get("metric") not in keep:
                    continue
                def _v(x):
                    if x is None: return "—"
                    try: return f"{float(x):.1f}" if abs(float(x)) >= 10 else f"{float(x):.2f}"
                    except Exception: return str(x)
                rows.append([c.get("label", ""), _v(c.get("match_value")), _v(c.get("team_season_avg")),
                             _v(c.get("league_avg")), _v(c.get("difference_vs_team_avg")),
                             str(c.get("percentile", "—")), c.get("interpretation", "")])
            if len(rows) > 1:
                t = Table(rows, colWidths=[34*mm, 20*mm, 22*mm, 22*mm, 20*mm, 16*mm, 54*mm])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), _CARD), ("TEXTCOLOR", (0, 0), (-1, 0), _GOLD),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#222")),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.7), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD2DA")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(t)

        # ── Goal Profile / Goals Conceded Profile ──
        gp_team = model.get("goal_profile_team") or (model.get("teams", {}) or {}).get("our", "")
        gp_prefix = f"{_short(gp_team)} " if gp_team else ""
        for gp_key, gp_title in [("goal_profile", f"{gp_prefix}Goal Profile (Scored)"),
                                 ("goals_conceded_profile", f"{gp_prefix}Goals Conceded Profile")]:
            gp = model.get(gp_key, {})
            if gp and gp.get("total", 0) >= 0 and gp.get("n_matches"):
                story.append(Paragraph(gp_title, ss["FAPH2"]))
                story.append(Paragraph(
                    f"<b>{gp['total']}</b> goals over {gp['n_matches']} matches "
                    f"(<b>{gp['per_match']}</b>/match) · 1st half {gp['first_half']} · 2nd half {gp['second_half']}",
                    ss["FAPBody"]))
                methods = {k: v for k, v in gp.get("methods", {}).items() if v > 0}
                if methods:
                    mrows = [["Method", "Goals"]] + [[k.title(), str(v)] for k, v in sorted(methods.items(), key=lambda kv: -kv[1])]
                    timing = {k: v for k, v in gp.get("timing", {}).items() if v > 0}
                    trows = [["Period", "Goals"]] + [[k, str(v)] for k, v in timing.items()]
                    mt = Table(mrows, colWidths=[40*mm, 20*mm])
                    tt = Table(trows, colWidths=[30*mm, 20*mm])
                    for tbl in (mt, tt):
                        tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), _CARD), ("TEXTCOLOR", (0, 0), (-1, 0), _GOLD),
                            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#222")),
                            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCD2DA")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]))
                    combo = Table([[mt, tt]], colWidths=[64*mm, 54*mm])
                    combo.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
                    story.append(combo)

        # ── Plan vs Execution ──
        pve = model.get("plan_vs_execution", {})
        if pve:
            hdr = f"Plan vs Execution — {pve.get('template','')}"
            if pve.get("score") is not None:
                hdr += f"  ({pve.get('score')}% · {pve.get('label','')})"
            story.append(Paragraph(hdr, ss["FAPH2"]))
            if pve.get("rationale"):
                story.append(Paragraph(f"<i>{pve['rationale']} · Confidence: {pve.get('confidence','')}</i>", ss["FAPBody"]))
            prows = pve.get("rows", [])
            if prows:
                has_actual = "actual" in prows[0]
                if has_actual:
                    head = ["Target", "Range", "Actual", "Status"]
                    body = [[r.get("label", ""), r.get("target", ""), str(r.get("actual", "")), r.get("status", "")] for r in prows]
                    cw = [55*mm, 35*mm, 28*mm, 40*mm]
                else:
                    head = ["Target", "Range", "Note"]
                    body = [[r.get("label", ""), r.get("target", ""), r.get("note", "")] for r in prows]
                    cw = [50*mm, 38*mm, 70*mm]
                t = Table([head] + body, colWidths=cw)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), _CARD),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _GOLD),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#222")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCD2DA")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(t)

        # ── Visual Analysis (rasterised charts via kaleido, if available) ──
        chart_imgs = _build_report_charts(model)
        if chart_imgs:
            story.append(Paragraph("Visual Analysis", ss["FAPH2"]))
            for title, png in chart_imgs:
                if title:
                    story.append(Paragraph(title, ss["FAPBody"]))
                bio = BytesIO(png)
                img = Image(bio, width=170*mm, height=170*mm*0.56)
                story.append(img)
                story.append(Spacer(1, 6))

        # ── Tactical findings ──
        tf = model.get("tactical_findings", [])
        if tf:
            story.append(Paragraph("Tactical Findings", ss["FAPH2"]))
            for f in tf:
                if isinstance(f, dict):
                    story.append(Paragraph(f"<b>{f.get('title','')}.</b> {f.get('body','')}", ss["FAPBody"]))
                else:
                    story.append(Paragraph(str(f), ss["FAPBody"]))

        # ── Recommendations ──
        rec = model.get("recommendations", [])
        if rec:
            story.append(Paragraph("Recommendations", ss["FAPH2"]))
            for r in rec:
                story.append(Paragraph(f"• {r}", ss["FAPBody"]))

        # ── Player notes ──
        pn = model.get("player_notes", [])
        if pn:
            story.append(Paragraph("Key Players", ss["FAPH2"]))
            for p in pn:
                if isinstance(p, dict):
                    story.append(Paragraph(f"<b>{p.get('name','')}.</b> {p.get('note','')}", ss["FAPBody"]))
                else:
                    story.append(Paragraph(str(p), ss["FAPBody"]))

        # ── Caveats & QA ──
        caveats = model.get("caveats", [])
        qa_warn = model.get("qa", {}).get("warnings", [])
        if caveats or qa_warn:
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.5, color=_MUTED, spaceAfter=6))
            for c in caveats:
                story.append(Paragraph(f"⚠ {c}", ss["FAPCaveat"]))
            for w in qa_warn:
                story.append(Paragraph(f"⚠ QA: {w}", ss["FAPCaveat"]))

        story.append(Spacer(1, 10))
        story.append(Paragraph(
            f"Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · Football Analytics Pro",
            ss["FAPCaveat"]))

        doc.build(story)
        buf.seek(0)
        safe = "".join(ch for ch in our if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
        fname = f"{'Pre' if rtype == 'pre' else 'Post'}-Match_Report_{safe}_{date}.pdf"
        return buf.getvalue(), fname
    except Exception as e:
        return None, f"PDF generation failed: {e}"
