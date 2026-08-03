from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
    ) -> BattleExportManifest:
        campaign_file = Path(campaign_path).resolve()
        state = load_campaign(campaign_file)
        if state.pending_battle is None:
            raise RuntimeError("Campaign has no pending battle")
        catalog = self.scanner.scan(code_x_directory)
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
        destination = self.archive.write(save_path, status=status_text, campaign_scn=scn_text)
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
        )
        self.manifest_path(destination).write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")
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
        state = load_campaign(campaign_file)
        if state.pending_battle is None or state.pending_battle.battle_id != manifest.battle_id:
            raise ValueError("Battle manifest does not match the pending campaign battle")
        engine = CampaignEngine(state)
        result = BattleResultImporter().import_save(engine, save_file, previous_status=manifest.baseline)
        save_campaign(state, campaign_file)
        return result
