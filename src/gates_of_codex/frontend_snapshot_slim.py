from __future__ import annotations

"""Consumer-search inventory and subtractive slim for frontend snapshots.

Slice 3 of #266. Presentation-only. Campaign.json remains the only authority.
Fields stay if any Godot script under ``godot/scripts/**`` or any production
Python reader of a ``gates-of-codex.frontend`` snapshot reads them.
"""

from typing import Any


# Top-level keys the live Godot path or a production snapshot reader consumes.
FRONTEND_CONSUMED_TOP_LEVEL = frozenset(
    {
        "schema",
        "schema_version",
        "application",
        "campaign",
        "strategic_map",
        "bounds",
        "factions",
        "alliances",
        "objectives",
        "provinces",
        "edges",
        "formations",
        "strategic_formations",
        "battalions",
        "battalion_stacks",
        "stack_presentations",
        "battalion_presentations",
        "strategic_formation_presentations",
        "pending_battle",
        "front_options",
        "operational_orders",
        "control",
        "province_names",
        "fog_of_war",
        "last_known_contacts",
        "acting_actor",
    }
)

# Proven unused: no Godot consumer and no production snapshot reader.
FRONTEND_OMITTED_TOP_LEVEL = frozenset({"research", "commanders"})

# Live Godot + snapshot contract readers of province rows.
FRONTEND_CONSUMED_PROVINCE_FIELDS = frozenset(
    {
        "id",
        "display_name",
        "name_is_human_readable",
        "owner",
        "x",
        "y",
        "resource_yield",
        "fortification",
        "infrastructure",
        "construction_options",
        "site_upgrade",
        "occupied_by",
        "occupied_by_battalions",
        "sovereign_owner",
        "military_controller",
        "controller_profile",
    }
)

# Static Earth3 / layout payload. Godot already loads centroid/is_water/source
# geometry from on-disk ``polygon_dataset``; no script reads these snapshot keys.
FRONTEND_OMITTED_PROVINCE_FIELDS = frozenset(
    {
        "metadata",
        "terrain",
        "map_region",
        "id_color",
        "name_source",
        "supply_source_for",
    }
)

# main.gd construction buttons: available, building, next_level, cost.
FRONTEND_CONSUMED_CONSTRUCTION_OPTION_FIELDS = frozenset(
    {"building", "next_level", "cost", "available"}
)

FRONTEND_OMITTED_CONSTRUCTION_OPTION_FIELDS = frozenset(
    {"blocked_reasons", "level", "max_level"}
)

# Godot + existing frontend-snapshot tests. Not an automatic drop of the object.
FRONTEND_CONSUMED_MAP_METADATA_KEYS = frozenset(
    {
        "province_names",
        "debug_show_placeholder_units",
        "operational_graph",
        "strategic_map_id",
        "marker_layout",
        "modern_control_profile",
        "scenario_id",
        "scenario_display_name",
        "scenario_selection",
        "ww3_2028_controller_profile",
    }
)

# Godot uses battalion_presentations.cards, not raw TOE rows.
FRONTEND_OMITTED_BATTALION_FIELDS = frozenset({"roster", "authorized_roster"})

# Campaign keys the live path or Slice 2 consumed-field parity still reads.
FRONTEND_CONSUMED_CAMPAIGN_FIELDS = frozenset(
    {
        "name",
        "turn_number",
        "current_faction",
        "selected_faction",
        "difficulty",
        "map_id",
        "map_metadata",
        "catalog_signature",
        "outcome",
        "operational_clock",
        "site_control",
        "calendar",
        "length_preset",
        "turn_cap",
        "hold_weeks",
        "continue_playing",
        "concluded",
        "momentum",
        "victory_model",
        "thresholds",
    }
)


def slim_construction_options(options: Any) -> list[dict[str, Any]]:
    """Keep only construction keys Godot actually paints as buttons."""

    rows: list[dict[str, Any]] = []
    if not isinstance(options, list):
        return rows
    for item in options:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                key: item[key]
                for key in FRONTEND_CONSUMED_CONSTRUCTION_OPTION_FIELDS
                if key in item
            }
        )
    return rows


def supported_frontend_schema_versions() -> frozenset[int]:
    from .frontend import FRONTEND_PREVIOUS_SCHEMA_VERSION, FRONTEND_SCHEMA_VERSION

    return frozenset({FRONTEND_PREVIOUS_SCHEMA_VERSION, FRONTEND_SCHEMA_VERSION})


def require_slimmable_frontend_schema(snapshot: dict[str, Any]) -> int:
    from .frontend import FRONTEND_SCHEMA_VERSION

    has_schema = "schema" in snapshot
    has_version = "schema_version" in snapshot
    if not has_schema and not has_version:
        return FRONTEND_SCHEMA_VERSION
    if has_schema and str(snapshot.get("schema", "")) != "gates-of-codex.frontend":
        raise ValueError(f"unsupported frontend snapshot schema: {snapshot.get('schema')!r}")
    raw = snapshot.get("schema_version")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"unsupported frontend snapshot schema_version: {raw!r}")
    if raw not in supported_frontend_schema_versions():
        raise ValueError(f"unsupported frontend snapshot schema_version: {raw}")
    return raw


def slim_unused_frontend_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Omit only fields the consumer search proved unused. Do not invent keys."""

    if not isinstance(snapshot, dict):
        raise ValueError("Frontend snapshot is not an object.")
    from .frontend import FRONTEND_SCHEMA_VERSION

    require_slimmable_frontend_schema(snapshot)
    slimmed = {
        key: value
        for key, value in snapshot.items()
        if key not in FRONTEND_OMITTED_TOP_LEVEL
    }
    slimmed["schema_version"] = FRONTEND_SCHEMA_VERSION
    campaign = slimmed.get("campaign")
    if isinstance(campaign, dict):
        metadata = campaign.get("map_metadata")
        if isinstance(metadata, dict):
            campaign = dict(campaign)
            campaign["map_metadata"] = {
                key: value
                for key, value in metadata.items()
                if key in FRONTEND_CONSUMED_MAP_METADATA_KEYS
            }
            slimmed["campaign"] = campaign
    provinces = slimmed.get("provinces")
    if isinstance(provinces, list):
        slimmed["provinces"] = [_slim_province_row(row) for row in provinces]
    battalions = slimmed.get("battalions")
    if isinstance(battalions, list):
        slimmed["battalions"] = [_slim_battalion_row(row) for row in battalions]
    return slimmed


def _slim_province_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    slimmed = {
        key: value
        for key, value in row.items()
        if key not in FRONTEND_OMITTED_PROVINCE_FIELDS
    }
    if "construction_options" in slimmed:
        slimmed["construction_options"] = slim_construction_options(
            slimmed.get("construction_options")
        )
    return slimmed


def _slim_battalion_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    return {
        key: value
        for key, value in row.items()
        if key not in FRONTEND_OMITTED_BATTALION_FIELDS
    }
