from __future__ import annotations

from .models import CampaignState


RETREAT_ORIGIN_NODES_KEY = "operational_edge_retreat_nodes"


def record_retreat_origin_node(
    state: CampaignState,
    formation_id: str,
    node_id: str,
) -> None:
    """Persist one formation's exact last legal node for battle finalization."""
    force_id = str(formation_id).strip()
    origin_node_id = str(node_id).strip()
    if not force_id or not origin_node_id:
        return
    store = state.map_metadata.setdefault(RETREAT_ORIGIN_NODES_KEY, {})
    if isinstance(store, dict):
        store[force_id] = origin_node_id


def retreat_origin_node(state: CampaignState, formation_id: str) -> str | None:
    """Return a formation's recorded pre-contact node, if one is persisted."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if not isinstance(store, dict):
        return None
    value = str(store.get(str(formation_id)) or "").strip()
    return value or None


def clear_retreat_origin_node(state: CampaignState, formation_id: str) -> None:
    """Clear one formation's recorded pre-contact node without inventing state."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if isinstance(store, dict):
        store.pop(str(formation_id), None)


def clear_retreat_origin_nodes(state: CampaignState) -> None:
    """Clear all recorded pre-contact nodes after atomic battle finalization."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if isinstance(store, dict):
        store.clear()
