from __future__ import annotations

from dataclasses import dataclass

from .data import (
    HttpJsonClient,
    OPENDOTA_HERO_STATS_URL,
    VALVE_HERO_LIST_URL,
    VALVE_PATCH_LIST_URL,
    DotaData,
)


@dataclass(frozen=True)
class SourceAudit:
    opendota_rows: int
    opendota_pub_rows: int
    opendota_rank_rows: tuple[int, ...]
    opendota_portrait_rows: int
    valve_heroes: int
    patch: str | None


def audit_live_sources(client: HttpJsonClient | None = None) -> SourceAudit:
    """Audit raw upstream contracts before DotaData normalizes/falls back.

    This deliberately checks the unparsed OpenDota payload so a fallback in our
    model cannot make a missing upstream medal field look healthy. It is used by
    CI as a live contract/sanity check, not by recommendation scoring.
    """
    client = client or HttpJsonClient()
    raw_stats = client.get_json(OPENDOTA_HERO_STATS_URL)
    raw_valve = client.get_json(VALVE_HERO_LIST_URL)
    raw_patches = client.get_json(VALVE_PATCH_LIST_URL)

    if not isinstance(raw_stats, list):
        raise RuntimeError("OpenDota heroStats raw payload is not a list")
    rows = [row for row in raw_stats if isinstance(row, dict) and row.get("id")]
    if len(rows) < 100:
        raise RuntimeError(f"OpenDota heroStats raw roster is unexpectedly small: {len(rows)}")

    pub_rows = sum(
        isinstance(row.get("pub_pick"), (int, float))
        and isinstance(row.get("pub_win"), (int, float))
        for row in rows
    )
    rank_rows = tuple(
        sum(
            isinstance(row.get(f"{rank}_pick"), (int, float))
            and isinstance(row.get(f"{rank}_win"), (int, float))
            for row in rows
        )
        for rank in range(1, 9)
    )
    portrait_rows = sum(bool(row.get("img")) for row in rows)

    if min(rank_rows) < 90:
        raise RuntimeError(
            "OpenDota raw medal-bucket coverage is too low: "
            + ", ".join(f"{rank + 1}={count}" for rank, count in enumerate(rank_rows))
        )
    if portrait_rows < 100:
        raise RuntimeError(f"OpenDota raw portrait-path coverage is too low: {portrait_rows}")

    valve_rows = DotaData._parse_valve_heroes(raw_valve)
    if len(valve_rows) < 100:
        raise RuntimeError(f"Valve raw hero roster is unexpectedly small: {len(valve_rows)}")
    patch = DotaData._parse_latest_patch(raw_patches)
    if not patch:
        raise RuntimeError("Valve patch list did not yield a current patch label")

    return SourceAudit(
        opendota_rows=len(rows),
        opendota_pub_rows=pub_rows,
        opendota_rank_rows=rank_rows,
        opendota_portrait_rows=portrait_rows,
        valve_heroes=len(valve_rows),
        patch=patch,
    )


def main() -> int:
    audit = audit_live_sources()
    print(f"Raw OpenDota heroStats rows: {audit.opendota_rows}")
    print(f"Raw OpenDota pub_pick/pub_win rows: {audit.opendota_pub_rows}/{audit.opendota_rows}")
    print(
        "Raw OpenDota medal rows: "
        + ", ".join(
            f"{rank}={count}/{audit.opendota_rows}"
            for rank, count in enumerate(audit.opendota_rank_rows, start=1)
        )
    )
    print(f"Raw OpenDota portrait rows: {audit.opendota_portrait_rows}/{audit.opendota_rows}")
    print(f"Raw Valve hero rows: {audit.valve_heroes}")
    print(f"Raw Valve latest patch: {audit.patch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
