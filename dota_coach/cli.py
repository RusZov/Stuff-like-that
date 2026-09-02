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
from .draft_layout import LayoutError, load_layout
from .draft_recognition import recognize_draft_slots
from .engine import normalize_position, normalize_rank_tier, validate_draft
from .portrait import (
    PortraitDependencyError,
    PortraitIndex,
    PortraitIndexError,
    download_reference_portraits,
)
from .service import coach_draft


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_many(data: DotaData, names: list[str], label: str) -> list[Hero]:
    heroes: list[Hero] = []
    missing: list[str] = []
    for name in names:
        resolved = data.resolve(name)
        if resolved is None:
            missing.append(name)
        else:
            heroes.append(resolved)
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
    print(
        "Bracket coverage: "
        + ", ".join(f"{RANK_NAMES[rank]}={bracket_coverages[rank - 1]}" for rank in RANK_NAMES)
    )
    if min(bracket_coverages) < max(90, int(len(data.heroes) * 0.65)):
        print("Health error: at least one OpenDota rank bucket has too little usable data", file=sys.stderr)
        return 6

    optional_warnings: list[str] = []
    data.load_lane_roles([1, 2, 3])
    for lane_role in (1, 2, 3):
        key = f"OpenDota lane role:{lane_role}"
        status = data.source_status.get(key, "missing")
        coverage = sum(
            data.lane_role_sample(hero.id, lane_role) is not None for hero in data.heroes.values()
        )
        print(f"Lane-role {lane_role} coverage: {coverage}/{len(data.heroes)}")
        print(f"Source {key}: {status}")
        if status.startswith("error:"):
            optional_warnings.append(f"lane-role {lane_role} source unavailable")
        elif coverage < max(70, int(len(data.heroes) * 0.50)):
            print(f"Health error: OpenDota lane-role {lane_role} returned too little usable data", file=sys.stderr)
            return 8

    probe = data.resolve("Axe") or next(iter(data.heroes.values()))
    data.load_enemy_matchups([probe.id])
    rows = data.matchup_count(probe.id)
    key = f"OpenDota matchups:{probe.id}"
    status = data.source_status.get(key, "missing")
    print(
        f"OpenDota matchup source: pro/league matches, roughly last {OPENDOTA_MATCHUP_WINDOW_DAYS} days"
    )
    print(f"Matchup rows for {probe.name}: {rows}")
    print(f"Source {key}: {status}")

    if rows < 50:
        if status.startswith("error:"):
            optional_warnings.append("matchup source unavailable")
        else:
            print("Health error: OpenDota matchup endpoint returned too little usable data", file=sys.stderr)
            return 5

    for warning in optional_warnings:
        print(f"Health warning: optional OpenDota {warning}")
    return 0


def _print_live_header(data: DotaData) -> None:
    print(f"Heroes loaded: {len(data.heroes)}")
    print(f"Patch: {data.patch or 'unknown'}")
    print(f"OpenDota heroStats: rolling {OPENDOTA_HERO_STATS_WINDOW_DAYS}-day public/medal sample")
    print(
        f"OpenDota matchups: supplemental pro/league sample, roughly {OPENDOTA_MATCHUP_WINDOW_DAYS} days"
    )
    for source, status in data.source_status.items():
        print(f"Source {source}: {status}")


def _prepare_portraits(data: DotaData, directory: str) -> int:
    try:
        saved, errors = download_reference_portraits(data.heroes.values(), directory)
    except PortraitDependencyError as exc:
        print(f"Portrait error: {exc}", file=sys.stderr)
        return 9

    print(f"Portrait references ready: {len(saved)}/{len(data.heroes)} in {directory}")
    if errors:
        print(f"Portrait warnings: {len(errors)} assets could not be prepared", file=sys.stderr)
        for hero_id, message in list(errors.items())[:8]:
            hero = data.heroes_by_id.get(hero_id)
            name = hero.name if hero else str(hero_id)
            print(f"- {name}: {message}", file=sys.stderr)
    if not saved:
        return 9
    return 0


def _recognize_saved_draft(
    data: DotaData,
    frame_path: str,
    layout_path: str | None,
    portrait_directory: str | None,
    *,
    picks_only: bool,
) -> int:
    if not layout_path:
        print("--recognize-draft requires --layout <layout.json>", file=sys.stderr)
        return 2
    if not portrait_directory:
        print("--recognize-draft requires --portraits <directory>", file=sys.stderr)
        return 2

    try:
        layout = load_layout(layout_path)
        index = PortraitIndex.from_directory(data.heroes.values(), portrait_directory)
        if index.hero_count == 0:
            print("Portrait error: reference index is empty; run --prepare-portraits first", file=sys.stderr)
            return 9
        recognition = recognize_draft_slots(
            frame_path,
            layout,
            index,
            include_bans=not picks_only,
        )
    except (LayoutError, PortraitDependencyError, PortraitIndexError, OSError) as exc:
        print(f"Recognition error: {exc}", file=sys.stderr)
        return 9

    print(f"Layout: {recognition.layout_name}")
    print(f"Portrait references indexed: {index.hero_count}/{len(data.heroes)}")
    for slot in recognition.slots:
        if slot.hero_name:
            status = "accepted" if slot.accepted else "manual"
            print(
                f"{slot.slot_id} [{slot.team}/{slot.kind}]: {slot.hero_name} "
                f"similarity={slot.similarity:.3f} margin={slot.margin:.3f} "
                f"confidence={slot.confidence:.0%} -> {status}"
            )
        else:
            print(f"{slot.slot_id} [{slot.team}/{slot.kind}]: unresolved -> {slot.reason}")

    accepted = len(recognition.accepted_slots)
    unresolved = len(recognition.unresolved_slots)
    print(f"Accepted slots: {accepted}; manual/unresolved: {unresolved}")
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

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--capture-draft",
        metavar="PNG",
        help="Windows: save one exact Dota HWND frame to PNG for draft-layout calibration; no data APIs are called",
    )
    modes.add_argument(
        "--prepare-portraits",
        metavar="DIR",
        help="Download/cache canonical hero portrait references into DIR (requires .[vision])",
    )
    modes.add_argument(
        "--recognize-draft",
        metavar="PNG",
        help="Recognize calibrated draft slots in a saved PNG; requires --layout and --portraits",
    )
    parser.add_argument("--capture-timeout", type=float, default=3.0, help="Seconds to wait for a captured Dota frame")
    parser.add_argument("--layout", metavar="JSON", help="Measured DraftLayout JSON for --recognize-draft")
    parser.add_argument("--portraits", metavar="DIR", help="Prepared portrait reference directory for --recognize-draft")
    parser.add_argument("--picks-only", action="store_true", help="With --recognize-draft, skip ban slots")
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

    _print_live_header(data)

    if args.health:
        return _run_health(data)

    if args.prepare_portraits:
        return _prepare_portraits(data, args.prepare_portraits)

    if args.recognize_draft:
        return _recognize_saved_draft(
            data,
            args.recognize_draft,
            args.layout,
            args.portraits,
            picks_only=args.picks_only,
        )

    try:
        allies = _resolve_many(data, _csv(args.allies), "allies")
        enemies = _resolve_many(data, _csv(args.enemies), "enemies")
        validate_draft(allies, enemies)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    meta_sample = (
        f"All public ({OPENDOTA_HERO_STATS_WINDOW_DAYS}d)"
        if rank_tier is None
        else f"{RANK_NAMES[rank_tier]} ({OPENDOTA_HERO_STATS_WINDOW_DAYS}d)"
    )
    print(f"\nRole: {position}")
    print(f"Meta sample: {meta_sample}")
    if allies:
        print("Allies: " + ", ".join(hero.name for hero in allies))
    if enemies:
        print("Enemies: " + ", ".join(hero.name for hero in enemies))

    result = coach_draft(data, allies, enemies, position, args.limit, rank_tier)

    print("\nRecommendations")
    for index, pick in enumerate(result.picks, start=1):
        print(f"{index}. {pick.hero}: score={pick.score:.2f}, confidence={pick.confidence:.0%}")
        for reason in pick.reasons:
            print(f"   - {reason}")

    if result.warnings:
        print("\nData warnings")
        for warning in result.warnings:
            print(f"- {warning}")

    print("\nTactics")
    for line in result.tactics:
        print(f"- {line}")

    print("\nData provenance")
    for note in result.source_notes:
        print(f"- {note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
