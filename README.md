# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the hero roster from Valve's Dota 2 datafeed.
- Merges live public pick/win statistics from OpenDota.
- Uses OpenDota hero matchup rows for enemy-draft counter signals.
- Scores candidates separately for positions 1-5.
- Accounts for visible team-role gaps, public win rate, sample size, and enemy matchups.
- Produces short draft tactics from the visible composition.
- Does **not** pretend to recognize moving 3D heroes from the whole screen.

## Run

Python 3.11+ is enough; the MVP has no third-party runtime dependencies.

```bash
python -m dota_coach.cli --role mid --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Validate data sources only:

```bash
python -m dota_coach.cli --health
```

Install the command locally:

```bash
python -m pip install -e .
dota-coach --role 3 --enemies "Puck,Anti-Mage"
```

## Data sources

- Valve hero roster: `https://www.dota2.com/datafeed/herolist?language=english`
- Valve patch list: `https://www.dota2.com/datafeed/patchnoteslist`
- OpenDota hero stats: `https://api.opendota.com/api/heroStats`
- OpenDota matchups: `https://api.opendota.com/api/heroes/{hero_id}/matchups`

The code degrades gracefully when one metadata source is unavailable; matchup failures reduce confidence instead of crashing recommendations.

## Architecture

```text
manual draft input
      |
      v
Valve roster + OpenDota meta
      |
      v
normalized Hero model
      |
      +--> position fit (1-5)
      +--> team role gaps
      +--> public WR + sample confidence
      +--> OpenDota enemy matchup evidence
      |
      v
ranked picks + tactical notes
```

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the deterministic suite on Linux and Windows.

## Next concrete step

Add **draft-screen ingestion**, not world-model detection:

1. Capture the Dota 2 window by HWND / Windows Graphics Capture.
2. Detect the draft UI layout and crop the fixed hero portrait slots.
3. Classify each slot with a portrait classifier/embedding model.
4. Feed only high-confidence picks/bans into the current normalized draft engine.
5. Keep manual selection as a fallback when confidence is low.

This avoids repeating the old mistake of searching the entire moving game scene with template matching.
