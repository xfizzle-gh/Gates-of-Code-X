from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .operational_schema import (
    PROGRESS_MILLI_MAX,
    PROGRESS_MILLI_MIN,
    FormationOperationalPosition,
    MoveOrderStatus,
    OperationalMoveOrder,
    PositionMode,
    require_strict_int,
)


_OPERATIONAL_SUPPLY_FIELDS = (
    "supplied",
    "cut_off",
    "source_hub_id",
    "route_cost",
    "grace_ticks_remaining",
    "last_supply_refresh_tick",
    "last_supply_refresh_turn",
    "last_grace_consuming_tick",
)


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


class ForceEchelon(StrEnum):
    """Strategic-map formation size. Balance/capacity values are intentionally unset."""

    BATTALION = "battalion"
    REGIMENT = "regiment"
    BRIGADE = "brigade"
    DIVISION = "division"


class CommanderStatus(StrEnum):
    ACTIVE = "active"
    UNASSIGNED = "unassigned"
    CASUALTY = "casualty"
    MISSING = "missing"


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
class ReinforcementPoolEntry:
    unit_name: str
    quantity: int
    category: str
    formation_id: str
    unit_cost: int

    def validate(self) -> None:
        if not self.unit_name.strip():
            raise ValueError("Reinforcement unit_name cannot be empty")
        if self.quantity < 1:
            raise ValueError("Reinforcement quantity must be positive")
        if not self.formation_id.strip():
            raise ValueError("Reinforcement entry must target a formation")
        if self.unit_cost < 0:
            raise ValueError("Reinforcement unit_cost cannot be negative")


@dataclass(slots=True)
class ResearchNode:
    key: str
    faction: Faction
    display_name: str
    cost: int
    prerequisites: list[str] = field(default_factory=list)
    unlock_categories: list[str] = field(default_factory=list)
    unlock_doctrines: list[str] = field(default_factory=list)
    unlock_units: list[str] = field(default_factory=list)
    source: str = "catalog-derived"

    def validate(self) -> None:
        if not self.key.strip():
            raise ValueError("Research key cannot be empty")
        if not self.display_name.strip():
            raise ValueError(f"Research node {self.key} has no display name")
        if self.faction == Faction.NEUTRAL:
            raise ValueError(f"Research node {self.key} cannot belong to neutral")
        if self.cost < 0:
            raise ValueError(f"Research node {self.key} has negative cost")


@dataclass(slots=True)
class UnitEconomy:
    unit_name: str
    faction: Faction
    category: str
    purchase_cost: int
    maintenance_cost: int
    repair_cost_per_point: int
    research_keys: list[str] = field(default_factory=list)
    doctrine: str = ""
    manpower_estimate: int = 0

    def validate(self) -> None:
        if not self.unit_name.strip():
            raise ValueError("Unit economy unit_name cannot be empty")
        if self.faction == Faction.NEUTRAL:
            raise ValueError(f"Unit economy {self.unit_name} cannot belong to neutral")
        if min(self.purchase_cost, self.maintenance_cost, self.repair_cost_per_point) < 0:
            raise ValueError(f"Unit economy {self.unit_name} has a negative cost")


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
    """TOE / national identity template (not the on-map strategic container)."""

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
class Commander:
    """Optional commander record. Old saves may have zero commanders."""

    commander_id: str
    display_name: str
    rank: str = ""
    portrait_key: str = ""
    assigned_strategic_formation_id: str | None = None
    assigned_battalion_id: str | None = None
    status: CommanderStatus = CommanderStatus.UNASSIGNED
    experience: int = 0
    source: str = "unassigned"
    provenance: str = ""

    def validate(self) -> None:
        if not self.commander_id.strip():
            raise ValueError("Commander ID cannot be empty")
        if not self.display_name.strip():
            raise ValueError(f"Commander {self.commander_id} has no display name")
        if self.assigned_strategic_formation_id and self.assigned_battalion_id:
            raise ValueError(
                f"Commander {self.commander_id} cannot be assigned to a formation and battalion simultaneously"
            )
        if self.experience < 0:
            raise ValueError(f"Commander {self.commander_id} experience cannot be negative")


@dataclass(slots=True)
class StrategicFormation:
    """On-map strategic force container (battalion..division). Designers call this a formation.

    Distinct from :class:`Formation`, which remains the TOE/identity template.
    """

    strategic_formation_id: str
    display_name: str
    faction: Faction
    province_id: str
    echelon: ForceEchelon = ForceEchelon.BATTALION
    commander_id: str | None = None
    battalion_ids: list[str] = field(default_factory=list)
    template_formation_id: str = ""
    stack_order: int = 0
    movement_state: str = "at_anchor"
    stance: str = "standard"
    actor_id: str = ""
    condition_summary: int = 100
    supply_summary: int = 100
    experience_summary: int = 0
    is_player_controlled: bool = False
    # Operational graph location (S2). province_id remains derived/legacy authority.
    position: FormationOperationalPosition | None = None
    # S3: current draft/active move order (formation is movement authority).
    move_order: OperationalMoveOrder | None = None
    # S8: deterministic operational supply connectivity state.
    supplied: bool = True
    cut_off: bool = False
    source_hub_id: str | None = None
    route_cost: int | None = None
    grace_ticks_remaining: int = 0
    last_supply_refresh_tick: int | None = None
    last_supply_refresh_turn: int | None = None
    last_grace_consuming_tick: int | None = None
    # S9C: tick after the first complete stationary Ambush tick.
    ambush_ready_tick: int | None = None

    def validate(self) -> None:
        if not self.strategic_formation_id.strip():
            raise ValueError("Strategic formation ID cannot be empty")
        if not self.display_name.strip():
            raise ValueError(f"Strategic formation {self.strategic_formation_id} has no display name")
        if not self.province_id.strip():
            raise ValueError(f"Strategic formation {self.strategic_formation_id} has no province")
        if self.faction == Faction.NEUTRAL:
            raise ValueError(f"Strategic formation {self.strategic_formation_id} cannot belong to neutral")
        if not self.battalion_ids:
            raise ValueError(f"Strategic formation {self.strategic_formation_id} must contain at least one battalion")
        if len(set(self.battalion_ids)) != len(self.battalion_ids):
            raise ValueError(f"Strategic formation {self.strategic_formation_id} has duplicate battalion membership")
        if self.position is not None:
            _validate_position_shape(self.position, force_id=self.strategic_formation_id)
        if self.move_order is not None:
            if self.move_order.formation_id and self.move_order.formation_id != self.strategic_formation_id:
                raise ValueError(
                    f"Strategic formation {self.strategic_formation_id} move_order formation_id mismatch"
                )
            if self.move_order.status not in {item.value for item in MoveOrderStatus}:
                raise ValueError(
                    f"Strategic formation {self.strategic_formation_id} has invalid move_order status"
                )
        if not isinstance(self.supplied, bool):
            raise ValueError(
                f"Strategic formation {self.strategic_formation_id} supplied must be bool"
            )
        if not isinstance(self.cut_off, bool):
            raise ValueError(
                f"Strategic formation {self.strategic_formation_id} cut_off must be bool"
            )
        if self.source_hub_id is not None and (
            not isinstance(self.source_hub_id, str)
            or not self.source_hub_id.strip()
        ):
            raise ValueError(
                f"Strategic formation {self.strategic_formation_id} source_hub_id cannot be empty"
            )
        for name, value in (
            ("route_cost", self.route_cost),
            ("last_supply_refresh_tick", self.last_supply_refresh_tick),
            ("last_supply_refresh_turn", self.last_supply_refresh_turn),
            ("last_grace_consuming_tick", self.last_grace_consuming_tick),
            ("ambush_ready_tick", self.ambush_ready_tick),
        ):
            if value is not None:
                require_strict_int(value, name=name, minimum=0)
        require_strict_int(
            self.grace_ticks_remaining,
            name="grace_ticks_remaining",
            minimum=0,
            maximum=1,
        )
        supply_shape = (
            self.supplied,
            self.cut_off,
            self.source_hub_id is not None,
            self.route_cost is not None,
            self.grace_ticks_remaining,
        )
        legal_supply_shapes = {
            (True, False, True, True, 0),
            (True, False, False, False, 0),
            (True, False, False, False, 1),
            (False, True, False, False, 0),
        }
        if supply_shape not in legal_supply_shapes:
            raise ValueError(
                f"Strategic formation {self.strategic_formation_id} "
                "invalid_operational_supply_state"
            )
        if self.last_grace_consuming_tick is not None and (
            self.last_supply_refresh_tick is None
            or self.last_supply_refresh_tick
            < self.last_grace_consuming_tick
        ):
            raise ValueError(
                f"Strategic formation {self.strategic_formation_id} "
                "invalid_supply_tick_order"
            )


@dataclass(slots=True)
class Battalion:
    battalion_id: str
    faction: Faction
    province_id: str
    battalion_type: BattalionType = BattalionType.COMBINED_ARMS
    roster: list[BattalionRosterEntry] = field(default_factory=list)
    authorized_roster: list[BattalionRosterEntry] = field(default_factory=list)
    formation_id: str = ""
    strategic_formation_id: str = ""
    commander_id: str | None = None
    is_player_controlled: bool = False
    movement_remaining: int = 1
    combat_actions_remaining: int = 1
    supply: int = 100
    condition: int = 100
    experience: int = 0
    encircled_turns: int = 0

    def validate(self) -> None:
        if not self.battalion_id.strip():
            raise ValueError("Battalion ID cannot be empty")
        if not self.province_id.strip():
            raise ValueError(f"Battalion {self.battalion_id} has no province")
        if not 0 <= self.supply <= 100:
            raise ValueError(f"Battalion {self.battalion_id} supply must be 0..100")
        if not 0 <= self.condition <= 100:
            raise ValueError(f"Battalion {self.battalion_id} condition must be 0..100")
        for entry in self.roster:
            entry.validate()
        for entry in self.authorized_roster:
            entry.validate()

    @property
    def unit_count(self) -> int:
        return sum(entry.quantity for entry in self.roster)

    @property
    def authorized_unit_count(self) -> int:
        return sum(entry.quantity for entry in self.authorized_roster)

    @property
    def replacement_deficit(self) -> int:
        return max(0, self.authorized_unit_count - self.unit_count)

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
    reinforcement_pool: list[ReinforcementPoolEntry] = field(default_factory=list)
    income_last_round: int = 0
    maintenance_last_round: int = 0
    is_human_controlled: bool = False
    is_eliminated: bool = False


@dataclass(slots=True)
class BattleParticipant:
    battalion_id: str
    faction: Faction
    stage: str
    is_primary: bool = False
    contact_initiator: bool = False
    ambush_eligible: bool = False
    ambush_triggered: bool = False
    ambush_strength_multiplier_milli: int = 1000
    ambush_readiness_consumed: bool = False


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
    # S4/S6 operational contact (empty for legacy province adjacency battles).
    encounter_node_id: str = ""
    encounter_kind: str = ""
    attacker_formation_id: str = ""
    defender_formation_id: str = ""
    encounter_edge_id: str = ""
    encounter_progress_milli: int | None = None
    encounter_pixel: list[int] = field(default_factory=list)


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
    catalog_signature: str = ""
    map_id: str = "custom"
    map_metadata: dict[str, Any] = field(default_factory=dict)
    factions: dict[str, FactionState] = field(default_factory=dict)
    alliances: dict[str, Alliance] = field(default_factory=dict)
    formations: dict[str, Formation] = field(default_factory=dict)
    strategic_formations: dict[str, StrategicFormation] = field(default_factory=dict)
    commanders: dict[str, Commander] = field(default_factory=dict)
    research_nodes: dict[str, ResearchNode] = field(default_factory=dict)
    unit_economy: dict[str, UnitEconomy] = field(default_factory=dict)
    provinces: dict[str, Province] = field(default_factory=dict)
    battalions: dict[str, Battalion] = field(default_factory=dict)
    pending_battle: PendingBattle | None = None
    schema_version: int = 4

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
        for key, node in self.research_nodes.items():
            if key != node.key:
                raise ValueError(f"Research key mismatch: {key}")
            node.validate()
            if node.faction.value not in self.factions:
                raise ValueError(f"Research node {key} references missing faction")
            for prerequisite in node.prerequisites:
                if prerequisite not in self.research_nodes:
                    raise ValueError(f"Research node {key} references missing prerequisite {prerequisite}")
        for key, economy in self.unit_economy.items():
            if key != economy.unit_name:
                raise ValueError(f"Unit economy key mismatch: {key}")
            economy.validate()
            for research_key in economy.research_keys:
                if research_key not in self.research_nodes:
                    raise ValueError(f"Unit economy {key} references missing research {research_key}")
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
        occupied_factions: dict[str, Faction] = {}
        membership: dict[str, str] = {}
        for key, force in self.strategic_formations.items():
            if key != force.strategic_formation_id:
                raise ValueError(f"Strategic formation key mismatch: {key}")
            force.validate()
            if force.faction.value not in self.factions:
                raise ValueError(f"Strategic formation {key} references missing faction")
            if force.province_id not in self.provinces:
                raise ValueError(f"Strategic formation {key} references missing province")
            if force.template_formation_id:
                template = self.formations.get(force.template_formation_id)
                if template is None:
                    raise ValueError(
                        f"Strategic formation {key} references missing TOE template {force.template_formation_id}"
                    )
                if template.faction != force.faction:
                    raise ValueError(f"Strategic formation {key} faction does not match TOE template")
            if force.commander_id:
                commander = self.commanders.get(force.commander_id)
                if commander is None:
                    raise ValueError(f"Strategic formation {key} references missing commander {force.commander_id}")
                if commander.assigned_strategic_formation_id != key:
                    raise ValueError(f"Commander {force.commander_id} is not assigned back to formation {key}")
                if commander.assigned_battalion_id:
                    raise ValueError(f"Commander {force.commander_id} has dual assignment")
            for battalion_id in force.battalion_ids:
                if battalion_id in membership:
                    raise ValueError(
                        f"Battalion {battalion_id} belongs to multiple strategic formations "
                        f"({membership[battalion_id]} and {key})"
                    )
                membership[battalion_id] = key
        for key, commander in self.commanders.items():
            if key != commander.commander_id:
                raise ValueError(f"Commander key mismatch: {key}")
            commander.validate()
            if commander.assigned_strategic_formation_id:
                force = self.strategic_formations.get(commander.assigned_strategic_formation_id)
                if force is None:
                    raise ValueError(
                        f"Commander {key} references missing strategic formation "
                        f"{commander.assigned_strategic_formation_id}"
                    )
                if force.commander_id != key:
                    raise ValueError(f"Strategic formation {force.strategic_formation_id} commander mismatch")
            if commander.assigned_battalion_id:
                battalion = self.battalions.get(commander.assigned_battalion_id)
                if battalion is None:
                    raise ValueError(
                        f"Commander {key} references missing battalion {commander.assigned_battalion_id}"
                    )
                if battalion.commander_id != key:
                    raise ValueError(f"Battalion {battalion.battalion_id} commander mismatch")
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
            if battalion.strategic_formation_id:
                force = self.strategic_formations.get(battalion.strategic_formation_id)
                if force is None:
                    raise ValueError(
                        f"Battalion {key} references missing strategic formation {battalion.strategic_formation_id}"
                    )
                if key not in force.battalion_ids:
                    raise ValueError(f"Battalion {key} missing from strategic formation membership list")
                if force.faction != battalion.faction:
                    raise ValueError(f"Battalion {key} faction does not match strategic formation")
                if force.province_id != battalion.province_id:
                    raise ValueError(
                        f"Battalion {key} province {battalion.province_id} does not match "
                        f"strategic formation province {force.province_id}"
                    )
                if membership.get(key) != battalion.strategic_formation_id:
                    raise ValueError(f"Battalion {key} strategic formation membership is inconsistent")
            elif self.strategic_formations:
                raise ValueError(f"Battalion {key} is not assigned to a strategic formation")
            if battalion.commander_id:
                commander = self.commanders.get(battalion.commander_id)
                if commander is None:
                    raise ValueError(f"Battalion {key} references missing commander {battalion.commander_id}")
                if commander.assigned_battalion_id != key:
                    raise ValueError(f"Commander {battalion.commander_id} is not assigned back to battalion {key}")
                if commander.assigned_strategic_formation_id:
                    raise ValueError(f"Commander {battalion.commander_id} has dual assignment")
            previous_faction = occupied_factions.setdefault(
                battalion.province_id, battalion.faction
            )
            if previous_faction != battalion.faction and not self._allows_mixed_province_presence():
                raise ValueError(
                    f"Province {battalion.province_id} contains battalions from multiple factions"
                )
        if self.strategic_formations:
            orphan_members = set(membership) - set(self.battalions)
            if orphan_members:
                raise ValueError(f"Strategic formations reference missing battalions: {sorted(orphan_members)}")
        for faction_state in self.factions.values():
            if faction_state.resources < 0:
                raise ValueError(f"Faction {faction_state.faction.value} has negative resources")
            for entry in faction_state.reinforcement_pool:
                entry.validate()
                formation = self.formations.get(entry.formation_id)
                if formation is None or formation.faction != faction_state.faction:
                    raise ValueError(f"Invalid reinforcement target {entry.formation_id}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.schema_version < 8:
            for row in payload.get("strategic_formations", {}).values():
                for key in _OPERATIONAL_SUPPLY_FIELDS:
                    row.pop(key, None)
        return payload

    def _allows_mixed_province_presence(self) -> bool:
        """Hostile co-presence only with explicit operational capability or contact.

        A stale/non-null formation ``position`` alone is not sufficient.
        """
        pending = self.pending_battle
        if pending is not None and str(getattr(pending, "encounter_kind", "") or ""):
            return True
        if bool(self.map_metadata.get("operational_maneuver_enabled")):
            return True
        # Resolvable operational graph path (must exist as a file, not merely be declared).
        configured = str(self.map_metadata.get("operational_graph", "") or "").strip()
        if configured:
            from pathlib import Path

            path = Path(configured).expanduser()
            if path.is_file():
                return True
            # Relative assets next to cwd / godot (same contract as operational_position).
            for candidate in (
                Path.cwd() / configured,
                Path.cwd() / "godot" / configured,
            ):
                try:
                    if candidate.is_file():
                        return True
                except OSError:
                    continue
        return False


def _validate_position_shape(position: FormationOperationalPosition, *, force_id: str) -> None:
    """Shape-only checks when no operational graph is loaded (full graph validate is S2 migration)."""
    try:
        progress = require_strict_int(
            position.progress_milli,
            name="progress_milli",
            minimum=PROGRESS_MILLI_MIN,
            maximum=PROGRESS_MILLI_MAX,
        )
    except ValueError as exc:
        raise ValueError(f"Strategic formation {force_id} position invalid: {exc}") from exc
    if position.mode == PositionMode.AT_NODE.value:
        if not position.node_id or not str(position.node_id).strip():
            raise ValueError(f"Strategic formation {force_id} at_node position requires node_id")
        if position.edge_id is not None:
            raise ValueError(f"Strategic formation {force_id} at_node position must not set edge_id")
        if progress != 0:
            raise ValueError(f"Strategic formation {force_id} at_node progress_milli must be 0")
        if position.facing_node_id is not None:
            raise ValueError(f"Strategic formation {force_id} at_node must not set facing_node_id")
    elif position.mode == PositionMode.ON_EDGE.value:
        if not position.edge_id or not str(position.edge_id).strip():
            raise ValueError(f"Strategic formation {force_id} on_edge position requires edge_id")
        if position.node_id is not None:
            raise ValueError(f"Strategic formation {force_id} on_edge position must not set node_id")
        if not position.facing_node_id or not str(position.facing_node_id).strip():
            raise ValueError(f"Strategic formation {force_id} on_edge requires facing_node_id")
    else:
        raise ValueError(f"Strategic formation {force_id} has invalid position mode {position.mode}")
