# Dota 2 Coach

Read-only desktop assistant for Dota 2 draft analysis and match planning.

## What is implemented

- Complete offline roster: **127 heroes** (including Kez, Ringmaster and Largo).
- Position-aware Top-5 draft recommendations for positions 1–5.
- Team-composition scoring: control, initiation, frontline and push.
- Official Valve hero roster as the primary online roster source.
- Official Valve Dota Plus ally/enemy matchup matrix as the primary counter source.
- Overall hero win-rate metadata with strict payload validation and an OpenDota fallback.
- Local normalized JSON cache so previously synchronized data keeps working offline.
- Hero portrait downloader for the screen-recognition module.
- Read-only screen capture and OpenCV template recognition.
- Russian tactical summary based on visible/selected lineups.
- Always-on-top desktop window. No input automation, DLL injection, process-memory reading or hidden-information extraction.

## Exact data sources

The application currently uses these exact URLs:

```text
Valve roster:
https://www.dota2.com/datafeed/herolist?language=english

Valve Dota Plus matchups:
https://www.dota2.com/webapi/IDOTA2Plus/GetPlusHeroAllyAndEnemyData/v001

Valve Dota Plus overall stats (attempted only after validating its JSON):
https://www.dota2.com/webapi/IDOTA2Plus/GetPlusStatsData/v001

OpenDota overall-stat fallback:
https://api.opendota.com/api/heroStats
```

Important: an HTTP `200` is **not** considered success by itself. The response structure is validated. At the time the live CI validation was added, Valve `GetPlusStatsData/v001` could return HTTP 200 with an `{success, error}` object instead of hero data. In that case the app rejects it and tries the OpenDota overall-stat fallback. Valve's matchup endpoint has a nested `ranked_hero_data -> rank -> hero_data` shape and is parsed accordingly.

No literal `{hero_id}` placeholder URL is used by the current application.

## Windows quick start

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Python 3.11–3.13 is recommended.

## First use

1. Start `python app.py`.
2. Select enemy heroes if you want their matchup coverage shown in the sync result.
3. Press **ОБНОВИТЬ ГЕРОЕВ + МАТЧАПЫ**. The status line shows which provider actually supplied roster/meta/matchups.
4. Press **СКАЧАТЬ ПОРТРЕТЫ ДЛЯ РАСПОЗНАВАНИЯ** once. Images are saved locally to `assets/heroes/` and are not committed to this repository.
5. Select allies, enemies and your position; press **АНАЛИЗИРОВАТЬ**.
6. **РАСПОЗНАТЬ ГЕРОЕВ НА ЭКРАНЕ** performs one read-only scan. Recognition is experimental because UI scale/resolution/theme affect template matching.

## Data/cache model

The app starts with a complete 127-hero offline roster. Runtime caches are stored under `data/`, including the raw Valve roster, normalized hero meta win rates, and the normalized Valve matchup matrix. Cached provider names are shown in the UI status line.

## Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py dota_data.py data_provider.py engine.py vision.py api_probe.py
python api_probe.py
```

`api_probe.py` is a **live network validation**, not a mock. It executes the same `sync_heroes()` and `sync_matchups()` paths as the desktop application and exits with an error if the real roster/meta/matchup payloads are missing or structurally invalid. GitHub Actions runs that live validation on Linux, unit tests on Linux and Windows, compiles all modules, and constructs the Qt window on both platforms.

## Fair-play scope

This project is intentionally limited to information the player enters or can already see on screen. It does **not** read Dota 2 process memory, reveal fog-of-war information, inject code, automate clicks/keys, or control the game.
