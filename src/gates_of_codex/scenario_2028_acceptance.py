from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .scenario import get_scenario
from .scenario_2028_authority import (
    EXPECTED_SELECTABLE_PROVINCES,
    Scenario2028AuthorityError,
    load_authority_document,
    load_province_authority,
    repository_root,
)


GATE_SCHEMA = "gates-of-codex.ww3-2028-acceptance-gate"
GATE_VERSION = 1
GATE_RELATIVE_PATH = Path("config/earth3/ww3_2028_acceptance_gate.json")
PROVINCE_AUTHORITY_RELATIVE_PATH = Path("config/earth3/ww3_2028_province_authority.json")


class Scenario2028AcceptanceError(ValueError):
    """The #225 cross-mode/native acceptance contract is inconsistent."""


P10_OVERMAP_CHECKS = frozenset(
    {
        "province_authority_materialized",
        "core_cross_mode_acceptance",
        "expanded_cross_mode_acceptance",
        "neutral_nation_persistence_acceptance",
        "owner_visual_accepted",
        "independent_review_accepted",
    }
)
P11_GOH_CHECKS = frozenset(
    {
        "core_goh_launch_accepted",
        "expanded_goh_launch_accepted",
        "goh_verify_import_round_trip_accepted",
    }
)


@dataclass(frozen=True, slots=True)
class AcceptanceGateStatus:
    status: str
    province_authority_materialized: bool
    production_authorized: bool
    p11_goh_authorized: bool
    blocker: str
    checks: dict[str, bool]
    p11_goh_checks: dict[str, bool]

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED" and not self.production_authorized


def gate_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / GATE_RELATIVE_PATH


def load_acceptance_gate(root: Path | None = None) -> dict[str, Any]:
    path = gate_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Scenario2028AcceptanceError(f"acceptance_gate_invalid:{path.as_posix()}") from exc
    if not isinstance(payload, dict):
        raise Scenario2028AcceptanceError("acceptance_gate_must_be_object")
    validate_acceptance_gate(payload, root=root)
    return payload


def validate_acceptance_gate(
    payload: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> AcceptanceGateStatus:
    if payload.get("schema") != GATE_SCHEMA:
        raise Scenario2028AcceptanceError("acceptance_gate_schema_mismatch")
    if payload.get("version") != GATE_VERSION:
        raise Scenario2028AcceptanceError("acceptance_gate_version_mismatch")
    if payload.get("scenario_authority_id") != "earth3_ww3_2028_v1":
        raise Scenario2028AcceptanceError("acceptance_gate_authority_mismatch")

    required = payload.get("required_before_production")
    if not isinstance(required, Mapping):
        raise Scenario2028AcceptanceError("acceptance_gate_required_checks_missing")
    if set(required) != P10_OVERMAP_CHECKS:
        raise Scenario2028AcceptanceError("acceptance_gate_check_set_mismatch")
    checks: dict[str, bool] = {}
    for name in sorted(P10_OVERMAP_CHECKS):
        value = required.get(name)
        if not isinstance(value, bool):
            raise Scenario2028AcceptanceError(f"acceptance_gate_check_not_bool:{name}")
        checks[name] = value

    p11_required = payload.get("required_before_p11_goh")
    if not isinstance(p11_required, Mapping):
        raise Scenario2028AcceptanceError("acceptance_gate_p11_goh_checks_missing")
    if set(p11_required) != P11_GOH_CHECKS:
        raise Scenario2028AcceptanceError("acceptance_gate_p11_goh_check_set_mismatch")
    p11_goh_checks: dict[str, bool] = {}
    for name in sorted(P11_GOH_CHECKS):
        value = p11_required.get(name)
        if not isinstance(value, bool):
            raise Scenario2028AcceptanceError(f"acceptance_gate_p11_goh_check_not_bool:{name}")
        p11_goh_checks[name] = value

    rules = payload.get("rules")
    if not isinstance(rules, Mapping):
        raise Scenario2028AcceptanceError("acceptance_gate_rules_missing")
    for name in (
        "missing_authority_fails_closed",
        "ci_may_validate_blocked_state_without_claiming_native_acceptance",
        "native_acceptance_requires_materialized_province_authority",
        "owner_acceptance_cannot_be_inferred_from_ci",
        "independent_review_cannot_be_self_declared",
        "goh_launch_verify_import_are_p11_after_p10_autoresolve",
    ):
        if rules.get(name) is not True:
            raise Scenario2028AcceptanceError(f"acceptance_gate_rule_required:{name}")

    repo = root or repository_root()
    authority_path = repo / PROVINCE_AUTHORITY_RELATIVE_PATH
    materialized = authority_path.exists()
    if materialized:
        try:
            rows = load_province_authority(repo)
        except Scenario2028AuthorityError as exc:
            raise Scenario2028AcceptanceError(
                f"acceptance_gate_materialized_authority_invalid:{exc}"
            ) from exc
        if len(rows) != EXPECTED_SELECTABLE_PROVINCES:
            raise Scenario2028AcceptanceError("acceptance_gate_province_count_mismatch")

    if checks["province_authority_materialized"] != materialized:
        raise Scenario2028AcceptanceError(
            "acceptance_gate_materialization_flag_does_not_match_repository"
        )

    production_authorized = payload.get("production_authorized")
    if not isinstance(production_authorized, bool):
        raise Scenario2028AcceptanceError("acceptance_gate_production_authorized_not_bool")
    all_required = all(checks.values())
    if production_authorized != all_required:
        raise Scenario2028AcceptanceError("acceptance_gate_authorization_not_derived_from_checks")

    p11_goh_authorized = payload.get("p11_goh_authorized")
    if not isinstance(p11_goh_authorized, bool):
        raise Scenario2028AcceptanceError("acceptance_gate_p11_goh_authorized_not_bool")
    if p11_goh_authorized != all(p11_goh_checks.values()):
        raise Scenario2028AcceptanceError(
            "acceptance_gate_p11_goh_authorization_not_derived_from_checks"
        )
    if p11_goh_authorized and not production_authorized:
        raise Scenario2028AcceptanceError("acceptance_gate_p11_goh_before_p10_overmap")

    expected_status = "READY" if production_authorized else "BLOCKED"
    if payload.get("status") != expected_status:
        raise Scenario2028AcceptanceError("acceptance_gate_status_mismatch")
    blocker = str(payload.get("blocker") or "").strip()
    if not production_authorized and not blocker:
        raise Scenario2028AcceptanceError("acceptance_gate_blocker_required")
    if not materialized:
        for name in (
            "core_cross_mode_acceptance",
            "expanded_cross_mode_acceptance",
            "neutral_nation_persistence_acceptance",
            "owner_visual_accepted",
            "independent_review_accepted",
        ):
            if checks[name]:
                raise Scenario2028AcceptanceError(
                    f"acceptance_gate_claim_before_authority:{name}"
                )
        for name, value in p11_goh_checks.items():
            if value:
                raise Scenario2028AcceptanceError(
                    f"acceptance_gate_p11_claim_before_authority:{name}"
                )

    return AcceptanceGateStatus(
        status=expected_status,
        province_authority_materialized=materialized,
        production_authorized=production_authorized,
        p11_goh_authorized=p11_goh_authorized,
        blocker=blocker,
        checks=checks,
        p11_goh_checks=p11_goh_checks,
    )


def cross_mode_contract_report() -> dict[str, Any]:
    """Return deterministic contract evidence that is valid before native unblock.

    This report proves Core and Expanded share the same world authority while
    retaining distinct actor catalogs. It deliberately does not mark any gate
    acceptance bit true. Passing CI is evidence about the implementation, not a
    substitute for owner visual acceptance or independent review. GoH launch,
    Verify/Import, and tactical round-trip are P11 after the P10 Auto-Resolve
    exit and are not a P10 production requirement.
    """

    authority = load_authority_document()
    core = get_scenario("ww3_2028_core")
    expanded = get_scenario("ww3_2028_expanded")
    gate = validate_acceptance_gate(load_acceptance_gate())
    return {
        "authority_id": authority["authority_id"],
        "scenario_year": authority["scenario_year"],
        "core": {
            "scenario_id": core.scenario_id,
            "world_authority_id": core.shared_world_authority_id,
            "actor_catalog_id": core.actor_catalog_id,
        },
        "expanded": {
            "scenario_id": expanded.scenario_id,
            "world_authority_id": expanded.shared_world_authority_id,
            "actor_catalog_id": expanded.actor_catalog_id,
        },
        "shared_world_authority": (
            core.shared_world_authority_id
            == expanded.shared_world_authority_id
            == authority["authority_id"]
        ),
        "distinct_actor_catalogs": core.actor_catalog_id != expanded.actor_catalog_id,
        "acceptance_gate": {
            "status": gate.status,
            "province_authority_materialized": gate.province_authority_materialized,
            "production_authorized": gate.production_authorized,
            "p11_goh_authorized": gate.p11_goh_authorized,
            "blocker": gate.blocker,
        },
    }
