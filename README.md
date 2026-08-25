# Dota 2 Coach MVP

Desktop assistant for hero-pick recommendations and simple match tactics. It is intentionally designed as a **screen-only/manual assistant**: no DLL injection, no process-memory reading, no hidden-information extraction, and no automated input into Dota 2.

## What works

- Windows/Linux desktop UI (PySide6)
- Always-on-top coach window
- Manual ally/enemy draft selection
- Position 1–5 selection
- Top-5 pick scoring from role fit, counters and team needs
- Human-readable tactical plan
- Optional screen capture + OpenCV template matching scaffold

## Run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Enable visible-screen hero recognition

Create `assets/heroes/` and add portrait crops as PNG files, for example:

```text
assets/heroes/
  axe.png
  crystal_maiden.png
  juggernaut.png
```

Use images you have the right to use. The app compares these templates against the visible screen. The current MVP deliberately does not ship Valve/Dota artwork.

For reliable production recognition, the next step is to define draft-screen ROIs per resolution (1920x1080, 2560x1440), crop only the pick slots, normalize portrait sizes, and classify each slot instead of scanning the entire screen.

## Next milestones

1. Full hero roster and patch-specific matchup dataset.
2. Draft-screen calibration wizard and slot-based recognition.
3. Transparent click-through overlay.
4. Strategy engine using only information visible to the player or explicitly entered by the user.
5. Packaging with PyInstaller and signed Windows builds.

## Fair-play boundary

This project should remain an advisory tool. Do not add memory reading, DLL injection, hidden enemy information, automatic actions, or other mechanisms that bypass normal player visibility. Check current Valve/Steam rules before distributing a live-match overlay.
