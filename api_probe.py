from __future__ import annotations

import json
import tempfile
import urllib.request

from data_provider import DotaData
from dota_data import VALVE_PLUS_STATS


def fetch_raw_json(url: str, timeout: float = 20.0):
    request = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach-live-ci/2.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        print(f"DIAGNOSTIC {url} -> HTTP {response.status}; bytes={len(raw)}")
        return json.loads(raw.decode("utf-8"))


def main() -> None:
    # This is deliberately NOT a mocked test. It executes the exact network
    # synchronization path used by the desktop application.
    with tempfile.TemporaryDirectory() as directory:
        data = DotaData(directory)

        hero_count = data.sync_heroes(timeout=20.0)
        meta_count = sum(hero.win_rate is not None for hero in data.heroes.values())
        print(f"LIVE roster: count={hero_count}; provider={data.roster_provider}")
        print(f"LIVE meta: usable={meta_count}; provider={data.meta_provider}")

        if hero_count < 120 or not data.roster_provider.startswith("Valve"):
            raise SystemExit("FAIL: official Valve hero roster is invalid/unavailable")
        if meta_count < 100 or data.meta_provider == "unavailable":
            raise SystemExit("FAIL: neither validated Valve meta nor OpenDota meta fallback is usable")

        matched = data.sync_matchups(["Axe", "Puck"], timeout=20.0)
        total_entries = sum(len(candidates) for candidates in data.matchups.values())
        print(
            f"LIVE matchups: requested={matched}/2; enemies={len(data.matchups)}; "
            f"entries={total_entries}; provider={data.matchup_provider}"
        )
        if matched != 2 or len(data.matchups) < 80 or total_entries < 1000:
            raise SystemExit("FAIL: Valve Dota Plus matchup payload is invalid/incomplete")

        # The undocumented PlusStats endpoint is only diagnostic because Valve
        # currently may return HTTP 200 with an error object. The app validates
        # it and automatically falls back instead of treating status 200 as success.
        try:
            plus_payload = fetch_raw_json(VALVE_PLUS_STATS)
            if isinstance(plus_payload, dict) and isinstance(plus_payload.get("heroes"), list):
                print(f"Valve PlusStats is currently usable: heroes={len(plus_payload['heroes'])}")
            else:
                print(f"Valve PlusStats is currently NOT usable; payload={plus_payload!r}")
        except Exception as exc:
            print(f"Valve PlusStats diagnostic request failed: {type(exc).__name__}: {exc}")

        print("LIVE DATA VALIDATION OK")


if __name__ == "__main__":
    main()
