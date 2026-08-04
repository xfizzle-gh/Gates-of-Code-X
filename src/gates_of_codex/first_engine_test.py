from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .campaign import CampaignEngine
from .codex.catalog import CodeXCatalogScanner
from .economy import initialize_economy
from .models import Battalion, CampaignState, Faction
from .modstack import resolve_stack, stack_to_strings
from .scenario import load_bundled_scenario
from .play_context import (
    allocate_visible_campaign_name,
    default_install_save_path,
    resolve_status_template,
)
from .stack_acceptance import HandoffResult, prepare_stack_handoff
from .starter import populate_acceptance_combat_rosters, populate_starter_rosters, set_player_faction
from .state_io import save_campaign
from .strategic import evaluate_campaign_outcome


DEFAULT_TEST_MAP = "multi/dcg_[cwa71]_fulda"
# Empty means: derive the install filename from the visible Conquest name the way GoH does.
DEFAULT_INSTALL_NAME = ""


@dataclass(frozen=True, slots=True)
class AcceptanceBattleSelection:
    attacker_battalion: str
    attacker_formation: str
    origin_province: str
    origin_name: str
    defender_battalion: str
    defender_formation: str
    target_province: str
    target_name: str
    battle_id: str


@dataclass(slots=True)
class FirstEngineTestResult:
    session_directory: str
    campaign_path: str
    export_save_path: str
    installed_save_path: str
    status_template_path: str
    map_name: str
    profile_directory: str
    install_directory: str
    selection: AcceptanceBattleSelection
    handoff: HandoffResult
    verify_command: str
    import_command: str
    visible_campaign_name: str = ""

    def to_dict(self) -> dict:
        return {
            "session_directory": self.session_directory,
            "campaign_path": self.campaign_path,
            "export_save_path": self.export_save_path,
            "installed_save_path": self.installed_save_path,
            "status_template_path": self.status_template_path,
            "map_name": self.map_name,
            "profile_directory": self.profile_directory,
            "install_directory": self.install_directory,
            "visible_campaign_name": self.visible_campaign_name,
            "selection": asdict(self.selection),
            "handoff": self.handoff.to_dict(),
            "verify_command": self.verify_command,
            "import_command": self.import_command,
            "load_instruction": (
                f"Load this exact Conquest entry: {self.visible_campaign_name}"
                if self.visible_campaign_name
                else ""
            ),
            "installed_save_name": Path(self.installed_save_path).name if self.installed_save_path else "",
        }


def stage_nato_russia_acceptance_battle(state: CampaignState) -> AcceptanceBattleSelection:
    """Stage a deterministic NATO attack on an adjacent Russian province."""

    if state.pending_battle is not None:
        raise RuntimeError("Acceptance campaign already has a pending battle")

    set_player_faction(state, Faction.NATO)
    state.current_faction = Faction.NATO
    origin_id, target_id = _select_nato_russia_border(state)
    attacker = _select_battalion(state, Faction.NATO, "nato-pol-mechanized")
    defender = _select_battalion(state, Faction.RUSSIA, "rusa-motor-rifle")

    _clear_border_occupants(state, origin_id, target_id, {attacker.battalion_id, defender.battalion_id})
    attacker.province_id = origin_id
    attacker.movement_remaining = 1
    attacker.combat_actions_remaining = 1
    attacker.condition = max(attacker.condition, 80)
    attacker.supply = max(attacker.supply, 80)
    defender.province_id = target_id
    defender.movement_remaining = 1
    defender.combat_actions_remaining = 1
    defender.condition = max(defender.condition, 80)
    defender.supply = max(defender.supply, 80)

    result = CampaignEngine(state).move_or_attack(attacker.battalion_id, target_id)
    if result.pending_battle is None:
        raise RuntimeError("Acceptance setup did not create a tactical battle")

    selection = AcceptanceBattleSelection(
        attacker_battalion=attacker.battalion_id,
        attacker_formation=attacker.formation_id,
        origin_province=origin_id,
        origin_name=state.provinces[origin_id].display_name,
        defender_battalion=defender.battalion_id,
        defender_formation=defender.formation_id,
        target_province=target_id,
        target_name=state.provinces[target_id].display_name,
        battle_id=result.pending_battle.battle_id,
    )
    state.map_metadata["first_engine_test"] = asdict(selection)
    return selection


def run_first_engine_test(
    *,
    game_directory: str | Path,
    code_x_directory: str | Path,
    profile_directory: str | Path,
    install_directory: str | Path,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
    work_root: str | Path = "live",
    map_name: str = DEFAULT_TEST_MAP,
    install_name: str = DEFAULT_INSTALL_NAME,
    template_save: str | Path | None = None,
    backup_root: str | Path = "backups",
    launch: bool = False,
) -> FirstEngineTestResult:
    game = Path(game_directory).expanduser().resolve()
    codex = Path(code_x_directory).expanduser().resolve()
    profile = Path(profile_directory).expanduser().resolve()
    install_root = Path(install_directory).expanduser().resolve()
    if not profile.is_dir():
        raise FileNotFoundError(f"GoH profile directory not found: {profile}")
    if not install_root.is_dir():
        raise FileNotFoundError(f"GoH campaign/save directory not found: {install_root}")
    if profile not in (install_root, *install_root.parents):
        raise ValueError(f"Install directory is not inside the selected profile: {install_root}")

    stack = resolve_stack(resource_stack, config=stack_config, fallback=codex)
    catalog = CodeXCatalogScanner().scan_stack(stack)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    session = Path(work_root).expanduser().resolve() / f"first-engine-test-{timestamp}"
    session.mkdir(parents=True, exist_ok=False)
    campaign_path = session / "campaign.json"
    export_save_path = session / "campaign.sav"

    state = load_bundled_scenario()
    state.code_x_directory = str(codex)
    state.map_metadata["resource_stack"] = stack_to_strings(stack)
    set_player_faction(state, Faction.NATO)
    populate_starter_rosters(state, catalog)
    populate_acceptance_combat_rosters(state, catalog)
    initialize_economy(state, catalog)
    evaluate_campaign_outcome(state)
    selection = stage_nato_russia_acceptance_battle(state)
    save_campaign(state, campaign_path)

    visible_name = allocate_visible_campaign_name(
        selection.battle_id,
        install_root=install_root,
        prefix="Gates of CodeX Test",
    )
    if install_name:
        installed_save_path = (install_root / install_name).resolve()
    else:
        installed_save_path = default_install_save_path(install_root, visible_name)
    template_path = resolve_status_template(install_root, installed_save_path, template_save)

    handoff = prepare_stack_handoff(
        campaign_path,
        game_directory=game,
        code_x_directory=codex,
        resource_stack=stack,
        save_path=export_save_path,
        map_name=map_name,
        profile_directory=profile,
        install_directory=install_root,
        install_save_path=installed_save_path,
        status_template_path=template_path,
        backup_root=backup_root,
        launch=launch,
        campaign_name=visible_name,
        name_prefix="Gates of CodeX Test",
        stack_config=stack_config,
    )
    if handoff.manifest.visible_campaign_name != visible_name:
        raise RuntimeError(
            "Handoff visible campaign name diverged from the precomputed GoH install name: "
            f"{handoff.manifest.visible_campaign_name!r} != {visible_name!r}"
        )

    verify_command = (
        f'& .\\.venv\\Scripts\\gates-of-codex-live.exe verify "{campaign_path}" '
        f'--save "{installed_save_path}" --stack-config "{Path(stack_config).resolve() if stack_config else ""}" '
        f'--output "{session / "acceptance-report.json"}"'
    )
    import_command = (
        f'& .\\.venv\\Scripts\\gates-of-codex.exe import-battle "{campaign_path}" '
        f'--save "{installed_save_path}"'
    )
    return FirstEngineTestResult(
        session_directory=str(session),
        campaign_path=str(campaign_path),
        export_save_path=str(export_save_path),
        installed_save_path=str(installed_save_path),
        status_template_path=str(template_path),
        map_name=map_name,
        profile_directory=str(profile),
        install_directory=str(install_root),
        selection=selection,
        handoff=handoff,
        verify_command=verify_command,
        import_command=import_command,
        visible_campaign_name=visible_name,
    )


def _select_nato_russia_border(state: CampaignState) -> tuple[str, str]:
    occupancy = {battalion.province_id for battalion in state.battalions.values()}
    candidates: list[tuple[int, str, str, str, str]] = []
    for origin in state.provinces.values():
        if origin.owner != Faction.NATO:
            continue
        for neighbor_id in origin.neighbors:
            target = state.provinces[neighbor_id]
            if target.owner != Faction.RUSSIA:
                continue
            occupied = int(origin.province_id in occupancy) + int(target.province_id in occupancy)
            candidates.append(
                (
                    occupied,
                    origin.display_name.lower(),
                    target.display_name.lower(),
                    origin.province_id,
                    target.province_id,
                )
            )
    if not candidates:
        raise RuntimeError("No NATO-to-Russia ownership border exists in the campaign map")
    _, _, _, origin_id, target_id = sorted(candidates)[0]
    return origin_id, target_id


def _select_battalion(state: CampaignState, faction: Faction, preferred_formation: str) -> Battalion:
    battalions = [value for value in state.battalions.values() if value.faction == faction]
    if not battalions:
        raise RuntimeError(f"No battalion exists for {faction.value}")
    return sorted(
        battalions,
        key=lambda value: (value.formation_id != preferred_formation, value.formation_id, value.battalion_id),
    )[0]


def _clear_border_occupants(
    state: CampaignState,
    origin_id: str,
    target_id: str,
    selected_ids: set[str],
) -> None:
    occupied = {value.province_id for value in state.battalions.values()}
    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        if battalion.battalion_id in selected_ids or battalion.province_id not in {origin_id, target_id}:
            continue
        destination = next(
            (
                province.province_id
                for province in sorted(state.provinces.values(), key=lambda value: value.province_id)
                if province.owner == battalion.faction
                and province.province_id not in occupied
                and province.province_id not in {origin_id, target_id}
            ),
            None,
        )
        if destination is None:
            raise RuntimeError(f"Could not relocate border occupant {battalion.battalion_id}")
        occupied.discard(battalion.province_id)
        battalion.province_id = destination
        occupied.add(destination)
