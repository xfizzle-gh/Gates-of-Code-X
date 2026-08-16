from __future__ import annotations

from gates_of_codex.scenario_2028_authority import (
    EXPECTED_SELECTABLE_PROVINCES,
    audit_controller_balance,
    load_province_authority,
)


def test_shipped_materialized_2028_authority_is_complete_and_authenticated() -> None:
    rows = load_province_authority()
    assert len(rows) == EXPECTED_SELECTABLE_PROVINCES == 3299
    assert all(str(row["country_label"]).strip() for row in rows)
    assert all(str(row["region_label"]).strip() for row in rows)

    belarus = [row for row in rows if row["sovereign_owner"] == "BLR"]
    assert belarus
    assert all(row["core_controller"] == "prc" for row in belarus)
    assert all(row["military_controller"] == "prc" for row in belarus)

    ukraine = [row for row in rows if row["sovereign_owner"] == "UKR"]
    assert ukraine
    assert all(row["front_reference_date"] == "2026-08-12" for row in ukraine)
    assert all(row["front_source"] == "deepstate_approximate" for row in ukraine)

    report = audit_controller_balance(rows)
    assert report.counts == {"nato": 2063, "ukr": 104, "rusa": 483, "prc": 53}
    assert report.deficits == {"ukr": 471, "rusa": 92, "prc": 522}
    assert report.surpluses == {"nato": 1286}
    assert report.within_target is False
