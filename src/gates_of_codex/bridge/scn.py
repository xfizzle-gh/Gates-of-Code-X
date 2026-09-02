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


@dataclass(frozen=True, slots=True)
class BreedInventoryItem:
    name: str
    filled: bool = False
    quantity: int | None = None
    kind: str = ""  # "", "ammo", "grenade", ...
    filling: str = ""
    user: str = ""


class ObjectIdAllocator:
    """Match live Conquest IDs: 0xc000, 0xc004, ... with small MIDs."""

    def __init__(self, start: int = 0xC000, step: int = 4, mid_start: int = 10) -> None:
        self.next = start
        self.step = step
        self.mid = mid_start

    def allocate(self) -> tuple[str, int]:
        value = f"0x{self.next:x}"
        mid = self.mid
        self.next += self.step
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
        # campaign.scn is the player's persistent army only. Conquest spawns
        # the enemy from {enemyArmy} + doctrines. Units we write here are
        # given to the local player regardless of {Player N} tags.
        participants = {
            item.battalion_id: item.stage
            for item in (*pending.attacking_participants, *pending.defending_participants)
            if item.faction == pending.player_faction
        }
        if not participants:
            raise ValueError("Pending battle has no player-faction units to export")
        self._preflight_rosters(state, participants)
        x_cursor = -1650.6
        for battalion_id, stage in participants.items():
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise KeyError(f"Missing battalion {battalion_id}")
            player = 0
            for entry in battalion.roster:
                definition = self.catalog.units.get(entry.unit_name)
                if definition is None:
                    raise KeyError(f"Code:X catalog has no definition for {entry.unit_name}")
                for _ in range(entry.quantity):
                    object_ids: list[str] = []
                    for vehicle in definition.vehicles[:1]:
                        object_id, mid = ids.allocate()
                        object_ids.append(object_id)
                        objects.append(self._entity(vehicle, object_id, player=player, mid=mid, x=x_cursor))
                        inventories.append(self._inventory(object_id, items=[]))
                        x_cursor += 37.65
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
                                    x=x_cursor,
                                )
                            )
                            inventories.append(
                                self._inventory(
                                    object_id,
                                    items=self._breed_inventory(breed, definition.side, definition.period),
                                )
                            )
                            x_cursor += 37.65
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
        x: float,
    ) -> str:
        path = self._resolve_breed(breed, side, period)
        name_a = (mid * 13) % 180
        name_b = (mid * 29) % 300
        return (
            f'\t{{Human "{path}" {object_id}\n'
            f"\t\t{{Position {x:.2f} 0}}\n"
            f"\t\t{{xform zl 90}}\n"
            f'\t\t{{TexMod "auto"}}\n'
            f"\t\t{{SpawnedInFog}}\n"
            f'\t\t{{Volume "ram"\n'
            f"\t\t\t{{able {{visible 0}}{{bullet 0}}{{throwing 0}}{{obstacle 0}}{{contact 0}}"
            f"{{contact_ground 0}}{{blast 0}}{{select 0}}{{touch 0}}{{blockcamera 0}}}}\n"
            f"\t\t\t{{disabled}}\n"
            f"\t\t}}\n"
            f"\t\t{{Player {player}}}\n"
            f"\t\t{{MID {mid}}}\n"
            f"\t\t{{NameId {name_a} {name_b}}}\n"
            f'\t\t{{FsmState "stand_noaim"}}\n'
            f"\t}}"
        )

    @staticmethod
    def _entity(entity: str, object_id: str, *, player: int, mid: int, x: float) -> str:
        return (
            f'\t{{Entity "{entity}" {object_id}\n'
            f"\t\t{{Position {x:.2f} 0}}\n"
            f"\t\t{{xform zl 90}}\n"
            f'\t\t{{TexMod "auto"}}\n'
            f"\t\t{{Player {player}}}\n"
            f"\t\t{{MID {mid}}}\n"
            f"\t}}"
        )

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
        lines = [f"\t{{Inventory {object_id}", "\t\t{box", "\t\t\t{clear}"]
        if not values:
            lines.extend(["\t\t}", "\t}"])
            return "\n".join(lines)
        cell_x = 0
        cell_y = 0
        handed = False
        for item in values:
            cell = f"{{cell {cell_x} {cell_y}}}"
            if item.user:
                lines.append(f'\t\t\t{{item "{item.name}" {cell}{{user "{item.user}"}}}}')
            elif item.filled and not handed and _looks_like_weapon(item.name):
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


_ARMOR_SLOT = re.compile(r'\{(head|body|leg|foot|hand)\s+"?([^"}\s]+)"?\}', re.IGNORECASE)


def parse_breed_inventory(text: str) -> list[BreedInventoryItem]:
    """Parse Code:X breed ``{inventory ...}`` / ``{armors ...}`` into campaign items."""

    block = _extract_named_block(text, "inventory")
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
        if quantity is not None:
            quantity = max(quantity, 1)
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
    armors = _extract_named_block(text, "armors")
    for slot, spec in _ARMOR_SLOT.findall(armors):
        items.append(BreedInventoryItem(name=spec.strip(), user=slot.lower()))
    return items


def _extract_named_block(text: str, name: str) -> str:
    marker = re.search(r"\{\s*" + re.escape(name) + r"\b", text, flags=re.IGNORECASE)
    if marker is None:
        return ""
    start = marker.start()
    depth = 0
    in_quote = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quote = False
            continue
        if char == '"':
            in_quote = True
        elif char == "{":
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
        player_faction = getattr(pending, "player_faction", None)
        player_ids = {
            item.battalion_id
            for item in (*pending.attacking_participants, *pending.defending_participants)
            if player_faction is None or getattr(item, "faction", player_faction) == player_faction
        }
        stage_to_battalion = {
            item.stage: item.battalion_id
            for item in (*pending.attacking_participants, *pending.defending_participants)
            if item.battalion_id in player_ids
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
