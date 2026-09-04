# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

Current package version: **0.8.1**.

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
- If two slots claim the same hero, only the strongest claim can remain accepted; weaker duplicates become manual/unresolved both during classification and in the final recognized-draft bridge.
- `recognize_draft_slots()` connects `DraftLayout -> exact slot crop -> PortraitIndex -> slot/hero/confidence`.
- `coach_recognized_draft()` now sanitizes duplicate hero claims before calling the legal-draft validator, so an otherwise usable frame does not crash the MVP.
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
