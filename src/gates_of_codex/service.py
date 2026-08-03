from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .bridge.archive import CampaignSaveArchive
from .bridge.result import BattleImportResult, BattleResultImporter
from .bridge.scn import CampaignScnBuilder
from .bridge.status import BattleStatusOptions, StatusBuilder, StatusResult
from .campaign import CampaignEngine
from .codex.catalog import CodeXCatalogScanner
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

    @property
    def baseline(self) -> StatusResult:
        return StatusResult(self.played_games, self.won_games)


class GatesOfCodeXService:
    def __init__(self) -> None:
        self.scanner = CodeXCatalogScanner()
        self.status = StatusBuilder()
        self.archive = CampaignSaveArchive()

    @staticmethod
    def manifest_path(save_path: str | Path) -> Path:
        save = Path(save_path)
        return save.with_suffix(save.suffix + ".goc.json")

    def export_battle(
        self,
        campaign_path: str | Path,
        *,
        code_x_directory: str | Path,
        save_path: str | Path,
        map_name: str,
        previous_status: StatusResult | None = None,
        allow_overwrite: bool = False,
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
        catalog = self.scanner.scan(code_x_directory)
        if state.catalog_signature and state.catalog_signature != catalog.signature:
            raise ValueError("Installed Code:X catalog differs from the campaign catalog")
        baseline = previous_status or StatusResult(0, 0)
        options = BattleStatusOptions(
            map_name=map_name,
            difficulty=state.difficulty,
            research=state.factions.get(state.selected_faction.value).researched_keys if state.selected_faction.value in state.factions else [],
            played_games=baseline.played_games,
            won_games=baseline.won_games,
        )
        status_text = self.status.build(state.pending_battle, options)
        scn_text = CampaignScnBuilder(catalog, code_x_directory).build(state, state.pending_battle)
        destination = self.archive.write(destination, status=status_text, campaign_scn=scn_text)
        state.pending_battle.exported_save_path = str(destination)
        state.pending_battle.started = True
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
            campaign_sha256=_sha256(campaign_file),
        )
        manifest_destination.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
        return manifest

    def import_battle(self, campaign_path: str | Path, *, save_path: str | Path) -> BattleImportResult:
        campaign_file = Path(campaign_path).resolve()
        save_file = Path(save_path).resolve()
        manifest_file = self.manifest_path(save_file)
        if not manifest_file.is_file():
            raise FileNotFoundError(f"Missing export manifest: {manifest_file}")
        manifest = BattleExportManifest(**json.loads(manifest_file.read_text(encoding="utf-8-sig")))
        if Path(manifest.campaign_path).resolve() != campaign_file:
            raise ValueError("Battle manifest belongs to a different campaign")
        if Path(manifest.save_path).resolve() != save_file:
            raise ValueError("Battle manifest belongs to a different tactical save")
        state = load_campaign(campaign_file)
        if state.pending_battle is None or state.pending_battle.battle_id != manifest.battle_id:
            raise ValueError("Battle manifest does not match the pending campaign battle")
        if state.code_x_directory and Path(state.code_x_directory).is_dir():
            signature = self.scanner.scan(state.code_x_directory).signature
            if signature != manifest.catalog_signature:
                raise ValueError("Installed Code:X catalog changed after the battle export")
        engine = CampaignEngine(state)
        result = BattleResultImporter().import_save(engine, save_file, previous_status=manifest.baseline)
        save_campaign(state, campaign_file)
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
