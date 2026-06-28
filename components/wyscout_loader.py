"""
components/wyscout_loader.py — Wyscout team-stat exports → clean team-match df.

The Wyscout upload is a folder of per-team Excel files. Each team has up to 5
files representing different stat groups (base, attacking, defensive, passing,
tempo/PPDA). Within a file, "X / Y" headers spill values into following
`Unnamed:` columns (e.g. "Shots / on target" → col N = shots, col N+1 = on target).

Rows 0-1 of each sheet are header junk ("<Team>" / "Opponents"); real match rows
start at row 2 and alternate team / opponent for each fixture.

This loader:
  - reads every file, keeps only real match rows (valid Date)
  - extracts the split "X / Y" columns by position
  - consolidates the 5 groups per team-match into one row
  - canonicalizes team names via the project's normalize_team (PSG != Paris FC)
  - deduplicates team-match rows (a fixture appears in both teams' files)
  - parses the "Home - Away H:A" Match string into home/away + score
  - returns one tidy team-match dataframe + a QA report

IMPORTANT: This is TEAM-LEVEL data. Wyscout xG here is a team match total, NOT
shot-level or player-level xG. Never present it as shot/player xG.
"""
import os
import re
import glob
import pandas as pd
import numpy as np

try:
    from data_loader import normalize_team
except Exception:
    def normalize_team(x):
        return x

# Map of stat-group → (header label in file, output column, offset for paired value)
# Offset 0 = the labelled column itself; 1 = the next Unnamed col, etc.
_SPLIT_FIELDS = {
    # base file
    "Goals": [("wyscout_goals", 0)],
    "xG": [("wyscout_xg", 0)],
    "Shots / on target": [("wyscout_shots", 0), ("wyscout_shots_on_target", 1)],
    "Passes / accurate": [("wyscout_passes", 0), ("wyscout_accurate_passes", 1)],
    "Possession, %": [("wyscout_possession_pct", 0)],
    # defensive file (2)
    "Conceded goals": [("wyscout_conceded_goals", 0)],
    "Shots against / on target": [("wyscout_shots_against", 0), ("wyscout_shots_against_on_target", 1)],
    # passing file (3)
    "Forward passes / accurate": [("wyscout_forward_passes", 0), ("wyscout_forward_passes_acc", 1)],
    "Long passes / accurate": [("wyscout_long_passes", 0), ("wyscout_long_passes_acc", 1)],
    "Passes to final third / accurate": [("wyscout_passes_final_third", 0), ("wyscout_passes_final_third_acc", 1)],
    "Progressive passes / accurate": [("wyscout_progressive_passes", 0), ("wyscout_progressive_passes_acc", 1)],
    # attacking file (1)
    "Positional attacks / with shots": [("wyscout_positional_attacks", 0), ("wyscout_positional_attacks_shots", 1)],
    "Counterattacks / with shots": [("wyscout_counterattacks", 0), ("wyscout_counterattacks_shots", 1)],
    "Corners / with shots": [("wyscout_corners", 0), ("wyscout_corners_with_shots", 1)],
    # tempo file (4) — these are plain single-value columns
    "Match tempo": [("wyscout_match_tempo", 0)],
    "Average passes per possession": [("wyscout_avg_passes_per_possession", 0)],
    "Long pass %": [("wyscout_long_pass_pct", 0)],
    "PPDA": [("wyscout_ppda", 0)],
    "Average shot distance": [("wyscout_avg_shot_distance", 0)],
    "Average pass length": [("wyscout_avg_pass_length", 0)],
}

# Plain single-value columns we also keep when present
_PLAIN_FIELDS = {
    "Scheme": "scheme",
}


def _team_from_filename(path):
    name = os.path.basename(path).replace("Team Stats ", "").replace(".xlsx", "")
    name = re.sub(r"\s*\(\d+\)\s*", "", name).strip()
    return name


def _parse_match_string(s):
    """'Olympique Lyonnais - Lens 0:4' → (home, away, hg, ag)."""
    if not isinstance(s, str):
        return None, None, None, None
    m = re.match(r"^(.*?)\s*-\s*(.*?)\s+(\d+):(\d+)\s*$", s.strip())
    if not m:
        return None, None, None, None
    return m.group(1).strip(), m.group(2).strip(), int(m.group(3)), int(m.group(4))


def _extract_file(path):
    """Read one Wyscout file, return rows of {Date, Match, Team, <fields>}."""
    raw = pd.read_excel(path, header=None)
    if raw.shape[0] < 3:
        return []
    header = raw.iloc[0].tolist()
    # Build column-index → label map from row 0
    label_at = {i: (str(header[i]).strip() if pd.notna(header[i]) else "") for i in range(len(header))}

    # Locate the base columns (Date/Match/Competition/Duration/Team/Scheme)
    base_idx = {}
    for i, lbl in label_at.items():
        if lbl in ("Date", "Match", "Competition", "Duration", "Team", "Scheme"):
            base_idx[lbl] = i

    # Locate split/plain stat fields by their header label
    field_cols = {}  # out_col → absolute column index
    for label, specs in _SPLIT_FIELDS.items():
        for i, lbl in label_at.items():
            if lbl == label:
                for out_col, offset in specs:
                    field_cols[out_col] = i + offset
                break

    rows = []
    for r in range(1, raw.shape[0]):
        date_val = raw.iloc[r, base_idx.get("Date", 0)] if "Date" in base_idx else None
        # Real match rows have an ISO-like date
        if not isinstance(date_val, (str,)) and not hasattr(date_val, "year"):
            # could be Timestamp
            if pd.isna(date_val):
                continue
        ds = str(date_val)
        if not re.match(r"^\d{4}-\d{2}-\d{2}", ds):
            continue
        team = raw.iloc[r, base_idx["Team"]] if "Team" in base_idx else None
        if pd.isna(team):
            continue
        rec = {"Date": ds[:10], "Team": str(team).strip(),
               "Match": str(raw.iloc[r, base_idx["Match"]]).strip() if "Match" in base_idx else ""}
        if "Scheme" in base_idx:
            rec["scheme"] = raw.iloc[r, base_idx["Scheme"]]
        for out_col, idx in field_cols.items():
            if idx < raw.shape[1]:
                v = raw.iloc[r, idx]
                rec[out_col] = pd.to_numeric(v, errors="coerce")
        rows.append(rec)
    return rows


def load_wyscout_team_matches(wyscout_dir):
    """Consolidate all Wyscout files into one team-match dataframe + QA report."""
    files = glob.glob(os.path.join(wyscout_dir, "*.xlsx"))
    qa = {"files_read": 0, "rows_extracted": 0, "team_matches": 0,
          "duplicates_dropped": 0, "unmapped_teams": [], "teams": 0}
    if not files:
        return pd.DataFrame(), qa

    all_rows = []
    for f in files:
        try:
            rows = _extract_file(f)
            all_rows.extend(rows)
            qa["files_read"] += 1
        except Exception as e:
            print(f"[WYSCOUT_QA] Failed reading {os.path.basename(f)}: {e}")
    if not all_rows:
        return pd.DataFrame(), qa

    df = pd.DataFrame(all_rows)
    qa["rows_extracted"] = len(df)

    # Canonicalize team names
    df["team_name_raw"] = df["Team"]
    df["team_name_canon"] = df["Team"].map(lambda v: normalize_team(v) if pd.notna(v) else v)
    unmapped = sorted({r for r, c in zip(df["team_name_raw"], df["team_name_canon"]) if r == c and r not in (
        "Olympique Lyonnais",)} - set(df["team_name_canon"]))
    # (light unmapped check; normalize_team returns input unchanged if unknown)

    # Parse match string → home/away/score
    parsed = df["Match"].map(_parse_match_string)
    df["home_team_raw"] = [p[0] for p in parsed]
    df["away_team_raw"] = [p[1] for p in parsed]
    df["home_goals"] = [p[2] for p in parsed]
    df["away_goals"] = [p[3] for p in parsed]
    df["home_team_canon"] = df["home_team_raw"].map(lambda v: normalize_team(v) if pd.notna(v) else v)
    df["away_team_canon"] = df["away_team_raw"].map(lambda v: normalize_team(v) if pd.notna(v) else v)

    # Determine opponent + team goals from perspective of the row's team
    def _opp(row):
        if row["team_name_canon"] == row["home_team_canon"]:
            return row["away_team_canon"], row["home_goals"], row["away_goals"]
        return row["home_team_canon"], row["away_goals"], row["home_goals"]
    opp = df.apply(_opp, axis=1, result_type="expand")
    df["opponent_name_canon"] = opp[0]
    df["team_goals"] = opp[1]
    df["opponent_goals"] = opp[2]

    # Consolidate the 5 stat groups: group by (date, team), combine non-null fields
    key = ["Date", "team_name_canon"]
    agg = {}
    for c in df.columns:
        if c in key:
            continue
        agg[c] = "first"
    # For numeric stat columns, take max of non-null (groups don't overlap, so first non-null)
    grouped = df.groupby(key, as_index=False).agg(
        {c: (lambda s: s.dropna().iloc[0] if s.dropna().size else np.nan) for c in df.columns if c not in key})

    before = len(df)
    qa["team_matches"] = len(grouped)
    qa["duplicates_dropped"] = before - len(grouped)
    qa["teams"] = grouped["team_name_canon"].nunique()
    grouped["source_status"] = "wyscout"
    grouped = grouped.rename(columns={"Date": "date"})
    return grouped, qa


def wyscout_lookup(wy_df, date, home_canon, away_canon):
    """Return (team_row, opp_row) dicts for a fixture, or (None, None)."""
    if wy_df is None or wy_df.empty:
        return None, None
    sub = wy_df[(wy_df["date"] == str(date)[:10])]
    home = sub[sub["team_name_canon"] == home_canon]
    away = sub[sub["team_name_canon"] == away_canon]
    h = home.iloc[0].to_dict() if not home.empty else None
    a = away.iloc[0].to_dict() if not away.empty else None
    return h, a
