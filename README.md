# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the hero roster from Valve's Dota 2 datafeed.
- Merges current OpenDota ranked public pick/win statistics from rank buckets `1_pick..8_pick` and `1_win..8_win`.
- Uses OpenDota hero matchup rows only as optional supplemental aggregate/pro-matchup evidence.
- Scores candidates separately for positions 1-5 with explicit position-profile gates so generic utility tags cannot easily push a wrong-role hero to the top.
- Accounts for visible team-role gaps, public win rate, sample size, and available enemy matchup evidence.
- Produces short draft tactics from the visible composition plus a position-specific lane plan.
- Retries transient API failures and does not permanently cache a failed matchup request as an empty matrix.
- Has a Windows capture foundation that enumerates real top-level windows, resolves the Dota window to an HWND, and captures that exact HWND through Windows Graphics Capture.
- Does **not** capture the whole desktop and does **not** pretend to recognize moving 3D heroes with template matching.

## Run

Python 3.11+ is enough for the manual-draft engine.

```bash
python -m dota_coach.cli --role mid --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Validate hero roster, ranked meta coverage and the optional matchup source:

```bash
python -m dota_coach.cli --health
```

Install the command locally:

```bash
python -m pip install -e .
dota-coach --role 3 --enemies "Puck,Anti-Mage"
```

For Windows HWND capture support:

```bash
python -m pip install -e ".[capture]"
```

The capture extra currently pins `windows-capture==2.0.1` and uses its `window_hwnd` target. `dota_coach.capture.capture_dota_frame()` resolves a visible Dota window first and then captures only that exact HWND. The returned BGRA frame is copied out of the native mapping before the callback exits.

## Data sources

- Valve hero roster: `https://www.dota2.com/datafeed/herolist?language=english`
- Valve patch list: `https://www.dota2.com/datafeed/patchnoteslist`
- OpenDota hero stats: `https://api.opendota.com/api/heroStats`
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

OpenDota's current `heroStats` schema exposes rank-specific pick/win buckets rather than relying on legacy `pub_pick/pub_win`. The loader aggregates ranks 1-8 and keeps the legacy fields only as a compatibility fallback.

The hero matchup endpoint is not treated as role-specific current-pub truth. Its signal is capped below position fit and labeled as `pro-матчап` in explanations. If that optional endpoint times out, recommendations fall back to position/meta/team evidence. The health command still fails if a successful response suddenly contains too little usable data, which catches schema/data regressions without making transient transport outages fail CI.

## Architecture

```text
manual draft input                         Windows Dota window
      |                                          |
      |                                    HWND enumeration
      |                                          |
      |                                    WGC exact-window frame
      |                                          |
      |                                  [next: draft layout/ROIs]
      |                                          |
      +-------------------- future recognized picks/bans
      |
      v
Valve roster + OpenDota ranked meta
      |
      v
normalized Hero model
      |
      +--> position profile gate + weighted role fit
      +--> team role gaps
      +--> ranked public WR + sample confidence
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

1. Capture and save representative **draft-screen** frames from the exact Dota HWND at 16:9 and 16:10.
2. Define normalized draft-layout anchors and pick/ban portrait ROIs from those real frames; do not hard-code desktop coordinates.
3. Add a layout validator that rejects non-draft screens before hero recognition.
4. Build a dedicated portrait classifier/embedding index for the cropped slots; do not search the moving world scene.
5. Return `slot -> hero + confidence`, and feed only high-confidence picks/bans into the existing engine.
6. Keep manual selection as fallback for low-confidence/unknown slots.
7. Add saved-frame regression tests before building any live overlay.

The immediate blocker for this slice is not code architecture anymore; it is obtaining representative current draft-screen frames so ROI coordinates are derived from the real UI instead of guessed.
