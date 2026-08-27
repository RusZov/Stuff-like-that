# Dota Coach MVP

Clean restart of the project after removing the unreliable full-screen `cv2.matchTemplate` prototype.

## What works now

- Loads the hero roster from Valve's Dota 2 datafeed.
- Merges current OpenDota ranked public pick/win statistics from rank buckets `1_pick..8_pick` and `1_win..8_win`.
- Uses OpenDota hero matchup rows for enemy-draft counter signals.
- Scores candidates separately for positions 1-5.
- Accounts for visible team-role gaps, public win rate, sample size, and enemy matchups.
- Produces short draft tactics from the visible composition.
- Retries transient API timeouts instead of immediately dropping live matchup evidence.
- Does **not** pretend to recognize moving 3D heroes from the whole screen.

## Run

Python 3.11+ is enough; the MVP has no third-party runtime dependencies.

```bash
python -m dota_coach.cli --role mid --allies "Axe,Crystal Maiden" --enemies "Puck,Juggernaut" --limit 5
```

Validate hero roster, ranked meta coverage and a live matchup endpoint:

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

OpenDota's current `heroStats` schema exposes rank-specific pick/win buckets rather than relying on legacy `pub_pick/pub_win`. The loader aggregates ranks 1-8 and keeps the legacy fields only as a compatibility fallback.

Matchup calls are retried on transient network failures. Recommendation code still degrades gracefully if matchup evidence is unavailable.

## Architecture

```text
manual draft input
      |
      v
Valve roster + OpenDota ranked meta
      |
      v
normalized Hero model
      |
      +--> position fit (1-5)
      +--> team role gaps
      +--> ranked public WR + sample confidence
      +--> OpenDota enemy matchup evidence
      |
      v
ranked picks + tactical notes
```

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs deterministic tests on Linux and Windows. The Linux job also verifies the live Valve/OpenDota sources, ranked meta coverage, and one real matchup matrix.

## Next concrete step

Implement **draft-screen ingestion**, not world-model detection:

1. Add a Windows-only Dota window capture adapter using HWND + Windows Graphics Capture/DXGI.
2. Store the window client rectangle and normalize coordinates independently of desktop position/DPI.
3. Detect/validate the draft UI layout before recognition.
4. Crop fixed pick/ban portrait slots as ROIs.
5. Classify each slot with a dedicated portrait classifier/embedding model and return `hero + confidence`.
6. Feed only high-confidence picks/bans into the existing draft engine; retain manual fallback.
7. Add saved-screenshot tests for 16:9 and 16:10 before connecting a live overlay.

This keeps capture, layout detection and hero classification separate and avoids repeating the old mistake of searching the entire moving game scene with template matching.
