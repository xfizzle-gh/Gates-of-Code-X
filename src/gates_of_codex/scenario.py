from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .models import CampaignState
from .state_io import campaign_from_dict


def load_scenario(path: str | Path) -> CampaignState:
    return campaign_from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def load_bundled_scenario() -> CampaignState:
    resource = files("gates_of_codex").joinpath("data/four_faction.json")
    return campaign_from_dict(json.loads(resource.read_text(encoding="utf-8")))
