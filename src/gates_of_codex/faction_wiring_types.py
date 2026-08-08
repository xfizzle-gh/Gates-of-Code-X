from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

SIDE_SUFFIX_RE = re.compile(r"\(([^()]+)\)$")
ENTITY_HINTS = ("vehicle", "tank", "cannon", "gun", "empl", "artillery", "mortar", "howitzer", "aa", "spg")

CATEGORY_ORDER = (
    "infantry", "recon", "anti_armor", "vehicle", "apc", "ifv",
    "tank", "artillery", "air_defense", "aviation", "logistics", "unknown",
)
CATEGORY_COSTS = {
    "infantry": 1, "recon": 2, "anti_armor": 2, "vehicle": 2,
    "apc": 3, "ifv": 4, "tank": 6, "artillery": 5,
    "air_defense": 5, "aviation": 8, "logistics": 2, "unknown": 2,
}


class ReferenceKind(str, Enum):
    VEHICLE_ENTITY = "vehicle_entity"
    PURCHASE_UNIT = "purchase_unit"
    STRATEGIC_CALL_IN = "strategic_call_in"
    INTERACTION_OBJECT = "interaction_object"


@dataclass(frozen=True, slots=True)
class DefinitionReference:
    identifier: str
    kind: ReferenceKind
    source: str
    line: int
    column: int


@dataclass(slots=True)
class SourceUnit:
    name: str
    source_side: str
    period: str = ""
    category: str = "unknown"
    members: dict[str, int] = field(default_factory=dict)
    vehicles: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    definition_references: list[DefinitionReference] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    source_layer: str = ""
    source_priority: int = -1
    virtual: bool = False
    tier: int = 1
    research_cost: int = 0

    @property
    def materializable(self) -> bool:
        return bool(self.members or self.vehicles)

    def to_dict(self, *, actor_id: str, tactical_side: str, component_id: str) -> dict[str, Any]:
        return {
            "unit_name": self.name,
            "actor_id": actor_id,
            "component_id": component_id,
            "source_side": self.source_side,
            "tactical_side": tactical_side,
            "period": self.period,
            "category": self.category,
            "members": dict(sorted(self.members.items())),
            "vehicles": sorted(set(self.vehicles)),
            "actions": sorted(set(self.actions)),
            "materializable": self.materializable,
            "source_files": sorted(set(self.source_files)),
            "source_layer": self.source_layer,
            "source_priority": self.source_priority,
            "virtual": self.virtual,
            "tier": self.tier,
            "research_cost": self.research_cost,
        }


@dataclass(frozen=True, slots=True)
class SourceResearchNode:
    node_id: str
    side: str
    kind: str
    prerequisite: str
    cost: int
    source_file: str
    source_layer: str
    source_priority: int


def _infer_category(name: str, members: Mapping[str, int], vehicles: Sequence[str]) -> str:
    base = _base_name(name).lower().replace("-", "_")
    text = " ".join([base, *members.keys(), *vehicles]).lower().replace("-", "_")
    if re.search(r"(?:^|_)(?:inf_)?(?:at|antitank)(?:_|$)", base):
        return "anti_armor"
    if not vehicles and (
        "rifle" in base
        or "fireteam" in base
        or re.search(r"(?:^|_)(?:inf|squad)(?:_|$)", base)
        or re.search(r"(?:^|_)(?:wgn|sto|stoe|kor)_\d+", base)
    ):
        return "infantry"
    rules = (
        ("aviation", ("heli", "helicopter", "uh60", "mi8", "ka52", "tornado", "a10", "c130", "il76", "v22")),
        ("air_defense", ("air_def", "manpad", "stinger", "igla", "shilka", "tunguska", "avenger", "roland", "otomatic", "zu23", "zsu")),
        ("artillery", ("art", "mortar", "howitzer", "m777", "m109", "pzh", "as90", "2s1", "2s19", "d30", "d_30", "122mm", "bm21", "bm_21", "grad", "rm70", "m270", "himars", "spg9")),
        ("anti_armor", ("antitank", "anti_tank", "atgm", "javelin", "tow", "kornet", "metis", "rpg", "carl", "pzf")),
        ("recon", ("recon", "scout", "razv", "sniper", "spotter", "fennek", "jackal", "ajax")),
        ("tank", ("tank", "abrams", "m1a", "leopard", "leopord", "challenger", "leclerc", "ariete", "strv", "t55", "t64", "t72", "t80", "t90", "k2gf")),
        ("ifv", ("ifv", "bmp", "bradley", "marder", "puma", "warrior", "cv90", "strf")),
        ("apc", ("apc", "btr", "m113", "stryker", "boxer", "ypr", "rosomak", "aavp", "mtlb")),
        ("logistics", ("truck", "cargo", "supply", "ammo", "ural", "fmtv", "medic")),
        ("vehicle", ("vehicle", "humvee", "matv", "centauro", "iveco", "cougar")),
        ("infantry", ("inf", "rifle", "fireteam", "squad", "marine", "airborne", "grenadier", "engineer", "saperi", "mg")),
    )
    for category, hints in rules:
        if any(hint in text for hint in hints):
            return category
    if members:
        return "infantry"
    if vehicles:
        return "vehicle"
    return "unknown"


def _merge_unit(base: SourceUnit | None, overlay: SourceUnit) -> SourceUnit:
    if base is None:
        return _copy_unit(overlay)
    return SourceUnit(
        name=overlay.name or base.name,
        source_side=overlay.source_side or base.source_side,
        period=overlay.period or base.period,
        category=overlay.category if overlay.category != "unknown" else base.category,
        members=dict(overlay.members) if overlay.members else dict(base.members),
        vehicles=list(overlay.vehicles) if overlay.vehicles else list(base.vehicles),
        actions=list(dict.fromkeys([*base.actions, *overlay.actions])),
        definition_references=list(dict.fromkeys([
            *base.definition_references,
            *overlay.definition_references,
        ])),
        source_files=list(dict.fromkeys([*base.source_files, *overlay.source_files])),
        source_layer=overlay.source_layer or base.source_layer,
        source_priority=max(base.source_priority, overlay.source_priority),
        virtual=base.virtual or overlay.virtual,
        tier=max(base.tier, overlay.tier),
        research_cost=max(base.research_cost, overlay.research_cost),
    )


def _copy_unit(unit: SourceUnit) -> SourceUnit:
    return SourceUnit(
        name=unit.name,
        source_side=unit.source_side,
        period=unit.period,
        category=unit.category,
        members=dict(unit.members),
        vehicles=list(unit.vehicles),
        actions=list(unit.actions),
        definition_references=list(unit.definition_references),
        source_files=list(unit.source_files),
        source_layer=unit.source_layer,
        source_priority=unit.source_priority,
        virtual=unit.virtual,
        tier=unit.tier,
        research_cost=unit.research_cost,
    )


def _match_existing_key(units: Mapping[str, SourceUnit], name: str, side: str) -> str | None:
    if name in units and units[name].source_side == side:
        return name
    suffixed = f"{_base_name(name)}({side})"
    if suffixed in units and units[suffixed].source_side == side:
        return suffixed
    base = _base_name(name).lower()
    matching = [key for key, unit in units.items() if unit.source_side == side and _base_name(key).lower() == base]
    return sorted(matching)[0] if matching else None


def _source_priority(source: str) -> int:
    match = re.match(r"(\d+):", source)
    return int(match.group(1)) if match else -1


def _layer_name(roots: Sequence[Path], priority: int) -> str:
    return roots[priority].name if 0 <= priority < len(roots) else "unknown"


def _base_name(name: str) -> str:
    return SIDE_SUFFIX_RE.sub("", name).strip()


def _paren_balance(value: str) -> int:
    without_quotes = re.sub(r'"[^"]*"', "", value)
    return without_quotes.count("(") - without_quotes.count(")")


def _display_name(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-.]+", " ", value)).strip().title()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unnamed"


def _category_rank(category: str) -> int:
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)
