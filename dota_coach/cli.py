from __future__ import annotations

import argparse
import sys

from .capture import CaptureError, capture_dota_png
from .data import (
    DataSourceError,
    DotaData,
    Hero,
    OPENDOTA_HERO_STATS_WINDOW_DAYS,
    OPENDOTA_MATCHUP_WINDOW_DAYS,
    RANK_NAMES,
)
from .engine import (
    build_strategy,
    normalize_position,
    normalize_rank_tier,
    rank_label,
    recommend,
    validate_draft,
)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_many(data: DotaData, names: list[str], label: str) -> list[Hero]:
    heroes: list[Hero] = []
    missing: list[str] = []
    for name in names:
        hero = data.resolve(name)
        if hero is None:
            missing.append(name)
        else:
            heroes.append(hero)
    if missing:
        raise ValueError(f"Unknown {label}: {', '.join(missing)}")
    return heroes


def _run_health(data: DotaData) -> int:
    print(f"OpenDota heroStats window: last {OPENDOTA_HERO_STATS_WINDOW_DAYS} UTC days")
    print(f"Meta coverage: {data.meta_coverage}/{len(data.heroes)} heroes")
    if data.meta_coverage < max(100, int(len(data.heroes) * 0.75)):
        print("Health error: OpenDota public meta coverage is too low", file=sys.stderr)
        return 4

    bracket_coverages = [data.rank_meta_coverage(rank) for rank in RANK_NAMES]
    print("Bracket coverage: " + ", ".join(
        f"{RANK_NAMES[rank]}={bracket_coverages[rank - 1]}" for rank in RANK_NAMES
    ))
    if min(bracket_coverages) < max(90, int(len(data.heroes) * 0.65)):
        print("Health error: at least one OpenDota rank bucket has too little usable data", file=sys.stderr)
        return 6

    optional_warnings: list[str] = []

    # Lane-role data is supplemental, but unlike broad role tags it tells us
    # where heroes are actually observed. Query lanes separately because the
    # OpenDota implementation caps an unfiltered laneRoles query at 1200 rows.
    data.load_lane_roles([1, 2, 3])
    lane_coverages: dict[int, int] = {}
    for lane_role in (1, 2, 3):
        key = f"OpenDota lane role:{lane_role}"
        status = data.source_status.get(key, "missing")
        coverage = sum(
            data.lane_role_sample(hero.id, lane_role) is not None
            for hero in data.heroes.values()
        )
        lane_coverages[lane_role] = coverage
        print(f"Lane-role {lane_role} coverage: {coverage}/{len(data.heroes)}")
        print(f"Source {key}: {status}")
        if status.startswith("error:"):
            optional_warnings.append(f"lane-role {lane_role} source unavailable")
        elif coverage < max(70, int(len(data.heroes) * 0.50)):
            print(
                f"Health error: OpenDota lane-role {lane_role} returned too little usable data",
                file=sys.stderr,
            )
            return 8

    probe = data.resolve("Axe") or next(iter(data.heroes.values()))
    data.load_enemy_matchups([probe.id])
    rows = data.matchup_count(probe.id)
    key = f"OpenDota matchups:{probe.id}"
    status = data.source_status.get(key, "missing")
    print(f"OpenDota matchup window: last {OPENDOTA_MATCHUP_WINDOW_DAYS} days")
    print(f"Matchup rows for {probe.name}: {rows}")
    print(f"Source {key}: {status}")

    # Matchups and lane roles are supplemental evidence and can have transient
    # read failures. A transport outage should degrade recommendations, not mark
    # otherwise healthy core data/code as broken. A successful response with a
    # collapsed schema/coverage still fails health validation.
    if rows < 50:
        if status.startswith("error:"):
            optional_warnings.append("matchup source unavailable")
        else:
            print("Health error: OpenDota matchup endpoint returned too little usable data", file=sys.stderr)
            return 5

    for warning in optional_warnings:
        print(f"Health warning: optional OpenDota {warning}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dota-coach",
        description="Draft-focused Dota 2 coach using live Valve/OpenDota data.",
    )
    parser.add_argument("--role", default="2", help="1/carry, 2/mid, 3/offlane, 4/support, 5/hard support")
    parser.add_argument(
        "--rank",
        default="all",
        help="all public or medal: Herald, Guardian, Crusader, Archon, Legend, Ancient, Divine, Immortal",
    )
    parser.add_argument("--allies", default="", help="Comma-separated allied hero names")
    parser.add_argument("--enemies", default="", help="Comma-separated enemy hero names")
    parser.add_argument("--limit", type=int, default=5, help="Number of recommendations")
    parser.add_argument("--health", action="store_true", help="Validate live hero, bracket-meta, lane-role and matchup data")
    parser.add_argument(
        "--capture-draft",
        metavar="PNG",
        help="Windows: save one exact Dota HWND frame to PNG for draft-layout calibration; no data APIs are called",
    )
    parser.add_argument("--capture-timeout", type=float, default=3.0, help="Seconds to wait for a captured Dota frame")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)

    if args.capture_draft:
        try:
            window, path = capture_dota_png(args.capture_draft, timeout=args.capture_timeout)
        except (CaptureError, ValueError) as exc:
            print(f"Capture error: {exc}", file=sys.stderr)
            return 7
        print(
            f"Captured {window.title!r} hwnd={window.hwnd} client={window.width}x{window.height} "
            f"aspect={window.aspect_ratio:.4f} -> {path}"
        )
        return 0

    try:
        position = normalize_position(args.role)
        rank_tier = normalize_rank_tier(args.rank)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    data = DotaData()
    try:
        data.refresh()
    except DataSourceError as exc:
        print(f"Data error: {exc}", file=sys.stderr)
        return 3

    print(f"Heroes loaded: {len(data.heroes)}")
    print(f"Patch: {data.patch or 'unknown'}")
    print(f"OpenDota heroStats: rolling {OPENDOTA_HERO_STATS_WINDOW_DAYS}-day window")
    print(f"OpenDota matchups: rolling {OPENDOTA_MATCHUP_WINDOW_DAYS}-day aggregate")
    for source, status in data.source_status.items():
        print(f"Source {source}: {status}")

    if args.health:
        return _run_health(data)

    try:
        allies = _resolve_many(data, _csv(args.allies), "allies")
        enemies = _resolve_many(data, _csv(args.enemies), "enemies")
        validate_draft(allies, enemies)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    data.load_enemy_matchups([hero.id for hero in enemies])

    print(f"\nRole: {position}")
    print(f"Meta bracket: {rank_label(rank_tier)}")
    if allies:
        print("Allies: " + ", ".join(hero.name for hero in allies))
    if enemies:
        print("Enemies: " + ", ".join(hero.name for hero in enemies))

    print("\nRecommendations")
    for index, pick in enumerate(
        recommend(data, allies, enemies, position, args.limit, rank_tier), start=1
    ):
        print(f"{index}. {pick.hero}: score={pick.score:.2f}, confidence={pick.confidence:.0%}")
        for reason in pick.reasons:
            print(f"   - {reason}")

    print("\nTactics")
    for line in build_strategy(allies, enemies, position):
        print(f"- {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
