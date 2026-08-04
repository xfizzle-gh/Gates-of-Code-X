from __future__ import annotations

from .models import (
    Battalion,
    CampaignState,
    ForceEchelon,
    StrategicFormation,
)

STRATEGIC_FORMATION_SCHEMA_VERSION = 6


def strategic_formation_id_for_battalion(battalion_id: str) -> str:
    """Deterministic independent-formation ID for a legacy battalion."""

    return f"sf-{battalion_id}"


def ensure_strategic_formations(state: CampaignState) -> dict[str, int]:
    """Migrate legacy battalion-only saves into strategic formations.

    Rules (issue #58 PR1):
    - Do **not** invent commander entities.
    - Formation location is authoritative; battalion province is synchronized.
    - Each battalion belongs to exactly one formation.
    - IDs are deterministic and idempotent.
    - Pending/archived battles are left untouched.
    """

    created = 0
    reused = 0
    synchronized = 0

    # Drop empty commander dict is fine; never auto-populate.
    if state.commanders is None:  # type: ignore[unreachable]
        state.commanders = {}

    owned: dict[str, str] = {}
    for force in state.strategic_formations.values():
        for battalion_id in force.battalion_ids:
            owned[battalion_id] = force.strategic_formation_id

    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        force_id = battalion.strategic_formation_id or owned.get(battalion.battalion_id) or strategic_formation_id_for_battalion(
            battalion.battalion_id
        )
        force = state.strategic_formations.get(force_id)
        if force is None:
            force = StrategicFormation(
                strategic_formation_id=force_id,
                display_name=_display_name_for_battalion(state, battalion),
                faction=battalion.faction,
                province_id=battalion.province_id,
                echelon=ForceEchelon.BATTALION,
                commander_id=None,
                battalion_ids=[battalion.battalion_id],
                template_formation_id=battalion.formation_id,
                stack_order=0,
                movement_state="at_anchor",
                stance="standard",
                actor_id=_actor_id_for_battalion(state, battalion),
                condition_summary=battalion.condition,
                supply_summary=battalion.supply,
                experience_summary=battalion.experience,
                is_player_controlled=battalion.is_player_controlled,
            )
            state.strategic_formations[force_id] = force
            created += 1
        else:
            reused += 1
            if battalion.battalion_id not in force.battalion_ids:
                force.battalion_ids.append(battalion.battalion_id)
            # Location authority: formation wins; pull battalion onto formation province.
            if battalion.province_id != force.province_id:
                battalion.province_id = force.province_id
                synchronized += 1
            if not force.template_formation_id and battalion.formation_id:
                force.template_formation_id = battalion.formation_id
            force.condition_summary = _average(
                state.battalions[item].condition for item in force.battalion_ids if item in state.battalions
            )
            force.supply_summary = _average(
                state.battalions[item].supply for item in force.battalion_ids if item in state.battalions
            )
            force.experience_summary = _average(
                state.battalions[item].experience for item in force.battalion_ids if item in state.battalions
            )

        battalion.strategic_formation_id = force_id
        # Never invent commanders during migration.
        if battalion.commander_id and battalion.commander_id not in state.commanders:
            battalion.commander_id = None
        if force.commander_id and force.commander_id not in state.commanders:
            force.commander_id = None

    # Final co-location pass for every force.
    for force in state.strategic_formations.values():
        for battalion_id in force.battalion_ids:
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                continue
            if battalion.province_id != force.province_id:
                battalion.province_id = force.province_id
                synchronized += 1
            battalion.strategic_formation_id = force.strategic_formation_id

    state.schema_version = max(state.schema_version, STRATEGIC_FORMATION_SCHEMA_VERSION)
    state.map_metadata["strategic_formation_migration"] = {
        "schema_version": STRATEGIC_FORMATION_SCHEMA_VERSION,
        "created": created,
        "reused": reused,
        "province_synchronized": synchronized,
        "commanders_invented": 0,
    }
    return state.map_metadata["strategic_formation_migration"]


def _display_name_for_battalion(state: CampaignState, battalion: Battalion) -> str:
    if battalion.formation_id and battalion.formation_id in state.formations:
        return state.formations[battalion.formation_id].display_name
    return battalion.battalion_id


def _actor_id_for_battalion(state: CampaignState, battalion: Battalion) -> str:
    if battalion.formation_id and battalion.formation_id in state.formations:
        return state.formations[battalion.formation_id].nation
    return battalion.faction.value


def _average(values) -> int:
    items = list(values)
    if not items:
        return 0
    return int(round(sum(items) / len(items)))
