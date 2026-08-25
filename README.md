# Dota 2 Coach

Read-only desktop assistant for Dota 2 draft analysis and match planning.

## What is implemented

- Complete offline roster: **127 heroes** (including Kez, Ringmaster and Largo).
- Position-aware Top-5 draft recommendations for positions 1–5.
- Team-composition scoring: control, initiation, frontline and push.
- Optional current hero statistics from OpenDota `GET /heroStats`.
- Optional matchup statistics for currently selected enemies from OpenDota `GET /heroes/{hero_id}/matchups`.
- Local JSON cache so the app keeps working offline after sync.
- Hero portrait downloader for the screen-recognition module.
- Read-only screen capture and OpenCV template recognition.
- Russian tactical summary based on visible/selected lineups.
- Always-on-top desktop window. No input automation, DLL injection, process-memory reading or hidden-information extraction.

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
2. Press **ОБНОВИТЬ ГЕРОЕВ + МАТЧАПЫ** to refresh hero metadata. If enemy heroes are already selected, their matchup packs are refreshed too.
3. Press **СКАЧАТЬ ПОРТРЕТЫ ДЛЯ РАСПОЗНАВАНИЯ** once. Images are saved locally to `assets/heroes/` and are not committed to this repository.
4. Select allies, enemies and your position; press **АНАЛИЗИРОВАТЬ**.
5. **РАСПОЗНАТЬ ГЕРОЕВ НА ЭКРАНЕ** performs one read-only scan. Recognition is experimental because UI scale/resolution/theme affect template matching.

## Data model

The app ships a complete 127-hero fallback roster, so it starts without internet. `data/hero_stats.json` and `data/matchups.json` are generated at runtime and ignored by Git. OpenDota is used only as an optional public-statistics source; API availability and rate limits are outside this project's control.

## Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py dota_data.py engine.py vision.py
```

GitHub Actions also installs all GUI dependencies, runs the unit tests, compiles every module and performs a headless Qt import/startup smoke test.

## Fair-play scope

This project is intentionally limited to information the player enters or can already see on screen. It does **not** read Dota 2 process memory, reveal fog-of-war information, inject code, automate clicks/keys, or control the game.
