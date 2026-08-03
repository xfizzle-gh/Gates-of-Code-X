from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Faction(StrEnum):
    NATO = "nato"
    UKRAINE = "ukr"
    RUSSIA = "rusa"
    PRC = "prc"
    NEUTRAL = "neutral"


class BattalionType(StrEnum):
    INFANTRY = "infantry"
    MECHANIZED = "mechanized"
    ARMOR = "armor"
    SUPPORT = "support"
    COMBINED_ARMS = "combined_arms"


class FormationKind(StrEnum):
    ARMORED_BRIGADE = "armored_brigade"
    MECHANIZED_BRIGADE = "mechanized_brigade"
    AIRBORNE_BRIGADE = "airborne_brigade"
    AIR_ASSAULT_BRIGADE = "air_assault_brigade"
    PANZERGRENADIER_BRIGADE = "panzergrenadier_brigade"
    NAVAL_INFANTRY_BRIGADE = "naval_infantry_brigade"
    COMBINED_ARMS_BRIGADE = "combined_arms_brigade"
    BATTLEGROUP = "battlegroup"
    EXPEDITIONARY_BRIGADE = "expeditionary_brigade"
    SUPPORT_GROUP = "support_group"


@dataclass(slots=True)
class BattalionRosterEntry:
    unit_name: str
    quantity: int = 1
    stage: str = ""
    category: str = "unknown"
    preserved_objects: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.unit_name.strip():
            raise ValueError("Roster unit_name cannot be empty")
        if self.quantity < 0:
            raise ValueError("Roster quantity cannot be negative")


@dataclass(slots=True)
class Alliance:
    alliance_id: str
    display_name: str
    factions: list[Faction]
    notes: str = ""

    def validate(self) -> None:
        if not self.alliance_id.strip():
            raise ValueError("Alliance ID cannot be empty")
        if not self.display_name.strip():
            raise ValueError(f"Alliance {self.alliance_id} has no display name")
        if len(self.factions) < 2:
            raise ValueError(f"Alliance {self.alliance_id} must contain at least two factions")
        if len(set(self.factions)) != len(self.factions):
            raise ValueError(f"Alliance {self.alliance_id} contains duplicate factions")
        if Faction.NEUTRAL in self.factions:
            raise ValueError(f"Alliance {self.alliance_id} cannot include neutral")


@dataclass(slots=True)
class Formation:
    formation_id: str
    display_name: str
    faction: Faction
    nation: str
    kind: FormationKind = FormationKind.COMBINED_ARMS_BRIGADE
    deployment_zone: str = ""
    doctrine_tags: list[str] = field(default_factory=list)
    preferred_categories: list[str] = field(default_factory=list)
    is_foreign_contingent: bool = False
    notes: str = ""

    def validate(self) -> None:
        if not self.formation_id.strip():
            raise ValueError("Formation ID cannot be empty")
        if not self.display_name.strip():
            raise ValueError(f"Formation {self.formation_id} has no display name")
        if not self.nation.strip():
            raise ValueError(f"Formation {self.formation_id} has no nation tag")
        if self.faction == Faction.NEUTRAL:
            raise ValueError(f"Formation {self.formation_id} cannot belong to neutral")


@dataclass(slots=True)
class Battalion:
    battalion_id: str
    faction: Faction
    province_id: str
    battalion_type: BattalionType = BattalionType.COMBINED_ARMS
    roster: list[BattalionRosterEntry] = field(default_factory=list)
    formation_id: str = ""
    is_player_controlled: bool = False
    movement_remaining: int = 1
    combat_actions_remaining: int = 1
    supply: int = 100
    experience: int = 0
    encircled_turns: int = 0

    def validate(self) -> None:
        if not self.battalion_id.strip():
            raise ValueError("Battalion ID cannot be empty")
        if not self.province_id.strip():
            raise ValueError(f"Battalion {self.battalion_id} has no province")
        if not 0 <= self.supply <= 100:
            raise ValueError(f"Battalion {self.battalion_id} supply must be 0..100")
        for entry in self.roster:
            entry.validate()

    @property
    def unit_count(self) -> int:
        return sum(entry.quantity for entry in self.roster)

    @property
    def is_destroyed(self) -> bool:
        return self.unit_count <= 0


@dataclass(slots=True)
class Province:
    province_id: str
    display_name: str
    owner: Faction = Faction.NEUTRAL
    neighbors: list[str] = field(default_factory=list)
    terrain: str = "temperate"
    map_region: str = "ostfront"
    x: float = 0.0
    y: float = 0.0
    resource_yield: int = 10
    fortification: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.province_id.strip():
            raise ValueError("Province ID cannot be empty")
        if self.province_id in self.neighbors:
            raise ValueError(f"Province {self.province_id} cannot neighbor itself")
        if self.fortification < 0:
            raise ValueError(f"Province {self.province_id} has negative fortification")


@dataclass(slots=True)
class FactionState:
    faction: Faction
    resources: int = 1000
    researched_keys: list[str] = field(default_factory=list)
    recruited_pool: list[BattalionRosterEntry] = field(default_factory=list)
    is_human_controlled: bool = False
    is_eliminated: bool = False


@dataclass(slots=True)
class BattleParticipant:
    battalion_id: str
    faction: Faction
    stage: str
    is_primary: bool = False


@dataclass(slots=True)
class PendingBattle:
    battle_id: str
    origin_province_id: str
    target_province_id: str
    attacker_faction: Faction
    defender_faction: Faction
    attacking_participants: list[BattleParticipant]
    defending_participants: list[BattleParticipant]
    player_faction: Faction
    player_is_attacker: bool
    exported_save_path: str = ""
    started: bool = False
    completed: bool = False


@dataclass(slots=True)
class CampaignState:
    campaign_name: str
    turn_number: int = 1
    current_faction: Faction = Faction.NATO
    selected_faction: Faction = Faction.NATO
    difficulty: str = "normal"
    game_directory: str = ""
    profile_directory: str = ""
    code_x_directory: str = ""
    map_id: str = "custom"
    map_metadata: dict[str, Any] = field(default_factory=dict)
    factions: dict[str, FactionState] = field(default_factory=dict)
    alliances: dict[str, Alliance] = field(default_factory=dict)
    formations: dict[str, Formation] = field(default_factory=dict)
    provinces: dict[str, Province] = field(default_factory=dict)
    battalions: dict[str, Battalion] = field(default_factory=dict)
    pending_battle: PendingBattle | None = None
    schema_version: int = 3

    def validate(self) -> None:
        if self.turn_number < 1:
            raise ValueError("Campaign turn_number must be at least 1")
        if not self.provinces:
            raise ValueError("Campaign must contain at least one province")
        for key, alliance in self.alliances.items():
            if key != alliance.alliance_id:
                raise ValueError(f"Alliance key mismatch: {key}")
            alliance.validate()
            for faction in alliance.factions:
                if faction.value not in self.factions:
                    raise ValueError(f"Alliance {key} references missing faction {faction.value}")
        for key, formation in self.formations.items():
            if key != formation.formation_id:
                raise ValueError(f"Formation key mismatch: {key}")
            formation.validate()
            if formation.faction.value not in self.factions:
                raise ValueError(f"Formation {key} references missing faction {formation.faction.value}")
        for key, province in self.provinces.items():
            if key != province.province_id:
                raise ValueError(f"Province key mismatch: {key}")
            province.validate()
            for neighbor_id in province.neighbors:
                if neighbor_id not in self.provinces:
                    raise ValueError(f"Province {key} references missing neighbor {neighbor_id}")
        for province in self.provinces.values():
            for neighbor_id in province.neighbors:
                if province.province_id not in self.provinces[neighbor_id].neighbors:
                    raise ValueError(f"Adjacency must be reciprocal: {province.province_id} -> {neighbor_id}")
        occupied: dict[str, str] = {}
        for key, battalion in self.battalions.items():
            if key != battalion.battalion_id:
                raise ValueError(f"Battalion key mismatch: {key}")
            battalion.validate()
            if battalion.province_id not in self.provinces:
                raise ValueError(f"Battalion {key} references missing province")
            if battalion.formation_id:
                formation = self.formations.get(battalion.formation_id)
                if formation is None:
                    raise ValueError(f"Battalion {key} references missing formation {battalion.formation_id}")
                if formation.faction != battalion.faction:
                    raise ValueError(f"Battalion {key} faction does not match formation {formation.formation_id}")
            previous = occupied.setdefault(battalion.province_id, key)
            if previous != key:
                raise ValueError(f"Province {battalion.province_id} contains multiple battalions")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
