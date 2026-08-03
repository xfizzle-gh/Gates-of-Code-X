from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CampaignSaveContents:
    status: str
    campaign_scn: str


class CampaignSaveArchive:
    STATUS_NAME = "status"
    SCN_NAME = "campaign.scn"

    def write(self, path: str | Path, *, status: str, campaign_scn: str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(self.STATUS_NAME, status)
                archive.writestr(self.SCN_NAME, campaign_scn)
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
                return CampaignSaveContents(
                    status=archive.read(self.STATUS_NAME).decode("utf-8-sig", errors="replace"),
                    campaign_scn=archive.read(self.SCN_NAME).decode("utf-8-sig", errors="replace"),
                )
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Invalid Dynamic Conquest save: {source}") from exc
