from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.bridge.scn import CampaignScnParser
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.codex.catalog import CodeXCatalog, CodeXCatalogScanner
from gates_of_codex.models import Battalion, BattalionRosterEntry, CampaignState, Faction
from gates_of_codex.modstack import resolve_stack, stack_to_strings
from gates_of_codex.play_context import (
    allocate_visible_campaign_name,
    default_install_save_path,
    resolve_status_template,
)
from gates_of_codex.profiles import discover_profile_locations
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.stack_acceptance import prepare_stack_handoff
from gates_of_codex.starter import set_player_faction
from gates_of_codex.state_io import save_campaign

AUDITED_COMMIT = "14d784de63d58ddbf993d71f95d9f31b8a370cb2"
DEFAULT_MAP = "multi/dcg_[cwa71]_fulda"

WRAPPERS: dict[str, tuple[str, int]] = {
    "goc_ildu_rifle": ("ukr", 11),
    "goc_ildu_at": ("ukr", 6),
    "goc_ildu_javelin": ("ukr", 4),
    "goc_ildu_recon": ("ukr", 4),
    "goc_ildu_engineer": ("ukr", 6),
    "goc_ildu_manpads": ("ukr", 4),
    "goc_sparta_rifle": ("rusa", 11),
    "goc_sparta_recon": ("rusa", 5),
    "goc_vostok_rifle": ("rusa", 11),
    "goc_vostok_mortar": ("rusa", 2),
    "goc_vostok_spg9": ("rusa", 2),
    "goc_serb_rifle": ("rusa", 10),
    "goc_serb_at": ("rusa", 6),
    "goc_serb_recon": ("rusa", 5),
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Prepare two disposable GoH Conquest saves that exercise all 14 national wrapper squads."
    )
    value.add_argument("--game", required=True)
    value.add_argument("--codex", required=True)
    value.add_argument("--stack-config", required=True)
    value.add_argument("--profile")
    value.add_argument("--install-directory")
    value.add_argument("--template-save")
    value.add_argument("--map", default=DEFAULT_MAP)
    value.add_argument("--work-root", default="live/issue161")
    value.add_argument("--backup-root", default="backups/issue161")
    value.add_argument("--output", default="live/issue161/latest-session.json")
    value.add_argument("--launch", action="store_true")
    value.add_argument("--discover-profiles", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.discover_profiles:
        print(json.dumps([item.to_dict() for item in discover_profile_locations()], indent=2))
        return 0

    profile, install_root = _resolve_profile(args.profile, args.install_directory)
    game = Path(args.game).expanduser().resolve()
    codex = Path(args.codex).expanduser().resolve()
    stack_config = Path(args.stack_config).expanduser().resolve()
    stack = resolve_stack(config=stack_config, fallback=codex)
    catalog = CodeXCatalogScanner().scan_stack(stack)
    wrapper_preflight = _validate_wrappers(catalog)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    session = Path(args.work_root).expanduser().resolve() / f"wrapper-engine-{stamp}"
    session.mkdir(parents=True, exist_ok=False)

    template = Path(args.template_save).expanduser().resolve() if args.template_save else None
    tests = []
    tests.append(
        _prepare_one(
            label="ukr-player",
            attacker=Faction.UKRAINE,
            defender=Faction.RUSSIA,
            player_side=Faction.UKRAINE,
            catalog=catalog,
            stack=stack,
            game=game,
            codex=codex,
            profile=profile,
            install_root=install_root,
            template=template,
            map_name=args.map,
            stack_config=stack_config,
            session=session,
            backup_root=Path(args.backup_root),
            launch=args.launch,
        )
    )
    tests.append(
        _prepare_one(
            label="rusa-player",
            attacker=Faction.RUSSIA,
            defender=Faction.UKRAINE,
            player_side=Faction.RUSSIA,
            catalog=catalog,
            stack=stack,
            game=game,
            codex=codex,
            profile=profile,
            install_root=install_root,
            template=template,
            map_name=args.map,
            stack_config=stack_config,
            session=session,
            backup_root=Path(args.backup_root),
            launch=False,
        )
    )

    matrix_path = session / "wrapper-result-matrix.csv"
    _write_matrix(matrix_path, tests)
    result = {
        "schema": "gates-of-codex.issue161-wrapper-engine-test",
        "schema_version": 1,
        "audited_commit": AUDITED_COMMIT,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "game_directory": str(game),
        "profile_directory": str(profile),
        "install_directory": str(install_root),
        "stack_config": str(stack_config),
        "resource_stack": stack_to_strings(stack),
        "catalog_signature": catalog.signature,
        "wrapper_preflight": wrapper_preflight,
        "tests": tests,
        "matrix": str(matrix_path),
        "instructions": [
            "Load the ukr-player save first and verify all six ILDU squads are controllable and all eight RUSA squads appear.",
            "Then load the rusa-player save and verify all eight RUSA squads are controllable and all six ILDU squads appear.",
            "Take at least one screenshot for ILDU, Sparta, Vostok, and Serbia.",
            "Exit the game completely, then run collect_wrapper_evidence.ps1.",
        ],
    }
    result_path = session / "session.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=True))
    print()
    print("LOAD FIRST:")
    print(tests[0]["visible_campaign_name"])
    print()
    print("LOAD SECOND AFTER THE FIRST TEST:")
    print(tests[1]["visible_campaign_name"])
    print()
    print(f"Session evidence directory: {session}")
    return 0


def _resolve_profile(profile_value: str | None, install_value: str | None) -> tuple[Path, Path]:
    if bool(profile_value) != bool(install_value):
        raise ValueError("Pass both --profile and --install-directory, or neither.")
    if profile_value and install_value:
        profile = Path(profile_value).expanduser().resolve()
        install = Path(install_value).expanduser().resolve()
        _validate_profile_pair(profile, install)
        return profile, install

    pairs: list[tuple[Path, Path]] = []
    for candidate in discover_profile_locations():
        profile = Path(candidate.path).expanduser().resolve()
        for raw_save in candidate.save_directories:
            save = Path(raw_save).expanduser().resolve()
            if save.is_dir() and profile in (save, *save.parents):
                pairs.append((profile, save))
    preferred = [pair for pair in pairs if pair[1].name.lower() in {"campaign", "campaigns", "dynamic_conquest"}]
    choices = preferred or pairs
    unique = {(str(profile).lower(), str(save).lower()): (profile, save) for profile, save in choices}
    values = list(unique.values())
    if len(values) != 1:
        payload = [
            {"profile": str(profile), "install_directory": str(save)}
            for profile, save in sorted(values, key=lambda item: (str(item[0]).lower(), str(item[1]).lower()))
        ]
        raise RuntimeError(
            "Could not select exactly one GoH profile/save directory automatically. "
            "Re-run with --profile and --install-directory. Candidates:\n"
            + json.dumps(payload, indent=2)
        )
    _validate_profile_pair(*values[0])
    return values[0]


def _validate_profile_pair(profile: Path, install: Path) -> None:
    if not profile.is_dir():
        raise FileNotFoundError(f"Profile directory not found: {profile}")
    if not install.is_dir():
        raise FileNotFoundError(f"Install directory not found: {install}")
    if profile not in (install, *install.parents):
        raise ValueError(f"Install directory is not inside profile: {install}")


def _validate_wrappers(catalog: CodeXCatalog) -> list[dict]:
    rows = []
    failures = []
    for unit_name, (side, expected_members) in WRAPPERS.items():
        definition = catalog.units.get(unit_name)
        if definition is None:
            failures.append(f"{unit_name}: missing from effective catalog")
            continue
        actual_members = sum(definition.members.values())
        row = {
            "unit_name": unit_name,
            "expected_side": side,
            "actual_side": definition.side,
            "expected_members": expected_members,
            "actual_members": actual_members,
            "materializable": definition.materializable,
            "source_files": list(definition.source_files),
        }
        rows.append(row)
        if definition.side != side:
            failures.append(f"{unit_name}: side {definition.side!r}, expected {side!r}")
        if actual_members != expected_members:
            failures.append(f"{unit_name}: {actual_members} members, expected {expected_members}")
        if not definition.materializable:
            failures.append(f"{unit_name}: not materializable")
    if failures:
        raise RuntimeError("Wrapper preflight failed:\n- " + "\n- ".join(failures))
    return rows


def _prepare_one(
    *,
    label: str,
    attacker: Faction,
    defender: Faction,
    player_side: Faction,
    catalog: CodeXCatalog,
    stack: Iterable[Path],
    game: Path,
    codex: Path,
    profile: Path,
    install_root: Path,
    template: Path | None,
    map_name: str,
    stack_config: Path,
    session: Path,
    backup_root: Path,
    launch: bool,
) -> dict:
    state = load_bundled_scenario()
    state.code_x_directory = str(codex)
    state.game_directory = str(game)
    state.profile_directory = str(profile)
    state.catalog_signature = catalog.signature
    state.map_metadata["resource_stack"] = stack_to_strings(stack)
    state.map_metadata["stack_config"] = str(stack_config)
    set_player_faction(state, player_side)

    attacker_force = _select_force(state, attacker)
    defender_force = _select_force(state, defender)
    attacker_units = [name for name, (side, _) in WRAPPERS.items() if side == attacker.value]
    defender_units = [name for name, (side, _) in WRAPPERS.items() if side == defender.value]
    _distribute_roster(state, attacker_force.battalion_ids, attacker_units, catalog)
    _distribute_roster(state, defender_force.battalion_ids, defender_units, catalog)

    origin_id, target_id = _select_adjacent_pair(state)
    state.provinces[origin_id].owner = attacker
    state.provinces[target_id].owner = defender
    _clear_pair_occupants(state, origin_id, target_id, set(attacker_force.battalion_ids + defender_force.battalion_ids))
    _move_force(state, attacker_force.strategic_formation_id, origin_id)
    _move_force(state, defender_force.strategic_formation_id, target_id)
    for battalion_id in attacker_force.battalion_ids + defender_force.battalion_ids:
        battalion = state.battalions[battalion_id]
        battalion.movement_remaining = 1
        battalion.combat_actions_remaining = 1
        battalion.condition = 100
        battalion.supply = 100

    mover = state.battalions[attacker_force.battalion_ids[0]]
    moved = CampaignEngine(state).move_or_attack(mover.battalion_id, target_id)
    if moved.pending_battle is None:
        raise RuntimeError(f"{label}: failed to create pending battle")

    work = session / label
    work.mkdir(parents=True, exist_ok=False)
    campaign_path = work / "campaign.json"
    export_path = work / "campaign.sav"
    save_campaign(state, campaign_path)

    visible_name = allocate_visible_campaign_name(
        moved.pending_battle.battle_id,
        install_root=install_root,
        prefix=f"Gates Wrapper {label}",
    )
    installed_path = default_install_save_path(install_root, visible_name)
    template_path = resolve_status_template(install_root, installed_path, template)
    handoff = prepare_stack_handoff(
        campaign_path,
        game_directory=game,
        code_x_directory=codex,
        resource_stack=stack,
        stack_config=stack_config,
        save_path=export_path,
        map_name=map_name,
        profile_directory=profile,
        install_directory=install_root,
        install_save_path=installed_path,
        status_template_path=template_path,
        backup_root=backup_root,
        launch=launch,
        campaign_name=visible_name,
        name_prefix=f"Gates Wrapper {label}",
    )

    exported = CampaignSaveArchive().read(installed_path)
    squads = CampaignScnParser().parse_squads(exported.campaign_scn)
    counts = {row.unit_name: len(row.object_ids) for row in squads if row.unit_name in WRAPPERS}
    expected = {name: members for name, (_, members) in WRAPPERS.items()}
    if counts != expected:
        raise RuntimeError(f"{label}: exported wrapper object counts mismatch: {counts!r} != {expected!r}")

    return {
        "label": label,
        "attacker": attacker.value,
        "defender": defender.value,
        "player_side": player_side.value,
        "visible_campaign_name": visible_name,
        "campaign_path": str(campaign_path),
        "export_save_path": str(export_path),
        "installed_save_path": str(installed_path),
        "template_save_path": str(template_path),
        "battle_id": moved.pending_battle.battle_id,
        "origin_province": origin_id,
        "target_province": target_id,
        "exported_wrapper_object_counts": counts,
        "handoff": handoff.to_dict(),
    }


def _select_force(state: CampaignState, faction: Faction):
    candidates = [force for force in state.strategic_formations.values() if force.faction == faction]
    if not candidates:
        raise RuntimeError(f"No strategic formation exists for {faction.value}")
    return min(candidates, key=lambda force: (len(force.battalion_ids), force.strategic_formation_id))


def _distribute_roster(
    state: CampaignState,
    battalion_ids: list[str],
    unit_names: list[str],
    catalog: CodeXCatalog,
) -> None:
    available = [item for item in battalion_ids if item in state.battalions]
    if not available:
        raise RuntimeError("Selected strategic formation has no battalions")
    buckets: dict[str, list[BattalionRosterEntry]] = {item: [] for item in available}
    for index, unit_name in enumerate(unit_names):
        definition = catalog.units[unit_name]
        battalion_id = available[index % len(available)]
        buckets[battalion_id].append(BattalionRosterEntry(unit_name, quantity=1, category=definition.category))
    for battalion_id, roster in buckets.items():
        if not roster:
            fallback = unit_names[0]
            definition = catalog.units[fallback]
            roster = [BattalionRosterEntry(fallback, quantity=1, category=definition.category)]
        battalion = state.battalions[battalion_id]
        battalion.roster = roster
        battalion.authorized_roster = [
            BattalionRosterEntry(item.unit_name, item.quantity, item.stage, item.category, list(item.preserved_objects))
            for item in roster
        ]
        battalion.condition = 100
        battalion.supply = 100


def _select_adjacent_pair(state: CampaignState) -> tuple[str, str]:
    occupied = {item.province_id for item in state.battalions.values()}
    candidates = []
    for province in state.provinces.values():
        for neighbor_id in province.neighbors:
            if province.province_id >= neighbor_id:
                continue
            score = int(province.province_id in occupied) + int(neighbor_id in occupied)
            candidates.append((score, province.province_id, neighbor_id))
    if not candidates:
        raise RuntimeError("Campaign map has no adjacent province pair")
    _, origin, target = min(candidates)
    return origin, target


def _clear_pair_occupants(
    state: CampaignState,
    origin_id: str,
    target_id: str,
    selected_ids: set[str],
) -> None:
    blocked = {origin_id, target_id}
    occupied = {item.province_id for item in state.battalions.values()}
    for battalion in sorted(state.battalions.values(), key=lambda item: item.battalion_id):
        if battalion.battalion_id in selected_ids or battalion.province_id not in blocked:
            continue
        destination = next(
            (
                province.province_id
                for province in sorted(state.provinces.values(), key=lambda item: item.province_id)
                if province.province_id not in occupied and province.province_id not in blocked
            ),
            None,
        )
        if destination is None:
            raise RuntimeError(f"Could not relocate occupant {battalion.battalion_id}")
        occupied.discard(battalion.province_id)
        battalion.province_id = destination
        occupied.add(destination)
        if battalion.strategic_formation_id:
            _move_force(state, battalion.strategic_formation_id, destination)


def _move_force(state: CampaignState, force_id: str, province_id: str) -> None:
    force = state.strategic_formations[force_id]
    force.province_id = province_id
    for battalion_id in force.battalion_ids:
        battalion = state.battalions.get(battalion_id)
        if battalion is not None:
            battalion.province_id = province_id


def _write_matrix(path: Path, tests: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination,
            fieldnames=[
                "unit_name",
                "tactical_side",
                "expected_members",
                "ukr_player_export_count",
                "rusa_player_export_count",
                "engine_spawn_pass",
                "actual_spawned_members",
                "screenshot",
                "notes",
            ],
        )
        writer.writeheader()
        for unit_name, (side, members) in WRAPPERS.items():
            writer.writerow(
                {
                    "unit_name": unit_name,
                    "tactical_side": side,
                    "expected_members": members,
                    "ukr_player_export_count": tests[0]["exported_wrapper_object_counts"].get(unit_name, 0),
                    "rusa_player_export_count": tests[1]["exported_wrapper_object_counts"].get(unit_name, 0),
                    "engine_spawn_pass": "",
                    "actual_spawned_members": "",
                    "screenshot": "",
                    "notes": "",
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
