from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .bridge.archive import CampaignSaveArchive
from .models import CampaignState, Faction
from .service import goh_conquest_save_filename, read_status_campaign_name, unique_acceptance_campaign_name
from .state_io import load_campaign, save_campaign


def collect_visible_campaign_names(install_root: str | Path) -> set[str]:
    names: set[str] = set()
    root = Path(install_root)
    if not root.is_dir():
        return names
    archive = CampaignSaveArchive()
    for path in root.glob("*.sav"):
        try:
            status = archive.read(path).status
        except (OSError, ValueError):
            continue
        name = read_status_campaign_name(status)
        if name:
            names.add(name)
    return names


def resolve_status_template(
    install_root: str | Path,
    installed_save_path: str | Path,
    explicit: str | Path | None = None,
    *,
    name_prefix: str = "Gates of CodeX",
) -> Path:
    archive = CampaignSaveArchive()
    install = Path(install_root)
    installed = Path(installed_save_path).resolve()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        archive.validate(candidate)
        return candidate
    candidates = sorted(
        (path for path in install.glob("*.sav") if path.resolve() != installed),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    # #166 D2: newest-wins let an unrelated campaign save become the template.
    # Prefer our own saves, and never silently adopt someone else's campaign.
    ours: list[Path] = []
    unrelated: list[Path] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            archive.validate(candidate)
        except (OSError, ValueError) as exc:
            errors.append(f"{candidate.name}: {exc}")
            continue
        (ours if _is_own_save(archive, candidate, name_prefix) else unrelated).append(candidate)
    if ours:
        return ours[0].resolve()
    if len(unrelated) == 1:
        # The documented first-run setup is "create and save one normal Conquest
        # with the intended mod stack", which carries the player's own name rather
        # than ours. A single candidate is that save; it is not a silent choice
        # among alternatives, and its {mods} block is fully replaced on export.
        return unrelated[0].resolve()
    if unrelated:
        listed = ", ".join(path.name for path in unrelated[:5])
        raise RuntimeError(
            f"Refusing to pick a saveinfo template by modification time among "
            f"{len(unrelated)} unrelated campaign saves in {install}: {listed}. "
            f"No {name_prefix} save is present to inherit from. Pass --template-save "
            "explicitly to choose the Conquest save that carries the intended mod stack."
        )
    detail = "; ".join(errors[:5]) if errors else "no other .sav files were found"
    raise RuntimeError(
        "No valid Conquest saveinfo template was found. Create and save one normal Conquest with the intended mod stack, "
        f"or pass --template-save explicitly. Details: {detail}"
    )


def _is_own_save(archive: CampaignSaveArchive, candidate: Path, name_prefix: str) -> bool:
    """True when a save's visible campaign name marks it as one of ours.

    Identity comes from the save's own ``{name}``, which is what
    :func:`allocate_visible_campaign_name` stamps, so a template can only be
    inherited from a campaign this tool created.
    """
    prefix = str(name_prefix).strip()
    if not prefix:
        return False
    try:
        status = archive.read(candidate).status
    except (OSError, ValueError):
        return False
    return read_status_campaign_name(status).strip().startswith(prefix)


def allocate_visible_campaign_name(
    battle_id: str,
    *,
    install_root: str | Path | None = None,
    prefix: str = "Gates of CodeX",
) -> str:
    reserved = collect_visible_campaign_names(install_root) if install_root else set()
    return unique_acceptance_campaign_name(battle_id, reserved=reserved, prefix=prefix)


def default_install_save_path(install_root: str | Path, visible_campaign_name: str) -> Path:
    return Path(install_root).expanduser().resolve() / goh_conquest_save_filename(visible_campaign_name)


def default_export_save_path(work_root: str | Path, battle_id: str) -> Path:
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in battle_id)
    folder = Path(work_root).expanduser().resolve() / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "campaign.sav"


def persist_play_context(
    campaign_path: str | Path,
    *,
    game_directory: str | Path | None = None,
    profile_directory: str | Path | None = None,
    install_directory: str | Path | None = None,
    preferred_map: str | None = None,
    stack_config: str | Path | None = None,
) -> None:
    path = Path(campaign_path).resolve()
    state = load_campaign(path)
    if game_directory:
        state.game_directory = str(Path(game_directory).expanduser().resolve())
    if profile_directory:
        state.profile_directory = str(Path(profile_directory).expanduser().resolve())
    if install_directory:
        state.map_metadata["install_directory"] = str(Path(install_directory).expanduser().resolve())
    if preferred_map:
        state.map_metadata["preferred_map"] = preferred_map
    if stack_config:
        state.map_metadata["stack_config"] = str(Path(stack_config).expanduser().resolve())
    save_campaign(state, path)


def build_operator_commands(
    campaign_path: str | Path,
    *,
    installed_save_path: str | Path,
    stack_config: str | Path | None = None,
    report_path: str | Path | None = None,
) -> tuple[str, str]:
    campaign = Path(campaign_path).resolve()
    installed = Path(installed_save_path).resolve()
    stack = f' --stack-config "{Path(stack_config).resolve()}"' if stack_config else ""
    report = (
        f' --output "{Path(report_path).resolve()}"'
        if report_path
        else f' --output "{installed.with_suffix(installed.suffix + ".acceptance-report.json")}"'
    )
    verify = (
        f'& .\\.venv\\Scripts\\gates-of-codex-live.exe verify "{campaign}" '
        f'--save "{installed}"{stack}{report}'
    )
    import_cmd = f'& .\\.venv\\Scripts\\gates-of-codex.exe import-battle "{campaign}" --save "{installed}"'
    return verify, import_cmd


def normalize_map_id(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/").lower()
    for prefix in ("resource/map/", "resource/maps/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def select_tactical_map(
    available: Iterable[str],
    *,
    preferred: str | None = None,
    used: Iterable[str] | None = None,
    battle_id: str = "",
    explicit: str | None = None,
) -> str:
    """Choose a tactical map for handoff.

    Explicit ``--map`` always wins. Otherwise rotate through playable ``dcg_``
    maps, skipping recently used ones so Conquest does not keep forcing Fulda.
    """

    if explicit:
        return explicit
    pool = [str(value) for value in available if str(value).strip()]
    if not pool:
        raise ValueError("No tactical maps are available in the configured mod stack")
    ranked = [
        value
        for value in pool
        if "dcg_" in value.lower() and "test" not in value.lower() and "zeeland_sum_test" not in value.lower()
    ]
    if not ranked:
        ranked = list(pool)
    used_norm = {normalize_map_id(value) for value in (used or []) if value}
    fresh = [value for value in ranked if normalize_map_id(value) not in used_norm]
    choices = fresh or ranked
    if preferred:
        preferred_norm = normalize_map_id(preferred)
        for value in choices:
            if normalize_map_id(value) == preferred_norm:
                # Only keep preferred while it is still fresh.
                if preferred_norm not in used_norm or not fresh:
                    return value
    if battle_id:
        index = sum(ord(character) for character in battle_id) % len(choices)
        return choices[index]
    return choices[0]


def list_front_options(state: CampaignState, faction: Faction | None = None) -> list[dict]:
    """List legal moves/attacks for the current (or specified) faction."""

    from .diplomacy import are_allied, is_friendly_owner
    from .earth3_bootstrap import earth3_p2_movement_unavailable

    if earth3_p2_movement_unavailable(state):
        return []

    active = faction or state.current_faction
    options: list[dict] = []
    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        if battalion.faction != active:
            continue
        if battalion.movement_remaining <= 0 and battalion.combat_actions_remaining <= 0:
            continue
        origin = state.provinces[battalion.province_id]
        for neighbor_id in origin.neighbors:
            target = state.provinces[neighbor_id]
            occupant = next(
                (
                    other
                    for other in state.battalions.values()
                    if other.province_id == neighbor_id
                ),
                None,
            )
            if occupant is not None and are_allied(state, battalion.faction, occupant.faction):
                continue
            if occupant is not None and not are_allied(state, battalion.faction, occupant.faction):
                kind = "battle"
                enemies = [occupant.battalion_id]
            elif occupant is None and (
                target.owner == Faction.NEUTRAL or is_friendly_owner(state, battalion.faction, target.owner)
            ):
                kind = "neutral" if target.owner == Faction.NEUTRAL else "move"
                enemies = []
            elif occupant is None and target.owner != Faction.NEUTRAL and not is_friendly_owner(
                state, battalion.faction, target.owner
            ):
                kind = "capture"
                enemies = []
            else:
                continue
            options.append(
                {
                    "battalion_id": battalion.battalion_id,
                    "formation_id": battalion.formation_id,
                    "origin": battalion.province_id,
                    "origin_name": origin.display_name,
                    "target": neighbor_id,
                    "target_name": target.display_name,
                    "target_owner": target.owner.value,
                    "kind": kind,
                    "enemies": enemies,
                    "command": f"move {battalion.battalion_id} {neighbor_id}",
                }
            )
    kind_order = {"battle": 0, "capture": 1, "neutral": 2, "move": 3}
    return sorted(options, key=lambda row: (kind_order.get(str(row["kind"]), 9), str(row["battalion_id"]), str(row["target"])))
