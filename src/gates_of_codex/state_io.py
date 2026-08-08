from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    BattleParticipant,
    CampaignState,
    Commander,
    CommanderStatus,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    PendingBattle,
    Province,
    ReinforcementPoolEntry,
    ResearchNode,
    StrategicFormation,
    UnitEconomy,
)


def _roster(value: dict[str, Any]) -> BattalionRosterEntry:
    return BattalionRosterEntry(**value)


def campaign_from_dict(data: dict[str, Any]) -> CampaignState:
    factions = {
        key: FactionState(
            faction=Faction(value["faction"]),
            resources=int(value.get("resources", 1000)),
            researched_keys=list(value.get("researched_keys", [])),
            recruited_pool=[_roster(item) for item in value.get("recruited_pool", [])],
            reinforcement_pool=[
                ReinforcementPoolEntry(
                    unit_name=item["unit_name"],
                    quantity=int(item.get("quantity", 1)),
                    category=item.get("category", "unknown"),
                    formation_id=item["formation_id"],
                    unit_cost=int(item.get("unit_cost", 0)),
                )
                for item in value.get("reinforcement_pool", [])
            ],
            income_last_round=int(value.get("income_last_round", 0)),
            maintenance_last_round=int(value.get("maintenance_last_round", 0)),
            is_human_controlled=value.get("is_human_controlled", False),
            is_eliminated=value.get("is_eliminated", False),
        )
        for key, value in data.get("factions", {}).items()
    }
    alliances = {
        key: Alliance(
            alliance_id=value["alliance_id"],
            display_name=value["display_name"],
            factions=[Faction(item) for item in value.get("factions", [])],
            notes=value.get("notes", ""),
        )
        for key, value in data.get("alliances", {}).items()
    }
    formations = {
        key: Formation(
            formation_id=value["formation_id"],
            display_name=value["display_name"],
            faction=Faction(value["faction"]),
            nation=value["nation"],
            kind=FormationKind(value.get("kind", "combined_arms_brigade")),
            deployment_zone=value.get("deployment_zone", ""),
            doctrine_tags=list(value.get("doctrine_tags", [])),
            preferred_categories=list(value.get("preferred_categories", [])),
            is_foreign_contingent=value.get("is_foreign_contingent", False),
            notes=value.get("notes", ""),
        )
        for key, value in data.get("formations", {}).items()
    }
    research_nodes = {
        key: ResearchNode(
            key=value["key"],
            faction=Faction(value["faction"]),
            display_name=value["display_name"],
            cost=int(value.get("cost", 0)),
            prerequisites=list(value.get("prerequisites", [])),
            unlock_categories=list(value.get("unlock_categories", [])),
            unlock_doctrines=list(value.get("unlock_doctrines", [])),
            unlock_units=list(value.get("unlock_units", [])),
            source=value.get("source", "catalog-derived"),
        )
        for key, value in data.get("research_nodes", {}).items()
    }
    unit_economy = {
        key: UnitEconomy(
            unit_name=value["unit_name"],
            faction=Faction(value["faction"]),
            category=value.get("category", "unknown"),
            purchase_cost=int(value.get("purchase_cost", 0)),
            maintenance_cost=int(value.get("maintenance_cost", 0)),
            repair_cost_per_point=int(value.get("repair_cost_per_point", 0)),
            research_keys=list(value.get("research_keys", [])),
            doctrine=value.get("doctrine", ""),
            manpower_estimate=int(value.get("manpower_estimate", 0)),
        )
        for key, value in data.get("unit_economy", {}).items()
    }
    provinces = {
        key: Province(
            province_id=value["province_id"],
            display_name=value["display_name"],
            owner=Faction(value.get("owner", "neutral")),
            neighbors=list(value.get("neighbors", [])),
            terrain=value.get("terrain", "temperate"),
            map_region=value.get("map_region", "ostfront"),
            x=float(value.get("x", 0)),
            y=float(value.get("y", 0)),
            resource_yield=int(value.get("resource_yield", 10)),
            fortification=int(value.get("fortification", 0)),
            metadata=dict(value.get("metadata", {})),
        )
        for key, value in data.get("provinces", {}).items()
    }
    battalions: dict[str, Battalion] = {}
    for key, value in data.get("battalions", {}).items():
        roster = [_roster(item) for item in value.get("roster", [])]
        authorized_data = value.get("authorized_roster")
        authorized = [_roster(item) for item in authorized_data] if authorized_data is not None else [
            BattalionRosterEntry(
                entry.unit_name,
                quantity=entry.quantity,
                stage=entry.stage,
                category=entry.category,
                preserved_objects=list(entry.preserved_objects),
            )
            for entry in roster
        ]
        commander_raw = value.get("commander_id", None)
        battalions[key] = Battalion(
            battalion_id=value["battalion_id"],
            faction=Faction(value["faction"]),
            province_id=value["province_id"],
            battalion_type=BattalionType(value.get("battalion_type", "combined_arms")),
            roster=roster,
            authorized_roster=authorized,
            formation_id=value.get("formation_id", ""),
            strategic_formation_id=str(value.get("strategic_formation_id", "") or ""),
            commander_id=None if commander_raw in (None, "") else str(commander_raw),
            is_player_controlled=value.get("is_player_controlled", False),
            movement_remaining=int(value.get("movement_remaining", 1)),
            combat_actions_remaining=int(value.get("combat_actions_remaining", 1)),
            supply=int(value.get("supply", 100)),
            condition=int(value.get("condition", 100)),
            experience=int(value.get("experience", 0)),
            encircled_turns=int(value.get("encircled_turns", 0)),
        )
    from .operational_movement import move_order_from_dict
    from .operational_position import position_from_dict

    strategic_formations = {
        key: StrategicFormation(
            strategic_formation_id=value["strategic_formation_id"],
            display_name=value["display_name"],
            faction=Faction(value["faction"]),
            province_id=value["province_id"],
            echelon=ForceEchelon(value.get("echelon", "battalion")),
            commander_id=(
                None
                if value.get("commander_id") in (None, "")
                else str(value.get("commander_id"))
            ),
            battalion_ids=list(value.get("battalion_ids", [])),
            template_formation_id=str(value.get("template_formation_id", "") or ""),
            stack_order=int(value.get("stack_order", 0)),
            movement_state=str(value.get("movement_state", "at_anchor")),
            stance=str(value.get("stance", "standard")),
            actor_id=str(value.get("actor_id", "") or ""),
            condition_summary=int(value.get("condition_summary", 100)),
            supply_summary=int(value.get("supply_summary", 100)),
            experience_summary=int(value.get("experience_summary", 0)),
            is_player_controlled=bool(value.get("is_player_controlled", False)),
            position=position_from_dict(value.get("position")),
            move_order=move_order_from_dict(value.get("move_order")),
            supplied=_strict_supply_bool(value.get("supplied", True), name="supplied"),
            cut_off=_strict_supply_bool(value.get("cut_off", False), name="cut_off"),
            source_hub_id=_optional_supply_id(
                value.get("source_hub_id"), name="source_hub_id"
            ),
            route_cost=_optional_supply_int(value.get("route_cost"), name="route_cost"),
            grace_ticks_remaining=_required_supply_int(
                value.get("grace_ticks_remaining", 0),
                name="grace_ticks_remaining",
                maximum=1,
            ),
            last_supply_refresh_tick=_optional_supply_int(
                value.get("last_supply_refresh_tick"),
                name="last_supply_refresh_tick",
            ),
            last_supply_refresh_turn=_optional_supply_int(
                value.get("last_supply_refresh_turn"),
                name="last_supply_refresh_turn",
            ),
            last_grace_consuming_tick=_optional_supply_int(
                value.get("last_grace_consuming_tick"),
                name="last_grace_consuming_tick",
            ),
        )
        for key, value in data.get("strategic_formations", {}).items()
    }
    # Reject contradictory persisted S8 state before authoritative load-time
    # recomputation can normalize it into a different legal shape.
    for force in strategic_formations.values():
        force.validate()
    commanders = {
        key: Commander(
            commander_id=value["commander_id"],
            display_name=value["display_name"],
            rank=str(value.get("rank", "") or ""),
            portrait_key=str(value.get("portrait_key", "") or ""),
            assigned_strategic_formation_id=(
                None
                if value.get("assigned_strategic_formation_id") in (None, "")
                else str(value.get("assigned_strategic_formation_id"))
            ),
            assigned_battalion_id=(
                None
                if value.get("assigned_battalion_id") in (None, "")
                else str(value.get("assigned_battalion_id"))
            ),
            status=CommanderStatus(value.get("status", "unassigned")),
            experience=int(value.get("experience", 0)),
            source=str(value.get("source", "unassigned") or "unassigned"),
            provenance=str(value.get("provenance", "") or ""),
        )
        for key, value in data.get("commanders", {}).items()
    }
    pending_data = data.get("pending_battle")
    pending = None
    if pending_data:
        pending = PendingBattle(
            battle_id=pending_data["battle_id"],
            origin_province_id=pending_data["origin_province_id"],
            target_province_id=pending_data["target_province_id"],
            attacker_faction=Faction(pending_data["attacker_faction"]),
            defender_faction=Faction(pending_data["defender_faction"]),
            attacking_participants=[
                BattleParticipant(
                    battalion_id=item["battalion_id"],
                    faction=Faction(item["faction"]),
                    stage=item["stage"],
                    is_primary=item.get("is_primary", False),
                )
                for item in pending_data.get("attacking_participants", [])
            ],
            defending_participants=[
                BattleParticipant(
                    battalion_id=item["battalion_id"],
                    faction=Faction(item["faction"]),
                    stage=item["stage"],
                    is_primary=item.get("is_primary", False),
                )
                for item in pending_data.get("defending_participants", [])
            ],
            player_faction=Faction(pending_data["player_faction"]),
            player_is_attacker=pending_data["player_is_attacker"],
            exported_save_path=pending_data.get("exported_save_path", ""),
            started=pending_data.get("started", False),
            completed=pending_data.get("completed", False),
            encounter_node_id=str(pending_data.get("encounter_node_id", "") or ""),
            encounter_kind=str(pending_data.get("encounter_kind", "") or ""),
            attacker_formation_id=str(pending_data.get("attacker_formation_id", "") or ""),
            defender_formation_id=str(pending_data.get("defender_formation_id", "") or ""),
            encounter_edge_id=str(pending_data.get("encounter_edge_id", "") or ""),
            encounter_progress_milli=_optional_strict_int(
                pending_data.get("encounter_progress_milli")
            ),
            encounter_pixel=_parse_encounter_pixel(pending_data.get("encounter_pixel")),
        )
        _validate_encounter_contract(pending)
    state = CampaignState(
        campaign_name=data["campaign_name"],
        turn_number=int(data.get("turn_number", 1)),
        current_faction=Faction(data.get("current_faction", "nato")),
        selected_faction=Faction(data.get("selected_faction", "nato")),
        difficulty=data.get("difficulty", "normal"),
        game_directory=data.get("game_directory", ""),
        profile_directory=data.get("profile_directory", ""),
        code_x_directory=data.get("code_x_directory", ""),
        catalog_signature=data.get("catalog_signature", ""),
        map_id=data.get("map_id", "custom"),
        map_metadata=dict(data.get("map_metadata", {})),
        factions=factions,
        alliances=alliances,
        formations=formations,
        strategic_formations=strategic_formations,
        commanders=commanders,
        research_nodes=research_nodes,
        unit_economy=unit_economy,
        provinces=provinces,
        battalions=battalions,
        pending_battle=pending,
        schema_version=max(1, int(data.get("schema_version", 1))),
    )
    from .force_migration import ensure_strategic_formations
    from .operational_capture import ensure_site_control_state
    from .operational_movement import ensure_move_orders
    from .operational_position import ensure_operational_positions
    from .operational_supply import refresh_operational_supply

    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    ensure_move_orders(state)
    ensure_site_control_state(state)
    refresh_operational_supply(state, consume_grace=False)
    state.validate()
    return state


def load_campaign(path: str | Path) -> CampaignState:
    source = Path(path)
    return campaign_from_dict(json.loads(source.read_text(encoding="utf-8-sig")))


def save_campaign(state: CampaignState, path: str | Path) -> Path:
    from .force_migration import ensure_strategic_formations
    from .operational_capture import ensure_site_control_state
    from .operational_movement import ensure_move_orders
    from .operational_position import ensure_operational_positions
    from .operational_supply import refresh_operational_supply
    from .strategic import ensure_strategic_layer

    ensure_strategic_layer(state)
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    ensure_move_orders(state)
    ensure_site_control_state(state)
    refresh_operational_supply(state, consume_grace=False)
    state.validate()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{destination.name}.",
        suffix=".tmp", dir=destination.parent, delete=False
    ) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    return destination


def _optional_strict_int(value: Any) -> int | None:
    # Missing key → None. Explicit empty string is malformed, not absent.
    if value is None:
        return None
    if value == "":
        raise ValueError("encounter_progress_milli must not be an empty string")
    from .operational_schema import require_strict_int

    return require_strict_int(value, name="encounter_progress_milli", minimum=0, maximum=1000)


def _strict_supply_bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be bool")
    return value


def _required_supply_int(
    value: Any, *, name: str, maximum: int | None = None
) -> int:
    from .operational_schema import require_strict_int

    return require_strict_int(value, name=name, minimum=0, maximum=maximum)


def _optional_supply_int(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    return _required_supply_int(value, name=name)


def _optional_supply_id(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string or null")
    return value


def _parse_encounter_pixel(value: Any) -> list[int]:
    # Missing / null → empty. Explicit "" is malformed.
    if value is None:
        return []
    if value == "":
        raise ValueError("encounter_pixel must not be an empty string")
    if value == []:
        return []
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("encounter_pixel must be a list of two strict ints")
    from .operational_schema import require_strict_int

    # Explicit empty strings inside the pair are malformed.
    if value[0] == "" or value[1] == "":
        raise ValueError("encounter_pixel coordinates must not be empty strings")
    return [
        require_strict_int(value[0], name="encounter_pixel[0]"),
        require_strict_int(value[1], name="encounter_pixel[1]"),
    ]


def _validate_encounter_contract(pending: PendingBattle) -> None:
    """Cross-field invariants for operational encounter serialization."""
    kind = str(pending.encounter_kind or "")
    node_id = str(pending.encounter_node_id or "")
    edge_id = str(pending.encounter_edge_id or "")
    progress = pending.encounter_progress_milli
    pixel = list(pending.encounter_pixel or [])
    atk = str(pending.attacker_formation_id or "")
    dfn = str(pending.defender_formation_id or "")

    edge_kinds = {"edge_cross", "edge_catchup"}
    node_kinds = {"node_contact", "node_simultaneous"}

    if not kind:
        # Legacy adjacency battle: operational location fields must be empty.
        if node_id or edge_id or progress is not None or pixel:
            raise ValueError(
                "legacy pending battle must not set operational encounter location fields"
            )
        return

    if kind in edge_kinds:
        if not edge_id.strip():
            raise ValueError(f"{kind} requires nonempty encounter_edge_id")
        if node_id:
            raise ValueError(f"{kind} requires empty encounter_node_id")
        if progress is None:
            raise ValueError(f"{kind} requires encounter_progress_milli")
        from .operational_schema import require_strict_int

        require_strict_int(progress, name="encounter_progress_milli", minimum=0, maximum=1000)
        if len(pixel) != 2:
            raise ValueError(f"{kind} requires encounter_pixel [x, y]")
        require_strict_int(pixel[0], name="encounter_pixel[0]")
        require_strict_int(pixel[1], name="encounter_pixel[1]")
        if not atk.strip() or not dfn.strip():
            raise ValueError(f"{kind} requires primary attacker and defender formation IDs")
        return

    if kind in node_kinds:
        if not node_id.strip():
            raise ValueError(f"{kind} requires nonempty encounter_node_id")
        if edge_id:
            raise ValueError(f"{kind} requires empty encounter_edge_id")
        if progress is not None:
            raise ValueError(f"{kind} requires empty encounter_progress_milli")
        if pixel:
            raise ValueError(f"{kind} requires empty encounter_pixel")
        if not atk.strip() or not dfn.strip():
            raise ValueError(f"{kind} requires primary attacker and defender formation IDs")
        return

    raise ValueError(f"unknown encounter_kind {kind!r}")
