# KPI Definitions

This document defines the key metrics used by Football Analytics Pro. Every metric is labelled by source and trust level.

## Source Types

| Source | Meaning |
|---|---|
| Wyscout | Provider team-match export. Used for official team-level xG, xGA, PPDA, possession and selected box-score metrics where available. |
| Event Data | Computed directly from Opta-style event CSV rows. |
| Estimated | Modelled internally from event location/qualifiers, not official provider data. |
| Inferred | Reconstructed from event sequences where no direct provider flag exists. |
| Unavailable | Not supported by the current event schema. |

---

## Goals and Scores

**Source:** Match registry.  
**Priority:** Wyscout official score → event-derived score with own-goal handling → filename fallback.  
**Use:** Match Center, H2H, reports, cup overview, trends.

Own goals are assigned to the opponent where event-feed convention requires correction. Score conflicts should be surfaced as QA warnings.

---

## Wyscout xG / xGA

**Source:** Wyscout team-match export.  
**Definition:** Official expected goals and expected goals against supplied by Wyscout.  
**Use:** Team KPI cards, report headline KPIs, season comparisons.  
**Trust:** High within Wyscout methodology.

### Caveat
Do not mix Wyscout xG with Estimated Event xG. They are different models.

---

## Estimated Event xG

**Source:** Internal event-based model.  
**Definition:** Shot-level estimate using shot coordinates and selected qualifiers.  
**Use:** Shot maps, xG by context, estimated xG timelines.  
**Trust:** Directional, not official.

### Important report rule
Reports must label:

- `Wyscout xG` for official provider values.
- `Estimated Event xG` for context charts and shot-map sums.

If the two differ, show a reconciliation note.

---

## PPDA

**Source:** Wyscout where available.  
**Definition:** Passes allowed per defensive action.  
**Interpretation:** Lower PPDA generally means a more aggressive press.

### Direction
Lower is usually better for pressing intensity, but context matters. A team leading comfortably may intentionally stop pressing.

---

## Wyscout Possession %

**Source:** Wyscout.  
**Definition:** Provider possession percentage.  
**Use:** Only this metric may be called `Possession`.

---

## Pass Share %

**Source:** Event Data.  
**Definition:** Team completed passes divided by both teams' completed passes.  
**Use:** Proxy for control when true possession is unavailable.  
**Important:** Do not call this true possession.

---

## Field Tilt

**Source:** Event Data.  
**Definition:** Team final-third touches divided by both teams' final-third touches.  
**Interpretation:** Territorial pressure in advanced zones.

---

## Final-Third Entries

**Source:** Event Data.  
**Definition:** Valid passes/carries starting outside the final third and ending inside it.  
**Threshold:** x crosses from `< 66.67` to `>= 66.67` on a normalized 0–100 pitch.

---

## Box Entries

**Source:** Event Data.  
**Definition:** Valid passes/carries starting outside the box and ending inside the attacking box.  
**Attacking box:** x >= 83 and y between approximately 21.1 and 78.9.

---

## Progressive Passes

**Source:** Event Data.  
**Definition:** Completed passes that advance the ball significantly toward goal, commonly x gain >= 10 on the 0–100 pitch.  
**Important:** This is not total pass volume.

---

## Key Passes

**Source:** Inferred unless a direct provider flag exists.  
**Definition:** Last completed same-team pass within a short window before a shot, excluding set-piece/penalty contexts where configured.  
**Confidence:** Medium when inferred.

### Radar rule
If a key-pass peer pool has all-zero values, the metric must be excluded. It must never appear as 100% because everyone has zero.

---

## Tackles Won

**Source:** Event Data / provider flag where available.  
**Definition:** Successful tackle events.  
**Report context:** Post-match reports compare match value against team season average and league average.

---

## Interceptions

**Source:** Event Data.  
**Definition:** Defensive action that cuts out an opponent pass or possession route.  
**Context:** Higher can be positive, but many interceptions may also indicate extended defending.

---

## Recoveries

**Source:** Event Data.  
**Definition:** Ball recoveries after loose ball or possession regain.  
**Context:** Compare to team average and league average. High recoveries can reflect effective counter-pressing or long defensive phases.

---

## Clearances, Blocks, Duels, Aerials

**Source:** Event Data.  
**Use:** Defensive output, individual performance, post-match context.

### Context rule
Defensive-volume metrics are contextual. More is not always better because it may mean the team defended too deep or too often.

---

## Goal Method Distribution

**Source:** Event flags and goal events.  
**Categories:** Open play, set piece, corner, free kick, penalty, transition/counter, own goal, header/cross when available.  
**Pre-match rule:** Goal distribution should describe the selected opponent's scoring/conceding profile.  
**Post-match rule:** Goal distribution should describe the selected match/team context.

---

## Player Radar

Two modes are supported.

### Max-normalized peer scale

`radar_value = player_metric / peer_group_max * 100`

- Peer group is the player's canonical position group.
- If a player leads the peer group in a metric, that metric is 100.
- If a metric has zero peer max or zero variance, it is excluded.

### Percentile rank

Shows where the player ranks against position peers. 50 = median peer.

### Radar table requirements
Every radar row should show:

- Raw value
- Peer max
- Radar %
- Percentile
- Rank / tie status
- Source
- Confidence

---

## Individual Influence Score

**Source:** Position-specific KPI template.  
**Definition:** Weighted score based on role-relevant metrics.  
**Examples:**

- GK: distribution, sweeper actions, goals conceded context if save data unavailable.
- CB: aerials, blocks, clearances, interceptions, progressive passing.
- FB/WB: crosses, recoveries, progressive carries, defensive actions.
- DM/CM/AM: progression, recoveries, key passes, final-third involvement by role.
- Winger/ST: xG, shots, box touches, key passes, take-ons, pressing contribution.

### Rule
GK, CB, midfielders and forwards must not be evaluated with the same universal metric set.

---

## Touch Map

**Source:** Event Data after valid-event filtering.  
**Valid touch events:** football-relevant spatial actions.  
**Excluded:** out-of-play events, admin rows, substitutions, deleted events, null coordinates, out-of-bounds coordinates.

### Validation
Displayed zone counts must equal plotted valid events. Map footer should show plotted and excluded rows.

---

## Pitch Zones

**Source:** Central zone model.  
**Thirds:**

- Defensive third: x < 33.33
- Middle third: 33.33 <= x < 66.67
- Attacking third: x >= 66.67

**Lanes:** Wide Left, Left Half-Space, Central, Right Half-Space, Wide Right.  
**Rule:** Every pitch map should use the same zone model.

---

## Threat / Weakness Engine

**Source:** team metrics normalized against league/sample benchmarks.  
**Definition:** Top threat/weakness should be selected by percentile, direction, sample confidence, and opponent relevance.  
**Rule:** Do not choose `High xG generation` for every team unless the normalized evidence supports it.

