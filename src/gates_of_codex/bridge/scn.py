from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..codex.catalog import CodeXCatalog
from ..models import BattalionRosterEntry, CampaignState, PendingBattle
from ..modstack import normalize_stack, resource_root


@dataclass(slots=True)
class ParsedCampaignSquad:
    unit_name: str
    stage: str
    object_ids: list[str] = field(default_factory=list)


class ObjectIdAllocator:
    def __init__(self, start: int = 0x10000001) -> None:
        self.next = start

    def allocate(self) -> str:
        value = f"0x{self.next:08x}"
        self.next += 1
        return value


class CampaignScnBuilder:
    def __init__(
        self,
        catalog: CodeXCatalog,
        code_x_directory: str | Path | None = None,
        *,
        resource_stack: Iterable[str | Path] | None = None,
    ) -> None:
        self.catalog = catalog
        values = list(resource_stack or ([] if code_x_directory is None else [code_x_directory]))
        self.roots = normalize_stack(values)
        if not self.roots:
            raise ValueError("CampaignScnBuilder requires at least one resource stack layer")
        self._breed_index: dict[str, str] | None = None

    def build(self, state: CampaignState, pending: PendingBattle) -> str:
        ids = ObjectIdAllocator()
        objects: list[str] = []
        inventories: list[str] = []
        squads: list[str] = []
        participants = {
            item.battalion_id: item.stage
            for item in (*pending.attacking_participants, *pending.defending_participants)
        }
        for battalion_id, stage in participants.items():
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise KeyError(f"Missing battalion {battalion_id}")
            for entry in battalion.roster:
                definition = self.catalog.units.get(entry.unit_name)
                if definition is None:
                    raise KeyError(f"Code:X catalog has no definition for {entry.unit_name}")
                for _ in range(entry.quantity):
                    object_ids: list[str] = []
                    for vehicle in definition.vehicles[:1]:
                        object_id = ids.allocate()
                        object_ids.append(object_id)
                        objects.append(self._entity(vehicle, object_id))
                        inventories.append(self._inventory(object_id))
                    for breed, count in definition.members.items():
                        for _ in range(count):
                            object_id = ids.allocate()
                            object_ids.append(object_id)
                            objects.append(self._human(breed, definition.side, definition.period, object_id))
                            inventories.append(self._inventory(object_id))
                    if not object_ids:
                        raise ValueError(f"Unit {entry.unit_name} has no materializable members")
                    squads.append(f'\t\t{{"{entry.unit_name}" "{stage}" {" ".join(object_ids)}}}')
        text = "{campaign\n" + "\n".join(objects + inventories) + "\n\t{CampaignSquads\n" + "\n".join(squads) + "\n\t}\n}\n"
        self.validate(text)
        return text

    @classmethod
    def validate(cls, text: str) -> None:
        squads = CampaignScnParser().parse_squads(text)
        if not squads:
            raise ValueError("campaign.scn has no CampaignSquads")
        objects = set(re.findall(r'\{(?:Human|Entity)\s+"[^"]+"\s+(0x[0-9a-fA-F]+)', text))
        inventories = set(re.findall(r'\{Inventory\s+(0x[0-9a-fA-F]+)', text))
        for squad in squads:
            for object_id in squad.object_ids:
                if object_id not in objects or object_id not in inventories:
                    raise ValueError(f"Invalid object graph for {object_id}")

    def _resolve_breed(self, breed: str, side: str, period: str) -> str:
        for root in reversed(self.roots):
            resources = resource_root(root)
            candidates = [
                resources / f"set/breed/mp/{side}/{breed}.set",
                resources / f"set/breed/mp/{period}/{side}/{breed}.set",
                resources / f"set/breed/{breed}.set",
            ]
            for path in candidates:
                if path.is_file():
                    return path.relative_to(resources).as_posix()
        if self._breed_index is None:
            self._breed_index = {}
            for root in reversed(self.roots):
                resources = resource_root(root)
                breed_root = resources / "set/breed"
                if breed_root.is_dir():
                    for path in breed_root.rglob("*.set"):
                        self._breed_index.setdefault(path.stem.lower(), path.relative_to(resources).as_posix())
        result = self._breed_index.get(breed.lower()) if self._breed_index else None
        if not result:
            raise FileNotFoundError(f"Could not resolve Code:X breed {breed} in the configured mod stack")
        return result

    def _human(self, breed: str, side: str, period: str, object_id: str) -> str:
        path = self._resolve_breed(breed, side, period)
        return f'\t{{Human "{path}" {object_id}\n\t\t{{Position 0 0}}\n\t\t{{Player 0}}\n\t\t{{MID {int(object_id, 16)}}}\n\t}}'

    @staticmethod
    def _entity(entity: str, object_id: str) -> str:
        return f'\t{{Entity "{entity}" {object_id}\n\t\t{{Position 0 0}}\n\t\t{{Player 0}}\n\t\t{{MID {int(object_id, 16)}}}\n\t}}'

    @staticmethod
    def _inventory(object_id: str) -> str:
        return f"\t{{Inventory {object_id}\n\t\t{{box\n\t\t\t{{clear}}\n\t\t}}\n\t}}"


class CampaignScnParser:
    ROW = re.compile(r'\{"([^"]+)"\s+"([^"]+)"\s+([^}]*)\}')

    def parse_squads(self, text: str) -> list[ParsedCampaignSquad]:
        marker = text.find("{CampaignSquads")
        if marker < 0:
            return []
        section = text[marker:]
        return [
            ParsedCampaignSquad(match.group(1), match.group(2), re.findall(r"0x[0-9a-fA-F]+", match.group(3)))
            for match in self.ROW.finditer(section)
        ]

    def survivor_rosters(self, text: str, pending: PendingBattle) -> dict[str, list[BattalionRosterEntry]]:
        stage_to_battalion = {
            item.stage: item.battalion_id
            for item in (*pending.attacking_participants, *pending.defending_participants)
        }
        counts: dict[str, dict[str, int]] = {}
        for squad in self.parse_squads(text):
            battalion_id = stage_to_battalion.get(squad.stage)
            if battalion_id and squad.object_ids:
                bucket = counts.setdefault(battalion_id, {})
                bucket[squad.unit_name] = bucket.get(squad.unit_name, 0) + 1
        return {
            battalion_id: [BattalionRosterEntry(unit_name=name, quantity=quantity) for name, quantity in sorted(units.items())]
            for battalion_id, units in counts.items()
        }
