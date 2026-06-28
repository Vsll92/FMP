# Player Position Overrides

`player_positions_ligue1_2025_26.csv` is the **authoritative position source**
for the dashboard. Event-data position (the modal `position` qualifier on a
player's events) is unreliable — it mislabels e.g. O. Édouard (a striker) as
CAM — so it is used only as a last-resort fallback.

## Position source priority (highest first)
1. This override CSV, matched by `player_id`
2. This override CSV, matched by `player_name` + `team_name_canon`
3. Wyscout / roster position (if available)
4. Lineup formation slot (if reliable)
5. Event-data modal position (last resort, flagged low confidence)

## How to populate from an authoritative source
FBref blocks automated scraping (HTTP 403) and is not in the sandbox network
allowlist, so positions cannot be fetched live. To populate this file:

1. Open the FBref Ligue 1 Standard / Playing Time table:
   https://fbref.com/en/comps/13/playingtime/Ligue-1-Stats#all_stats_playing_time
   (or the Transfermarkt squad page for each club).
2. Copy the Player and Pos columns into a sheet.
3. Map each FBref/Transfermarkt position to `primary_position` and fill
   `position_group` using the mapping below.
4. Set `source` (FBref / Transfermarkt / Wyscout), `source_url`, and
   `confidence` (high / medium / low).
5. Leave `player_id` blank to match by name+team, or fill it for an exact match.

## Position-group normalization
| External codes                | position_group |
|-------------------------------|----------------|
| FW, ST, CF                    | ST             |
| LW, RW, LM, RM, W             | Winger         |
| AM, CAM, SS, AMF              | AM             |
| CM, MF, MC, CMF               | CM             |
| DM, CDM, DMF                  | DM             |
| LB, RB, LWB, RWB, FB, WB      | FB/WB          |
| CB, DF, DC                    | CB             |
| GK                            | GK             |

## Columns
`player_name, player_id, team_name_canon, primary_position,
secondary_positions, position_group, source, source_url, confidence, notes`

Rows currently present are source-confirmed corrections for the most-used club
(RC Lens) plus any player whose event position is clearly wrong. Add more rows
to raise coverage; the loader merges them automatically and the release-QA
"position mismatch" check lists players whose event position differs from
canonical.
