from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any, Mapping

from .earth3_operational import (
    P3_STARTING_FORMATION_IDS,
    validate_earth3_p3_campaign_extension,
)
from .models import (
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    CampaignState,
    Commander,
    CommanderStatus,
    Faction,
    ForceEchelon,
    Formation,
    StrategicFormation,
)
from .operational_schema import FormationOperationalPosition, PositionMode, stable_node_id


FIXTURE_SCENARIO_ID = "earth3_native_acceptance"
FIXTURE_AUTHORITY_KEY = "earth3_native_acceptance_fixture_authority"
FIXTURE_SCHEMA = "gates-of-codex.earth3-native-acceptance-fixture"
FIXTURE_SCHEMA_VERSION = 1
FIXTURE_MANIFEST_RESOURCE = "earth3_native_acceptance/fixture_manifest.json"
DEFAULT_SCENARIO_ID = "earth3_v1"

_MARKER_FIELDS = (
    "schema",
    "schema_version",
    "fixture_id",
    "scenario_id",
    "purpose",
    "production_scenario",
    "manifest_sha256",
)


class Earth3FixtureAuthorityError(RuntimeError):
    """Raised when native-acceptance fixture identity or dispatch is invalid."""


def earth3_requires_stack(scenario_id: str) -> bool:
    return scenario_id in {DEFAULT_SCENARIO_ID, FIXTURE_SCENARIO_ID}


def load_fixture_manifest() -> dict[str, Any]:
    resource = files("gates_of_codex").joinpath("data").joinpath(FIXTURE_MANIFEST_RESOURCE)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Earth3FixtureAuthorityError("fixture manifest must be an object")
    return payload


def fixture_manifest_sha256() -> str:
    return _canonical_sha256(load_fixture_manifest())


def authored_fixture_authority_marker() -> dict[str, Any]:
    manifest = load_fixture_manifest()
    return {
        "schema": str(manifest["schema"]),
        "schema_version": int(manifest["schema_version"]),
        "fixture_id": str(manifest["fixture_id"]),
        "scenario_id": str(manifest["scenario_id"]),
        "purpose": str(manifest["purpose"]),
        "production_scenario": bool(manifest["production_scenario"]),
        "manifest_sha256": fixture_manifest_sha256(),
    }


def validate_earth3_operational_authority(state: CampaignState) -> frozenset[str]:
    """Dispatch Earth3 operational validation without weakening production P3."""
    scenario_id = str(state.map_metadata.get("scenario_id", "") or "")
    marker = state.map_metadata.get(FIXTURE_AUTHORITY_KEY)
    if scenario_id == DEFAULT_SCENARIO_ID:
        if marker is not None:
            raise Earth3FixtureAuthorityError(
                "earth3_v1 cannot carry native-acceptance fixture authority"
            )
        return validate_earth3_p3_campaign_extension(state)
    if scenario_id == FIXTURE_SCENARIO_ID:
        if marker is None:
            raise Earth3FixtureAuthorityError(
                "earth3_native_acceptance requires exact fixture authority marker"
            )
        return validate_earth3_native_acceptance_fixture(state)
    if marker is not None:
        raise Earth3FixtureAuthorityError(
            f"fixture authority marker is illegal on scenario {scenario_id!r}"
        )
    return validate_earth3_p3_campaign_extension(state)


def validate_earth3_native_acceptance_fixture(state: CampaignState) -> frozenset[str]:
    from .earth3_operational import (
        EARTH3_MAP_ID,
        P3_AUTHORITY_METADATA_KEY,
        load_authenticated_p3_graph_for_state,
    )
    from .earth3_bootstrap import is_earth3_p2_campaign, load_earth3_bootstrap
    from .operational_position import _graph_indexes, _position_is_valid

    if str(state.map_metadata.get("scenario_id", "")) != FIXTURE_SCENARIO_ID:
        raise Earth3FixtureAuthorityError("fixture validator requires earth3_native_acceptance")
    _require_exact_marker(state)
    if state.map_id != EARTH3_MAP_ID or not is_earth3_p2_campaign(state):
        raise Earth3FixtureAuthorityError("fixture state must extend authenticated Earth3 P2/P3")
    if P3_AUTHORITY_METADATA_KEY not in state.map_metadata:
        raise Earth3FixtureAuthorityError("fixture state requires production P3 authority marker")

    graph = load_authenticated_p3_graph_for_state(state)
    if graph is None:
        raise Earth3FixtureAuthorityError("authenticated P3 graph is unavailable")
    node_ids, edge_ids, edges_by_id, nodes_by_id = _graph_indexes(graph)
    graph_provinces = frozenset(
        str(node.get("province_id") or "")
        for node in nodes_by_id.values()
        if node.get("province_id")
    )

    manifest = load_fixture_manifest()
    selected = manifest["selected_existing_formations"]
    required_existing = {
        str(selected["nato"]),
        str(selected["ukr"]),
        str(selected["rusa"]),
    }
    prc_spec = manifest["fixture_prc_formation"]
    prc_id = str(prc_spec["formation_id"])
    allowlist = set(P3_STARTING_FORMATION_IDS) | {prc_id}
    current_ids = set(state.strategic_formations)
    extra = current_ids - allowlist
    if extra:
        raise Earth3FixtureAuthorityError(
            "fixture formation identity is outside the authored allowlist: "
            + ", ".join(sorted(extra))
        )
    missing_required = required_existing - current_ids
    if missing_required:
        raise Earth3FixtureAuthorityError(
            "fixture is missing required existing formations: "
            + ", ".join(sorted(missing_required))
        )
    if prc_id not in current_ids:
        raise Earth3FixtureAuthorityError(f"fixture is missing PRC formation {prc_id}")

    bundle = load_earth3_bootstrap()
    expected_rows = {
        str(row["formation_id"]): row
        for row in bundle.documents["formations.json"]["formations"]
    }
    for formation_id in sorted(current_ids & P3_STARTING_FORMATION_IDS):
        force = state.strategic_formations[formation_id]
        expected = expected_rows[formation_id]
        if (
            force.actor_id != str(expected["actor_id"])
            or force.faction.value != str(expected["faction"])
            or force.template_formation_id != f"toe_{formation_id}"
        ):
            raise Earth3FixtureAuthorityError(
                f"fixture production formation identity mismatch: {formation_id}"
            )
        if not _position_is_valid(
            force.position,
            province_id=force.province_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
        ):
            raise Earth3FixtureAuthorityError(
                f"fixture production formation {formation_id} position is invalid"
            )

    _validate_prc_formation(
        state,
        spec=prc_spec,
        node_ids=node_ids,
        edge_ids=edge_ids,
        edges_by_id=edges_by_id,
        nodes_by_id=nodes_by_id,
        graph_provinces=graph_provinces,
    )
    _reject_production_ownership_mutation(state, bundle)
    return graph_provinces


def apply_earth3_native_acceptance_fixture(state: CampaignState) -> CampaignState:
    if str(state.map_metadata.get("scenario_id", "")) != FIXTURE_SCENARIO_ID:
        raise Earth3FixtureAuthorityError(
            "fixture overlay requires stamped earth3_native_acceptance identity"
        )
    if FIXTURE_AUTHORITY_KEY in state.map_metadata:
        raise Earth3FixtureAuthorityError("fixture overlay has already been applied")
    validate_earth3_p3_campaign_extension(state)
    manifest = load_fixture_manifest()
    spec = manifest["fixture_prc_formation"]
    _install_prc_formation(state, spec)
    state.map_metadata[FIXTURE_AUTHORITY_KEY] = authored_fixture_authority_marker()
    validate_earth3_native_acceptance_fixture(state)
    return state


def _require_exact_marker(state: CampaignState) -> dict[str, Any]:
    marker = state.map_metadata.get(FIXTURE_AUTHORITY_KEY)
    expected = authored_fixture_authority_marker()
    if not isinstance(marker, dict):
        raise Earth3FixtureAuthorityError("fixture authority marker must be an object")
    if set(marker) != set(_MARKER_FIELDS):
        raise Earth3FixtureAuthorityError("fixture authority marker fields are not exact")
    if marker != expected:
        raise Earth3FixtureAuthorityError("fixture authority marker does not match authored contract")
    return marker


def _validate_prc_formation(
    state: CampaignState,
    *,
    spec: Mapping[str, Any],
    node_ids: set[str],
    edge_ids: set[str],
    edges_by_id: dict[str, Any],
    nodes_by_id: Mapping[str, Any],
    graph_provinces: frozenset[str],
) -> None:
    from .operational_position import _position_is_valid

    formation_id = str(spec["formation_id"])
    force = state.strategic_formations[formation_id]
    expected_template = f"toe_{formation_id}"
    expected_battalion = f"bn_{formation_id}"
    expected_node = stable_node_id(str(spec["province_id"]))
    if force.actor_id != str(spec["actor_id"]) or force.faction.value != str(spec["faction"]):
        raise Earth3FixtureAuthorityError("fixture PRC actor/faction substitution is forbidden")
    if force.template_formation_id != expected_template:
        raise Earth3FixtureAuthorityError("fixture PRC template substitution is forbidden")
    if force.commander_id != str(spec["commander_id"]):
        raise Earth3FixtureAuthorityError("fixture PRC commander identity mismatch")
    if force.province_id != str(spec["province_id"]):
        raise Earth3FixtureAuthorityError("fixture PRC province is not the authored node province")
    if force.province_id not in graph_provinces:
        raise Earth3FixtureAuthorityError("fixture PRC province is outside authenticated P3 nodes")
    if expected_node not in node_ids:
        raise Earth3FixtureAuthorityError("fixture PRC node is not an authenticated P3 node")
    if not _position_is_valid(
        force.position,
        province_id=force.province_id,
        node_ids=node_ids,
        edge_ids=edge_ids,
        edges_by_id=edges_by_id,
        nodes_by_id=nodes_by_id,
    ):
        raise Earth3FixtureAuthorityError("fixture PRC position is not on the authenticated graph")
    if force.position is None or force.position.node_id != expected_node:
        raise Earth3FixtureAuthorityError("fixture PRC must occupy the authored P3 anchor")
    if expected_battalion not in state.battalions:
        raise Earth3FixtureAuthorityError("fixture PRC battalion is missing")
    battalion = state.battalions[expected_battalion]
    if battalion.faction != Faction.PRC or battalion.strategic_formation_id != formation_id:
        raise Earth3FixtureAuthorityError("fixture PRC battalion identity mismatch")
    if expected_template not in state.formations:
        raise Earth3FixtureAuthorityError("fixture PRC template is missing")
    template = state.formations[expected_template]
    if template.faction != Faction.PRC or template.nation != str(spec["nation"]):
        raise Earth3FixtureAuthorityError("fixture PRC template identity mismatch")
    commander_id = str(spec["commander_id"])
    if commander_id not in state.commanders:
        raise Earth3FixtureAuthorityError("fixture PRC commander is missing")
    commander = state.commanders[commander_id]
    if commander.assigned_strategic_formation_id != formation_id:
        raise Earth3FixtureAuthorityError("fixture PRC commander assignment mismatch")


def _reject_production_ownership_mutation(state: CampaignState, bundle: Any) -> None:
    expected = {
        str(row["province_id"]): (str(row["faction"]), str(row["actor_id"]))
        for row in bundle.documents["ownership.json"]["ownership"]
    }
    for province_id, (faction, actor_id) in expected.items():
        province = state.provinces[province_id]
        if province.owner.value != faction:
            raise Earth3FixtureAuthorityError(
                f"fixture mutated production ownership: {province_id}"
            )
        if str(province.metadata.get("owner_actor_id", "")) != actor_id:
            raise Earth3FixtureAuthorityError(
                f"fixture mutated production actor ownership: {province_id}"
            )
    authored = set(expected)
    for province in state.provinces.values():
        if province.province_id in authored:
            continue
        if province.owner != Faction.NEUTRAL:
            raise Earth3FixtureAuthorityError(
                f"fixture assigned ownership outside production footprint: {province.province_id}"
            )


def _install_prc_formation(state: CampaignState, spec: Mapping[str, Any]) -> None:
    from .earth3_bootstrap import _copy_roster

    formation_id = str(spec["formation_id"])
    if not formation_id.startswith("sf_fix_"):
        raise Earth3FixtureAuthorityError("fixture PRC formation ID must be debug-only")
    if formation_id in state.strategic_formations:
        raise Earth3FixtureAuthorityError("fixture PRC formation already exists")
    template_id = f"toe_{formation_id}"
    battalion_id = f"bn_{formation_id}"
    commander_id = str(spec["commander_id"])
    province_id = str(spec["province_id"])
    node_id = stable_node_id(province_id)
    roster = _copy_roster(_prc_roster_from_installed(state, list(spec["roster"])))
    state.formations[template_id] = Formation(
        formation_id=template_id,
        display_name=str(spec["display_name"]),
        faction=Faction.PRC,
        nation=str(spec["nation"]),
        deployment_zone="prc",
        preferred_categories=[str(row["category"]) for row in spec["roster"]],
        notes="Earth3 native-acceptance fixture-only PRC template",
    )
    state.battalions[battalion_id] = Battalion(
        battalion_id=battalion_id,
        faction=Faction.PRC,
        province_id=province_id,
        battalion_type=BattalionType.COMBINED_ARMS,
        roster=roster,
        authorized_roster=_copy_roster(roster),
        formation_id=template_id,
        strategic_formation_id=formation_id,
        is_player_controlled=False,
        movement_remaining=1,
        combat_actions_remaining=1,
        supply=100,
        condition=100,
    )
    state.strategic_formations[formation_id] = StrategicFormation(
        strategic_formation_id=formation_id,
        display_name=str(spec["display_name"]),
        faction=Faction.PRC,
        province_id=province_id,
        echelon=ForceEchelon.BRIGADE,
        commander_id=commander_id,
        battalion_ids=[battalion_id],
        template_formation_id=template_id,
        actor_id=str(spec["actor_id"]),
        is_player_controlled=False,
        movement_state="at_anchor",
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=node_id,
            edge_id=None,
            progress_milli=0,
            facing_node_id=None,
        ),
    )
    state.commanders[commander_id] = Commander(
        commander_id=commander_id,
        display_name="PRC Acceptance Brigade Commander",
        rank="Brigade Commander",
        assigned_strategic_formation_id=formation_id,
        status=CommanderStatus.ACTIVE,
        source="fixture_authored_fictional_role",
        provenance="src/gates_of_codex/data/earth3_native_acceptance/fixture_manifest.json",
    )


def _prc_roster_from_installed(
    state: CampaignState,
    requests: list[dict[str, Any]],
) -> list[BattalionRosterEntry]:
    content = state.map_metadata.get("actor_content_runtime")
    if not isinstance(content, Mapping):
        raise Earth3FixtureAuthorityError("fixture PRC roster requires installed actor content")
    actors = content.get("actors")
    if not isinstance(actors, Mapping) or "prc" not in actors:
        raise Earth3FixtureAuthorityError("installed actor content lacks PRC")
    actor = actors["prc"]
    if not isinstance(actor, Mapping):
        raise Earth3FixtureAuthorityError("installed PRC actor content is invalid")
    raw_units = actor.get("units")
    units: list[Mapping[str, Any]]
    if isinstance(raw_units, Mapping):
        units = [row for row in raw_units.values() if isinstance(row, Mapping)]
    elif isinstance(raw_units, list):
        units = [row for row in raw_units if isinstance(row, Mapping)]
    else:
        raise Earth3FixtureAuthorityError("installed PRC units are invalid")
    roster: list[BattalionRosterEntry] = []
    for request in requests:
        category = str(request["category"])
        candidates = [
            row
            for row in units
            if str(row.get("category", "")) == category
            and row.get("materializable", True)
        ]
        if not candidates:
            raise Earth3FixtureAuthorityError(f"PRC cannot materialize {category}")
        chosen = min(
            candidates,
            key=lambda row: (int(row.get("tier", 1)), str(row.get("unit_name", ""))),
        )
        roster.append(
            BattalionRosterEntry(
                unit_name=str(chosen["unit_name"]),
                quantity=int(request["quantity"]),
                category=category,
            )
        )
    return roster


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
