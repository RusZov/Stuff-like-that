from __future__ import annotations

import json
import urllib.error
import urllib.request

URLS = [
    "https://api.opendota.com/api/heroStats",
    "https://api.opendota.com/api/heroes/2/matchups",
    "https://www.dota2.com/datafeed/herolist?language=english",
    "https://www.dota2.com/webapi/IDOTA2Plus/GetPlusStatsData/v001",
    "https://www.dota2.com/webapi/IDOTA2Plus/GetPlusHeroAllyAndEnemyData/v001",
]


def probe(url: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach-api-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            ctype = response.headers.get("content-type", "")
            print(f"{url} -> HTTP {response.status}; content-type={ctype}; bytes={len(raw)}")
            try:
                payload = json.loads(raw.decode("utf-8"))
                print(f"  JSON type: {type(payload).__name__}; top-level={list(payload)[:8] if isinstance(payload, dict) else 'array'}")
            except Exception as exc:
                print(f"  JSON decode failed: {exc}")
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", errors="replace")
        print(f"{url} -> HTTP {exc.code}; body={body!r}")
    except Exception as exc:
        print(f"{url} -> ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    for item in URLS:
        probe(item)
