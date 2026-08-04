from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .bridge.archive import CampaignSaveArchive
from .bridge.result import BattleImportResult, BattleResultImporter
from .bridge.scn import CampaignScnBuilder
from .bridge.status import BattleStatusOptions, StatusBuilder, StatusResult
from .campaign import CampaignEngine
from .codex.catalog import CodeXCatalogScanner
from .modstack import resolve_stack, stack_mod_tokens, stack_to_strings
from .state_io import load_campaign, save_campaign


@dataclass(slots=True)
class BattleExportManifest:
    battle_id: str
    campaign_path: str
    save_path: str
    catalog_signature: str
    played_games: int
    won_games: int
    map_name: str = ""
    created_at_utc: str = ""
    campaign_sha256: str = ""
    resource_stack: list[str] = field(default_factory=list)
    status_template_path: str = ""
    visible_campaign_name: str = ""
    installed_size: int = 0
    installed_mtime_ns: int = 0
    installed_sha256: str = ""

    @property
    def baseline(self) -> StatusResult:
        return StatusResult(self.played_games, self.won_games)

    @property
    def has_installed_fingerprint(self) -> bool:
        return bool(self.installed_sha256) and self.installed_size > 0


@dataclass(frozen=True, slots=True)
class SaveFingerprint:
    sha256: str
    size: int
    mtime_ns: int


class GatesOfCodeXService:
    def __init__(self) -> None:
        self.scanner = CodeXCatalogScanner()
        self.status = StatusBuilder()
        self.archive = CampaignSaveArchive()

    @staticmethod
    def manifest_path(save_path: str | Path) -> Path:
        save = Path(save_path)
        return save.with_suffix(save.suffix + ".goc.json")

    @classmethod
    def load_manifest(cls, path: str | Path) -> BattleExportManifest:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        allowed = {item.name for item in fields(BattleExportManifest)}
        return BattleExportManifest(**{key: value for key, value in payload.items() if key in allowed})

    def write_manifest(self, manifest: BattleExportManifest, path: str | Path | None = None) -> Path:
        destination = Path(path) if path else self.manifest_path(manifest.save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
        return destination

    def export_battle(
        self,
        campaign_path: str | Path,
        *,
        code_x_directory: str | Path | None,
        save_path: str | Path,
        map_name: str,
        resource_stack: Iterable[str | Path] | None = None,
        previous_status: StatusResult | None = None,
        status_template_path: str | Path | None = None,
        allow_overwrite: bool = False,
        campaign_name: str | None = None,
    ) -> BattleExportManifest:
        campaign_file = Path(campaign_path).resolve()
        destination = Path(save_path).resolve()
        manifest_destination = self.manifest_path(destination)
        if not allow_overwrite and (destination.exists() or manifest_destination.exists()):
            raise FileExistsError(
                f"Refusing to overwrite an existing tactical export: {destination}. "
                "Back it up or explicitly allow overwrite."
            )
        state = load_campaign(campaign_file)
        if state.pending_battle is None:
            raise RuntimeError("Campaign has no pending battle")
        saved_stack = state.map_metadata.get("resource_stack", [])
        stack = resolve_stack(resource_stack or saved_stack, fallback=code_x_directory or state.code_x_directory)
        if not stack:
            raise ValueError("No Code:X resource stack was configured")
        catalog = self.scanner.scan_stack(stack)
        if state.catalog_signature and state.catalog_signature != catalog.signature:
            raise ValueError("Installed Code:X mod stack differs from the campaign catalog")

        template_path = Path(status_template_path).resolve() if status_template_path else None
        template_status = self.archive.read(template_path).status if template_path else ""
        baseline = previous_status or (
            self.status.parse_result(template_status) if template_status else StatusResult(0, 0)
        )
        reserved_names: set[str] = set()
        if template_status:
            template_name = read_status_campaign_name(template_status)
            if template_name:
                reserved_names.add(template_name)
        visible_name = campaign_name or unique_acceptance_campaign_name(
            state.pending_battle.battle_id,
            reserved=reserved_names,
        )
        if visible_name in reserved_names:
            raise ValueError(
                f"Generated Conquest visible name collides with the template name {visible_name!r}. "
                "Choose a unique battle id or pass an explicit campaign_name."
            )
        research = []
        if state.selected_faction.value in state.factions:
            research = state.factions[state.selected_faction.value].researched_keys
        options = BattleStatusOptions(
            map_name=map_name,
            difficulty=state.difficulty,
            research=research,
            played_games=baseline.played_games,
            won_games=baseline.won_games,
            template_status=template_status,
            campaign_name=visible_name,
            mods=stack_mod_tokens(stack),
        )
        status_text = self.status.build(state.pending_battle, options)
        scn_text = CampaignScnBuilder(catalog, resource_stack=stack).build(state, state.pending_battle)
        destination = self.archive.write(destination, status=status_text, campaign_scn=scn_text)
        self.archive.validate(destination)

        state.pending_battle.exported_save_path = str(destination)
        state.pending_battle.started = True
        state.map_metadata["resource_stack"] = stack_to_strings(stack)
        state.map_metadata["visible_campaign_name"] = visible_name
        if code_x_directory:
            state.code_x_directory = str(Path(code_x_directory).resolve())
        save_campaign(state, campaign_file)
        manifest = BattleExportManifest(
            battle_id=state.pending_battle.battle_id,
            campaign_path=str(campaign_file),
            save_path=str(destination.resolve()),
            catalog_signature=catalog.signature,
            played_games=baseline.played_games,
            won_games=baseline.won_games,
            map_name=map_name,
            created_at_utc=datetime.now(UTC).isoformat(),
            campaign_sha256=file_sha256(campaign_file),
            resource_stack=stack_to_strings(stack),
            status_template_path=str(template_path) if template_path else "",
            visible_campaign_name=visible_name,
        )
        self.write_manifest(manifest, manifest_destination)
        return manifest

    def import_battle(self, campaign_path: str | Path, *, save_path: str | Path) -> BattleImportResult:
        campaign_file = Path(campaign_path).resolve()
        save_file = Path(save_path).resolve()
        manifest_file = self.manifest_path(save_file)
        if not manifest_file.is_file():
            raise FileNotFoundError(f"Missing export manifest: {manifest_file}")
        manifest = self.load_manifest(manifest_file)
        if Path(manifest.campaign_path).resolve() != campaign_file:
            raise ValueError("Battle manifest belongs to a different campaign")
        if Path(manifest.save_path).resolve() != save_file:
            raise ValueError("Battle manifest belongs to a different tactical save")
        state = load_campaign(campaign_file)
        if state.pending_battle is None or state.pending_battle.battle_id != manifest.battle_id:
            raise ValueError("Battle manifest does not match the pending campaign battle")
        stack = resolve_stack(
            state.map_metadata.get("resource_stack", []) or manifest.resource_stack,
            fallback=state.code_x_directory,
        )
        if stack:
            signature = self.scanner.scan_stack(stack).signature
            if signature != manifest.catalog_signature:
                raise ValueError("Installed Code:X mod stack changed after the battle export")
        engine = CampaignEngine(state)
        result = BattleResultImporter().import_save(engine, save_file, previous_status=manifest.baseline)
        save_campaign(state, campaign_file)
        return result


def unique_acceptance_campaign_name(battle_id: str, *, reserved: Iterable[str] | None = None) -> str:
    """Build a short, deterministic GoH-visible Conquest name for an acceptance handoff."""

    blocked = {value.strip() for value in (reserved or []) if value and value.strip()}
    token = _battle_token(battle_id)
    candidates = [
        f"Gates of CodeX Test {token}",
        f"Gates of CodeX Test {token}-a",
        f"Gates of CodeX Test {token}-b",
        f"Gates of CodeX Test {battle_id.replace(':', '-')[-16:]}",
    ]
    for candidate in candidates:
        if candidate not in blocked:
            return candidate
    raise ValueError(f"Could not allocate a unique Conquest visible name for battle {battle_id!r}")


def read_status_campaign_name(status_text: str) -> str:
    match = re.search(r'(?m)^\t\{name\s+"([^"]*)"\}\s*$', status_text.replace("\r\n", "\n").replace("\r", "\n"))
    return match.group(1) if match else ""


def fingerprint_save(path: str | Path) -> SaveFingerprint:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    stats = source.stat()
    mtime_ns = getattr(stats, "st_mtime_ns", int(stats.st_mtime * 1_000_000_000))
    return SaveFingerprint(sha256=file_sha256(source), size=stats.st_size, mtime_ns=int(mtime_ns))


def apply_installed_fingerprint(manifest: BattleExportManifest, path: str | Path) -> BattleExportManifest:
    fingerprint = fingerprint_save(path)
    manifest.installed_sha256 = fingerprint.sha256
    manifest.installed_size = fingerprint.size
    manifest.installed_mtime_ns = fingerprint.mtime_ns
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _battle_token(battle_id: str) -> str:
    # Prefer the trailing battle segment (goc-1-b714b08b42 -> b714b08b).
    segment = battle_id.rsplit("-", 1)[-1] if "-" in battle_id else battle_id
    cleaned = re.sub(r"[^0-9A-Za-z]+", "", segment)
    if not cleaned:
        cleaned = re.sub(r"[^0-9A-Za-z]+", "", battle_id) or "battle"
    return cleaned[:8]
