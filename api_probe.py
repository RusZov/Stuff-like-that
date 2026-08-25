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


def summarize(payload: object) -> str:
    if isinstance(payload, list):
        return f"array size={len(payload)} sample={payload[0] if payload else None}"
    if isinstance(payload, dict):
        if "heroes" in payload and isinstance(payload["heroes"], list):
            return f"heroes size={len(payload['heroes'])} sample={payload['heroes'][0] if payload['heroes'] else None}"
        if "ranked_hero_data" in payload and isinstance(payload["ranked_hero_data"], list):
            rows = payload["ranked_hero_data"]
            return f"ranked_hero_data size={len(rows)} sample={rows[0] if rows else None}"
        result = payload.get("result")
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict) and isinstance(data.get("heroes"), list):
                heroes = data["heroes"]
                return f"result.data.heroes size={len(heroes)} sample={heroes[0] if heroes else None}"
        return f"dict keys={list(payload)[:12]}"
    return type(payload).__name__


def probe(url: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach-api-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            ctype = response.headers.get("content-type", "")
            print(f"{url} -> HTTP {response.status}; content-type={ctype}; bytes={len(raw)}")
            payload = json.loads(raw.decode("utf-8"))
            print("  " + summarize(payload))
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", errors="replace")
        print(f"{url} -> HTTP {exc.code}; body={body!r}")
    except Exception as exc:
        print(f"{url} -> ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    for item in URLS:
        probe(item)
