from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import BattalionRosterEntry, CampaignState, Faction


RUNTIME_KEY = "neutral_nation_runtime"
RUNTIME_SCHEMA_VERSION = 1
HOSTILE_METADATA_KEY = "neutral_hostile_to_actor_ids"
MOBILIZED_METADATA_KEY = "neutral_garrison_mobilized_against"


class NeutralNationRuntimeError(ValueError):
    """Fail-closed neutral nation hostility or recovery state error."""


def _is_ww3_2028(state: CampaignState) -> bool:
    scenario_id = str(state.map_metadata.get("scenario_id") or "")
    if scenario_id.startswith("ww3_2028_"):
        return True
    profile = state.map_metadata.get("scenario_profile")
    return isinstance(profile, Mapping) and str(profile.get("scenario_id") or "").startswith(
        "ww3_2028_"
    )


def _runtime(state: CampaignState, *, create: bool = True) -> dict[str, Any]:
    raw = state.map_metadata.get(RUNTIME_KEY)
    if raw is None:
        if not create:
            return {}
        raw = {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "nations": {},
            "garrisons": {},
        }
        state.map_metadata[RUNTIME_KEY] = raw
    if not isinstance(raw, dict):
        raise NeutralNationRuntimeError("neutral_nation_runtime_must_be_object")
    if raw.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise NeutralNationRuntimeError("neutral_nation_runtime_schema_version_unsupported")
    if set(raw) - {"schema_version", "nations", "garrisons"}:
        raise NeutralNationRuntimeError("neutral_nation_runtime_unknown_fields")
    for key in ("nations", "garrisons"):
        if not isinstance(raw.get(key), dict):
            raise NeutralNationRuntimeError(f"neutral_nation_runtime_{key}_must_be_object")
    return raw


def _sovereign_owner(state: CampaignState, province_id: str) -> str:
    province = state.provinces.get(province_id)
    if province is None:
        raise NeutralNationRuntimeError(f"neutral_nation_unknown_province:{province_id}")
    value = province.metadata.get("sovereign_owner")
    if not isinstance(value, str) or not value.strip():
        raise NeutralNationRuntimeError(
            f"neutral_nation_sovereign_owner_required:{province_id}"
        )
    return value.strip()


def _is_neutral_controlled(province: Any) -> bool:
    core = str(province.metadata.get("core_controller") or "")
    military = str(province.metadata.get("military_controller") or "")
    return province.owner == Faction.NEUTRAL or core == "neutral" or military == "neutral"


def declare_neutral_nation_hostile(
    state: CampaignState,
    province_id: str,
    attacker_id: str,
) -> dict[str, Any] | None:
    """Make an attacked sovereign neutral nation hostile only to ``attacker_id``.

    The operation is intentionally a no-op outside the 2028 scenario family.
    It never changes sovereignty, tactical faction ownership, alliances, or any
    other attacker's relationship. The hostility is projected onto every
    province of that sovereign nation so subsequent combat/diplomacy checks and
    untouched garrisons can consume the nation-wide mobilization immediately.
    """

    if not _is_ww3_2028(state):
        return None
    attacker = str(attacker_id or "").strip()
    if not attacker:
        raise NeutralNationRuntimeError("neutral_nation_attacker_id_required")
    province = state.provinces.get(province_id)
    if province is None:
        raise NeutralNationRuntimeError(f"neutral_nation_unknown_province:{province_id}")
    if not _is_neutral_controlled(province):
        return None

    sovereign = _sovereign_owner(state, province_id)
    nation_provinces = sorted(
        candidate.province_id
        for candidate in state.provinces.values()
        if str(candidate.metadata.get("sovereign_owner") or "") == sovereign
    )
    if not nation_provinces:
        raise NeutralNationRuntimeError(f"neutral_nation_has_no_provinces:{sovereign}")

    runtime = _runtime(state)
    nations = runtime["nations"]
    record = dict(nations.get(sovereign) or {})
    hostile_to = sorted({*(record.get("hostile_to") or []), attacker})
    first_turns = dict(record.get("first_hostile_turn_by_attacker") or {})
    first_turns.setdefault(attacker, int(state.turn_number))

    mobilized_province_ids: list[str] = []
    for candidate_id in nation_provinces:
        candidate = state.provinces[candidate_id]
        candidate.metadata[HOSTILE_METADATA_KEY] = list(hostile_to)
        if _is_neutral_controlled(candidate):
            candidate.metadata[MOBILIZED_METADATA_KEY] = list(hostile_to)
            mobilized_province_ids.append(candidate_id)

    record.update(
        {
            "sovereign_owner": sovereign,
            "province_ids": nation_provinces,
            "hostile_to": hostile_to,
            "first_hostile_turn_by_attacker": dict(sorted(first_turns.items())),
            "mobilized_province_ids": mobilized_province_ids,
        }
    )
    nations[sovereign] = record
    runtime["nations"] = dict(sorted(nations.items()))
    state.map_metadata[RUNTIME_KEY] = runtime
    return record


def nation_is_hostile_to(
    state: CampaignState,
    sovereign_owner: str,
    attacker_id: str,
) -> bool:
    runtime = _runtime(state, create=False)
    if not runtime:
        return False
    record = runtime["nations"].get(str(sovereign_owner))
    return isinstance(record, Mapping) and str(attacker_id) in record.get("hostile_to", [])


def province_is_hostile_to(
    state: CampaignState,
    province_id: str,
    attacker_id: str,
) -> bool:
    province = state.provinces.get(province_id)
    if province is None:
        raise NeutralNationRuntimeError(f"neutral_nation_unknown_province:{province_id}")
    projected = province.metadata.get(HOSTILE_METADATA_KEY)
    if isinstance(projected, list) and str(attacker_id) in projected:
        return True
    return nation_is_hostile_to(state, _sovereign_owner(state, province_id), attacker_id)


def garrison_is_mobilized_against(
    state: CampaignState,
    province_id: str,
    attacker_id: str,
) -> bool:
    province = state.provinces.get(province_id)
    if province is None:
        raise NeutralNationRuntimeError(f"neutral_nation_unknown_province:{province_id}")
    projected = province.metadata.get(MOBILIZED_METADATA_KEY)
    return isinstance(projected, list) and str(attacker_id) in projected


def capture_garrison_battle_state(state: CampaignState, province_id: str) -> None:
    """Capture authored capacity after #48 persists a neutral battle result."""

    if not _is_ww3_2028(state):
        return
    from .neutral_garrison import RUNTIME_KEY as GARRISON_RUNTIME_KEY

    garrison_runtime = state.map_metadata.get(GARRISON_RUNTIME_KEY)
    if not isinstance(garrison_runtime, Mapping):
        return
    provinces = garrison_runtime.get("provinces")
    if not isinstance(provinces, Mapping):
        return
    record = provinces.get(province_id)
    if not isinstance(record, Mapping):
        return
    selection = record.get("selection")
    if not isinstance(selection, Mapping):
        return
    units = selection.get("units")
    if not isinstance(units, list) or not units:
        return

    capacity: list[dict[str, Any]] = []
    for raw in units:
        if not isinstance(raw, Mapping):
            raise NeutralNationRuntimeError("neutral_garrison_capacity_unit_invalid")
        unit_name = str(raw.get("unit_name") or "").strip()
        quantity = raw.get("quantity")
        if not unit_name or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise NeutralNationRuntimeError("neutral_garrison_capacity_unit_invalid")
        capacity.append(
            {
                "unit_name": unit_name,
                "quantity": quantity,
                "category": str(raw.get("category") or "unknown"),
            }
        )

    runtime = _runtime(state)
    garrisons = runtime["garrisons"]
    entry = dict(garrisons.get(province_id) or {})
    entry.update(
        {
            "province_id": province_id,
            "capacity_roster": capacity,
            "recovery_per_unit_per_turn": 1,
            "last_recovery_turn": int(state.turn_number),
        }
    )
    garrisons[province_id] = entry
    runtime["garrisons"] = dict(sorted(garrisons.items()))
    state.map_metadata[RUNTIME_KEY] = runtime


def advance_neutral_garrison_recovery(state: CampaignState) -> int:
    """Recover persistent neutral losses toward authored capacity once per turn."""

    if not _is_ww3_2028(state):
        return 0
    runtime = _runtime(state, create=False)
    if not runtime:
        return 0

    from .neutral_garrison import RUNTIME_KEY as GARRISON_RUNTIME_KEY, garrison_battalion_id

    garrison_runtime = state.map_metadata.get(GARRISON_RUNTIME_KEY)
    if not isinstance(garrison_runtime, dict):
        return 0
    provinces = garrison_runtime.get("provinces")
    if not isinstance(provinces, dict):
        return 0

    changed = 0
    for province_id, recovery in sorted(runtime["garrisons"].items()):
        if not isinstance(recovery, dict):
            raise NeutralNationRuntimeError("neutral_garrison_recovery_record_invalid")
        last_turn = int(recovery.get("last_recovery_turn", state.turn_number))
        elapsed = int(state.turn_number) - last_turn
        if elapsed <= 0:
            continue
        capacity = recovery.get("capacity_roster")
        if not isinstance(capacity, list) or not capacity:
            continue
        record = provinces.get(province_id)
        if not isinstance(record, dict):
            continue
        current_rows = record.get("roster")
        if not isinstance(current_rows, list):
            current_rows = []
        current = {
            str(row.get("unit_name")): int(row.get("quantity", 0))
            for row in current_rows
            if isinstance(row, Mapping) and str(row.get("unit_name") or "")
        }
        rate = int(recovery.get("recovery_per_unit_per_turn", 1))
        if rate < 1:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_rate_invalid")

        new_roster: list[dict[str, Any]] = []
        total = 0
        capacity_total = 0
        for cap in capacity:
            if not isinstance(cap, Mapping):
                raise NeutralNationRuntimeError("neutral_garrison_capacity_unit_invalid")
            unit_name = str(cap["unit_name"])
            maximum = int(cap["quantity"])
            capacity_total += maximum
            quantity = min(maximum, max(0, current.get(unit_name, 0)) + rate * elapsed)
            total += quantity
            if quantity:
                new_roster.append(
                    {
                        "unit_name": unit_name,
                        "quantity": quantity,
                        "category": str(cap.get("category") or "unknown"),
                    }
                )

        record["roster"] = new_roster
        record["defeated"] = total == 0
        readiness = 0 if capacity_total <= 0 else round(1000 * total / capacity_total)
        record["readiness_milli"] = max(0, min(1000, readiness))
        if total:
            record["condition"] = max(10, min(100, max(1, readiness) // 10))
        provinces[province_id] = record
        recovery["last_recovery_turn"] = int(state.turn_number)

        battalion = state.battalions.get(garrison_battalion_id(province_id))
        if battalion is not None:
            battalion.roster = [
                BattalionRosterEntry(
                    unit_name=str(row["unit_name"]),
                    quantity=int(row["quantity"]),
                    category=str(row["category"]),
                )
                for row in new_roster
            ]
            if total:
                battalion.condition = int(record["condition"])
        changed += 1

    garrison_runtime["provinces"] = dict(sorted(provinces.items()))
    state.map_metadata[GARRISON_RUNTIME_KEY] = garrison_runtime
    state.map_metadata[RUNTIME_KEY] = runtime
    return changed


def _authenticated_capacity_from_selection(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    units = selection.get("units")
    if not isinstance(units, list) or not units:
        raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_units_required")
    capacity: list[dict[str, Any]] = []
    for raw in units:
        if not isinstance(raw, Mapping):
            raise NeutralNationRuntimeError("neutral_garrison_capacity_unit_invalid")
        unit_name = str(raw.get("unit_name") or "").strip()
        quantity = raw.get("quantity")
        category = str(raw.get("category") or "unknown")
        if not unit_name or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise NeutralNationRuntimeError("neutral_garrison_capacity_unit_invalid")
        capacity.append(
            {
                "unit_name": unit_name,
                "quantity": quantity,
                "category": category,
            }
        )
    return capacity


def validate_neutral_nation_runtime(state: CampaignState) -> None:
    raw = state.map_metadata.get(RUNTIME_KEY)
    if raw is None:
        return
    runtime = _runtime(state, create=False)
    for sovereign, record in runtime["nations"].items():
        if not isinstance(record, Mapping):
            raise NeutralNationRuntimeError("neutral_nation_record_invalid")
        if record.get("sovereign_owner") != sovereign:
            raise NeutralNationRuntimeError("neutral_nation_sovereign_key_mismatch")
        province_ids = record.get("province_ids")
        hostile_to = record.get("hostile_to")
        mobilized = record.get("mobilized_province_ids")
        if not isinstance(province_ids, list) or not province_ids:
            raise NeutralNationRuntimeError("neutral_nation_province_ids_required")
        if province_ids != sorted(set(province_ids)):
            raise NeutralNationRuntimeError("neutral_nation_province_ids_not_canonical")
        if not isinstance(hostile_to, list) or hostile_to != sorted(set(hostile_to)):
            raise NeutralNationRuntimeError("neutral_nation_hostile_to_not_canonical")
        if not isinstance(mobilized, list) or mobilized != sorted(set(mobilized)):
            raise NeutralNationRuntimeError("neutral_nation_mobilized_province_ids_not_canonical")
        if not set(mobilized) <= set(province_ids):
            raise NeutralNationRuntimeError("neutral_nation_mobilized_province_outside_nation")
        for province_id in province_ids:
            if _sovereign_owner(state, str(province_id)) != sovereign:
                raise NeutralNationRuntimeError("neutral_nation_province_sovereignty_mismatch")
            projected = state.provinces[str(province_id)].metadata.get(HOSTILE_METADATA_KEY)
            if projected != list(hostile_to):
                raise NeutralNationRuntimeError("neutral_nation_projected_hostility_mismatch")
        for province_id in mobilized:
            projected = state.provinces[str(province_id)].metadata.get(MOBILIZED_METADATA_KEY)
            if projected != list(hostile_to):
                raise NeutralNationRuntimeError("neutral_nation_projected_mobilization_mismatch")

    # Recovery capacity is authority, not ordinary mutable runtime data. Authenticate
    # the underlying #48 selection before trusting any persisted recovery record.
    from .neutral_garrison import (
        RUNTIME_KEY as GARRISON_RUNTIME_KEY,
        NeutralGarrisonError,
        validate_neutral_garrison_runtime,
    )

    try:
        validate_neutral_garrison_runtime(state)
    except NeutralGarrisonError as exc:
        raise NeutralNationRuntimeError(f"neutral_garrison_recovery_authority_invalid:{exc}") from exc

    garrisons = runtime["garrisons"]
    if not garrisons:
        return
    garrison_runtime = state.map_metadata.get(GARRISON_RUNTIME_KEY)
    if not isinstance(garrison_runtime, Mapping):
        raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_missing")
    authoritative_provinces = garrison_runtime.get("provinces")
    if not isinstance(authoritative_provinces, Mapping):
        raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_provinces_missing")

    expected_fields = {
        "province_id",
        "capacity_roster",
        "recovery_per_unit_per_turn",
        "last_recovery_turn",
    }
    for province_id, recovery in sorted(garrisons.items()):
        if not isinstance(recovery, Mapping):
            raise NeutralNationRuntimeError("neutral_garrison_recovery_record_invalid")
        if set(recovery) != expected_fields:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_record_fields_invalid")
        if recovery.get("province_id") != province_id:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_province_key_mismatch")
        if province_id not in state.provinces:
            raise NeutralNationRuntimeError(f"neutral_garrison_recovery_unknown_province:{province_id}")

        authority_record = authoritative_provinces.get(province_id)
        if not isinstance(authority_record, Mapping):
            raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_record_missing")
        selection = authority_record.get("selection")
        if not isinstance(selection, Mapping):
            raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_selection_missing")
        if str(selection.get("province_id") or "") != province_id:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_authority_province_mismatch")
        authoritative_capacity = _authenticated_capacity_from_selection(selection)
        if recovery.get("capacity_roster") != authoritative_capacity:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_capacity_mismatch")

        rate = recovery.get("recovery_per_unit_per_turn")
        if not isinstance(rate, int) or isinstance(rate, bool) or rate != 1:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_rate_invalid")
        last_turn = recovery.get("last_recovery_turn")
        if not isinstance(last_turn, int) or isinstance(last_turn, bool) or last_turn < 0:
            raise NeutralNationRuntimeError("neutral_garrison_recovery_last_turn_invalid")
        if last_turn > int(state.turn_number):
            raise NeutralNationRuntimeError("neutral_garrison_recovery_last_turn_in_future")
