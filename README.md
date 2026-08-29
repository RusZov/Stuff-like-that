# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the hero roster from Valve's Dota 2 datafeed.
- Merges current OpenDota ranked public pick/win statistics from medal buckets `1_pick..8_pick` and `1_win..8_win`.
- Can score the meta for a selected bracket: Herald, Guardian, Crusader, Archon, Legend, Ancient, Divine or Immortal; `all` remains the default.
- Uses OpenDota hero matchup rows only as optional supplemental aggregate matchup evidence.
- Scores candidates separately for positions 1-5 with explicit position-profile gates so generic utility tags cannot easily push a wrong-role hero to the top.
- Accounts for visible team-role gaps, selected-bracket win rate, sample size, optional matchup evidence, and a deliberately weak composition fallback (for example, extra control into multiple Escape heroes).
- Rejects impossible manual drafts such as the same hero appearing on both teams or more than five heroes per team.
- Produces short draft tactics from the visible composition plus a position-specific lane plan.
- Retries transient API failures and does not permanently cache a failed matchup request as an empty matrix.
- Has a Windows capture foundation that enumerates real top-level windows, resolves the Dota window to an HWND, and captures that exact HWND through Windows Graphics Capture.
- Can save a real Dota client frame directly to PNG for draft-layout calibration without calling Valve/OpenDota and without OpenCV.
- Does **not** capture the whole desktop and does **not** pretend to recognize moving 3D heroes with template matching.

## Run

Python 3.11+ is enough for the manual-draft engine.

```bash
python -m dota_coach.cli --role mid --rank legend --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Available rank selectors: `all`, `herald`, `guardian`, `crusader`, `archon`, `legend`, `ancient`, `divine`, `immortal` (or numbers 1-8).

Validate hero roster, rank-bucket meta coverage and the optional matchup source:

```bash
python -m dota_coach.cli --health
```

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
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

OpenDota's current `heroStats` response defines medal-specific fields: `1_*` Herald, `2_*` Guardian, `3_*` Crusader, `4_*` Archon, `5_*` Legend, `6_*` Ancient, `7_*` Divine, `8_*` Immortal. The loader stores all eight samples and also aggregates them for the default `all` mode. Legacy `pub_pick/pub_win` fields remain only as a compatibility fallback.

The hero matchup endpoint is not treated as selected-bracket or role-specific current-pub truth. Its signal is capped below position fit and labeled as aggregate matchup evidence. If that optional endpoint times out, recommendations fall back to position, bracket-meta, team-gap and composition evidence.

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
Valve roster + OpenDota medal meta
      |
      v
normalized Hero model
      |
      +--> position profile gate + weighted role fit
      +--> team role gaps
      +--> selected-bracket WR + sample confidence
      +--> weak enemy-role fallback
      +--> capped optional OpenDota matchup evidence
      |
      v
ranked picks + position-aware tactical notes
```

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs deterministic tests on Linux and Windows. Linux verifies the live Valve/OpenDota core sources. Windows installs the capture extra and verifies that the installed capture backend exposes exact `window_hwnd` targeting.

## Next concrete step

Continue issue **MVP-2: draft-screen ingestion without full-screen template matching** with the layout/classification slice:

1. Use `dota-coach --capture-draft ...` to collect current draft-screen frames at **16:9** and **16:10** from the exact Dota HWND.
2. Define normalized draft-layout anchors and pick/ban portrait ROIs from those real frames; do not hard-code desktop coordinates.
3. Add a layout validator that rejects non-draft screens before hero recognition.
4. Build a dedicated portrait classifier/embedding index for the cropped slots; do not search the moving world scene.
5. Return `slot -> hero + confidence`, and feed only high-confidence picks/bans into the existing engine.
6. Keep manual selection as fallback for low-confidence/unknown slots.
7. Add saved-frame regression tests before building any live overlay.

The remaining blocker for automatic draft ingestion is representative current draft-screen imagery. The project now contains the exact-HWND PNG capture command needed to obtain those frames without guessing ROI coordinates.
