from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import CampaignState, Faction


_GEOMETRY_KEYS = frozenset(
    {
        "border_segments",
        "edges",
        "geometry",
        "polygon_dataset",
        "ring",
        "triangles",
        "vertices",
    }
)

_EXPECTED_FORMATION_ACTORS = {
    "sf_deu_berlin": "deu",
    "sf_usa_tallinn": "usa",
    "sf_usa_riga": "usa",
    "sf_pol_vilnius": "pol",
    "sf_ukr_kyiv": "ukr",
    "sf_ukr_odesa": "ukr",
    "sf_ukr_kherson": "ukr",
    "sf_ukr_zaporizhzhia": "ukr",
    "sf_rus_rostov": "rus",
    "sf_rus_luhansk": "rus",
    "sf_rus_donetsk": "rus",
}

_EXPECTED_OPENING_PROVINCE_ACTORS = {
    "e3_0592": (Faction.NATO, "deu"),
    "e3_0513": (Faction.NATO, "usa"),
    "e3_0504": (Faction.NATO, "usa"),
    "e3_0442": (Faction.NATO, "pol"),
    "e3_1937": (Faction.UKRAINE, "ukr"),
    "e3_1749": (Faction.UKRAINE, "ukr"),
    "e3_1208": (Faction.UKRAINE, "ukr"),
    "e3_1962": (Faction.UKRAINE, "ukr"),
    "e3_2793": (Faction.RUSSIA, "rus"),
    "e3_2794": (Faction.RUSSIA, "rus"),
    "e3_3380": (Faction.RUSSIA, "rus"),
}


def is_earth3_p2_campaign(state: CampaignState) -> bool:
    metadata = state.map_metadata.get("earth3_bootstrap")
    return bool(
        state.map_id == "earth3_europe_mediterranean"
        and isinstance(metadata, dict)
        and metadata.get("bootstrap_id") == "earth3_v1_campaign_bootstrap"
    )


def earth3_p2_supply_disabled(state: CampaignState) -> bool:
    if not is_earth3_p2_campaign(state):
        return False
    metadata = state.map_metadata.get("earth3_bootstrap")
    return bool(
        isinstance(metadata, dict)
        and metadata.get("supply_connectivity_authority") == "none_until_p3"
    )


def validate_earth3_p2_integrity(state: CampaignState) -> None:
    """Validate immutable P1 authority and strict P2 actor ownership without mutation."""
    if not is_earth3_p2_campaign(state):
        return
    _validate_persisted_p1_authority(state)
    _validate_strict_actor_assignments(state)


def _validate_persisted_p1_authority(state: CampaignState) -> None:
    from .earth3_bootstrap import Earth3BootstrapError
    from .earth3_operational import (
        P3_AUTHORITY_METADATA_KEY,
        P3_GRAPH_RELATIVE_PATH,
    )
    from .earth3_campaign import (
        APPROVED_LAND_COUNT,
        APPROVED_PROVINCE_COUNT,
        APPROVED_SELECTABLE_COUNT,
        APPROVED_TOPOLOGY_EDGE_COUNT,
        APPROVED_WATER_COUNT,
        CAMPAIGN_DATASET_IDENTIFIER,
        CAMPAIGN_MANIFEST_IDENTIFIER,
        EARTH3_MAP_ID,
        EARTH3_SCENARIO_ID,
        PRODUCTION_AUTHORITY_IDENTIFIER,
        load_earth3_authority,
    )

    authority = load_earth3_authority()
    production = authority.production
    expected_metadata = {
        "scenario_id": EARTH3_SCENARIO_ID,
        "scenario_status": "production",
        "strategic_map_id": EARTH3_MAP_ID,
        "strategic_map_manifest": CAMPAIGN_MANIFEST_IDENTIFIER,
        "strategic_map_provenance": "earth3_production_authority",
        "manifest_identifier": CAMPAIGN_MANIFEST_IDENTIFIER,
        "manifest_sha256": authority.manifest_sha256,
        "dataset_identifier": CAMPAIGN_DATASET_IDENTIFIER,
        "dataset_sha256": authority.dataset_sha256,
        "embedded_dataset_sha256": authority.embedded_dataset_sha256,
        "geometry_sha256": authority.geometry_sha256,
        "production_asset_version": authority.production_asset_version,
        "production_authority_identifier": PRODUCTION_AUTHORITY_IDENTIFIER,
        "production_authority_schema_version": int(production["schema_version"]),
        "province_count": APPROVED_PROVINCE_COUNT,
        "land_count": APPROVED_LAND_COUNT,
        "water_count": APPROVED_WATER_COUNT,
        "selectable_province_count": APPROVED_SELECTABLE_COUNT,
        "topology_edge_count": APPROVED_TOPOLOGY_EDGE_COUNT,
        "included_ids_sha256": authority.included_ids_sha256,
        "stable_id_policy": str(production["stable_id_policy"]),
        "water_policy": str(production["water_policy"]["v1"]),
        "adjacency_authority": [
            f"{CAMPAIGN_DATASET_IDENTIFIER}#edges",
            f"{CAMPAIGN_DATASET_IDENTIFIER}#provinces[].neighbors",
        ],
        "approved_operational_assets": [],
        "operational_graph": (
            P3_GRAPH_RELATIVE_PATH
            if P3_AUTHORITY_METADATA_KEY in state.map_metadata
            else None
        ),
    }
    if state.map_id != EARTH3_MAP_ID:
        raise Earth3BootstrapError("Earth3 P2 persisted map identity mismatch")
    for key, expected in expected_metadata.items():
        if state.map_metadata.get(key) != expected:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted P1 authority mismatch: {key}"
            )
    _reject_geometry_shaped_state(state.map_metadata, path="map_metadata")

    authority_rows = {str(row["id"]): row for row in authority.provinces}
    if set(state.provinces) != set(authority_rows):
        raise Earth3BootstrapError("Earth3 P2 persisted province set mismatch")

    water_count = 0
    selectable_count = 0
    actual_edges: set[tuple[str, str]] = set()
    for province_id in sorted(authority_rows):
        row = authority_rows[province_id]
        province = state.provinces[province_id]
        expected_water = bool(row["is_water"])
        expected_neighbors = sorted(str(value) for value in row["neighbors"])
        expected_label = [float(row["label"][0]), float(row["label"][1])]
        expected_centroid = [float(row["centroid"][0]), float(row["centroid"][1])]
        expected_scalars = {
            "source_id": int(row["source_id"]),
            "terrain_id": int(row["terrain_id"]),
            "continent_id": int(row["continent_id"]),
            "is_water": expected_water,
            "selectable": not expected_water,
            "centroid": expected_centroid,
            "display_anchor_source": "earth3_label",
        }
        if province.province_id != province_id:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted province key mismatch: {province_id}"
            )
        if province.map_region != EARTH3_MAP_ID:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted province map region mismatch: {province_id}"
            )
        expected_terrain = "water" if expected_water else f"earth3_{int(row['terrain_id'])}"
        if province.terrain != expected_terrain:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted province terrain mismatch: {province_id}"
            )
        if [float(province.x), float(province.y)] != expected_label:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted province label mismatch: {province_id}"
            )
        if province.neighbors != expected_neighbors:
            raise Earth3BootstrapError(
                f"Earth3 P2 persisted province topology mismatch: {province_id}"
            )
        for key, expected in expected_scalars.items():
            if province.metadata.get(key) != expected:
                raise Earth3BootstrapError(
                    f"Earth3 P2 persisted province authority mismatch: {province_id}.{key}"
                )
        _reject_geometry_shaped_state(
            province.metadata,
            path=f"provinces.{province_id}.metadata",
        )
        water_count += int(expected_water)
        selectable_count += int(not expected_water)
        for neighbor_id in expected_neighbors:
            actual_edges.add(tuple(sorted((province_id, neighbor_id))))

    if len(state.provinces) != APPROVED_PROVINCE_COUNT:
        raise Earth3BootstrapError("Earth3 P2 persisted province count mismatch")
    if water_count != APPROVED_WATER_COUNT:
        raise Earth3BootstrapError("Earth3 P2 persisted water count mismatch")
    if selectable_count != APPROVED_SELECTABLE_COUNT:
        raise Earth3BootstrapError("Earth3 P2 persisted selectable count mismatch")
    if len(state.provinces) - water_count != APPROVED_LAND_COUNT:
        raise Earth3BootstrapError("Earth3 P2 persisted land count mismatch")
    if len(actual_edges) != APPROVED_TOPOLOGY_EDGE_COUNT:
        raise Earth3BootstrapError("Earth3 P2 persisted topology edge count mismatch")


def _validate_strict_actor_assignments(state: CampaignState) -> None:
    from .actor_economy import ACTOR_CONTENT_KEY
    from .earth3_bootstrap import Earth3BootstrapError
    from .strategic_actors import ACTOR_RUNTIME_KEY

    runtime = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if not isinstance(runtime, dict) or runtime.get("schema_version") != 1:
        raise Earth3BootstrapError("Earth3 P2 strategic actor runtime is missing")
    raw_actors = runtime.get("actors")
    if not isinstance(raw_actors, dict) or not raw_actors:
        raise Earth3BootstrapError("Earth3 P2 strategic actor rows are missing")

    actor_sides: dict[str, Faction] = {}
    for actor_id, raw_actor in raw_actors.items():
        if not isinstance(actor_id, str) or not actor_id:
            raise Earth3BootstrapError("Earth3 P2 actor key is invalid")
        if not isinstance(raw_actor, Mapping) or raw_actor.get("actor_id") != actor_id:
            raise Earth3BootstrapError(f"Earth3 P2 actor key mismatch: {actor_id}")
        try:
            actor_sides[actor_id] = Faction(str(raw_actor.get("tactical_side")))
        except ValueError as exc:
            raise Earth3BootstrapError(
                f"Earth3 P2 actor tactical side is invalid: {actor_id}"
            ) from exc

    selected_actor_id = runtime.get("selected_actor_id")
    current_actor_id = runtime.get("current_actor_id")
    if selected_actor_id not in actor_sides or current_actor_id not in actor_sides:
        raise Earth3BootstrapError("Earth3 P2 selected/current actor is invalid")
    if actor_sides[str(selected_actor_id)] != state.selected_faction:
        raise Earth3BootstrapError("Earth3 P2 selected actor tactical side mismatch")
    if actor_sides[str(current_actor_id)] != state.current_faction:
        raise Earth3BootstrapError("Earth3 P2 current actor tactical side mismatch")

    actor_content = state.map_metadata.get(ACTOR_CONTENT_KEY)
    if not isinstance(actor_content, dict):
        raise Earth3BootstrapError("Earth3 P2 actor content runtime is missing")
    content_actors = actor_content.get("actors")
    if not isinstance(content_actors, dict) or set(content_actors) != set(actor_sides):
        raise Earth3BootstrapError("Earth3 P2 actor content set mismatch")

    for force_id, force in state.strategic_formations.items():
        actor_id = force.actor_id
        if not actor_id or actor_id not in actor_sides:
            raise Earth3BootstrapError(
                f"Earth3 P2 strategic formation actor is missing or invalid: {force_id}"
            )
        if actor_sides[actor_id] != force.faction:
            raise Earth3BootstrapError(
                f"Earth3 P2 strategic formation actor side mismatch: {force_id}"
            )
        expected_actor = _EXPECTED_FORMATION_ACTORS.get(force_id)
        if expected_actor is not None and actor_id != expected_actor:
            raise Earth3BootstrapError(
                f"Earth3 P2 strategic formation actor assignment mismatch: {force_id}"
            )
        actor_units = content_actors[actor_id].get("units")
        if not isinstance(actor_units, dict):
            raise Earth3BootstrapError(
                f"Earth3 P2 actor unit catalog is missing: {actor_id}"
            )
        for battalion_id in force.battalion_ids:
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise Earth3BootstrapError(
                    f"Earth3 P2 formation references missing battalion: {force_id}:{battalion_id}"
                )
            if battalion.strategic_formation_id != force_id:
                raise Earth3BootstrapError(
                    f"Earth3 P2 battalion formation assignment mismatch: {battalion_id}"
                )
            if battalion.faction != force.faction:
                raise Earth3BootstrapError(
                    f"Earth3 P2 battalion faction does not match formation: {battalion_id}"
                )
            for entry in battalion.roster + battalion.authorized_roster:
                if entry.unit_name not in actor_units:
                    raise Earth3BootstrapError(
                        f"Earth3 P2 battalion roster crosses actor authority: "
                        f"{battalion_id}:{entry.unit_name}"
                    )

    for province_id, province in state.provinces.items():
        raw_actor_id = province.metadata.get("owner_actor_id")
        if province.owner == Faction.NEUTRAL:
            if raw_actor_id not in (None, ""):
                raise Earth3BootstrapError(
                    f"Earth3 P2 neutral province has an owner actor: {province_id}"
                )
            continue
        if not isinstance(raw_actor_id, str) or raw_actor_id not in actor_sides:
            raise Earth3BootstrapError(
                f"Earth3 P2 province owner actor is missing or invalid: {province_id}"
            )
        if actor_sides[raw_actor_id] != province.owner:
            raise Earth3BootstrapError(
                f"Earth3 P2 province owner actor side mismatch: {province_id}"
            )
        opening = _EXPECTED_OPENING_PROVINCE_ACTORS.get(province_id)
        if opening is not None and province.owner == opening[0] and raw_actor_id != opening[1]:
            raise Earth3BootstrapError(
                f"Earth3 P2 province actor assignment mismatch: {province_id}"
            )

    pool = actor_content.get("reinforcement_pool")
    if not isinstance(pool, list):
        raise Earth3BootstrapError("Earth3 P2 reinforcement pool must be an array")
    for entry in pool:
        if not isinstance(entry, Mapping):
            raise Earth3BootstrapError("Earth3 P2 reinforcement pool entry must be an object")
        actor_id = entry.get("actor_id")
        force_id = entry.get("strategic_formation_id")
        unit_name = entry.get("unit_name")
        if not isinstance(actor_id, str) or actor_id not in actor_sides:
            raise Earth3BootstrapError("Earth3 P2 reinforcement actor is invalid")
        if not isinstance(force_id, str) or force_id not in state.strategic_formations:
            raise Earth3BootstrapError("Earth3 P2 reinforcement formation is invalid")
        force = state.strategic_formations[force_id]
        if force.actor_id != actor_id:
            raise Earth3BootstrapError(
                f"Earth3 P2 reinforcement actor/formation mismatch: {force_id}"
            )
        units = content_actors[actor_id].get("units")
        if not isinstance(units, dict) or unit_name not in units:
            raise Earth3BootstrapError(
                f"Earth3 P2 reinforcement unit crosses actor authority: {actor_id}:{unit_name}"
            )


def _reject_geometry_shaped_state(value: Any, *, path: str) -> None:
    from .earth3_bootstrap import Earth3BootstrapError

    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _GEOMETRY_KEYS:
                raise Earth3BootstrapError(
                    f"Earth3 P2 persisted state contains geometry authority at {path}.{key}"
                )
            _reject_geometry_shaped_state(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_geometry_shaped_state(item, path=f"{path}[{index}]")
