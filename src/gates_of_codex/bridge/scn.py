from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..codex.catalog import CodeXCatalog
from ..models import BattalionRosterEntry, CampaignState, PendingBattle
from ..modstack import normalize_stack, resource_root
from ..tactical_morale_profile import (
    apply_aio_morale_marker,
    morale_profile_from_unit_definition,
    morale_profile_log_comment,
    morale_profile_visibility_tag_line,
)


@dataclass(slots=True)
class ParsedCampaignSquad:
    unit_name: str
    stage: str
    object_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BreedInventoryItem:
    name: str
    filled: bool = False
    quantity: int | None = None
    kind: str = ""  # "", "ammo", "grenade", ...
    filling: str = ""


class ObjectIdAllocator:
    def __init__(self, start: int = 0x8000) -> None:
        self.next = start
        self.mid = 1

    def allocate(self) -> tuple[str, int]:
        value = f"0x{self.next:x}"
        mid = self.mid
        self.next += 1
        self.mid += 1
        return value, mid


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
        self._breed_token_index: dict[str, str] | None = None
        self._breed_path_index: dict[str, Path] | None = None
        self._inventory_cache: dict[str, list[BreedInventoryItem]] = {}

    def build(self, state: CampaignState, pending: PendingBattle) -> str:
        ids = ObjectIdAllocator()
        objects: list[str] = []
        inventories: list[str] = []
        squads: list[str] = []
        participants = {
            item.battalion_id: item.stage
            for item in (*pending.attacking_participants, *pending.defending_participants)
        }
        self._preflight_rosters(state, participants)
        player_by_battalion = {
            item.battalion_id: (0 if pending.player_is_attacker else 1)
            for item in pending.attacking_participants
        }
        player_by_battalion.update(
            {
                item.battalion_id: (1 if pending.player_is_attacker else 0)
                for item in pending.defending_participants
            }
        )
        for battalion_id, stage in participants.items():
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise KeyError(f"Missing battalion {battalion_id}")
            player = player_by_battalion.get(battalion_id, 0)
            for entry in battalion.roster:
                definition = self.catalog.units.get(entry.unit_name)
                if definition is None:
                    raise KeyError(f"Code:X catalog has no definition for {entry.unit_name}")
                for _ in range(entry.quantity):
                    object_ids: list[str] = []
                    morale_profile = morale_profile_from_unit_definition(definition)
                    for vehicle in definition.vehicles[:1]:
                        object_id, mid = ids.allocate()
                        object_ids.append(object_id)
                        objects.append(
                            self._entity(
                                vehicle,
                                object_id,
                                player=player,
                                mid=mid,
                                unit_name=entry.unit_name,
                                morale_profile=morale_profile,
                            )
                        )
                        inventories.append(self._inventory(object_id, items=[]))
                    for breed, count in definition.members.items():
                        for _ in range(count):
                            object_id, mid = ids.allocate()
                            object_ids.append(object_id)
                            objects.append(
                                self._human(
                                    breed,
                                    definition.side,
                                    definition.period,
                                    object_id,
                                    player=player,
                                    mid=mid,
                                    unit_name=entry.unit_name,
                                    morale_profile=morale_profile,
                                )
                            )
                            inventories.append(
                                self._inventory(
                                    object_id,
                                    items=apply_aio_morale_marker(
                                        self._breed_inventory(
                                            breed, definition.side, definition.period
                                        ),
                                        morale_profile,
                                    ),
                                )
                            )
                    if not object_ids:
                        raise ValueError(f"Unit {entry.unit_name} has no materializable members")
                    squads.append(f'\t\t{{"{entry.unit_name}" "{stage}" {" ".join(object_ids)}}}')
        text = "{campaign\n" + "\n".join(objects + inventories) + "\n\t{CampaignSquads\n" + "\n".join(squads) + "\n\t}\n}\n"
        self.validate(text)
        return text

    def _preflight_rosters(self, state: CampaignState, participants: dict[str, str]) -> None:
        invalid: list[str] = []
        for battalion_id in participants:
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                invalid.append(f"{battalion_id}: battalion is missing")
                continue
            for entry in battalion.roster:
                definition = self.catalog.units.get(entry.unit_name)
                if definition is None:
                    invalid.append(f"{battalion_id}: {entry.unit_name} is absent from the Code:X catalog")
                elif not definition.materializable:
                    sources = ", ".join(definition.source_files) or "unknown source"
                    invalid.append(
                        f"{battalion_id}: {entry.unit_name} has no parsed members or vehicles ({sources})"
                    )
        if invalid:
            details = "\n- ".join(sorted(set(invalid)))
            raise ValueError(f"Tactical roster contains nonmaterializable Code:X entries:\n- {details}")

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
        path = self._resolve_breed_path(breed, side, period)
        return self._to_breed_token(self._relative_breed_posix(path))

    def _resolve_breed_path(self, breed: str, side: str, period: str) -> Path:
        for root in reversed(self.roots):
            resources = resource_root(root)
            candidates = [
                resources / f"set/breed/mp/{side}/{period}/{breed}.set",
                resources / f"set/breed/mp/{side}/{breed}.set",
                resources / f"set/breed/mp/{period}/{side}/{breed}.set",
                resources / f"set/breed/{breed}.set",
            ]
            for path in candidates:
                if path.is_file():
                    return path
        self._ensure_breed_indexes()
        assert self._breed_path_index is not None
        path = self._breed_path_index.get(breed.lower())
        if path is None:
            raise FileNotFoundError(f"Could not resolve Code:X breed {breed} in the configured mod stack")
        return path

    def _ensure_breed_indexes(self) -> None:
        if self._breed_token_index is not None and self._breed_path_index is not None:
            return
        token_index: dict[str, str] = {}
        path_index: dict[str, Path] = {}
        for root in reversed(self.roots):
            resources = resource_root(root)
            breed_root = resources / "set/breed"
            if not breed_root.is_dir():
                continue
            for path in breed_root.rglob("*.set"):
                stem = path.stem.lower()
                token_index.setdefault(stem, self._to_breed_token(path.relative_to(resources).as_posix()))
                path_index.setdefault(stem, path)
        self._breed_token_index = token_index
        self._breed_path_index = path_index

    def _relative_breed_posix(self, path: Path) -> str:
        for root in reversed(self.roots):
            resources = resource_root(root)
            try:
                return path.relative_to(resources).as_posix()
            except ValueError:
                continue
        return path.as_posix()

    @staticmethod
    def _to_breed_token(relative_posix: str) -> str:
        # Real Conquest saves store short tokens like mp/nato/2022s/usarmy_vehicleman
        # rather than set/breed/.../*.set filesystem paths.
        text = relative_posix.replace("\\", "/")
        if text.startswith("set/breed/"):
            text = text[len("set/breed/") :]
        if text.endswith(".set"):
            text = text[: -len(".set")]
        return text

    def _human(
        self,
        breed: str,
        side: str,
        period: str,
        object_id: str,
        *,
        player: int,
        mid: int,
        unit_name: str = "",
        morale_profile: str = "",
    ) -> str:
        path = self._resolve_breed(breed, side, period)
        return self._tactical_object_block(
            kind="Human",
            token=path,
            object_id=object_id,
            player=player,
            mid=mid,
            unit_name=unit_name,
            morale_profile=morale_profile,
            spawned_in_fog=True,
            fsm_state="stand_noaim",
        )

    @classmethod
    def _entity(
        cls,
        entity: str,
        object_id: str,
        *,
        player: int,
        mid: int,
        unit_name: str = "",
        morale_profile: str = "",
    ) -> str:
        return cls._tactical_object_block(
            kind="Entity",
            token=entity,
            object_id=object_id,
            player=player,
            mid=mid,
            unit_name=unit_name,
            morale_profile=morale_profile,
            spawned_in_fog=False,
            fsm_state="",
        )

    @staticmethod
    def _tactical_object_block(
        *,
        kind: str,
        token: str,
        object_id: str,
        player: int,
        mid: int,
        unit_name: str,
        morale_profile: str,
        spawned_in_fog: bool,
        fsm_state: str,
    ) -> str:
        carrier = "human" if kind == "Human" else "entity"
        lines = [
            morale_profile_log_comment(
                unit_name=unit_name or token,
                profile=morale_profile,
                object_id=object_id,
                carrier=carrier,
            ),
            f'\t{{{kind} "{token}" {object_id}',
            "\t\t{Position 0 0}",
            "\t\t{xform zl 90}",
            '\t\t{TexMod "auto"}',
        ]
        if spawned_in_fog:
            lines.append("\t\t{SpawnedInFog}")
        lines.append(f"\t\t{{Player {player}}}")
        lines.append(f"\t\t{{MID {mid}}}")
        if fsm_state:
            lines.append(f'\t\t{{FsmState "{fsm_state}"}}')
        lines.append(morale_profile_visibility_tag_line(morale_profile))
        lines.append("\t}")
        return "\n".join(lines)

    def _breed_inventory(self, breed: str, side: str, period: str) -> list[BreedInventoryItem]:
        cache_key = f"{side}/{period}/{breed}".lower()
        cached = self._inventory_cache.get(cache_key)
        if cached is not None:
            return cached
        path = self._resolve_breed_path(breed, side, period)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        items = parse_breed_inventory(text)
        self._inventory_cache[cache_key] = items
        return items

    @classmethod
    def _inventory(cls, object_id: str, *, items: list[BreedInventoryItem] | None = None) -> str:
        values = list(items or [])
        if not values:
            return f"\t{{Inventory {object_id}\n\t\t{{box\n\t\t\t{{clear}}\n\t\t}}\n\t}}"
        lines = [f"\t{{Inventory {object_id}", "\t\t{box"]
        cell_x = 0
        cell_y = 0
        handed = False
        for item in values:
            cell = f"{{cell {cell_x} {cell_y}}}"
            if item.filled and not handed and _looks_like_weapon(item.name):
                lines.append(f'\t\t\t{{item "{item.name}" filled {cell}{{user "hand_right"}}}}')
                handed = True
            elif item.kind:
                qty = item.quantity if item.quantity is not None else 1
                lines.append(f'\t\t\t{{item "{item.name}" "{item.kind}" {qty} {cell}}}')
            elif item.filled:
                lines.append(f'\t\t\t{{item "{item.name}" filled {cell}}}')
            elif item.quantity is not None:
                lines.append(f'\t\t\t{{item "{item.name}" {item.quantity} {cell}}}')
            else:
                lines.append(f'\t\t\t{{item "{item.name}" {cell}}}')
            cell_x += 2
            if cell_x > 8:
                cell_x = 0
                cell_y += 1
        lines.extend(["\t\t}", "\t}"])
        return "\n".join(lines)


def parse_breed_inventory(text: str) -> list[BreedInventoryItem]:
    """Parse Code:X breed ``{inventory ...}`` defaults into campaign inventory items."""

    block = _extract_inventory_block(text)
    if not block:
        return []
    items: list[BreedInventoryItem] = []
    for raw in re.finditer(r"\{item\b([^}]*)\}", block):
        body = raw.group(1).strip()
        if not body:
            continue
        name_match = re.match(r'"([^"]+)"\s*(.*)$', body)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        rest = name_match.group(2).strip()
        filling_match = re.search(r'filling\s+"([^"]+)"', rest)
        filling = filling_match.group(1) if filling_match else ""
        filled = bool(re.search(r"\bfilled\b", rest)) or bool(filling)
        numbers = [float(value) for value in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", rest)]
        quantity = int(numbers[0]) if numbers else None
        kind = ""
        item_name = name
        lowered = name.lower()
        for suffix, label in ((" ammo", "ammo"), (" grenade", "grenade"), (" weapon", "")):
            if lowered.endswith(suffix):
                item_name = name[: -len(suffix)].strip()
                kind = label
                break
        if kind == "" and " ammo" in f" {rest.lower()} ":
            kind = "ammo"
        if filling and not kind:
            # Keep weapon name; ammo is separate in many breed rows.
            pass
        items.append(
            BreedInventoryItem(
                name=item_name,
                filled=filled,
                quantity=quantity,
                kind=kind,
                filling=filling,
            )
        )
        if filling and quantity is not None:
            fill_name = filling
            fill_kind = ""
            if fill_name.lower().endswith(" ammo"):
                fill_name = fill_name[: -len(" ammo")].strip()
                fill_kind = "ammo"
            items.append(BreedInventoryItem(name=fill_name, quantity=quantity, kind=fill_kind or "ammo"))
    return items


def _extract_inventory_block(text: str) -> str:
    marker = re.search(r"\{inventory\b", text, flags=re.IGNORECASE)
    if marker is None:
        return ""
    start = marker.start()
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _looks_like_weapon(name: str) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in ("bandage", "shovel", "backpack", "vest", "belt", "mask", "helmet", "armor")):
        return False
    return True


class CampaignScnParser:
    ROW = re.compile(r'\{"([^"]+)"\s+"([^"]+)"\s+([^}]*)\}')
    DEAD_OBJECT_IDS = frozenset({"0xffffffff"})

    @classmethod
    def live_object_ids(cls, value: str) -> list[str]:
        return [
            object_id
            for object_id in re.findall(r"0x[0-9a-fA-F]+", value)
            if object_id.lower() not in cls.DEAD_OBJECT_IDS
        ]

    def parse_squads(self, text: str) -> list[ParsedCampaignSquad]:
        marker = text.find("{CampaignSquads")
        if marker < 0:
            return []
        section = text[marker:]
        return [
            ParsedCampaignSquad(match.group(1), match.group(2), self.live_object_ids(match.group(3)))
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
