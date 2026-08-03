from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .acceptance import (
    AcceptanceReport,
    HandoffResult,
    MapCandidate,
    ValidationCheck,
    backup_existing_files,
    discover_maps,
    verify_tactical_result,
)
from .codex.catalog import CodeXCatalogScanner
from .launcher import find_game_executable, launch_game
from .modstack import (
    resolve_stack,
    stack_to_strings,
    validate_known_order,
    validate_stack_paths,
)
from .service import BattleExportManifest, GatesOfCodeXService


@dataclass(slots=True)
class StackValidationReport:
    game_directory: str
    code_x_directory: str
    profile_directory: str
    resource_stack: list[str] = field(default_factory=list)
    catalog_signature: str = ""
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
        for faction in ("nato", "ukr", "rusa", "prc"):
            report.unit_counts[faction] = len(catalog.by_faction(faction))
        missing = [faction for faction, count in report.unit_counts.items() if count <= 0]
        report.checks.append(
            ValidationCheck(
                "code_x_factions",
                not missing,
                "all four factions found" if not missing else f"missing unit catalogs: {', '.join(missing)}",
            )
        )
    except Exception as exc:
        report.checks.append(ValidationCheck("code_x_catalog", False, str(exc)))

    report.maps = discover_maps(*stack)
    report.checks.append(
        ValidationCheck(
            "tactical_maps",
            bool(report.maps),
            f"{len(report.maps)} candidate map identifiers discovered across the stack",
        )
    )
    if profile is not None:
        report.checks.append(ValidationCheck("profile_directory", profile.is_dir(), str(profile)))
        report.checks.append(ValidationCheck("profile_writable", _directory_writable(profile), str(profile)))
    return report


def prepare_stack_handoff(
    campaign_path: str | Path,
    *,
    game_directory: str | Path,
    code_x_directory: str | Path,
    save_path: str | Path,
    map_name: str,
    resource_stack: Iterable[str | Path] | None = None,
    stack_config: str | Path | None = None,
    profile_directory: str | Path | None = None,
    install_save_path: str | Path | None = None,
    backup_root: str | Path | None = None,
    launch: bool = False,
) -> HandoffResult:
    stack = resolve_stack(resource_stack, config=stack_config, fallback=code_x_directory)
    validation = validate_mod_stack(
        game_directory,
        code_x_directory,
        resource_stack=stack,
        profile_directory=profile_directory,
    )
    if not validation.ok:
        failed = [check.detail for check in validation.checks if not check.ok]
        raise RuntimeError("Live mod-stack validation failed: " + "; ".join(failed))

    normalized = _normalize_map(map_name)
    discovered = {_normalize_map(value.identifier) for value in validation.maps}
    if normalized not in discovered:
        raise ValueError(f"Map identifier was not discovered in the configured mod stack: {map_name}")

    campaign = Path(campaign_path).resolve()
    export_save = Path(save_path).resolve()
    installed = Path(install_save_path).resolve() if install_save_path else None
    service = GatesOfCodeXService()
    paths = [campaign, export_save, service.manifest_path(export_save)]
    if installed is not None:
        paths.extend([installed, service.manifest_path(installed)])
    backup = backup_existing_files(paths, backup_root=backup_root, label="tactical-handoff")
    manifest = service.export_battle(
        campaign,
        code_x_directory=code_x_directory,
        resource_stack=stack,
        save_path=export_save,
        map_name=map_name,
        allow_overwrite=True,
    )

    installed_path = ""
    if installed is not None:
        installed.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(export_save, installed)
        _atomic_copy(service.manifest_path(export_save), service.manifest_path(installed))
        installed_path = str(installed)

    session_path = service.manifest_path(export_save).with_suffix(".session.json")
    result = HandoffResult(
        manifest=manifest,
        validation=validation,
        backup=backup,
        installed_save_path=installed_path,
        session_path=str(session_path),
        launched=False,
    )
    if launch:
        launch_game(game_directory)
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
        manifest = BattleExportManifest(**json.loads(Path(manifest_path).read_text(encoding="utf-8-sig")))
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
