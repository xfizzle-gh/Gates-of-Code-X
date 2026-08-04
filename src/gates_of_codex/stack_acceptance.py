from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable

from .acceptance import (
    AcceptanceReport,
    HandoffResult,
    ValidationCheck,
    backup_existing_files,
    verify_tactical_result,
)
from .codex.catalog import CodeXCatalogScanner
from .launcher import find_game_executable, launch_game
from .map_discovery import MapCandidate, discover_maps
from .modstack import (
    resolve_stack,
    stack_mod_tokens,
    stack_to_strings,
    validate_known_order,
    validate_stack_paths,
)
from .service import (
    BattleExportManifest,
    GatesOfCodeXService,
    apply_installed_fingerprint,
    merge_mod_tokens,
    read_profile_mod_tokens,
)


@dataclass(slots=True)
class StackValidationReport:
    game_directory: str
    code_x_directory: str
    profile_directory: str
    resource_stack: list[str] = field(default_factory=list)
    catalog_signature: str = ""
    raw_unit_counts: dict[str, int] = field(default_factory=dict)
    unit_counts: dict[str, int] = field(default_factory=dict)
    maps: list[MapCandidate] = field(default_factory=list)
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "game_directory": self.game_directory,
            "code_x_directory": self.code_x_directory,
            "profile_directory": self.profile_directory,
            "resource_stack": self.resource_stack,
            "catalog_signature": self.catalog_signature,
            "raw_unit_counts": self.raw_unit_counts,
            "unit_counts": self.unit_counts,
            "maps": [asdict(value) for value in self.maps],
            "checks": [asdict(value) for value in self.checks],
        }


def validate_mod_stack(
    game_directory: str | Path,
    code_x_directory: str | Path,
    *,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
    profile_directory: str | Path | None = None,
) -> StackValidationReport:
    game = Path(game_directory).expanduser().resolve()
    codex = Path(code_x_directory).expanduser().resolve()
    profile = Path(profile_directory).expanduser().resolve() if profile_directory else None
    stack = resolve_stack(resource_stack, config=stack_config, fallback=codex)
    report = StackValidationReport(
        game_directory=str(game),
        code_x_directory=str(codex),
        profile_directory=str(profile) if profile else "",
        resource_stack=stack_to_strings(stack),
    )

    report.checks.append(ValidationCheck("game_directory", game.is_dir(), str(game)))
    try:
        executable = find_game_executable(game)
        report.checks.append(ValidationCheck("game_executable", True, str(executable)))
    except Exception as exc:
        report.checks.append(ValidationCheck("game_executable", False, str(exc)))

    report.checks.append(ValidationCheck("code_x_directory", codex.is_dir(), str(codex)))
    report.checks.append(ValidationCheck("code_x_mod_info", (codex / "mod.info").is_file(), str(codex / "mod.info")))
    report.checks.append(
        ValidationCheck(
            "code_x_in_stack",
            codex in stack,
            "primary Code:X layer is present" if codex in stack else f"primary Code:X layer missing from stack: {codex}",
        )
    )

    path_errors = validate_stack_paths(stack)
    report.checks.append(
        ValidationCheck(
            "stack_paths",
            not path_errors,
            f"{len(stack)} ordered layers found" if not path_errors else "; ".join(path_errors),
        )
    )
    order_ok, order_detail = validate_known_order(stack)
    report.checks.append(ValidationCheck("stack_order", order_ok, order_detail))

    try:
        catalog = CodeXCatalogScanner().scan_stack(stack)
        report.catalog_signature = catalog.signature
        diagnostics = catalog.diagnostic_counts()
        for faction in ("nato", "ukr", "rusa", "prc"):
            report.raw_unit_counts[faction] = diagnostics[faction]["raw"]
            report.unit_counts[faction] = diagnostics[faction]["materializable"]
        missing = [faction for faction, count in report.unit_counts.items() if count <= 0]
        detail = "; ".join(
            f"{faction}: {report.unit_counts[faction]} materializable / {report.raw_unit_counts[faction]} raw"
            for faction in ("nato", "ukr", "rusa", "prc")
        )
        report.checks.append(
            ValidationCheck(
                "code_x_factions",
                not missing,
                detail if not missing else f"missing materializable unit catalogs: {', '.join(missing)}; {detail}",
            )
        )
    except Exception as exc:
        report.checks.append(ValidationCheck("code_x_catalog", False, str(exc)))

    report.maps = discover_maps(*stack)
    report.checks.append(
        ValidationCheck(
            "tactical_maps",
            bool(report.maps),
            f"{len(report.maps)} playable map roots discovered across the stack",
        )
    )
    if profile is not None:
        report.checks.append(ValidationCheck("profile_directory", profile.is_dir(), str(profile)))
        report.checks.append(ValidationCheck("profile_writable", _directory_writable(profile), str(profile)))
    return report


def prepare_stack_handoff(
    campaign_path: str | Path,
    *,
    game_directory: str | Path | None = None,
    code_x_directory: str | Path | None = None,
    save_path: str | Path | None = None,
    map_name: str | None = None,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
    profile_directory: str | Path | None = None,
    install_directory: str | Path | None = None,
    install_save_path: str | Path | None = None,
    status_template_path: str | Path | None = None,
    backup_root: str | Path | None = None,
    work_root: str | Path = "live",
    launch: bool = False,
    campaign_name: str | None = None,
    name_prefix: str = "Gates of CodeX",
) -> HandoffResult:
    from .play_context import (
        allocate_visible_campaign_name,
        build_operator_commands,
        default_export_save_path,
        default_install_save_path,
        resolve_status_template,
    )
    from .state_io import load_campaign, save_campaign

    campaign = Path(campaign_path).resolve()
    state = load_campaign(campaign)
    if state.pending_battle is None:
        raise RuntimeError("Campaign has no pending battle to hand off")

    game_raw = game_directory or state.game_directory
    codex_raw = code_x_directory or state.code_x_directory
    if not game_raw:
        raise ValueError("game_directory is required (pass --game or persist it on the campaign)")
    if not codex_raw:
        raise ValueError("code_x_directory is required (pass --codex or persist it on the campaign)")
    game = Path(game_raw).expanduser().resolve()
    codex = Path(codex_raw).expanduser().resolve()

    profile = None
    if profile_directory or state.profile_directory:
        profile = Path(profile_directory or state.profile_directory).expanduser().resolve()

    preferred_map = map_name or str(state.map_metadata.get("preferred_map") or "")
    if not preferred_map:
        raise ValueError("map_name is required (pass --map or set campaign map_metadata.preferred_map)")

    stack = resolve_stack(
        resource_stack or state.map_metadata.get("resource_stack"),
        config=stack_config or state.map_metadata.get("stack_config"),
        fallback=codex,
    )
    validation = validate_mod_stack(
        game,
        codex,
        resource_stack=stack,
        profile_directory=profile,
    )
    if not validation.ok:
        failed = [check.detail for check in validation.checks if not check.ok]
        raise RuntimeError("Live mod-stack validation failed: " + "; ".join(failed))

    normalized = _normalize_map(preferred_map)
    discovered = {_normalize_map(value.identifier) for value in validation.maps}
    if normalized not in discovered:
        raise ValueError(f"Map identifier was not discovered in the configured mod stack: {preferred_map}")

    install_root = None
    if install_directory:
        install_root = Path(install_directory).expanduser().resolve()
    elif state.map_metadata.get("install_directory"):
        install_root = Path(str(state.map_metadata["install_directory"])).expanduser().resolve()
    elif profile is not None:
        candidate = profile / "campaign"
        install_root = candidate if candidate.is_dir() else profile

    visible_name = campaign_name or allocate_visible_campaign_name(
        state.pending_battle.battle_id,
        install_root=install_root,
        prefix=name_prefix,
    )

    if save_path is None:
        export_save = default_export_save_path(work_root, state.pending_battle.battle_id)
    else:
        export_save = Path(save_path).expanduser().resolve()
        if export_save.exists() and export_save.is_dir():
            export_save = export_save / f"{state.pending_battle.battle_id}.sav"
        elif export_save.suffix.lower() != ".sav":
            export_save.mkdir(parents=True, exist_ok=True)
            export_save = export_save / f"{state.pending_battle.battle_id}.sav"

    if install_save_path:
        installed = Path(install_save_path).expanduser().resolve()
    elif install_root is not None:
        installed = default_install_save_path(install_root, visible_name)
    else:
        installed = None

    if status_template_path:
        template = Path(status_template_path).expanduser().resolve()
    elif install_root is not None:
        template = resolve_status_template(install_root, installed or export_save)
    else:
        template = None

    service = GatesOfCodeXService()
    if template is not None:
        service.archive.validate(template)
    paths = [campaign, export_save, service.manifest_path(export_save)]
    if installed is not None:
        paths.extend([installed, service.manifest_path(installed)])
    backup = backup_existing_files(paths, backup_root=backup_root, label="tactical-handoff")
    profile_mods = read_profile_mod_tokens(profile)
    export_mods = merge_mod_tokens(profile_mods, stack_mod_tokens(stack))
    manifest = service.export_battle(
        campaign,
        code_x_directory=codex,
        resource_stack=stack,
        save_path=export_save,
        map_name=preferred_map,
        status_template_path=template,
        allow_overwrite=True,
        campaign_name=visible_name,
        mods=export_mods,
    )
    service.archive.validate(export_save)

    installed_path = ""
    if installed is not None:
        installed.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(export_save, installed)
        service.archive.validate(installed)
        installed_manifest = replace(manifest, save_path=str(installed))
        apply_installed_fingerprint(installed_manifest, installed)
        service.write_manifest(installed_manifest)
        apply_installed_fingerprint(manifest, installed)
        service.write_manifest(manifest)
        installed_path = str(installed)

    # Persist play context so the next battle needs fewer flags.
    state = load_campaign(campaign)
    state.game_directory = str(game)
    state.code_x_directory = str(codex)
    if profile is not None:
        state.profile_directory = str(profile)
    state.map_metadata["resource_stack"] = stack_to_strings(stack)
    state.map_metadata["preferred_map"] = preferred_map
    if install_root is not None:
        state.map_metadata["install_directory"] = str(install_root)
    if stack_config:
        state.map_metadata["stack_config"] = str(Path(stack_config).expanduser().resolve())
    elif state.map_metadata.get("stack_config"):
        pass
    save_campaign(state, campaign)

    verify_command = ""
    import_command = ""
    if installed_path:
        verify_command, import_command = build_operator_commands(
            campaign,
            installed_save_path=installed_path,
            stack_config=stack_config or state.map_metadata.get("stack_config"),
            report_path=Path(export_save).with_name("acceptance-report.json"),
        )

    session_path = service.manifest_path(export_save).with_suffix(".session.json")
    result = HandoffResult(
        manifest=manifest,
        validation=validation,
        backup=backup,
        installed_save_path=installed_path,
        session_path=str(session_path),
        launched=False,
        visible_campaign_name=manifest.visible_campaign_name,
        verify_command=verify_command,
        import_command=import_command,
    )
    if launch:
        launch_game(game)
        result.launched = True
    session_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return result


def verify_stack_result(
    campaign_path: str | Path,
    *,
    save_path: str | Path,
    code_x_directory: str | Path | None = None,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
) -> AcceptanceReport:
    report = verify_tactical_result(campaign_path, save_path=save_path, code_x_directory=None)
    report.warnings = [value for value in report.warnings if "signature was not rechecked" not in value]
    manifest_path = GatesOfCodeXService.manifest_path(save_path)
    try:
        manifest = GatesOfCodeXService.load_manifest(manifest_path)
        stack = resolve_stack(
            resource_stack or manifest.resource_stack,
            config=stack_config,
            fallback=code_x_directory,
        )
        if not stack:
            report.catalog_matches = False
            report.errors.append("No mod stack was available for post-battle verification")
        else:
            signature = CodeXCatalogScanner().scan_stack(stack).signature
            report.catalog_matches = signature == manifest.catalog_signature
            if not report.catalog_matches:
                report.errors.append("Code:X mod stack changed after export")
    except Exception as exc:
        report.catalog_matches = False
        report.errors.append(str(exc))
    report.ok = report.archive_valid and report.catalog_matches and not report.errors
    return report


def _directory_writable(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".goc-write-test-", delete=True):
            return True
    except OSError:
        return False


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.goc-tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _normalize_map(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/").lower()
    for prefix in ("resource/map/", "resource/maps/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized
