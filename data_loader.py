"""
data_loader.py — Multi-League Data Engine v2
FIXES:
  - Memory: 2GB→~300MB via column pruning + category dtypes
  - Safety: All .iloc[0] guarded, NaN-safe, missing-column-safe
  - Multi-season: Auto-discovers team names, handles schema differences
  - Cache: Proper keying, match_id included in h2h results
"""

import pandas as pd
import numpy as np
import glob
import os
import re
import base64

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGOS_DIR = os.path.join(BASE_DIR, "assets", "logos")


# ── Competition / knockout-stage helpers ─────────────────────────────
_CUP_ROUND_ORDER = {
    "64th Finals": 0,
    "32nd Finals": 1,
    "16th Finals": 2,
    "8th Finals": 3,
    "Quarter-finals": 4,
    "Quarter Finals": 4,
    "Semi-finals": 5,
    "Semi Finals": 5,
    "Final": 6,
}

_CUP_ROUND_LABELS = {
    0: "64th Finals", 1: "32nd Finals", 2: "16th Finals", 3: "8th Finals",
    4: "Quarter-finals", 5: "Semi-finals", 6: "Final",
}

def is_knockout_competition(league_folder: str) -> bool:
    """True for cup/knockout folders such as Coupe de France."""
    lf = str(league_folder or "").lower()
    return any(k in lf for k in ["cup", "coupe", "copa", "knockout"])

def _infer_round_from_filename(path: str):
    """Infer competition stage metadata from an Opta CSV filename.

    League files usually start with a numeric matchweek (e.g. `10_Lens_Metz...`).
    Cup files usually start with a stage string (e.g. `32nd Finals_Lens...`).
    Returns (round_name, round_order, competition_type).
    """
    name = os.path.basename(str(path))
    prefix = name.split("_")[0].strip()
    # League matchweek prefix
    if re.fullmatch(r"\d+", prefix):
        w = int(prefix)
        return f"Matchweek {w}", w, "league"
    # Known cup stages
    for stage, order in _CUP_ROUND_ORDER.items():
        if prefix.lower() == stage.lower():
            return _CUP_ROUND_LABELS.get(order, stage), order, "knockout"
    # Generic fallback: non-numeric first token = stage-like cup round
    return prefix or "Round", 0, "knockout"

def competition_display_name(folder: str) -> str:
    raw = str(folder or "").replace("_", " ")
    raw = raw.replace("France Coupe de France 25-26", "France Coupe de France 2025-26")
    raw = raw.replace("France League 1 25-26", "France Ligue 1 2025-26")
    return raw

# Robust qualifier-flag detector (kept local to avoid import cycles).
# Mirrors components/definitions.is_flag — single behaviour everywhere.
_FLAG_TRUE = {"si", "sí", "yes", "y", "1", "true", "t", "x", "✓"}
def _is_flag_local(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return (not (isinstance(value, float) and value != value)) and value == 1
    if isinstance(value, str):
        return value.strip().lower() in _FLAG_TRUE
    return False


TEAM_LOGO_MAP = {
    "AS Monaco FC": "as-monaco.football-logos.cc.png",
    "Angers Sporting Club de l'Ouest": "angers.football-logos.cc.png",
    "Association Jeunesse Auxerroise": "auxerre.football-logos.cc.png",
    "FC Lorient": "lorient.football-logos.cc.png",
    "FC Metz": "fc-metz.football-logos.cc.png",
    "FC Nantes": "nantes.football-logos.cc.png",
    "Le Havre AC": "le-havre-ac.football-logos.cc.png",
    "Lille OSC": "lille.football-logos.cc.png",
    "OGC Nice Côte d'Azur": "nice.football-logos.cc.png",
    "Olympique Lyonnais": "lyon.football-logos.cc.png",
    "Olympique de Marseille": "marseille.football-logos.cc.png",
    "Paris FC": "paris-fc.football-logos.cc.png",
    "Paris Saint-Germain FC": "paris-saint-germain.football-logos.cc.png",
    "RC Strasbourg Alsace": "rc-strasbourg-alsace.football-logos.cc.png",
    "Racing Club de Lens": "rc-lens.football-logos.cc.png",
    "Stade Brestois 29": "brest.football-logos.cc.png",
    "Stade Rennais FC": "rennes.football-logos.cc.png",
    "Toulouse FC": "toulouse.football-logos.cc.png",
}
TEAM_SHORT = {
    "AS Monaco FC": "Monaco", "Angers Sporting Club de l'Ouest": "Angers",
    "Association Jeunesse Auxerroise": "Auxerre", "FC Lorient": "Lorient",
    "FC Metz": "Metz", "FC Nantes": "Nantes", "Le Havre AC": "Le Havre",
    "Lille OSC": "Lille", "OGC Nice Côte d'Azur": "Nice",
    "Olympique Lyonnais": "Lyon", "Olympique de Marseille": "Marseille",
    "Paris FC": "Paris FC", "Paris Saint-Germain FC": "PSG",
    "RC Strasbourg Alsace": "Strasbourg", "Racing Club de Lens": "Lens",
    "Stade Brestois 29": "Brest", "Stade Rennais FC": "Rennes",
    "Toulouse FC": "Toulouse",
}
TEAM_COLORS = {
    "AS Monaco FC": "#E2001A", "Angers Sporting Club de l'Ouest": "#000000",
    "Association Jeunesse Auxerroise": "#1B3C8C", "FC Lorient": "#F47920",
    "FC Metz": "#812040", "FC Nantes": "#10B981", "Le Havre AC": "#00A3E0",
    "Lille OSC": "#C8102E", "OGC Nice Côte d'Azur": "#E2001A",
    "Olympique Lyonnais": "#004A8F", "Olympique de Marseille": "#2FAADE",
    "Paris FC": "#004A8F", "Paris Saint-Germain FC": "#004170",
    "RC Strasbourg Alsace": "#005CA9", "Racing Club de Lens": "#FFD700",
    "Stade Brestois 29": "#E2001A", "Stade Rennais FC": "#C8102E",
    "Toulouse FC": "#6A1B9A",
}

DEFAULT_CLUB = "Racing Club de Lens"
LENS_GOLD = "#FFD700"
LENS_RED = "#E2001A"
_COLOR_PALETTE = ["#E2001A","#004A8F","#10B981","#F47920","#6A1B9A","#00A3E0","#C8102E","#812040","#005CA9","#2FAADE"]

# ── Central team-name normalization ────────────────────────────────────
# Maps any alias / short name / Wyscout label to the canonical event-CSV name,
# so logos, colors, short names, league table, H2H, and Wyscout matching all
# agree. Built from short names + Wyscout labels + common variants.
TEAM_ALIASES = {
    # canonical -> canonical (identity, so normalize() is safe to call twice)
    **{c: c for c in TEAM_LOGO_MAP},
    # short names -> canonical
    "Monaco": "AS Monaco FC", "Angers": "Angers Sporting Club de l'Ouest",
    "Auxerre": "Association Jeunesse Auxerroise", "Lorient": "FC Lorient",
    "Metz": "FC Metz", "Nantes": "FC Nantes", "Le Havre": "Le Havre AC",
    "Lille": "Lille OSC", "Nice": "OGC Nice Côte d'Azur",
    "Lyon": "Olympique Lyonnais", "Lyo": "Olympique Lyonnais",
    "Marseille": "Olympique de Marseille", "PSG": "Paris Saint-Germain FC",
    "Strasbourg": "RC Strasbourg Alsace", "Lens": "Racing Club de Lens",
    "Brest": "Stade Brestois 29", "Rennes": "Stade Rennais FC",
    "Toulouse": "Toulouse FC",
    # Wyscout labels + common variants -> canonical
    "Olympique Marseille": "Olympique de Marseille",
    "Paris SG": "Paris Saint-Germain FC", "Paris Saint Germain": "Paris Saint-Germain FC",
    "Paris": "Paris FC", "Angers SCO": "Angers Sporting Club de l'Ouest",
    "AS Monaco": "AS Monaco FC", "Stade Rennais": "Stade Rennais FC",
    "Stade Brestois": "Stade Brestois 29", "RC Lens": "Racing Club de Lens",
    "RC Strasbourg": "RC Strasbourg Alsace", "Nice OGC": "OGC Nice Côte d'Azur",
}

def normalize_team(name) -> str:
    """Resolve any alias/short/variant to the canonical event-CSV team name."""
    if name is None:
        return name
    s = str(name).strip()
    if s in TEAM_ALIASES:
        return TEAM_ALIASES[s]
    # Case-insensitive fallback
    low = s.lower()
    for alias, canon in TEAM_ALIASES.items():
        if alias.lower() == low:
            return canon
    return s  # unknown — return as-is (QA can flag)

def unmapped_team_report(names) -> list:
    """QA helper: returns any names that don't resolve to a known canonical team."""
    canon = set(TEAM_LOGO_MAP)
    return sorted({n for n in names if normalize_team(n) not in canon})

def get_logo_base64(team_name: str) -> str:
    fname = TEAM_LOGO_MAP.get(normalize_team(team_name))
    if not fname: return ""
    path = os.path.join(LOGOS_DIR, fname)
    if not os.path.exists(path): return ""
    try:
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception: return ""

def short(team_name: str) -> str:
    canon = normalize_team(team_name)
    if canon in TEAM_SHORT: return TEAM_SHORT[canon]
    parts = canon.replace("FC","").replace("SC","").replace("AC","").strip().split()
    s = parts[0][:12] if parts else canon[:12]
    TEAM_SHORT[canon] = s
    return s

def team_color(team_name: str) -> str:
    canon = normalize_team(team_name)
    if canon in TEAM_COLORS: return TEAM_COLORS[canon]
    c = _COLOR_PALETTE[hash(canon) % len(_COLOR_PALETTE)]
    TEAM_COLORS[canon] = c
    return c

def _safe_first(df, col, default="Unknown"):
    if df.empty: return default
    v = df[col].iloc[0]
    return default if pd.isna(v) else v

def _safe_col(df, col):
    return df[col] if col in df.columns else pd.Series(dtype="object", index=df.index)

# ── League discovery ───────────────────────────────────────────────────
def discover_leagues() -> list:
    leagues = []
    if not os.path.isdir(DATA_DIR): return leagues
    _NON_LEAGUE = {"reference", "cache", "wyscout", "__pycache__"}
    for folder in sorted(os.listdir(DATA_DIR)):
        if folder.lower() in _NON_LEAGUE or "wyscout" in folder.lower() or folder.startswith("."):
            continue
        fp = os.path.join(DATA_DIR, folder)
        if os.path.isdir(fp):
            csvs = glob.glob(os.path.join(fp, "*.csv"))
            if csvs:
                leagues.append({"folder": folder, "path": fp,
                                "display_name": competition_display_name(folder), "csv_count": len(csvs),
                                "competition_type": "knockout" if is_knockout_competition(folder) else "league"})
    return leagues

# ── Columns we actually use (everything else is dropped) ──────────────
_KEEP_COLS = {
    "match_id","event","type_id","period_id","time_min","time_sec",
    "team_name","team_position","player_name","player_id",
    "x","y","Pass End X","Pass End Y","outcome",
    "Goal Mouth Y Coordinate","Goal Mouth Z Coordinate",
    "description","week","local_date","venue_long_name",
    "competition_id","competition_name","competition_known_name","competition_code",
    "position","Jersey Number","formation","Formation slot",
    "Big Chance","Head","Cross","Through ball","Long ball",
    "Switch of play","Fast break","Set piece","From corner",
    "Corner taken","Free kick taken","Regular play",
    "Yellow Card","Red Card","Second yellow","Assist",
    "Leading to attempt","Leading to goal",
    "Left footed","Right footed","Volley","Individual Play",
    "Goal Kick","Keeper Throw","Gk kick from hands",
    "Head pass","Chipped","Lay-off","Launch","Flick-on",
    "Pull Back","macro_category","categorias","Zone","Direction of play",
    "Length","Angle","Blocked X Coordinate","Blocked Y Coordinate",
}
_CAT_COLS = ["event","team_name","team_position","position","macro_category",
             "categorias","Zone","Direction of play"]

# ── Data loading — OPTIMIZED ──────────────────────────────────────────
_CACHE = {}

def load_league_data(league_folder: str) -> pd.DataFrame:
    ck = f"league_{league_folder}"
    if ck in _CACHE: return _CACHE[ck]
    fp = os.path.join(DATA_DIR, league_folder)
    files = glob.glob(os.path.join(fp, "*.csv"))
    if not files: return pd.DataFrame()

    # ── Disk cache (parquet): processed frame is written once, then cold starts
    # read parquet (~5-10x faster than parsing 300+ CSVs). Invalidated if any
    # source CSV is newer than the cache.
    cache_dir = os.path.join(DATA_DIR, ".cache")
    pq_path = os.path.join(cache_dir, f"{league_folder}.parquet")
    try:
        if os.path.exists(pq_path):
            newest_csv = max(os.path.getmtime(f) for f in files)
            if os.path.getmtime(pq_path) >= newest_csv:
                master = pd.read_parquet(pq_path)
                for col in _CAT_COLS:
                    if col in master.columns:
                        try: master[col] = master[col].astype("category")
                        except Exception: pass
                _CACHE[ck] = master
                return master
    except Exception:
        pass  # any cache issue → fall through to full parse

    # Parse CSVs in parallel (I/O-bound) to cut cold-start time. Falls back to
    # serial on any executor issue. Result is cached in-memory for the session,
    # so this cost is paid once per app start, not per request.
    def _read_one(f):
        try:
            hdr = pd.read_csv(f, nrows=0, low_memory=False).columns.tolist()
            use = [c for c in hdr if c in _KEEP_COLS]
            fr = pd.read_csv(f, usecols=use, low_memory=False)
            rname, rorder, ctype = _infer_round_from_filename(f)
            fr["source_file_name"] = os.path.basename(f)
            fr["round_name"] = rname
            fr["round_order"] = rorder
            fr["competition_type"] = "knockout" if is_knockout_competition(league_folder) else ctype
            return fr
        except Exception:
            return None
    frames = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            frames = [fr for fr in ex.map(_read_one, files) if fr is not None]
    except Exception:
        frames = [fr for fr in (_read_one(f) for f in files) if fr is not None]
    if not frames: return pd.DataFrame()
    master = pd.concat(frames, ignore_index=True)

    # ── Canonicalize team names immediately (single source of truth) ──
    if "team_name" in master.columns:
        master["team_name_raw"] = master["team_name"].astype("object")
        master["team_name"] = master["team_name_raw"].map(
            lambda v: normalize_team(v) if pd.notna(v) else v)
        master["team_name_canon"] = master["team_name"]
        unmapped = unmapped_team_report(master["team_name"].dropna().unique())
        # In cup competitions many lower-division clubs do not have preloaded
        # Ligue 1 logo/color mappings. They are valid cup participants, not data
        # errors. Keep warning only for league folders.
        if unmapped and not is_knockout_competition(league_folder):
            print(f"[DATA_QA] Unmapped team names after normalization: {unmapped}")

    # Numeric
    for col in ["time_min","time_sec","x","y","Pass End X","Pass End Y","outcome",
                "Goal Mouth Y Coordinate","Goal Mouth Z Coordinate","Length","Angle",
                "Jersey Number","Formation slot","Blocked X Coordinate","Blocked Y Coordinate"]:
        if col in master.columns:
            master[col] = pd.to_numeric(master[col], errors="coerce")
    # ── Competition-stage metadata ───────────────────────────────────
    # Cup/knockout CSVs often have week == NaN. The dashboard still needs a
    # numeric order for sorting/dropdowns, so use round_order as the canonical
    # numeric stage while preserving round_name for labels.
    if "round_order" in master.columns:
        master["round_order"] = pd.to_numeric(master["round_order"], errors="coerce").fillna(0).astype(int)
    else:
        master["round_order"] = pd.to_numeric(master.get("week", 0), errors="coerce").fillna(0).astype(int)
    if "round_name" not in master.columns:
        master["round_name"] = master["round_order"].map(lambda v: f"Matchweek {int(v)}")
    if "competition_type" not in master.columns:
        master["competition_type"] = "knockout" if is_knockout_competition(league_folder) else "league"
    if "week" not in master.columns:
        master["week"] = master["round_order"]
    else:
        w = pd.to_numeric(master["week"], errors="coerce")
        master["week"] = w.fillna(master["round_order"]).fillna(0).astype(int)

    # Write parquet disk cache (object dtypes; categories re-applied on read).
    # Mixed-type object columns (flag cols with str+float) must be stringified
    # for Arrow, so we cast a copy rather than mutating the working frame.
    try:
        os.makedirs(cache_dir, exist_ok=True)
        to_write = master.copy()
        for col in to_write.columns:
            if to_write[col].dtype == object:
                to_write[col] = to_write[col].astype(str).where(to_write[col].notna(), None)
        to_write.to_parquet(pq_path, index=False)
    except Exception:
        pass
    # Category for low-cardinality (in-memory only)
    for col in _CAT_COLS:
        if col in master.columns:
            try: master[col] = master[col].astype("category")
            except: pass
    _CACHE[ck] = master
    return master

def clear_league_cache(league_folder: str = None):
    if league_folder:
        for k in [k for k in _CACHE if league_folder in k]: del _CACHE[k]
    else: _CACHE.clear()

# ── Match list ─────────────────────────────────────────────────────────
def get_match_list(league_folder: str) -> pd.DataFrame:
    """Thin wrapper over the canonical match registry. ALL score/own-goal/
    Wyscout logic lives in components/match_registry.build_match_registry.
    This function only adapts the registry to the column names the UI expects."""
    ck = f"matchlist_{league_folder}"
    if ck in _CACHE:
        return _CACHE[ck]
    df = load_league_data(league_folder)
    if df.empty:
        return pd.DataFrame()

    from components.match_registry import get_registry
    reg = get_registry(league_folder)
    if reg.empty:
        return pd.DataFrame()

    # Venue per match (metadata not carried in the registry)
    venue_map = df.groupby("match_id", observed=True)["venue_long_name"].first().to_dict()
    desc_map = df.groupby("match_id", observed=True)["description"].first().to_dict()

    out = reg.rename(columns={
        "home_team_canon": "home_team", "away_team_canon": "away_team",
        "home_score": "home_goals", "away_score": "away_goals",
        "matchweek": "week", "date": "local_date",
    }).copy()
    out["home_team_canon"] = out["home_team"]
    out["away_team_canon"] = out["away_team"]
    # Ensure round metadata exists for both leagues and cups.
    if "round_order" not in out.columns:
        out["round_order"] = out["week"]
    if "round_name" not in out.columns:
        out["round_name"] = out["week"].map(lambda w: f"Matchweek {int(w)}")
    if "competition_type" not in out.columns:
        out["competition_type"] = "knockout" if is_knockout_competition(league_folder) else "league"
    out["venue"] = out["match_id"].map(venue_map)
    out["description"] = out["match_id"].map(desc_map)
    out = out.sort_values(["round_order", "local_date"]).reset_index(drop=True)
    _CACHE[ck] = out
    return out


def get_teams(lf): 
    ml = get_match_list(lf)
    if ml.empty: return []
    return sorted(set(ml["home_team"].tolist()+ml["away_team"].tolist()) - {"Unknown"})

def get_rounds(lf):
    """Return ordered round/stage options for league or knockout competitions."""
    ml = get_match_list(lf)
    if ml.empty:
        return []
    if "round_name" not in ml.columns:
        return [{"value": int(w), "label": f"Matchweek {int(w)}"} for w in sorted(ml["week"].dropna().unique())]
    tmp = ml[["round_order", "round_name"]].drop_duplicates().sort_values("round_order")
    return [{"value": int(r["round_order"]), "label": str(r["round_name"])} for _, r in tmp.iterrows()]

def is_knockout_lf(lf):
    if is_knockout_competition(lf):
        return True
    try:
        ml = get_match_list(lf)
        return (not ml.empty) and str(ml.get("competition_type", pd.Series(["league"])).iloc[0]).lower() == "knockout"
    except Exception:
        return False

def compute_cup_progress_table(lf):
    """Knockout competition summary: no points table, just progress/results."""
    ml = get_match_list(lf)
    if ml.empty:
        return pd.DataFrame()
    teams = sorted(set(ml["home_team"].tolist() + ml["away_team"].tolist()) - {"Unknown"})
    rows = []
    for t in teams:
        tm = ml[(ml["home_team"] == t) | (ml["away_team"] == t)].sort_values(["round_order", "local_date"])
        p=w=l=gf=ga=0; reached="—"; last_result="—"
        for _, r in tm.iterrows():
            p += 1
            is_home = r["home_team"] == t
            f = int(r["home_goals"] if is_home else r["away_goals"])
            a = int(r["away_goals"] if is_home else r["home_goals"])
            gf += f; ga += a
            # knockout matches can technically have penalties; provider scoreline
            # may be level after ET. Keep W/L only for resolved scorelines.
            if f > a:
                w += 1; last_result = "W"
            elif f < a:
                l += 1; last_result = "L"
            else:
                last_result = "D/Pens"
            reached = r.get("round_name", f"Round {r.get('round_order', 0)}")
        rows.append({"Team": t, "Short": short(t), "P": p, "W": w, "L": l, "GF": gf, "GA": ga,
                     "GD": gf-ga, "Reached": reached, "Last": last_result})
    return pd.DataFrame(rows).sort_values(["Reached", "W", "GD", "GF"], ascending=[False, False, False, False]).reset_index(drop=True)

def get_match_data(lf, mid):
    return load_league_data(lf)[load_league_data(lf)["match_id"]==mid].copy()

def filter_by_period(df, period):
    if period=="1st": return df[df["period_id"]==1]
    if period=="2nd": return df[df["period_id"]==2]
    return df

def filter_by_minutes(df, mf, mt):
    return df[(df["time_min"]>=mf)&(df["time_min"]<=mt)]

# ── League table ───────────────────────────────────────────────────────
def compute_league_table(lf, up_to_week=None, venue="all"):
    ck = f"leaguetable_{lf}_{up_to_week}_{venue}"
    if ck in _CACHE: return _CACHE[ck]
    ml = get_match_list(lf)
    if ml.empty: return pd.DataFrame()
    if up_to_week is not None: ml = ml[ml["week"]<=up_to_week]
    teams = sorted(set(ml["home_team"].tolist()+ml["away_team"].tolist())-{"Unknown"})
    table = []
    for t in teams:
        if venue == "home":
            tm = ml[ml["home_team"]==t]
        elif venue == "away":
            tm = ml[ml["away_team"]==t]
        else:
            tm = ml[(ml["home_team"]==t)|(ml["away_team"]==t)]
        p=w=d=lo=gf=ga=0; form=[]
        for _, r in tm.sort_values("week").iterrows():
            p+=1
            if r["home_team"]==t:
                gf+=r["home_goals"]; ga+=r["away_goals"]
                if r["home_goals"]>r["away_goals"]: w+=1; form.append("W")
                elif r["home_goals"]==r["away_goals"]: d+=1; form.append("D")
                else: lo+=1; form.append("L")
            else:
                gf+=r["away_goals"]; ga+=r["home_goals"]
                if r["away_goals"]>r["home_goals"]: w+=1; form.append("W")
                elif r["away_goals"]==r["home_goals"]: d+=1; form.append("D")
                else: lo+=1; form.append("L")
        table.append({"Team":t,"Short":short(t),"P":p,"W":w,"D":d,"L":lo,
                      "GF":gf,"GA":ga,"GD":gf-ga,"Pts":w*3+d,"Form":form[-5:]})
    result = pd.DataFrame(table).sort_values(["Pts","GD","GF"],ascending=[False,False,False]).reset_index(drop=True)
    _CACHE[ck] = result
    return result

# ── Match stats ────────────────────────────────────────────────────────
def compute_match_stats(lf, mid, period="all", min_from=0, min_to=120):
    mdf = get_match_data(lf, mid)
    if mdf.empty: return {}
    full = mdf.copy()
    mdf = filter_by_period(mdf, period)
    mdf = filter_by_minutes(mdf, min_from, min_to)
    hn = _safe_first(full[full["team_position"]=="home"],"team_name","Home")
    an = _safe_first(full[full["team_position"]=="away"],"team_name","Away")
    stats = {}
    for label, team in [("home",hn),("away",an)]:
        tdf = mdf[mdf["team_name"]==team]
        passes = tdf[tdf["event"]=="Pass"]
        shots = tdf[tdf["event"].isin(["Goal","Miss","Post","Saved Shot"])]
        stats[label] = {
            "team":team, "goals":len(tdf[tdf["event"]=="Goal"]),
            "shots":len(shots), "shots_on_target":len(tdf[tdf["event"].isin(["Goal","Saved Shot"])]),
            "passes":len(passes), "pass_accuracy":round(passes["outcome"].mean()*100,1) if len(passes)>0 else 0,
            "tackles":len(tdf[tdf["event"]=="Tackle"]),
            "interceptions":len(tdf[tdf["event"]=="Interception"]),
            "fouls":len(tdf[(tdf["event"]=="Foul")&(tdf["outcome"]==0)]),
            # Corners = passes flagged 'Corner taken' (actual corners the team took).
            # NOT 'Corner Awarded' — that event fires for both teams (awarded +
            # conceded), so it double-counts. Verified: Corner Awarded gave 20/20
            # for a 20-corner match; Corner taken gives the correct per-team split.
            "corners":int(_safe_col(tdf[tdf["event"]=="Pass"],"Corner taken").apply(_is_flag_local).sum()),
            "aerials_won":len(tdf[(tdf["event"]=="Aerial")&(tdf["outcome"]==1)]),
            "clearances":len(tdf[tdf["event"]=="Clearance"]),
            "recoveries":len(tdf[tdf["event"]=="Ball recovery"]),
            "take_ons":len(tdf[tdf["event"]=="Take On"]),
            "yellow_cards":len(tdf[(tdf["event"]=="Card")&(_safe_col(tdf,"Yellow Card").apply(_is_flag_local))]),
            "red_cards":len(tdf[(tdf["event"]=="Card")&(_safe_col(tdf,"Red Card").apply(_is_flag_local))]),
            "big_chances":int(_safe_col(shots,"Big Chance").apply(_is_flag_local).sum()),
            "long_balls":int(_safe_col(passes,"Long ball").apply(_is_flag_local).sum()),
            "crosses":int(_safe_col(passes,"Cross").apply(_is_flag_local).sum()),
            "through_balls":int(_safe_col(passes,"Through ball").apply(_is_flag_local).sum()),
            "tackle_success":round(tdf[tdf["event"]=="Tackle"]["outcome"].mean()*100,1) if len(tdf[tdf["event"]=="Tackle"])>0 else 0,
            "take_on_success":round(tdf[tdf["event"]=="Take On"]["outcome"].mean()*100,1) if len(tdf[tdf["event"]=="Take On"])>0 else 0,
        }
    # ── Canonical score override (own-goal-aware, Wyscout-true) ──
    # The raw per-team Goal-event count mis-credits own goals. For the FULL match
    # (no minute/half filter), replace goals with the canonical scoreline so the
    # Match Center banner and winner are always correct.
    if period == "all" and min_from <= 0 and min_to >= 120:
        try:
            ml = get_match_list(lf)
            row = ml[ml["match_id"] == mid]
            if not row.empty:
                r = row.iloc[0]
                # Match by canonical names so home/away orientation is correct
                if normalize_team(hn) == r["home_team"]:
                    stats["home"]["goals"] = int(r["home_goals"])
                    stats["away"]["goals"] = int(r["away_goals"])
                else:
                    stats["home"]["goals"] = int(r["away_goals"])
                    stats["away"]["goals"] = int(r["home_goals"])
                stats["home"]["score_source"] = "Wyscout/registry"
        except Exception:
            pass
    return stats

# ── Player stats ───────────────────────────────────────────────────────
def get_player_stats(lf, team_name=None):
    if team_name:
        # Public data functions accept league, cup, short-name, and raw provider
        # team labels. Unknown/non-Ligue 1 cup clubs are valid; do not silently
        # drop them or warn unless downstream QA explicitly requests it.
        team_name = normalize_team(team_name)
    ck = f"playerstats_{lf}_{team_name}"
    if ck in _CACHE: return _CACHE[ck]
    df = load_league_data(lf)
    if df.empty: return pd.DataFrame()
    if team_name: df = df[df["team_name"]==team_name]
    dp = df[df["player_name"].notna()].copy()
    if dp.empty: return pd.DataFrame()
    # ── Vectorized aggregation (replaces the slow per-player Python loop) ──
    # Precompute boolean/event-indicator columns once, then a single groupby.
    dp = dp.copy()
    ev = dp["event"].astype(str)
    dp["_is_goal"] = (ev == "Goal")
    dp["_is_shot"] = ev.isin(["Goal","Miss","Post","Saved Shot"])
    dp["_is_sot"] = ev.isin(["Goal","Saved Shot"])
    dp["_is_pass"] = (ev == "Pass")
    dp["_is_tackle"] = (ev == "Tackle")
    dp["_is_int"] = (ev == "Interception")
    dp["_is_takeon"] = (ev == "Take On")
    dp["_is_recovery"] = (ev == "Ball recovery")
    dp["_is_clearance"] = (ev == "Clearance")
    dp["_is_aerial_won"] = (ev == "Aerial") & (dp["outcome"] == 1)
    dp["_is_foul_lost"] = (ev == "Foul") & (dp["outcome"] == 0)
    dp["_is_card"] = (ev == "Card")
    dp["_assist_goal"] = (_safe_col(dp, "Assist") == 16)
    dp["_pass_out"] = dp["outcome"].where(dp["_is_pass"])             # NaN for non-passes
    dp["_takeon_out"] = dp["outcome"].where(dp["_is_takeon"])
    # Key passes: provider has no clean flag ("Leading to attempt" is on
    # Error/Deleted rows), so we infer them (last completed same-team pass
    # before a shot). Computed below after aggregation; placeholder here.
    dp["_key_pass"] = False
    # ── Real per-shot xG estimate (vectorized) and progressive-pass flag ──
    # xG: same distance/angle model used elsewhere, computed vectorized here so
    # the player aggregate carries TRUE estimated xG (not 'shots' relabelled).
    _sx = pd.to_numeric(dp["x"], errors="coerce")
    _sy = pd.to_numeric(dp["y"], errors="coerce")
    _dist = np.sqrt((100 - _sx) ** 2 + ((_sy - 50) * 0.68) ** 2)
    _xg = (0.40 * np.exp(-0.11 * _dist)).clip(0, 0.99)
    _is_head = _safe_col(dp, "Head").apply(_is_flag_local) if "Head" in dp.columns else False
    _is_bigchance = _safe_col(dp, "Big Chance").apply(_is_flag_local) if "Big Chance" in dp.columns else False
    _xg = _xg.where(~_is_head, _xg * 0.7)
    _xg = _xg.where(~_is_bigchance, _xg.clip(lower=0.35))
    dp["_xg"] = _xg.where(dp["_is_shot"], 0.0).fillna(0.0)
    # Progressive pass: completed pass moving the ball >=10 toward goal (x up)
    _pex = pd.to_numeric(_safe_col(dp, "Pass End X"), errors="coerce")
    dp["_prog_pass"] = (dp["_is_pass"] & (dp["outcome"] == 1) & ((_pex - _sx) >= 10)).fillna(False)
    # ── GK-specific flags (saves, claims, sweeper actions) ──
    dp["_save"] = dp["event"].isin(["Save", "Keeper Save"])
    dp["_claim"] = dp["event"].isin(["Claim", "Punch", "Keeper pick-up", "Smother"])
    dp["_sweeper"] = (dp["event"] == "Keeper Sweeper")
    yc = _safe_col(dp, "Yellow Card"); rc = _safe_col(dp, "Red Card")
    dp["_yellow"] = dp["_is_card"] & yc.apply(_is_flag_local)
    dp["_red"] = dp["_is_card"] & rc.apply(_is_flag_local)
    jn = pd.to_numeric(_safe_col(dp, "Jersey Number"), errors="coerce")
    dp["_jersey"] = jn

    g = dp.groupby(["player_id","player_name","team_name"], observed=True)
    agg = g.agg(
        matches=("match_id","nunique"),
        goals=("_is_goal","sum"),
        assists=("_assist_goal","sum"),
        shots=("_is_shot","sum"),
        shots_on_target=("_is_sot","sum"),
        xg=("_xg","sum"),
        prog_passes=("_prog_pass","sum"),
        saves=("_save","sum"),
        claims=("_claim","sum"),
        sweeper_actions=("_sweeper","sum"),
        passes=("_is_pass","sum"),
        _pass_acc=("_pass_out","mean"),
        key_passes=("_key_pass","sum"),
        tackles=("_is_tackle","sum"),
        interceptions=("_is_int","sum"),
        take_ons=("_is_takeon","sum"),
        _takeon_acc=("_takeon_out","mean"),
        recoveries=("_is_recovery","sum"),
        clearances=("_is_clearance","sum"),
        aerials_won=("_is_aerial_won","sum"),
        fouls_committed=("_is_foul_lost","sum"),
        yellow_cards=("_yellow","sum"),
        red_cards=("_red","sum"),
        _jersey=("_jersey","first"),
    ).reset_index()

    # Position = mode per player (vectorized; cast to str to avoid categorical setitem issues)
    pos_src = dp.dropna(subset=["position"]).copy()
    pos_src["position"] = pos_src["position"].astype("object")
    pos_df = (pos_src
                .groupby(["player_id","player_name","team_name"], observed=True)["position"]
                .agg(lambda s: s.mode().iloc[0] if len(s.mode()) else "?")
                .reset_index())
    agg = agg.merge(pos_df, on=["player_id","player_name","team_name"], how="left")

    agg["position"] = agg["position"].astype("object").fillna("?")

    # ── Canonical position (override > … > event mode) ──
    # Keep the raw event-mode position for QA, then resolve canonical.
    agg["event_position"] = agg["position"]
    try:
        from components.player_positions import canonical_player_position
        canon = agg.apply(lambda r: canonical_player_position(
            r["player_id"], r["player_name"], r["team_name"], r["event_position"]), axis=1)
        agg["position"] = [c["position"] for c in canon]
        agg["position_group"] = [c["group"] for c in canon]
        agg["position_source"] = [c["source"] for c in canon]
        agg["position_confidence"] = [c["confidence"] for c in canon]
        agg["position_mismatch"] = [c["mismatch"] for c in canon]
    except Exception:
        agg["position_group"] = agg["position"]
        agg["position_source"] = "Event data fallback"
        agg["position_confidence"] = "low"
        agg["position_mismatch"] = False

    agg["team_short"] = agg["team_name"].map(short)
    agg["jersey"] = agg["_jersey"].fillna(0).astype(int)
    agg["pass_accuracy"] = (agg["_pass_acc"]*100).round(1).fillna(0)
    agg["take_on_success"] = (agg["_takeon_acc"]*100).round(1).fillna(0)
    agg = agg.drop(columns=["_pass_acc","_takeon_acc","_jersey"])

    # ── Inferred key passes (provider lacks a clean flag) ──
    # Use the cached, vectorized league-wide table and map by player_id, so this
    # is O(1) lookups regardless of team filter (no per-call recomputation).
    try:
        from components.metric_engine import build_inferred_key_pass_table
        full_df = df if not team_name else load_league_data(lf)
        kp_table = build_inferred_key_pass_table(full_df)
        agg["key_passes"] = agg["player_id"].map(kp_table).fillna(0).astype(int)
        agg["key_pass_source"] = "inferred"
    except Exception:
        agg["key_passes"] = 0
        agg["key_pass_source"] = "unavailable"

    # Int-cast count columns
    for c in ["matches","goals","assists","shots","shots_on_target","passes","key_passes",
              "tackles","interceptions","take_ons","recoveries","clearances","aerials_won",
              "fouls_committed","yellow_cards","red_cards"]:
        agg[c] = agg[c].astype(int)

    result = agg.sort_values("goals",ascending=False).reset_index(drop=True)
    _CACHE[ck] = result
    return result

# ── Lineup ─────────────────────────────────────────────────────────────
def get_match_lineup(lf, mid):
    mdf = get_match_data(lf, mid)
    if mdf.empty: return {"home":{"team":"?","formation":"?","players":[]},"away":{"team":"?","formation":"?","players":[]}}
    result = {}
    for side in ["home","away"]:
        sd = mdf[mdf["team_position"]==side]
        if sd.empty: result[side]={"team":"?","formation":"?","players":[]}; continue
        tn = _safe_first(sd,"team_name","?")
        fms = sd["formation"].dropna().unique()
        fs = str(int(fms[0])) if len(fms)>0 else "?"
        pls = sd[sd["player_name"].notna()]
        if pls.empty: result[side]={"team":tn,"formation":fs,"players":[]}; continue
        ps = pls.groupby("player_name", observed=True).agg(
            position=("position",lambda x: x.mode().iloc[0] if len(x.mode())>0 else "?"),
            jersey=("Jersey Number","first"), min_time=("time_min","min"),
            events=("event","count"), is_sub=("event",lambda x:"Player on" in x.values),
        ).reset_index()
        starters = ps[(~ps["is_sub"])&(ps["min_time"]<=5)].sort_values("events",ascending=False).head(11)
        subs = ps[ps["is_sub"]|( ps["min_time"]>45)]
        subs = subs[~subs["player_name"].isin(starters["player_name"])].head(7)
        lineup = []
        for _,p in starters.iterrows():
            lineup.append({"name":p["player_name"],"position":p["position"],
                          "jersey":int(p["jersey"]) if pd.notna(p["jersey"]) else 0,"starter":True})
        for _,p in subs.iterrows():
            lineup.append({"name":p["player_name"],"position":p["position"],
                          "jersey":int(p["jersey"]) if pd.notna(p["jersey"]) else 0,"starter":False})
        result[side] = {"team":tn,"formation":fs,"players":lineup}
    return result

# ── H2H (now includes match_id) ───────────────────────────────────────
def get_head_to_head(lf, ta, tb):
    ta = normalize_team(ta); tb = normalize_team(tb)
    ml = get_match_list(lf)
    h2h = ml[((ml["home_team"]==ta)&(ml["away_team"]==tb))|((ml["home_team"]==tb)&(ml["away_team"]==ta))].sort_values("week")
    aw=bw=dr=ag=bg=0; matches=[]
    for _, r in h2h.iterrows():
        gfa = r["home_goals"] if r["home_team"]==ta else r["away_goals"]
        gfb = r["away_goals"] if r["home_team"]==ta else r["home_goals"]
        ag+=gfa; bg+=gfb
        if gfa>gfb: aw+=1
        elif gfb>gfa: bw+=1
        else: dr+=1
        matches.append({"week":r["week"],"date":r["local_date"],"home":r["home_team"],
                        "away":r["away_team"],"home_goals":r["home_goals"],
                        "away_goals":r["away_goals"],"match_id":r["match_id"]})
    return {"team_a":ta,"team_b":tb,"a_wins":aw,"b_wins":bw,"draws":dr,
            "a_goals":ag,"b_goals":bg,"total":len(h2h),"matches":matches}

# ── Scorers / Assists / Fixtures / Results ─────────────────────────────
def get_top_scorers(lf, top_n=15):
    ck = f"topscorers_{lf}_{top_n}"
    if ck in _CACHE: return _CACHE[ck]
    ps = get_player_stats(lf)
    result = ps[ps["goals"]>0].sort_values("goals",ascending=False).head(top_n) if not ps.empty else pd.DataFrame()
    _CACHE[ck] = result
    return result

def get_top_assists(lf, top_n=15):
    ck = f"topassists_{lf}_{top_n}"
    if ck in _CACHE: return _CACHE[ck]
    ps = get_player_stats(lf)
    result = ps[ps["assists"]>0].sort_values("assists",ascending=False).head(top_n) if not ps.empty else pd.DataFrame()
    _CACHE[ck] = result
    return result

def get_week_fixtures(lf, week):
    ml = get_match_list(lf)
    return ml[ml["week"]==week].sort_values("local_date")

def get_team_results(lf, team_name):
    team_name = normalize_team(team_name)
    ck = f"teamresults_{lf}_{team_name}"
    if ck in _CACHE: return _CACHE[ck]
    ml = get_match_list(lf)
    tm = ml[(ml["home_team"]==team_name)|(ml["away_team"]==team_name)]
    results = []
    sort_cols = ["round_order", "local_date"] if "round_order" in tm.columns else ["week"]
    for _, r in tm.sort_values(sort_cols).iterrows():
        ih = r["home_team"]==team_name
        gf = r["home_goals"] if ih else r["away_goals"]
        ga = r["away_goals"] if ih else r["home_goals"]
        results.append({"week":r["week"],"round_order":r.get("round_order", r["week"]),
                        "round_name":r.get("round_name", f"Matchweek {r['week']}"),
                        "date":r["local_date"],
                        "opponent":r["away_team"] if ih else r["home_team"],
                        "venue":"H" if ih else "A","gf":gf,"ga":ga,
                        "result":"W" if gf>ga else("D" if gf==ga else "L"),
                        "match_id":r["match_id"]})
    result = pd.DataFrame(results)
    _CACHE[ck] = result
    return result
