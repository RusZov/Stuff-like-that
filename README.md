# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the canonical hero roster and current patch label from Valve's Dota 2 datafeed.
- Uses OpenDota's rolling **7-day** `pub_pick/pub_win` sample for the default public meta.
- Supports medal-specific 7-day samples through `1_pick..8_pick` / `1_win..8_win`: Herald through Immortal.
- Loads OpenDota `scenarios/laneRoles` one lane at a time and uses observed safelane/mid/offlane share as supplemental position evidence.
- Uses OpenDota `/heroes/{id}/matchups` only as **supplemental pro/league evidence**. Current upstream SQL joins `leagues`, so this source must not be presented as public-bracket matchup truth. Its influence is deliberately capped.
- Scores positions 1-5 separately with explicit position-profile gates, diminishing returns for generic multi-role tags, team-gap bonuses, redundancy penalties, lane-role evidence and selected-bracket meta.
- Rejects impossible drafts: duplicate heroes, cross-team overlap and more than five heroes per side.
- Produces position-aware tactics from the visible composition and calls out missing control, missing initiation, greedy multi-core drafts, push pressure and other broad draft risks.
- Retries transient API failures and degrades gracefully when optional lane-role or matchup evidence is unavailable.
- Preserves OpenDota hero portrait/icon paths for the upcoming portrait classifier.
- Captures the exact Dota window on Windows through its HWND using Windows Graphics Capture; it does not capture the whole desktop.
- Saves exact-window PNG frames with `--capture-draft` for layout calibration.
- Includes a normalized `DraftLayout` model for future pick/ban slot calibration. No guessed Dota coordinates are hardcoded.

## High-level MVP API

Use `coach_draft()` for application code. It is the integration boundary for the CLI and the future screen reader: it automatically preloads optional lane-role and enemy-matchup evidence, runs recommendation scoring, calibrates extreme scores by confidence, produces tactics and returns source warnings/provenance.

```python
from dota_coach.data import DotaData
from dota_coach.service import coach_draft

data = DotaData()
data.refresh()
allies = [data.resolve("Crystal Maiden")]
enemies = [data.resolve("Axe")]
result = coach_draft(data, allies, enemies, "mid", limit=5, rank_tier="legend")

for pick in result.picks:
    print(pick.hero, pick.score, pick.confidence)
```

The lower-level `recommend()` remains available for deterministic engine testing, but application code should prefer `coach_draft()` so optional evidence is not accidentally skipped.

## CLI

Python 3.11+ is enough for the manual-draft engine.

```bash
python -m dota_coach.cli --role mid --rank legend --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Rank selectors: `all`, `herald`, `guardian`, `crusader`, `archon`, `legend`, `ancient`, `divine`, `immortal` or numbers 1-8. `all` means OpenDota's explicit all-public sample, not a sum of medal buckets.

Validate live sources:

```bash
python -m dota_coach.cli --health
```

Install locally:

```bash
python -m pip install -e .
dota-coach --role 3 --rank ancient --enemies "Puck,Anti-Mage"
```

For exact-HWND Windows capture:

```bash
python -m pip install -e ".[capture]"
dota-coach --capture-draft captures/draft_169.png
```

`--capture-draft` resolves a visible Dota window and targets its HWND directly. It deliberately bypasses network data loading so calibration screenshots can still be captured if Valve/OpenDota is unavailable.

## Data-source semantics

- Valve heroes: `https://www.dota2.com/datafeed/herolist?language=english`
- Valve patch list: `https://www.dota2.com/datafeed/patchnoteslist`
- OpenDota hero stats: `https://api.opendota.com/api/heroStats`
- OpenDota lane roles: `https://api.opendota.com/api/scenarios/laneRoles?lane_role={lane_role}`
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

OpenDota `heroStats` currently exposes explicit `pub_pick/pub_win` plus medal fields `1_*..8_*` from a short rolling window. Dota Coach keeps those populations separate. Summing medal buckets is only a compatibility fallback for old/cached payloads that lack `pub_*`.

`scenarios/laneRoles` is lane assignment, not exact farm priority. The engine therefore treats it as supporting evidence rather than declaring position 1 vs 5 or position 3 vs 4 from lane alone. Requests are split by lane because the current upstream query is limited to 1200 rows.

The OpenDota hero matchup route currently joins `leagues`, so its rows are pro/league evidence rather than bracket-specific public matchup statistics. `wins` belongs to the hero whose endpoint was requested. Dota Coach requests each visible enemy once and inverts that enemy win rate to estimate candidate-vs-enemy evidence. This signal remains below position/meta evidence because its population is different from the user's public bracket and it is not role-specific.

## Draft-layout calibration foundation

`dota_coach/draft_layout.py` now provides:

- normalized rectangles in frame-relative coordinates;
- pick/ban slot IDs and team labels;
- aspect-ratio guards so a 16:9 calibration is not silently applied to a 16:10 frame;
- normalized-to-pixel conversion;
- JSON save/load for measured calibration profiles.

There are intentionally **no real Dota ROI coordinates yet**. They will be measured from current exact-HWND screenshots rather than guessed from old screenshots or desktop coordinates.

## Architecture

```text
manual draft input                     exact Dota HWND frame
      |                                       |
      |                                  DraftLayout profile
      |                                       |
      |                           [next: anchor validator + crops]
      |                                       |
      +---------------- future recognized slot -> hero + confidence
      |
      v
Valve roster + OpenDota 7d public/medal meta + lane-role + optional pro/league matchup
      |
      v
coach_draft()
      |
      +--> position/role fit
      +--> observed lane share
      +--> team gaps/redundancy
      +--> selected-bracket meta + sample confidence
      +--> capped enemy composition / matchup evidence
      +--> confidence calibration
      |
      v
ranked picks + warnings + tactics + source provenance
```

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs unit/compile checks on Linux and Windows, validates the exact-HWND capture dependency on Windows, validates live Valve/OpenDota coverage on Linux and smoke-tests the high-level `coach_draft()` service against live data.

## Next concrete step

Continue issue **MVP-2: draft-screen ingestion without full-screen template matching**:

1. Capture one current draft frame at **16:9** and one at **16:10** using `dota-coach --capture-draft`.
2. Measure stable UI anchors plus pick/ban portrait rectangles into two `DraftLayout` JSON fixtures.
3. Add a validator that chooses a profile by aspect ratio plus anchor evidence and rejects non-draft screens.
4. Build a dedicated portrait classifier/embedding index from the stored OpenDota `Hero.img` / `Hero.icon` references.
5. Return `slot -> hero + confidence` and feed only high-confidence slots into `coach_draft()`.
6. Keep manual selection as fallback for low-confidence/unknown slots.
7. Add saved-frame regression tests for both aspect ratios before any live overlay work.

The remaining blocker for automatic draft ingestion is representative current draft-screen imagery, not screen capture or engine architecture.