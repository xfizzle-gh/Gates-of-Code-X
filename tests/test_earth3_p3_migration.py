from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3_bootstrap import (
    Earth3BootstrapError,
    validate_earth3_bootstrap_campaign_state,
)
from gates_of_codex.earth3_operational import (
    P3_AUTHORITY_METADATA_KEY,
    P3_GRAPH_RELATIVE_PATH,
    P3_MIGRATION_METADATA_KEY,
    Earth3OperationalAuthorityError,
    authenticated_p3_state_metadata,
    migrate_earth3_p2_to_p3,
    validate_earth3_p3_campaign_extension,
)
from gates_of_codex.operational_position import ensure_operational_positions
from gates_of_codex.operational_schema import FormationOperationalPosition, PositionMode
from gates_of_codex.state_io import campaign_from_dict, load_campaign, save_campaign
from test_p2_earth3_campaign_bootstrap import _campaign


EXPECTED_STARTING_POSITIONS = {
    "sf_deu_berlin": "op-node-e3_0592-anchor",
    "sf_pol_vilnius": "op-node-e3_0442-anchor",
    "sf_rus_donetsk": "op-node-e3_3380-anchor",
    "sf_rus_luhansk": "op-node-e3_2794-anchor",
    "sf_rus_rostov": "op-node-e3_2793-anchor",
    "sf_ukr_kherson": "op-node-e3_1208-anchor",
    "sf_ukr_kyiv": "op-node-e3_1937-anchor",
    "sf_ukr_odesa": "op-node-e3_1749-anchor",
    "sf_ukr_zaporizhzhia": "op-node-e3_1962-anchor",
    "sf_usa_riga": "op-node-e3_0504-anchor",
    "sf_usa_tallinn": "op-node-e3_0513-anchor",
}


def _canonical_state(state) -> str:
    return json.dumps(
        state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _assert_exact_starting_positions(state) -> None:
    assert set(state.strategic_formations) == set(EXPECTED_STARTING_POSITIONS)
    for formation_id, expected_node_id in EXPECTED_STARTING_POSITIONS.items():
        position = state.strategic_formations[formation_id].position
        assert position is not None
        assert position.mode == PositionMode.AT_NODE.value
        assert position.node_id == expected_node_id
        assert position.edge_id is None
        assert position.progress_milli == 0
        assert position.facing_node_id is None


def test_raw_p2_migration_returns_a_validated_replacement_with_exact_anchors() -> None:
    source = _campaign()
    before = _canonical_state(source)

    migrated = migrate_earth3_p2_to_p3(source)

    assert migrated is not source
    assert _canonical_state(source) == before
    assert migrated.map_metadata[P3_AUTHORITY_METADATA_KEY] == (
        authenticated_p3_state_metadata()
    )
    assert migrated.map_metadata["operational_graph"] == P3_GRAPH_RELATIVE_PATH
    assert migrated.map_metadata["operational_maneuver_enabled"] is True
    assert P3_MIGRATION_METADATA_KEY in migrated.map_metadata
    unchanged_metadata = copy.deepcopy(migrated.map_metadata)
    for key in (
        P3_AUTHORITY_METADATA_KEY,
        P3_MIGRATION_METADATA_KEY,
        "operational_graph",
        "operational_maneuver_enabled",
    ):
        unchanged_metadata.pop(key)
    source_metadata = copy.deepcopy(source.map_metadata)
    source_metadata.pop("operational_graph")
    source_metadata.pop("operational_maneuver_enabled")
    assert unchanged_metadata == source_metadata
    _assert_exact_starting_positions(migrated)
    validate_earth3_p3_campaign_extension(migrated)
    migrated.validate()


def test_raw_p2_campaign_dict_load_migrates_after_authentication() -> None:
    source = _campaign()
    payload = source.to_dict()
    before = copy.deepcopy(payload)

    loaded = campaign_from_dict(payload)

    assert payload == before
    _assert_exact_starting_positions(loaded)
    validate_earth3_p3_campaign_extension(loaded)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            "missing_formation",
            "references missing strategic formation sf_usa_tallinn",
        ),
        (
            "missing_membership",
            "missing from strategic formation membership list",
        ),
    ],
)
def test_raw_p2_load_rejects_formation_damage_before_legacy_repair(
    mutation: str,
    error: str,
) -> None:
    payload = _campaign().to_dict()
    formation_id = "sf_usa_tallinn"
    battalion_id = payload["strategic_formations"][formation_id]["battalion_ids"][0]
    if mutation == "missing_formation":
        payload["strategic_formations"].pop(formation_id)
    else:
        payload["strategic_formations"][formation_id]["battalion_ids"].remove(
            battalion_id
        )
    before = copy.deepcopy(payload)

    with pytest.raises(ValueError, match=error):
        campaign_from_dict(payload)

    assert payload == before
    if mutation == "missing_formation":
        assert formation_id not in payload["strategic_formations"]
    else:
        assert battalion_id not in payload["strategic_formations"][formation_id][
            "battalion_ids"
        ]


def test_authentication_failure_happens_before_any_source_mutation() -> None:
    source = _campaign()
    before = _canonical_state(source)

    def reject_before_copy(*args, **kwargs):
        assert _canonical_state(source) == before
        raise Earth3OperationalAuthorityError("authentication denied")

    with patch(
        "gates_of_codex.earth3_operational.load_authenticated_p3_graph",
        side_effect=reject_before_copy,
    ), pytest.raises(Earth3OperationalAuthorityError, match="authentication denied"):
        migrate_earth3_p2_to_p3(source)

    assert _canonical_state(source) == before


def test_failed_raw_p2_file_load_never_rewrites_source_bytes(tmp_path: Path) -> None:
    path = tmp_path / "raw-p2.json"
    original = (json.dumps(_campaign().to_dict(), indent=2, ensure_ascii=False) + "\n").encode()
    path.write_bytes(original)

    with patch(
        "gates_of_codex.earth3_operational.load_authenticated_p3_graph",
        side_effect=Earth3OperationalAuthorityError("graph unavailable"),
    ), pytest.raises(Earth3OperationalAuthorityError, match="graph unavailable"):
        load_campaign(path)

    assert path.read_bytes() == original


def test_post_authentication_state_rejection_leaves_source_unchanged() -> None:
    source = _campaign()
    force = source.strategic_formations["sf_usa_tallinn"]
    force.province_id = "e3_0504"
    source.battalions[force.battalion_ids[0]].province_id = "e3_0504"
    before = _canonical_state(source)

    with pytest.raises(Earth3OperationalAuthorityError, match="province.*authority"):
        migrate_earth3_p2_to_p3(source)

    assert _canonical_state(source) == before


def test_migration_is_idempotent_and_does_not_reinitialize_mutable_p3_state() -> None:
    migrated = migrate_earth3_p2_to_p3(_campaign())
    formation = migrated.strategic_formations["sf_ukr_kyiv"]
    formation.position = FormationOperationalPosition(
        mode=PositionMode.ON_EDGE.value,
        node_id=None,
        edge_id=(
            "op-edge-corridor-op-node-e3_1937-anchor__"
            "op-node-e3_1938-anchor"
        ),
        progress_milli=375,
        facing_node_id="op-node-e3_1938-anchor",
    )
    before = _canonical_state(migrated)

    again = migrate_earth3_p2_to_p3(migrated)

    assert _canonical_state(migrated) == before
    assert _canonical_state(again) == before
    assert again.strategic_formations["sf_ukr_kyiv"].position.progress_milli == 375


def test_migration_and_save_bytes_are_independent_of_mapping_order(
    tmp_path: Path,
) -> None:
    first = _campaign()
    second = copy.deepcopy(first)
    second.strategic_formations = dict(reversed(list(second.strategic_formations.items())))
    second.battalions = dict(reversed(list(second.battalions.items())))
    second.commanders = dict(reversed(list(second.commanders.items())))

    first_migrated = migrate_earth3_p2_to_p3(first)
    second_migrated = migrate_earth3_p2_to_p3(second)
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    save_campaign(first_migrated, first_path)
    save_campaign(second_migrated, second_path)

    assert first_path.read_bytes() == second_path.read_bytes()


@pytest.mark.parametrize("mutation", ["missing", "unknown", "invalid"])
def test_authenticated_p3_positions_fail_closed_without_auto_repair(
    mutation: str,
) -> None:
    state = migrate_earth3_p2_to_p3(_campaign())
    force = state.strategic_formations["sf_usa_tallinn"]
    if mutation == "missing":
        force.position = None
    elif mutation == "unknown":
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id="op-node-e3_unknown-anchor",
            progress_milli=0,
        )
    else:
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=EXPECTED_STARTING_POSITIONS[force.strategic_formation_id],
            progress_milli=1,
        )
    before = _canonical_state(state)

    with pytest.raises(Earth3OperationalAuthorityError, match="position"):
        ensure_operational_positions(state)

    assert _canonical_state(state) == before


def test_authenticated_p3_duplicate_formation_position_record_is_rejected(
    tmp_path: Path,
) -> None:
    state = migrate_earth3_p2_to_p3(_campaign())
    payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
    marker = '"strategic_formations": {'
    formation_id = "sf_usa_tallinn"
    row = json.dumps(
        state.to_dict()["strategic_formations"][formation_id], ensure_ascii=False
    )
    payload = payload.replace(
        marker,
        marker + f'\n    "{formation_id}": {row},',
        1,
    )
    path = tmp_path / "duplicate-position.json"
    original = (payload + "\n").encode()
    path.write_bytes(original)

    with pytest.raises(ValueError, match="duplicate JSON key.*sf_usa_tallinn"):
        load_campaign(path)

    assert path.read_bytes() == original


def test_raw_p2_validator_remains_strict_without_p3_marker() -> None:
    state = _campaign()
    state.map_metadata["operational_graph"] = P3_GRAPH_RELATIVE_PATH
    state.map_metadata["operational_maneuver_enabled"] = True

    with pytest.raises(Earth3BootstrapError, match="P2 cannot enable"):
        validate_earth3_bootstrap_campaign_state(state)


def test_p3_migration_provenance_cannot_survive_marker_downgrade() -> None:
    state = migrate_earth3_p2_to_p3(_campaign())
    state.map_metadata.pop(P3_AUTHORITY_METADATA_KEY)
    state.map_metadata["operational_graph"] = None
    state.map_metadata["operational_maneuver_enabled"] = False

    with pytest.raises(Earth3BootstrapError, match="P3 migration.*marker"):
        validate_earth3_bootstrap_campaign_state(state)
