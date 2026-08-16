from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import CampaignState, Faction
from .scenario_2028_authority import (
    EXPECTED_SELECTABLE_PROVINCES,
    Scenario2028AuthorityError,
    audit_controller_balance,
    authority_hash,
    load_authority_document,
    load_province_authority,
    validate_province_rows,
)


CORE_2028_SCENARIO_ID = "ww3_2028_core"
CORE_2028_WORLD_AUTHORITY_ID = "earth3_ww3_2028_v1"
CORE_2028_ACTOR_CATALOG_ID = "core_2028"
CORE_2028_ACTOR_CATALOG_VERSION = "1"


def _build_earth3_base(**options: Any) -> CampaignState:
    from .earth3_bootstrap import build_earth3_v1_campaign
    from .earth3_operational import migrate_earth3_p2_to_p3
    from .operational_capture import ensure_site_control_state

    state = migrate_earth3_p2_to_p3(build_earth3_v1_campaign(**options))
    ensure_site_control_state(state)
    return state


def apply_core_2028_control(
    state: CampaignState,
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_count: int = EXPECTED_SELECTABLE_PROVINCES,
) -> CampaignState:
    materialized = [dict(row) for row in rows]
    validate_province_rows(materialized, expected_count=expected_count)

    by_id = state.provinces
    missing = sorted(str(row["province_id"]) for row in materialized if row["province_id"] not in by_id)
    if missing:
        sample = ",".join(missing[:5])
        raise Scenario2028AuthorityError(
            f"province_authority_unknown_earth3_ids:{len(missing)}:{sample}"
        )

    for row in materialized:
        province = by_id[str(row["province_id"])]
        core_controller = str(row["core_controller"])
        province.metadata["sovereign_owner"] = str(row["sovereign_owner"])
        province.metadata["military_controller"] = str(row["military_controller"])
        province.metadata["core_controller"] = core_controller
        province.metadata["controller_profile"] = "core"
        if row.get("front_reference_date"):
            province.metadata["front_reference_date"] = str(row["front_reference_date"])
        if row.get("front_source"):
            province.metadata["front_source"] = str(row["front_source"])
        province.owner = Faction(core_controller)

    balance = audit_controller_balance(materialized)
    authority = load_authority_document()
    state.map_metadata["ww3_2028_authority_id"] = CORE_2028_WORLD_AUTHORITY_ID
    state.map_metadata["ww3_2028_authority_sha256"] = authority_hash(authority)
    state.map_metadata["ww3_2028_controller_profile"] = "core"
    state.map_metadata["ww3_2028_controller_balance"] = {
        "counts": dict(balance.counts),
        "mean": balance.mean,
        "lower_bound": balance.lower_bound,
        "upper_bound": balance.upper_bound,
        "deficits": dict(balance.deficits),
        "surpluses": dict(balance.surpluses),
        "within_target": balance.within_target,
    }
    state.map_metadata["ww3_2028_prc_balance_shortfall"] = int(balance.deficits.get("prc", 0))
    return state


def build_ww3_2028_core_campaign(
    *,
    province_rows: Iterable[Mapping[str, Any]] | None = None,
    province_expected_count: int = EXPECTED_SELECTABLE_PROVINCES,
    **earth3_options: Any,
) -> CampaignState:
    from .neutral_nation_runtime_hooks import install_neutral_nation_runtime_hooks

    state = _build_earth3_base(**earth3_options)
    rows = list(province_rows) if province_rows is not None else load_province_authority()
    apply_core_2028_control(state, rows, expected_count=province_expected_count)
    install_neutral_nation_runtime_hooks()
    return state
