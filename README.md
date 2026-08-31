# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the hero roster from Valve's Dota 2 datafeed.
- Uses OpenDota's explicit rolling **7-day** `pub_pick/pub_win` sample for the default `all` meta instead of incorrectly summing medal buckets.
- Can score the same rolling 7-day meta for a selected bracket using `1_pick..8_pick` and `1_win..8_win`: Herald, Guardian, Crusader, Archon, Legend, Ancient, Divine or Immortal.
- Loads OpenDota `scenarios/laneRoles` per lane and uses observed safelane/mid/offlane shares as supplemental position evidence instead of relying only on broad `Carry`/`Support`/`Nuker` tags.
- Queries lane roles separately because OpenDota's implementation limits the lane-role query to 1200 rows; this avoids silently truncating a combined all-lanes sample.
- Uses OpenDota hero matchup rows only as optional supplemental aggregate evidence. The upstream endpoint currently covers the **last year**, so it is not presented as patch-, role- or bracket-specific truth.
- Scores candidates separately for positions 1-5 with explicit position-profile gates, diminishing returns for multi-tag heroes, capped team-gap bonuses and mild redundancy penalties. This prevents flexible heroes from reaching `99` simply because they have many generic tags.
- Accounts for visible team-role gaps, selected-bracket win rate, sample size, observed lane share, optional matchup evidence, and a deliberately weak composition fallback.
- Rejects impossible manual drafts such as the same hero appearing on both teams or more than five heroes per team.
- Produces short draft tactics from the visible composition plus a position-specific lane plan. It also calls out greedy multi-carry drafts and drafts that lack late carry potential.
- Retries transient API failures and does not permanently cache failed matchup/lane-role requests as empty matrices.
- Preserves OpenDota `img` and `icon` references on each `Hero` as reference assets for the upcoming portrait classifier.
- Has a Windows capture foundation that enumerates real top-level windows, resolves the Dota window to an HWND, and captures that exact HWND through Windows Graphics Capture.
- Can save a real Dota client frame directly to PNG for draft-layout calibration without calling Valve/OpenDota and without OpenCV.
- Does **not** capture the whole desktop and does **not** pretend to recognize moving 3D heroes with template matching.

## Run

Python 3.11+ is enough for the manual-draft engine.

```bash
python -m dota_coach.cli --role mid --rank legend --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Available rank selectors: `all`, `herald`, `guardian`, `crusader`, `archon`, `legend`, `ancient`, `divine`, `immortal` (or numbers 1-8). `all` means OpenDota's explicit all-public sample, not a sum of medal buckets.

Validate hero roster, rank-bucket meta coverage, lane-role evidence and the optional matchup source:

```bash
python -m dota_coach.cli --health
```

The CLI prints the source windows explicitly: `heroStats` is a rolling 7-day sample and hero matchups are a rolling one-year aggregate according to the current upstream OpenDota implementation.

Install the command locally:

```bash
python -m pip install -e .
dota-coach --role 3 --rank ancient --enemies "Puck,Anti-Mage"
```

For Windows HWND capture support:

```bash
python -m pip install -e ".[capture]"
```

While the real Dota draft screen is open, save an exact-window calibration frame:

```bash
dota-coach --capture-draft captures/draft_169.png
```

`--capture-draft` resolves the visible Dota window, targets its exact HWND through Windows Graphics Capture, and calls the capture backend's native `Frame.save_as_image()` while the frame is valid. It deliberately bypasses network data loading so screenshot collection still works if Valve/OpenDota is unavailable.

## Data sources

- Valve hero roster: `https://www.dota2.com/datafeed/herolist?language=english`
- Valve patch list: `https://www.dota2.com/datafeed/patchnoteslist`
- OpenDota hero stats: `https://api.opendota.com/api/heroStats`
- OpenDota lane roles: `https://api.opendota.com/api/scenarios/laneRoles?lane_role={lane_role}`
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

OpenDota's current `heroStats` implementation sums seven UTC day buckets. It exposes explicit `pub_pick/pub_win` fields for the all-public population and medal-specific fields `1_*` Herald, `2_*` Guardian, `3_*` Crusader, `4_*` Archon, `5_*` Legend, `6_*` Ancient, `7_*` Divine, `8_*` Immortal. Dota Coach now keeps those populations separate: default `all` uses `pub_*`, while a selected medal uses its own tier bucket. Summing tier buckets remains only a compatibility fallback for old/cached payloads that do not contain `pub_*`. The same response provides `img` and `icon` reference paths used as classifier groundwork.

`scenarios/laneRoles` provides `hero_id`, `lane_role`, `time`, `games` and `wins`. Dota Coach aggregates the time buckets per hero/lane and uses lane share only after all three normal lane samples are available, preventing a partial response from creating a biased denominator. Lane-role data is aggregate and does not distinguish position 1 from 5 or position 3 from 4, so explicit role tags still decide farm-priority fit while lane data acts only as supporting evidence. The upstream query currently has `LIMIT 1200`, which is why Dota Coach requests one lane at a time.

The hero matchup endpoint currently queries matches from the last year. Its `wins` field belongs to the hero whose endpoint was requested. Dota Coach requests each visible enemy once, stores that enemy's results versus every opposing hero, and inverts the queried enemy's win rate to obtain candidate-vs-enemy evidence. This keeps network calls low while preserving the endpoint's direction correctly. Matchup influence is capped below position fit because the source is not role-, medal- or current-patch-specific.

If optional OpenDota lane-role or matchup endpoints time out, recommendations fall back to role fit, 7-day meta, team gaps and composition evidence.

## Architecture

```text
manual draft input                         Windows Dota window
      |                                          |
      |                                    HWND enumeration
      |                                          |
      |                                    WGC exact-window frame
      |                                          |
      |                                    PNG calibration capture
      |                                          |
      |                                  [next: draft layout/ROIs]
      |                                          |
      +-------------------- future recognized picks/bans
      |
      v
Valve roster + OpenDota 7d public/medal meta + lane-role scenarios
      |
      v
normalized Hero model (+ portrait/icon reference paths)
      |
      +--> position profile gate + weighted role fit
      +--> observed lane-role share
      +--> team role gaps + redundancy control
      +--> selected 7d public/medal WR + sample confidence
      +--> weak enemy-role fallback
      +--> capped optional 1y aggregate matchup evidence
      |
      v
ranked picks + position-aware tactical notes
```

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs deterministic tests on Linux and Windows. Tests cover position/rank scoring, correct `pub_*` vs medal-bucket semantics, matchup direction inversion, lane-role parsing and scoring, score-saturation regression, matchup fallbacks, draft validation, tactics and exact Dota-window selection. Linux verifies live Valve/OpenDota core sources plus lane-role coverage. Windows installs the capture extra and verifies that the installed capture backend exposes exact `window_hwnd` targeting.

## Next concrete step

Continue issue **MVP-2: draft-screen ingestion without full-screen template matching** with the layout/classification slice:

1. Use `dota-coach --capture-draft ...` to collect current draft-screen frames at **16:9** and **16:10** from the exact Dota HWND.
2. Define normalized draft-layout anchors and pick/ban portrait ROIs from those real frames; do not hard-code desktop coordinates.
3. Add a layout validator that rejects non-draft screens before hero recognition.
4. Build a dedicated portrait classifier/embedding index using the current OpenDota `img`/`icon` reference paths; do not search the moving world scene.
5. Return `slot -> hero + confidence`, and feed only high-confidence picks/bans into the existing engine.
6. Keep manual selection as fallback for low-confidence/unknown slots.
7. Add saved-frame regression tests for at least 16:9 and 16:10 before building any live overlay.

The remaining blocker for automatic draft ingestion is representative current draft-screen imagery. The project already contains the exact-HWND PNG capture command needed to obtain those frames without guessing ROI coordinates.
