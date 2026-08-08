from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from .diplomacy import are_allied
from .models import (
    BattleParticipant,
    CampaignState,
    Faction,
    PendingBattle,
    StrategicFormation,
)
from .operational_schema import FormationStance, PositionMode

ENCOUNTER_KIND_NODE_CONTACT = "node_contact"
ENCOUNTER_KIND_EDGE_CROSS = "edge_cross"
ENCOUNTER_KIND_EDGE_CATCHUP = "edge_catchup"
ENCOUNTER_KIND_NODE_SIMULTANEOUS = "node_simultaneous"
DEFAULT_MAX_FRIENDLY_PER_NODE = 3


def max_friendly_formations_per_node(state: CampaignState) -> int:
    from .operational_position import load_operational_graph_for_state

    graph = load_operational_graph_for_state(state)
    if graph is None:
        return DEFAULT_MAX_FRIENDLY_PER_NODE
    rules = graph.get("rules") or {}
    try:
        return max(1, int(rules.get("max_friendly_formations_per_node", DEFAULT_MAX_FRIENDLY_PER_NODE)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_FRIENDLY_PER_NODE


def formation_at_node_id(force: StrategicFormation) -> str | None:
    """S4 v1: only at_node positions occupy a node (on_edge does not)."""
    if force.position is None:
        return None
    if force.position.mode != PositionMode.AT_NODE.value:
        return None
    node_id = force.position.node_id
    if not node_id:
        return None
    return str(node_id)


def formations_at_node(
    state: CampaignState,
    node_id: str,
    *,
    excluding_formation_id: str | None = None,
) -> list[StrategicFormation]:
    found: list[StrategicFormation] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if excluding_formation_id and force.strategic_formation_id == excluding_formation_id:
            continue
        if formation_at_node_id(force) == node_id:
            found.append(force)
    return found


def formation_is_combat_capable(
    state: CampaignState,
    force: StrategicFormation,
) -> bool:
    """True when a formation has at least one non-destroyed battalion."""
    return any(
        battalion is not None and not battalion.is_destroyed
        for battalion_id in force.battalion_ids
        if (battalion := state.battalions.get(battalion_id)) is not None
    )


def combat_capable_formations_at_node(
    state: CampaignState,
    node_id: str,
    *,
    excluding_formation_id: str | None = None,
) -> list[StrategicFormation]:
    """Authoritative physical occupants for contact and node capacity."""
    return [
        force
        for force in formations_at_node(
            state,
            node_id,
            excluding_formation_id=excluding_formation_id,
        )
        if formation_is_combat_capable(state, force)
    ]


def enemy_formations_at_node(
    state: CampaignState,
    node_id: str,
    *,
    faction: Faction,
    excluding_formation_id: str | None = None,
) -> list[StrategicFormation]:
    enemies: list[StrategicFormation] = []
    for force in combat_capable_formations_at_node(
        state, node_id, excluding_formation_id=excluding_formation_id
    ):
        if force.faction == faction:
            continue
        if are_allied(state, faction, force.faction):
            continue
        enemies.append(force)
    return enemies


def friendly_formations_at_node(
    state: CampaignState,
    node_id: str,
    *,
    faction: Faction,
    excluding_formation_id: str | None = None,
) -> list[StrategicFormation]:
    friends: list[StrategicFormation] = []
    for force in combat_capable_formations_at_node(
        state, node_id, excluding_formation_id=excluding_formation_id
    ):
        if force.faction == faction or are_allied(state, faction, force.faction):
            friends.append(force)
    return friends


def node_is_contested(state: CampaignState, node_id: str) -> bool:
    present = combat_capable_formations_at_node(state, node_id)
    if len(present) < 2:
        return False
    factions = {force.faction for force in present}
    if len(factions) < 2:
        return False
    ordered = sorted(factions, key=lambda value: value.value)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if not are_allied(state, left, right):
                return True
    return False


def can_enter_node_friendly_stack(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
) -> bool:
    """True if force may occupy node without exceeding friendly stack cap."""
    if formation_at_node_id(force) == node_id:
        return True
    friends = friendly_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    )
    return len(friends) < max_friendly_formations_per_node(state)


def coalition_sides_at_node(
    state: CampaignState,
    node_id: str,
    *,
    seed_attacker: StrategicFormation,
) -> tuple[list[StrategicFormation], list[StrategicFormation]]:
    """Split all formations on a node into attacker coalition vs defender coalition."""
    present = combat_capable_formations_at_node(state, node_id)
    attackers: list[StrategicFormation] = []
    defenders: list[StrategicFormation] = []
    for force in present:
        if force.faction == seed_attacker.faction or are_allied(
            state, seed_attacker.faction, force.faction
        ):
            attackers.append(force)
        else:
            defenders.append(force)
    # Ensure seed attacker is included even if position not yet committed.
    if seed_attacker.strategic_formation_id not in {
        item.strategic_formation_id for item in attackers
    }:
        attackers.append(seed_attacker)
    attackers = sorted(attackers, key=lambda value: value.strategic_formation_id)
    defenders = sorted(defenders, key=lambda value: value.strategic_formation_id)
    return attackers, defenders


def choose_static_attacker_defender(
    state: CampaignState,
    left: StrategicFormation,
    right: StrategicFormation,
    *,
    node_province_id: str,
) -> tuple[StrategicFormation, StrategicFormation]:
    """Deterministic initiative for static co-location.

    Rule: province owner defends when exactly one side matches owner;
    otherwise lower strategic_formation_id attacks.
    """
    owner = Faction.NEUTRAL
    province = state.provinces.get(node_province_id)
    if province is not None:
        owner = province.owner
    left_owns = left.faction == owner or are_allied(state, left.faction, owner)
    right_owns = right.faction == owner or are_allied(state, right.faction, owner)
    if left_owns and not right_owns:
        return right, left
    if right_owns and not left_owns:
        return left, right
    if left.strategic_formation_id <= right.strategic_formation_id:
        return left, right
    return right, left


def try_create_node_contact_battle(
    state: CampaignState,
    seed_attacker: StrategicFormation,
    seed_defender: StrategicFormation,
    *,
    node_id: str,
    origin_province_id: str | None = None,
    retreat_origins: dict[str, str] | None = None,
    initiating_formation_ids: tuple[str, ...] = (),
) -> PendingBattle | None:
    """Create cooperative multi-formation node-contact battle.

    Includes every battalion from every friendly formation on the attacker side
    and every battalion from every hostile formation on the defender side at the node.
    """
    if state.pending_battle is not None:
        return None
    if not formation_is_combat_capable(state, seed_attacker):
        return None
    if not formation_is_combat_capable(state, seed_defender):
        return None

    attackers, defenders = coalition_sides_at_node(
        state, node_id, seed_attacker=seed_attacker
    )
    # Ensure seed defender side is represented.
    if seed_defender.strategic_formation_id not in {
        item.strategic_formation_id for item in defenders
    }:
        # Re-bucket if seed defender was misclassified (should not happen).
        if seed_defender.faction == seed_attacker.faction or are_allied(
            state, seed_attacker.faction, seed_defender.faction
        ):
            return None
        defenders.append(seed_defender)
        defenders = sorted(defenders, key=lambda value: value.strategic_formation_id)

    atk_parts = _participants_for_forces(state, attackers, stage="stage_1")
    def_parts = _participants_for_forces(state, defenders, stage="stage_2")
    if not atk_parts or not def_parts:
        # Empty/invalid roster: cannot open a battle (caller must not deadlock).
        return None

    # Mark first battalion of seed formations as primary when present.
    _mark_primary(atk_parts, seed_attacker, state)
    _mark_primary(def_parts, seed_defender, state)

    target_province = (
        seed_defender.province_id
        or seed_attacker.province_id
        or origin_province_id
        or ""
    )
    origin = origin_province_id or seed_attacker.province_id or target_province
    primary_atk = seed_attacker.strategic_formation_id
    primary_def = seed_defender.strategic_formation_id
    pending = PendingBattle(
        battle_id=f"goc-op-{state.turn_number}-{uuid.uuid4().hex[:10]}",
        origin_province_id=str(origin),
        target_province_id=str(target_province),
        attacker_faction=seed_attacker.faction,
        defender_faction=seed_defender.faction,
        attacking_participants=atk_parts,
        defending_participants=def_parts,
        player_faction=state.selected_faction,
        player_is_attacker=seed_attacker.faction == state.selected_faction,
        encounter_node_id=node_id,
        encounter_kind=ENCOUNTER_KIND_NODE_CONTACT,
        attacker_formation_id=primary_atk,
        defender_formation_id=primary_def,
    )
    state.pending_battle = pending
    from .operational_ambush import apply_pending_battle_ambush

    apply_pending_battle_ambush(
        state,
        initiating_formation_ids=initiating_formation_ids,
    )
    _interrupt_refit_participants(state, pending)
    if retreat_origins:
        from .operational_retreat import record_retreat_origin_node

        for formation_id, origin_node_id in sorted(retreat_origins.items()):
            record_retreat_origin_node(state, formation_id, origin_node_id)
    return pending


def inspect_node_entry(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
) -> dict[str, Any]:
    """Read-only node entry check (no battle creation).

    Friendly stack cap is enforced even when enemies occupy the node: a fourth
    friendly cannot enter a contested node that already has three friendlies.
    """
    enemies = enemy_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    )
    friends = friendly_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    )
    contested = node_is_contested(state, node_id) or bool(enemies)
    # Cap first: contested nodes still respect max friendly formations per node.
    if not can_enter_node_friendly_stack(state, force, node_id):
        return {
            "ok": False,
            "reason": "friendly_stack_cap",
            "battle_id": "",
            "contested": contested,
            "enemies": [item.strategic_formation_id for item in enemies],
            "friendlies": [item.strategic_formation_id for item in friends],
        }
    if enemies:
        return {
            "ok": False,
            "reason": "enemy_contact",
            "battle_id": "",
            "contested": True,
            "enemies": [item.strategic_formation_id for item in enemies],
            "friendlies": [item.strategic_formation_id for item in friends],
        }
    return {
        "ok": True,
        "reason": "",
        "battle_id": "",
        "contested": contested,
        "enemies": [],
        "friendlies": [item.strategic_formation_id for item in friends],
    }


def resolve_node_entry_contact(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
    *,
    create_battle: bool = True,
    origin_province_id: str | None = None,
    origin_node_id: str | None = None,
) -> dict[str, Any]:
    """After a formation arrives/occupies a node: stack check + cooperative contact battle."""
    if not formation_is_combat_capable(state, force):
        return {
            "ok": True,
            "reason": "",
            "battle_id": "",
            "contested": node_is_contested(state, node_id),
            "enemies": [],
            "friendlies": [],
        }
    result = inspect_node_entry(state, force, node_id)
    if result["reason"] != "enemy_contact" or not create_battle:
        return result
    enemies = enemy_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    )
    if not enemies:
        return result
    # Prefer province-owner as defender seed when possible.
    seed_def = enemies[0]
    province_id = force.province_id
    for enemy in enemies:
        province = state.provinces.get(enemy.province_id or "")
        if province is not None and (
            province.owner == enemy.faction
            or are_allied(state, enemy.faction, province.owner)
        ):
            seed_def = enemy
            break
    battle = try_create_node_contact_battle(
        state,
        force,
        seed_def,
        node_id=node_id,
        origin_province_id=origin_province_id or force.province_id,
        retreat_origins=(
            {force.strategic_formation_id: origin_node_id}
            if origin_node_id
            else None
        ),
        initiating_formation_ids=(force.strategic_formation_id,),
    )
    if battle is None:
        result["reason"] = "invalid_contact_roster"
        result["battle_id"] = ""
        return result
    result["battle_id"] = battle.battle_id
    result["enemies"] = [item.strategic_formation_id for item in enemies]
    # Expand friendlies to full attacker coalition after battle build.
    attackers, _defs = coalition_sides_at_node(state, node_id, seed_attacker=force)
    result["friendlies"] = [item.strategic_formation_id for item in attackers]
    return result


def try_create_edge_contact_battle(
    state: CampaignState,
    *,
    attacker: StrategicFormation,
    defender: StrategicFormation,
    edge_id: str,
    progress_canonical: int,
    encounter_kind: str,
    encounter_pixel: list[int],
    encounter_province_id: str,
    origin_province_id: str | None = None,
    participant_ids: tuple[str, ...] | None = None,
    initiating_formation_ids: tuple[str, ...] = (),
    edge: Any = None,
) -> PendingBattle | None:
    """Create cooperative edge-contact battle at a shared canonical progress.

    Only formations on ``edge_id`` at **exact** ``progress_canonical`` may join.
    Formations elsewhere on the same edge are excluded. Caller must stop/block
    every included participant first.
    """
    if state.pending_battle is not None:
        return None
    from .operational_interception import formation_canonical_on_edge
    from .operational_schema import require_strict_int

    progress = require_strict_int(
        progress_canonical, name="encounter_progress_milli", minimum=0, maximum=1000
    )
    if not isinstance(encounter_pixel, list) or len(encounter_pixel) != 2:
        raise ValueError("encounter_pixel must be [x, y] strict ints")
    pixel = [
        require_strict_int(encounter_pixel[0], name="encounter_pixel[0]"),
        require_strict_int(encounter_pixel[1], name="encounter_pixel[1]"),
    ]
    if edge is None:
        return None

    allowed = set(
        participant_ids
        or (attacker.strategic_formation_id, defender.strategic_formation_id)
    )
    attackers: list[StrategicFormation] = []
    defenders: list[StrategicFormation] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if force.strategic_formation_id not in allowed:
            continue
        canonical = formation_canonical_on_edge(force, edge=edge)
        if canonical is None or canonical != progress:
            continue
        if force.faction == attacker.faction or are_allied(
            state, attacker.faction, force.faction
        ):
            attackers.append(force)
        elif force.faction == defender.faction or are_allied(
            state, defender.faction, force.faction
        ):
            defenders.append(force)

    atk_parts = _participants_for_forces(state, attackers, stage="stage_1")
    def_parts = _participants_for_forces(state, defenders, stage="stage_2")
    if not atk_parts or not def_parts:
        return None
    _mark_primary(atk_parts, attacker, state)
    _mark_primary(def_parts, defender, state)
    pending = PendingBattle(
        battle_id=f"goc-op-{state.turn_number}-{uuid.uuid4().hex[:10]}",
        origin_province_id=str(
            origin_province_id or attacker.province_id or encounter_province_id
        ),
        target_province_id=str(encounter_province_id or defender.province_id),
        attacker_faction=attacker.faction,
        defender_faction=defender.faction,
        attacking_participants=atk_parts,
        defending_participants=def_parts,
        player_faction=state.selected_faction,
        player_is_attacker=attacker.faction == state.selected_faction,
        encounter_node_id="",
        encounter_kind=encounter_kind,
        attacker_formation_id=attacker.strategic_formation_id,
        defender_formation_id=defender.strategic_formation_id,
        encounter_edge_id=edge_id,
        encounter_progress_milli=progress,
        encounter_pixel=pixel,
    )
    state.pending_battle = pending
    from .operational_ambush import apply_pending_battle_ambush

    apply_pending_battle_ambush(
        state,
        initiating_formation_ids=initiating_formation_ids,
    )
    _interrupt_refit_participants(state, pending)
    return pending


def detect_static_node_contacts(state: CampaignState) -> list[str]:
    """Open one cooperative contact battle if enemies already share a node."""
    if state.pending_battle is not None:
        return []
    by_node: dict[str, list[StrategicFormation]] = {}
    for force in state.strategic_formations.values():
        node_id = formation_at_node_id(force)
        if node_id:
            by_node.setdefault(node_id, []).append(force)
    for node_id in sorted(by_node):
        present = sorted(
            combat_capable_formations_at_node(state, node_id),
            key=lambda value: value.strategic_formation_id,
        )
        for index, left in enumerate(present):
            for right in present[index + 1 :]:
                if left.faction == right.faction:
                    continue
                if are_allied(state, left.faction, right.faction):
                    continue
                province_id = left.province_id or right.province_id
                attacker, defender = choose_static_attacker_defender(
                    state, left, right, node_province_id=province_id
                )
                battle = try_create_node_contact_battle(
                    state,
                    attacker,
                    defender,
                    node_id=node_id,
                    origin_province_id=attacker.province_id,
                )
                if battle is not None:
                    attackers, defenders = coalition_sides_at_node(
                        state, node_id, seed_attacker=attacker
                    )
                    return [
                        item.strategic_formation_id for item in attackers + defenders
                    ]
                # Invalid roster: skip this pair, keep searching.
    return []


def _participants_for_forces(
    state: CampaignState,
    forces: list[StrategicFormation],
    *,
    stage: str,
) -> list[BattleParticipant]:
    parts: list[BattleParticipant] = []
    seen: set[str] = set()
    for force in forces:
        for battalion_id in force.battalion_ids:
            if battalion_id in seen:
                continue
            battalion = state.battalions.get(battalion_id)
            if battalion is None or battalion.is_destroyed:
                continue
            seen.add(battalion_id)
            parts.append(
                BattleParticipant(
                    battalion_id=battalion_id,
                    faction=battalion.faction,
                    stage=stage,
                    is_primary=False,
                )
            )
    return parts


def _interrupt_refit_participants(state: CampaignState, pending: PendingBattle) -> None:
    """End refit immediately for formations committed to hostile contact."""
    participant_ids = {
        participant.battalion_id
        for participant in pending.attacking_participants + pending.defending_participants
    }
    for force in state.strategic_formations.values():
        if not participant_ids.intersection(force.battalion_ids):
            continue
        order = force.move_order
        locked = order.locked_stance if order is not None else None
        if (
            force.stance != FormationStance.REFIT_RESUPPLY.value
            and locked != FormationStance.REFIT_RESUPPLY.value
        ):
            continue
        force.stance = FormationStance.OPERATIONAL.value
        if order is not None and locked == FormationStance.REFIT_RESUPPLY.value:
            force.move_order = replace(
                order, locked_stance=FormationStance.OPERATIONAL.value
            )


def _mark_primary(
    parts: list[BattleParticipant],
    seed: StrategicFormation,
    state: CampaignState,
) -> None:
    for battalion_id in seed.battalion_ids:
        for part in parts:
            if part.battalion_id == battalion_id:
                part.is_primary = True
                return
    if parts:
        parts[0].is_primary = True
