from __future__ import annotations

from pathlib import Path

from .bridge.archive import CampaignSaveArchive
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
    errors: list[str] = []
    for candidate in candidates:
        try:
            archive.validate(candidate)
            return candidate.resolve()
        except (OSError, ValueError) as exc:
            errors.append(f"{candidate.name}: {exc}")
    detail = "; ".join(errors[:5]) if errors else "no other .sav files were found"
    raise RuntimeError(
        "No valid Conquest saveinfo template was found. Create and save one normal Conquest with the intended mod stack, "
        f"or pass --template-save explicitly. Details: {detail}"
    )


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
