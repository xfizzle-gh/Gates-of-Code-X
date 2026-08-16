from __future__ import annotations

import copy

import pytest

from gates_of_codex.earth3_campaign import load_earth3_authority
from gates_of_codex.scenario_2028_authority import (
    CORE_POWERS,
    EXPECTED_SELECTABLE_PROVINCES,
    UKRAINE_FRONT_METHOD,
    Scenario2028AuthorityError,
    audit_controller_balance,
    load_authority_document,
    validate_authority_document,
    validate_province_rows,
)


def _row(
    province_id: str,
    sovereign_owner: str,
    controller: str,
    *,
    expanded_controller: str | None = None,
    neighbors: list[str] | None = None,
    hostile_neighbors: list[str] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "province_id": province_id,
        "sovereign_owner": sovereign_owner,
        "military_controller": controller,
        "core_controller": controller,
        "expanded_controller": expanded_controller or controller,
        "garrison_actor": None,
        "neighbors": neighbors or [],
        "hostile_neighbors": hostile_neighbors or [],
        "metrics": {"graph_degree": len(neighbors or []), "selectable_degree": len(neighbors or [])},
        "strategic": {"is_chokepoint": False, "strategic_value": 0},
    }
    if sovereign_owner == "UKR":
        row.update(
            {
                "front_reference_date": "2026-08-12",
                "front_source": "deepstate_approximate",
                "front_method": UKRAINE_FRONT_METHOD,
            }
        )
    return row


def _rows() -> list[dict[str, object]]:
    return [
        _row("e3_0001", "BLR", "prc"),
        _row("e3_0002", "UKR", "ukr"),
        _row("e3_0003", "POL", "nato"),
        _row("e3_0004", "RUS", "rusa"),
    ]


def test_shipped_2028_authority_document_is_valid_and_locked() -> None:
    authority = load_authority_document()
    assert authority["scenario_year"] == 2028
    assert authority["earth3_dataset"]["selectable_province_count"] == EXPECTED_SELECTABLE_PROVINCES
    assert EXPECTED_SELECTABLE_PROVINCES == 3299
    assert tuple(authority["profiles"]["core"]["campaign_powers"]) == CORE_POWERS
    assert authority["belarus"]["mandatory_military_controller"] == "prc"
    assert authority["belarus"]["sovereignty_transfer"] is False
    assert authority["neutral_nations"]["automatic_coalition_entry"] is False
    assert authority["ukraine_front"]["reference_date"] == "2026-08-12"
    mapping = authority["ukraine_front"]["whole_province_mapping_rule"]
    assert mapping["method"] == UKRAINE_FRONT_METHOD
    assert mapping["geometry_input_required"] is False
    assert mapping["owner_visual_audit_required"] is True


def test_authority_rejects_any_fifth_core_campaign_power() -> None:
    authority = load_authority_document()
    mutated = copy.deepcopy(authority)
    mutated["profiles"]["core"]["campaign_powers"].append("blr")
    with pytest.raises(Scenario2028AuthorityError, match="core_campaign_powers_mismatch"):
        validate_authority_document(mutated)


def test_authority_rejects_belarus_sovereignty_transfer() -> None:
    authority = load_authority_document()
    mutated = copy.deepcopy(authority)
    mutated["belarus"]["sovereignty_transfer"] = True
    with pytest.raises(Scenario2028AuthorityError, match="belarus_sovereignty_transfer_forbidden"):
        validate_authority_document(mutated)


def test_province_rows_require_prc_control_for_every_belarus_row() -> None:
    rows = _rows()
    rows[0]["military_controller"] = "rusa"
    rows[0]["core_controller"] = "rusa"
    with pytest.raises(Scenario2028AuthorityError, match="belarus_prc_control_required"):
        validate_province_rows(rows, expected_count=len(rows))


def test_province_rows_require_dated_approximate_front_provenance_for_ukraine() -> None:
    rows = _rows()
    rows[1].pop("front_method")
    with pytest.raises(Scenario2028AuthorityError, match="ukraine_front_method_required"):
        validate_province_rows(rows, expected_count=len(rows))


def test_province_rows_fail_closed_on_missing_coverage() -> None:
    with pytest.raises(Scenario2028AuthorityError, match="province_authority_count_mismatch"):
        validate_province_rows(_rows(), expected_count=EXPECTED_SELECTABLE_PROVINCES)


def test_province_rows_reject_existing_nonselectable_id_substitution() -> None:
    earth3 = load_earth3_authority()
    land_ids = [str(row["id"]) for row in earth3.provinces if not bool(row["is_water"])]
    water_id = next(str(row["id"]) for row in earth3.provinces if bool(row["is_water"]))
    expected = set(land_ids[:4])
    rows = [
        _row(land_ids[0], "BLR", "prc"),
        _row(land_ids[1], "UKR", "ukr"),
        _row(land_ids[2], "POL", "nato"),
        _row(water_id, "RUS", "rusa"),
    ]
    with pytest.raises(Scenario2028AuthorityError, match="province_authority_id_set_mismatch"):
        validate_province_rows(
            rows,
            expected_count=4,
            expected_province_ids=expected,
        )


def test_province_rows_authenticate_adjacency_graph_metrics_and_hostility() -> None:
    canonical = {
        "e3_0001": {"neighbors": ["e3_0002"], "is_water": False},
        "e3_0002": {"neighbors": ["e3_0001", "e3_0003"], "is_water": False},
        "e3_0003": {"neighbors": ["e3_0002", "e3_0004"], "is_water": False},
        "e3_0004": {"neighbors": ["e3_0003"], "is_water": False},
    }
    rows = [
        _row("e3_0001", "BLR", "prc", neighbors=["e3_0002"], hostile_neighbors=["e3_0002"]),
        _row(
            "e3_0002",
            "UKR",
            "ukr",
            neighbors=["e3_0001", "e3_0003"],
            hostile_neighbors=["e3_0001", "e3_0003"],
        ),
        _row(
            "e3_0003",
            "RUS",
            "rusa",
            neighbors=["e3_0002", "e3_0004"],
            hostile_neighbors=["e3_0002"],
        ),
        _row("e3_0004", "RUS", "rusa", neighbors=["e3_0003"]),
    ]
    for row in rows:
        degree = len(row["neighbors"])
        row["metrics"] = {"graph_degree": degree, "selectable_degree": degree}
    rows[1]["strategic"] = {"is_chokepoint": True, "strategic_value": 1}
    rows[2]["strategic"] = {"is_chokepoint": True, "strategic_value": 1}

    validate_province_rows(
        rows,
        expected_count=4,
        expected_province_ids=set(canonical),
        canonical_rows=canonical,
    )

    mutated = copy.deepcopy(rows)
    mutated[0]["metrics"]["selectable_degree"] = 99
    with pytest.raises(Scenario2028AuthorityError, match="province_selectable_degree_mismatch"):
        validate_province_rows(
            mutated,
            expected_count=4,
            expected_province_ids=set(canonical),
            canonical_rows=canonical,
        )


def test_controller_balance_reports_prc_deficit_without_mutating_rows() -> None:
    rows = _rows()
    rows.extend(
        _row(f"nato-{index}", "POL", "nato")
        for index in range(5)
    )
    before = copy.deepcopy(rows)
    report = audit_controller_balance(rows)
    assert report.counts == {"nato": 6, "ukr": 1, "rusa": 1, "prc": 1}
    assert report.deficits["prc"] > 0
    assert rows == before
