# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

Current package version: **0.7.0**.

## What works now

### Draft recommendation engine

- Loads the canonical hero roster and current patch label from Valve's Dota 2 datafeed.
- Uses OpenDota's rolling **7-day** `pub_pick/pub_win` sample for the default public meta.
- Supports medal-specific 7-day samples through `1_pick..8_pick` / `1_win..8_win`: Herald through Immortal.
- Loads OpenDota `scenarios/laneRoles` one lane at a time and uses observed safelane/mid/offlane share as supplemental position evidence.
- Uses OpenDota `/heroes/{id}/matchups` only as **supplemental pro/league evidence**. Current upstream SQL joins `leagues`; it is not public-bracket matchup truth and its influence is capped.
- Scores positions 1-5 separately with position-profile gates, team-gap bonuses, redundancy penalties, lane-role evidence and selected-bracket meta.
- Rejects impossible drafts: duplicate heroes, cross-team overlap and more than five heroes per side.
- Produces position-aware tactics and calls out missing control/initiation, greedy multi-core drafts, push pressure and other broad composition risks.
- Retries transient optional-source failures and exposes source warnings/provenance.
- `coach_draft()` calibrates the complete candidate pool by confidence before top-N truncation.

### Draft-screen ingestion foundation

- Captures the **exact Dota window HWND** on Windows through Windows Graphics Capture; the whole desktop is not scanned.
- Saves exact-window PNG frames with `--capture-draft` for layout calibration.
- `DraftLayout` stores normalized pick/ban rectangles, team labels, aspect-ratio guards and optional anchors. There are no guessed real Dota coordinates in the repository.
- OpenDota `Hero.img` / `Hero.icon` paths are preserved. Live health currently verifies portrait-path coverage across the roster.
- `PortraitIndex` builds a compact image embedding from an already-cropped portrait ROI using chroma, normalized luminance structure and edge energy. It does **not** slide a template over the frame.
- Recognition checks absolute likeness **and** the margin to the second-best hero, so ambiguous crops fail closed.
- Visually flat/unfilled slots are rejected before classification instead of being assigned the mathematically nearest hero.
- If two slots claim the same hero, only the strongest claim can remain accepted; weaker duplicates become manual/unresolved because duplicate heroes are impossible in a legal draft.
- `recognize_draft_slots()` connects `DraftLayout -> exact slot crop -> PortraitIndex -> slot/hero/confidence`.
- Low-confidence slots remain unresolved for manual fallback.
- Synthetic regression tests cover aspect mismatch, blank slots, duplicate claims, brightness changes and class-margin ambiguity.

## Install

Manual draft engine:

```bash
python -m pip install -e .
```

Portrait recognition:

```bash
python -m pip install -e ".[vision]"
```

Exact-HWND Windows capture + portrait recognition:

```bash
python -m pip install -e ".[capture,vision]"
```

## Manual draft CLI

```bash
python -m dota_coach.cli \
  --role mid \
  --rank legend \
  --allies "Axe,Crystal Maiden" \
  --enemies "Puck,Juggernaut" \
  --limit 5
```

Rank selectors: `all`, `herald`, `guardian`, `crusader`, `archon`, `legend`, `ancient`, `divine`, `immortal` or numbers 1-8. `all` means OpenDota's explicit all-public sample, not a sum of medal buckets.

Validate live sources:

```bash
python -m dota_coach.cli --health
```

The health command checks roster/meta coverage, medal buckets, portrait paths, all three lane-role samples and one live matchup matrix.

## Exact Dota frame capture

Windows only:

```bash
dota-coach --capture-draft captures/draft_169.png
```

`--capture-draft` resolves a visible Dota window and targets its HWND directly. It deliberately bypasses Valve/OpenDota loading so calibration frames can still be captured during a data-source outage.

## Portrait reference preparation

Once the vision package is installed, prepare the canonical reference set:

```bash
dota-coach --prepare-portraits assets/hero_portraits
```

References are stored as `<hero_id>.png`, so localization/name changes do not break the cache. Individual download failures are reported. Recognition refuses to run with a dangerously small partial index; at least 75% of the current roster and never fewer than 100 hero references must be present.

## Recognize a saved draft frame

After a real measured layout exists:

```bash
dota-coach \
  --recognize-draft captures/draft_169.png \
  --layout layouts/draft_169.json \
  --portraits assets/hero_portraits
```

Use `--picks-only` to skip ban slots.

Output is per slot and includes hero, similarity, second-best margin, confidence and either `accepted` or `manual`. A flat empty slot has no hero ID. A weaker duplicate hero claim is forced back to manual review.

Important: this command is intentionally **not** usable with guessed coordinates. A current measured `DraftLayout` is required.

## High-level API

Use `coach_draft()` for recommendation code:

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

For calibrated screen recognition:

```python
from dota_coach import PortraitIndex, recognize_draft_slots
from dota_coach.draft_layout import load_layout

layout = load_layout("layouts/draft_169.json")
index = PortraitIndex.from_directory(data.heroes.values(), "assets/hero_portraits")
recognized = recognize_draft_slots("captures/draft_169.png", layout, index)

for slot in recognized.accepted_slots:
    print(slot.slot_id, slot.hero_name, slot.confidence)
```

The application integration rule is simple: **only accepted high-confidence pick slots may be fed automatically into `coach_draft()`; unresolved slots stay manual.**

## Data-source semantics

- Valve heroes: `https://www.dota2.com/datafeed/herolist?language=english`
- Valve patch list: `https://www.dota2.com/datafeed/patchnoteslist`
- OpenDota hero stats: `https://api.opendota.com/api/heroStats`
- OpenDota lane roles: `https://api.opendota.com/api/scenarios/laneRoles?lane_role={lane_role}`
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

OpenDota `heroStats` exposes explicit `pub_pick/pub_win` plus medal fields `1_*..8_*` from a short rolling window. Dota Coach keeps those populations separate. Summing medal buckets is only a compatibility fallback for old/cached payloads without `pub_*`.

`scenarios/laneRoles` is lane assignment, not exact farm priority. It is supporting evidence rather than a direct declaration of position 1/5 or 3/4. Requests are split by lane because the current upstream query is limited to 1200 rows.

The OpenDota hero matchup route currently joins `leagues`, so its rows are pro/league evidence rather than bracket-specific public matchup statistics. `wins` belongs to the hero whose endpoint was requested. Dota Coach requests each visible enemy once and inverts that enemy win rate to estimate candidate-vs-enemy evidence.

## Architecture

```text
manual draft input                              exact Dota HWND frame
      |                                                |
      |                                          DraftLayout
      |                                                |
      |                                    exact portrait slot crops
      |                                                |
      |                                         PortraitIndex
      |                                                |
      |                                hero + confidence / unresolved
      |                                                |
      +---------------- accepted real pick slots ------+
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

GitHub Actions installs the vision extras and runs unit/compile checks on Linux and Windows. Windows additionally validates the exact-HWND capture dependency. Linux validates live Valve/OpenDota coverage and smoke-tests the high-level `coach_draft()` service against live data.

## Next concrete step

The generic recognition pipeline is implemented. The remaining blocker is **real current Dota draft geometry and calibration**, not `cv2` or screen capture.

1. Capture one current draft frame at **16:9** and one at **16:10** using `dota-coach --capture-draft`.
2. Measure stable draft UI anchors plus the real pick/ban portrait rectangles into two `DraftLayout` JSON fixtures.
3. Add an anchor validator that chooses a layout by aspect ratio + measured anchor evidence and rejects non-draft screens.
4. Run the existing `recognize_draft_slots()` pipeline on those real frames and calibrate `min_similarity`, `min_margin` and `min_confidence` from real positive, empty and transitional slots.
5. Add saved-frame regression fixtures for 16:9 and 16:10.
6. Map only accepted Radiant/Dire **pick** slots into `coach_draft()`; keep unresolved slots manual.
7. Only after this is stable, build the live overlay loop.

Do not add OCR or moving-world hero detection to solve draft ingestion. The MVP scope stays on the stable draft HUD.
