from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CampaignState, Faction
from .operational_movement import move_order_to_dict
from .operational_order_options import list_operational_move_options
from .operational_position import load_operational_graph_for_state
from .operational_schema import FormationOperationalPosition, PositionMode


NATIVE_CONTACT_PLAYER_FORMATION = "sf_pol_vilnius"
NATIVE_CONTACT_METADATA_KEY = "native_acceptance_contact_stage"


class NativeAcceptanceStageError(RuntimeError):
    """Raised when a native-acceptance shortcut cannot be staged safely."""


@dataclass(frozen=True, slots=True)
class NativeContactStage:
    formation_id: str
    staging_node_id: str
    staging_province_id: str
    target_formation_id: str
    target_node_id: str
    target_province_id: str
    edge_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "formation_id": self.formation_id,
            "staging_node_id": self.staging_node_id,
            "staging_province_id": self.staging_province_id,
            "target_formation_id": self.target_formation_id,
            "target_node_id": self.target_node_id,
            "target_province_id": self.target_province_id,
            "edge_id": self.edge_id,
        }


def stage_player_one_hop_from_rusa(
    state: CampaignState,
    *,
    formation_id: str = NATIVE_CONTACT_PLAYER_FORMATION,
) -> NativeContactStage:
    """Stage a fresh Earth3 native-test campaign one approved hop from RUSA.

    This is deliberately test-only state preparation. It does not add, remove,
    or alter operational graph nodes/edges. The staging node is selected from
    the penultimate node of a route already emitted by the production
    graph-native order projector to a currently occupied Russian node.
    """
    if str(state.map_metadata.get("scenario_id", "")) != "earth3_v1":
        raise NativeAcceptanceStageError("native contact staging requires earth3_v1")
    if state.turn_number != 1:
        raise NativeAcceptanceStageError("native contact staging requires a fresh turn-1 campaign")
    if state.pending_battle is not None:
        raise NativeAcceptanceStageError("native contact staging refuses a campaign with a pending battle")
    if state.selected_faction != Faction.NATO or state.current_faction != Faction.NATO:
        raise NativeAcceptanceStageError("native contact staging requires the opening NATO turn")

    player = state.strategic_formations.get(formation_id)
    if player is None:
        raise NativeAcceptanceStageError(f"missing player formation: {formation_id}")
    # The native shortcut targets one explicit strategic formation on the
    # selected human NATO side. `is_player_controlled` is battalion/bootstrap
    # presentation metadata and is not strategic movement authority; Vilnius is
    # intentionally movable by the NATO player even though that flag is false.
    if player.faction != Faction.NATO:
        raise NativeAcceptanceStageError(f"formation is not the intended player NATO force: {formation_id}")
    if player.move_order is not None:
        raise NativeAcceptanceStageError(
            f"formation already has a move order: {move_order_to_dict(player.move_order)}"
        )

    graph = load_operational_graph_for_state(state)
    if graph is None:
        raise NativeAcceptanceStageError("authenticated operational graph is unavailable")
    nodes_by_id = {
        str(node["node_id"]): node
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }

    russian_by_node: dict[str, str] = {}
    occupied_nodes: set[str] = set()
    for force in state.strategic_formations.values():
        position = force.position
        if position is None or position.mode != PositionMode.AT_NODE.value or not position.node_id:
            continue
        node_id = str(position.node_id)
        occupied_nodes.add(node_id)
        if force.faction == Faction.RUSSIA:
            russian_by_node[node_id] = force.strategic_formation_id

    if not russian_by_node:
        raise NativeAcceptanceStageError("no Russian formation is positioned on an operational node")

    candidates: list[dict[str, Any]] = []
    for row in list_operational_move_options(state, Faction.NATO):
        if row.get("formation_id") != formation_id:
            continue
        target_node_id = str(row.get("target_node_id", ""))
        path_node_ids = [str(value) for value in row.get("path_node_ids", [])]
        path_edge_ids = [str(value) for value in row.get("path_edge_ids", [])]
        if target_node_id not in russian_by_node:
            continue
        if len(path_node_ids) < 3 or len(path_edge_ids) < 2:
            # Already one hop away does not need this helper, but do not silently
            # rewrite an opening whose intended shortcut cannot be proven.
            continue
        staging_node_id = path_node_ids[-2]
        if staging_node_id in occupied_nodes:
            continue
        candidates.append(row)

    if not candidates:
        raise NativeAcceptanceStageError(
            "no free penultimate node exists on an approved player route to RUSA"
        )

    row = min(
        candidates,
        key=lambda value: (
            int(value.get("hop_count", 10**9)),
            str(value.get("target_node_id", "")),
        ),
    )
    path_node_ids = [str(value) for value in row["path_node_ids"]]
    path_edge_ids = [str(value) for value in row["path_edge_ids"]]
    staging_node_id = path_node_ids[-2]
    target_node_id = path_node_ids[-1]
    staging_node = nodes_by_id.get(staging_node_id)
    target_node = nodes_by_id.get(target_node_id)
    if staging_node is None or target_node is None:
        raise NativeAcceptanceStageError("approved route references a missing operational node")
    staging_province_id = str(staging_node.get("province_id", ""))
    target_province_id = str(target_node.get("province_id", ""))
    if not staging_province_id or not target_province_id:
        raise NativeAcceptanceStageError("approved route node is missing province authority")

    player.position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=staging_node_id,
    )
    player.province_id = staging_province_id
    player.movement_state = "at_anchor"
    player.move_order = None
    for battalion_id in player.battalion_ids:
        battalion = state.battalions.get(battalion_id)
        if battalion is None:
            raise NativeAcceptanceStageError(
                f"player formation references missing battalion: {battalion_id}"
            )
        battalion.province_id = staging_province_id

    staged = NativeContactStage(
        formation_id=formation_id,
        staging_node_id=staging_node_id,
        staging_province_id=staging_province_id,
        target_formation_id=russian_by_node[target_node_id],
        target_node_id=target_node_id,
        target_province_id=target_province_id,
        edge_id=path_edge_ids[-1],
    )
    state.map_metadata[NATIVE_CONTACT_METADATA_KEY] = staged.to_dict()

    # Re-project after relocation and require the live production surface to
    # expose the Russian contact as exactly one approved hop.
    one_hop = [
        option
        for option in list_operational_move_options(state, Faction.NATO)
        if option.get("formation_id") == formation_id
        and option.get("target_node_id") == target_node_id
    ]
    if len(one_hop) != 1:
        raise NativeAcceptanceStageError("staged Russian contact is not uniquely offered")
    option = one_hop[0]
    if int(option.get("hop_count", -1)) != 1:
        raise NativeAcceptanceStageError("staged Russian contact is not one hop away")
    if [str(value) for value in option.get("path_edge_ids", [])] != [staged.edge_id]:
        raise NativeAcceptanceStageError("staged contact does not use the expected approved edge")

    state.validate()
    return staged
