from __future__ import annotations

import uuid
from typing import Any

from .diplomacy import are_allied
from .models import (
    BattleParticipant,
    CampaignState,
    Faction,
    PendingBattle,
    StrategicFormation,
)
from .operational_schema import PositionMode

ENCOUNTER_KIND_NODE_CONTACT = "node_contact"
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


def enemy_formations_at_node(
    state: CampaignState,
    node_id: str,
    *,
    faction: Faction,
    excluding_formation_id: str | None = None,
) -> list[StrategicFormation]:
    enemies: list[StrategicFormation] = []
    for force in formations_at_node(
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
    for force in formations_at_node(
        state, node_id, excluding_formation_id=excluding_formation_id
    ):
        if force.faction == faction or are_allied(state, faction, force.faction):
            friends.append(force)
    return friends


def node_is_contested(state: CampaignState, node_id: str) -> bool:
    present = formations_at_node(state, node_id)
    if len(present) < 2:
        return False
    factions = {force.faction for force in present}
    if len(factions) < 2:
        return False
    # Contested if any pair is not allied.
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
    # Already on this node counts as occupying (re-entry ok).
    if formation_at_node_id(force) == node_id:
        return True
    friends = friendly_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    )
    return len(friends) < max_friendly_formations_per_node(state)


def try_create_node_contact_battle(
    state: CampaignState,
    attacker: StrategicFormation,
    defender: StrategicFormation,
    *,
    node_id: str,
) -> PendingBattle | None:
    """Create pending battle for enemy node contact. No-op if battle already pending."""
    if state.pending_battle is not None:
        return None
    atk_bn = _primary_battalion(state, attacker)
    def_bn = _primary_battalion(state, defender)
    if atk_bn is None or def_bn is None:
        return None
    province_id = attacker.province_id or defender.province_id
    pending = PendingBattle(
        battle_id=f"goc-op-{state.turn_number}-{uuid.uuid4().hex[:10]}",
        origin_province_id=attacker.province_id or province_id,
        target_province_id=province_id,
        attacker_faction=attacker.faction,
        defender_faction=defender.faction,
        attacking_participants=[
            BattleParticipant(atk_bn.battalion_id, attacker.faction, "stage_1", True)
        ],
        defending_participants=[
            BattleParticipant(def_bn.battalion_id, defender.faction, "stage_2", True)
        ],
        player_faction=state.selected_faction,
        player_is_attacker=attacker.faction == state.selected_faction,
        encounter_node_id=node_id,
        encounter_kind=ENCOUNTER_KIND_NODE_CONTACT,
        attacker_formation_id=attacker.strategic_formation_id,
        defender_formation_id=defender.strategic_formation_id,
    )
    state.pending_battle = pending
    return pending


def inspect_node_entry(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
) -> dict[str, Any]:
    """Read-only node entry check (no battle creation)."""
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
    if enemies:
        return {
            "ok": False,
            "reason": "enemy_contact",
            "battle_id": "",
            "contested": True,
            "enemies": [item.strategic_formation_id for item in enemies],
            "friendlies": [item.strategic_formation_id for item in friends],
        }
    if not can_enter_node_friendly_stack(state, force, node_id):
        return {
            "ok": False,
            "reason": "friendly_stack_cap",
            "battle_id": "",
            "contested": contested,
            "enemies": [],
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
) -> dict[str, Any]:
    """After a formation arrives/occupies a node: stack check + enemy contact.

    Returns keys: ok, reason, battle_id, contested, enemies, friendlies.
    """
    result = inspect_node_entry(state, force, node_id)
    if result["reason"] == "enemy_contact" and create_battle:
        enemies = enemy_formations_at_node(
            state,
            node_id,
            faction=force.faction,
            excluding_formation_id=force.strategic_formation_id,
        )
        if enemies:
            battle = try_create_node_contact_battle(
                state, force, enemies[0], node_id=node_id
            )
            result["battle_id"] = battle.battle_id if battle else (
                state.pending_battle.battle_id if state.pending_battle else ""
            )
    return result


def detect_static_node_contacts(state: CampaignState) -> list[str]:
    """If enemies already share a node and no battle pending, open contact battles.

    Processes nodes in sorted order; creates at most one pending battle (engine limit).
    Returns formation ids involved in detected contacts.
    """
    if state.pending_battle is not None:
        return []
    by_node: dict[str, list[StrategicFormation]] = {}
    for force in state.strategic_formations.values():
        node_id = formation_at_node_id(force)
        if node_id:
            by_node.setdefault(node_id, []).append(force)
    involved: list[str] = []
    for node_id in sorted(by_node):
        present = sorted(by_node[node_id], key=lambda value: value.strategic_formation_id)
        for index, left in enumerate(present):
            for right in present[index + 1 :]:
                if left.faction == right.faction:
                    continue
                if are_allied(state, left.faction, right.faction):
                    continue
                battle = try_create_node_contact_battle(
                    state, left, right, node_id=node_id
                )
                if battle is not None:
                    involved.extend(
                        [left.strategic_formation_id, right.strategic_formation_id]
                    )
                    return involved
    return involved


def _primary_battalion(state: CampaignState, force: StrategicFormation):
    for battalion_id in force.battalion_ids:
        battalion = state.battalions.get(battalion_id)
        if battalion is not None:
            return battalion
    return None
