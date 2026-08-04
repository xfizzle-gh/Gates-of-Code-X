from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .status import StatusBuilder


@dataclass(frozen=True, slots=True)
class CampaignSaveContents:
    status: str
    campaign_scn: str


class CampaignSaveArchive:
    STATUS_NAME = "status"
    SCN_NAME = "campaign.scn"

    def write(self, path: str | Path, *, status: str, campaign_scn: str) -> Path:
        status = StatusBuilder.validate(status)
        if not campaign_scn.strip():
            raise ValueError("Campaign scenario is empty")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            # Real GoH Conquest saves store campaign.scn before status.
            with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(self.SCN_NAME, self._to_game_bytes(campaign_scn))
                archive.writestr(self.STATUS_NAME, self._to_game_bytes(status))
            self.validate(temporary_path)
            temporary_path.replace(destination)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return destination

    def read(self, path: str | Path) -> CampaignSaveContents:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        try:
            with zipfile.ZipFile(source, "r") as archive:
                status = archive.read(self.STATUS_NAME).decode("utf-8-sig", errors="replace")
                campaign_scn = archive.read(self.SCN_NAME).decode("utf-8-sig", errors="replace")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Invalid Dynamic Conquest save: {source}") from exc
        StatusBuilder.validate(status)
        if not campaign_scn.strip():
            raise ValueError(f"Invalid Dynamic Conquest save with empty campaign.scn: {source}")
        return CampaignSaveContents(status=status, campaign_scn=campaign_scn)

    def validate(self, path: str | Path) -> Path:
        self.read(path)
        return Path(path)

    @staticmethod
    def _to_game_bytes(text: str) -> bytes:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.endswith("\n"):
            normalized += "\n"
        return normalized.replace("\n", "\r\n").encode("utf-8")
