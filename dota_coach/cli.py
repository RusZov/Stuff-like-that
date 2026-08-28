from __future__ import annotations

import argparse
import sys

from .data import DataSourceError, DotaData, Hero
from .engine import build_strategy, normalize_position, recommend


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
    print(f"Meta coverage: {data.meta_coverage}/{len(data.heroes)} heroes")
    if data.meta_coverage < max(100, int(len(data.heroes) * 0.75)):
        print("Health error: OpenDota ranked meta coverage is too low", file=sys.stderr)
        return 4

    probe = data.resolve("Axe") or next(iter(data.heroes.values()))
    data.load_enemy_matchups([probe.id])
    rows = data.matchup_count(probe.id)
    key = f"OpenDota pro matchups:{probe.id}"
    status = data.source_status.get(key, "missing")
    print(f"Matchup rows for {probe.name}: {rows}")
    print(f"Source {key}: {status}")

    # The matchup endpoint is optional supplemental evidence and has shown
    # transient read timeouts in CI. A transport outage should degrade the
    # coach, not mark otherwise healthy deterministic code as broken. If the
    # endpoint responds successfully but its schema/data collapses, still fail.
    if rows < 50:
        if status.startswith("error:"):
            print("Health warning: optional OpenDota matchup source is temporarily unavailable")
            return 0
        print("Health error: OpenDota matchup endpoint returned too little usable data", file=sys.stderr)
        return 5
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dota-coach",
        description="Draft-focused Dota 2 coach using live Valve/OpenDota data.",
    )
    parser.add_argument("--role", default="2", help="1/carry, 2/mid, 3/offlane, 4/support, 5/hard support")
    parser.add_argument("--allies", default="", help="Comma-separated allied hero names")
    parser.add_argument("--enemies", default="", help="Comma-separated enemy hero names")
    parser.add_argument("--limit", type=int, default=5, help="Number of recommendations")
    parser.add_argument("--health", action="store_true", help="Validate live hero, meta and matchup data")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        position = normalize_position(args.role)
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
    for source, status in data.source_status.items():
        print(f"Source {source}: {status}")

    if args.health:
        return _run_health(data)

    try:
        allies = _resolve_many(data, _csv(args.allies), "allies")
        enemies = _resolve_many(data, _csv(args.enemies), "enemies")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    data.load_enemy_matchups([hero.id for hero in enemies])

    print(f"\nRole: {position}")
    if allies:
        print("Allies: " + ", ".join(hero.name for hero in allies))
    if enemies:
        print("Enemies: " + ", ".join(hero.name for hero in enemies))

    print("\nRecommendations")
    for index, pick in enumerate(recommend(data, allies, enemies, position, args.limit), start=1):
        print(f"{index}. {pick.hero}: score={pick.score:.2f}, confidence={pick.confidence:.0%}")
        for reason in pick.reasons:
            print(f"   - {reason}")

    print("\nTactics")
    for line in build_strategy(allies, enemies, position):
        print(f"- {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
