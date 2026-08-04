from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .bridge.archive import CampaignSaveArchive
from .bridge.scn import CampaignScnBuilder, CampaignScnParser
from .bridge.status import StatusBuilder
from .codex.catalog import CodeXCatalogScanner
from .launcher import find_game_executable, launch_game
from .service import (
    BattleExportManifest,
    GatesOfCodeXService,
    fingerprint_save,
)
from .state_io import load_campaign


@dataclass(frozen=True, slots=True)
class MapCandidate:
    identifier: str
    source: str
    path: str


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    ok: bool
    detail: str


@dataclass(slots=True)
class LiveValidationReport:
    game_directory: str
    code_x_directory: str
    profile_directory: str
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
            "catalog_signature": self.catalog_signature,
            "unit_counts": self.unit_counts,
            "maps": [asdict(value) for value in self.maps],
            "checks": [asdict(value) for value in self.checks],
        }


@dataclass(slots=True)
class BackupRecord:
    backup_directory: str
    files: dict[str, str]
    created_at_utc: str


@dataclass(slots=True)
class HandoffResult:
    manifest: BattleExportManifest
    validation: LiveValidationReport
    backup: BackupRecord
    installed_save_path: str = ""
    session_path: str = ""
    launched: bool = False
    visible_campaign_name: str = ""
    verify_command: str = ""
    import_command: str = ""

    def to_dict(self) -> dict:
        return {
            "manifest": asdict(self.manifest),
            "validation": self.validation.to_dict(),
            "backup": asdict(self.backup),
            "installed_save_path": self.installed_save_path,
            "session_path": self.session_path,
            "launched": self.launched,
            "visible_campaign_name": self.visible_campaign_name or self.manifest.visible_campaign_name,
            "verify_command": self.verify_command,
            "import_command": self.import_command,
            "load_instruction": (
                f"Load this exact Conquest entry: {self.visible_campaign_name or self.manifest.visible_campaign_name}"
                if (self.visible_campaign_name or self.manifest.visible_campaign_name)
                else ""
            ),
        }


@dataclass(slots=True)
class AcceptanceReport:
    ok: bool
    battle_id: str = ""
    map_name: str = ""
    visible_campaign_name: str = ""
    catalog_matches: bool = False
    archive_valid: bool = False
    installed_save_rewritten: bool | None = None
    played_games_before: int = 0
    played_games_after: int = 0
    won_games_before: int = 0
    won_games_after: int = 0
    surviving_squads: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_maps(*roots: str | Path) -> list[MapCandidate]:
    values: dict[str, MapCandidate] = {}
    for raw_root in roots:
        root = Path(raw_root)
        if not root.is_dir():
            continue
        for relative_root in (Path("resource/map"), Path("resource/maps")):
            map_root = root / relative_root
            if not map_root.is_dir():
                continue
            for path in map_root.rglob("*"):
                if not path.is_file():
                    continue
                name = path.name.lower()
                if name not in {"map", "map.mi"} and path.suffix.lower() != ".mi":
                    continue
                if name in {"map", "map.mi"}:
                    identifier_path = path.parent.relative_to(map_root)
                else:
                    identifier_path = path.relative_to(map_root).with_suffix("")
                identifier = identifier_path.as_posix().strip("/")
                if not identifier or identifier == ".":
                    continue
                values.setdefault(
                    identifier.lower(),
                    MapCandidate(identifier=identifier, source=str(root.resolve()), path=str(path.resolve())),
                )
    return sorted(values.values(), key=lambda value: value.identifier.lower())


def validate_live_installation(
    game_directory: str | Path,
    code_x_directory: str | Path,
    profile_directory: str | Path | None = None,
) -> LiveValidationReport:
    game = Path(game_directory).resolve()
    codex = Path(code_x_directory).resolve()
    profile = Path(profile_directory).resolve() if profile_directory else None
    report = LiveValidationReport(str(game), str(codex), str(profile) if profile else "")

    report.checks.append(ValidationCheck("game_directory", game.is_dir(), str(game)))
    try:
        executable = find_game_executable(game)
        report.checks.append(ValidationCheck("game_executable", True, str(executable)))
    except Exception as exc:
        report.checks.append(ValidationCheck("game_executable", False, str(exc)))

    mod_info = codex / "mod.info"
    report.checks.append(ValidationCheck("code_x_directory", codex.is_dir(), str(codex)))
    report.checks.append(ValidationCheck("code_x_mod_info", mod_info.is_file(), str(mod_info)))
    try:
        catalog = CodeXCatalogScanner().scan(codex)
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

    report.maps = discover_maps(game, codex)
    report.checks.append(
        ValidationCheck(
            "tactical_maps",
            bool(report.maps),
            f"{len(report.maps)} candidate map identifiers discovered",
        )
    )
    if profile is not None:
        report.checks.append(ValidationCheck("profile_directory", profile.is_dir(), str(profile)))
        report.checks.append(
            ValidationCheck("profile_writable", _directory_writable(profile), str(profile))
        )
    return report


def backup_existing_files(
    paths: Iterable[str | Path],
    *,
    backup_root: str | Path | None = None,
    label: str = "handoff",
) -> BackupRecord:
    root = Path(backup_root) if backup_root else Path(tempfile.gettempdir()) / "GatesOfCodeXBackups"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = root.resolve() / f"{timestamp}-{_safe_name(label)}"
    destination.mkdir(parents=True, exist_ok=False)
    copied: dict[str, str] = {}
    for index, raw_path in enumerate(paths):
        source = Path(raw_path).resolve()
        if not source.is_file():
            continue
        backup = destination / f"{index:02d}-{source.name}"
        shutil.copy2(source, backup)
        copied[str(source)] = str(backup)
    record = BackupRecord(str(destination), copied, datetime.now(UTC).isoformat())
    (destination / "backup.json").write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")
    return record


def restore_backup(backup: BackupRecord | str | Path) -> list[Path]:
    if isinstance(backup, BackupRecord):
        record = backup
    else:
        root = Path(backup)
        manifest = root / "backup.json" if root.is_dir() else root
        record = BackupRecord(**json.loads(manifest.read_text(encoding="utf-8-sig")))
    restored: list[Path] = []
    for original, saved in record.files.items():
        source = Path(saved)
        destination = Path(original)
        if not source.is_file():
            raise FileNotFoundError(f"Backup file is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(source, destination)
        restored.append(destination)
    return restored


def prepare_tactical_handoff(
    campaign_path: str | Path,
    *,
    game_directory: str | Path,
    code_x_directory: str | Path,
    save_path: str | Path,
    map_name: str,
    profile_directory: str | Path | None = None,
    install_save_path: str | Path | None = None,
    backup_root: str | Path | None = None,
    launch: bool = False,
) -> HandoffResult:
    campaign = Path(campaign_path).resolve()
    export_save = Path(save_path).resolve()
    installed = Path(install_save_path).resolve() if install_save_path else None
    validation = validate_live_installation(game_directory, code_x_directory, profile_directory)
    if not validation.ok:
        failed = [check.detail for check in validation.checks if not check.ok]
        raise RuntimeError("Live installation validation failed: " + "; ".join(failed))
    normalized = _normalize_map(map_name)
    discovered = {_normalize_map(value.identifier) for value in validation.maps}
    if normalized not in discovered:
        raise ValueError(f"Map identifier was not discovered in GoH or Code:X: {map_name}")

    service = GatesOfCodeXService()
    paths = [campaign, export_save, service.manifest_path(export_save)]
    if installed is not None:
        paths.extend([installed, service.manifest_path(installed)])
    backup = backup_existing_files(paths, backup_root=backup_root, label="tactical-handoff")
    manifest = service.export_battle(
        campaign,
        code_x_directory=code_x_directory,
        save_path=export_save,
        map_name=map_name,
        allow_overwrite=True,
    )
    installed_path = ""
    if installed is not None:
        from .service import apply_installed_fingerprint

        installed.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy(export_save, installed)
        installed_manifest = service.load_manifest(service.manifest_path(export_save))
        installed_manifest.save_path = str(installed)
        apply_installed_fingerprint(installed_manifest, installed)
        service.write_manifest(installed_manifest)
        apply_installed_fingerprint(manifest, installed)
        service.write_manifest(manifest)
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


def verify_tactical_result(
    campaign_path: str | Path,
    *,
    save_path: str | Path,
    code_x_directory: str | Path | None = None,
) -> AcceptanceReport:
    service = GatesOfCodeXService()
    campaign = Path(campaign_path).resolve()
    save = Path(save_path).resolve()
    manifest_path = service.manifest_path(save)
    report = AcceptanceReport(ok=False)
    if not campaign.is_file():
        report.errors.append(f"Campaign file not found: {campaign}")
        return report
    if not save.is_file():
        report.errors.append(f"Tactical save not found: {save}")
        return report
    if not manifest_path.is_file():
        report.errors.append(f"Battle manifest not found: {manifest_path}")
        return report

    try:
        manifest = GatesOfCodeXService.load_manifest(manifest_path)
        report.battle_id = manifest.battle_id
        report.map_name = manifest.map_name
        report.visible_campaign_name = manifest.visible_campaign_name
        report.played_games_before = manifest.played_games
        report.won_games_before = manifest.won_games
        if Path(manifest.campaign_path).resolve() != campaign:
            report.errors.append("Manifest belongs to a different strategic campaign")
        if Path(manifest.save_path).resolve() != save:
            report.errors.append("Manifest belongs to a different tactical save")
        if manifest.has_installed_fingerprint:
            current_fingerprint = fingerprint_save(save)
            unchanged = (
                current_fingerprint.sha256 == manifest.installed_sha256
                and current_fingerprint.size == manifest.installed_size
            )
            report.installed_save_rewritten = not unchanged
            if unchanged:
                report.errors.append("Installed acceptance save was not rewritten by GoH")
        else:
            report.warnings.append(
                "Installed save fingerprint was not recorded at handoff; "
                "untouched-target detection is unavailable for this manifest"
            )
        state = load_campaign(campaign)
        if state.pending_battle is None or state.pending_battle.battle_id != manifest.battle_id:
            report.errors.append("Campaign pending battle does not match the manifest")
        if code_x_directory:
            signature = CodeXCatalogScanner().scan(code_x_directory).signature
            report.catalog_matches = signature == manifest.catalog_signature
            if not report.catalog_matches:
                report.errors.append("Code:X catalog changed after export")
        else:
            report.catalog_matches = True
            report.warnings.append("Code:X catalog signature was not rechecked")
        contents = CampaignSaveArchive().read(save)
        CampaignScnBuilder.validate(contents.campaign_scn)
        squads = CampaignScnParser().parse_squads(contents.campaign_scn)
        report.surviving_squads = len([value for value in squads if value.object_ids])
        current = StatusBuilder().parse_result(contents.status)
        report.played_games_after = current.played_games
        report.won_games_after = current.won_games
        report.archive_valid = True
        if current.played_games <= manifest.played_games:
            report.errors.append("GoH has not recorded completion of this battle")
        if not squads:
            report.errors.append("Updated campaign.scn contains no surviving campaign squads")
    except Exception as exc:
        report.errors.append(str(exc))
    report.ok = report.archive_valid and report.catalog_matches and not report.errors
    return report


def write_acceptance_report(report: AcceptanceReport, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    return destination


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


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "-" for character in value).strip("-") or "backup"
