from __future__ import annotations

from .models import (
    Battalion,
    CampaignState,
    ForceEchelon,
    NEUTRAL_GARRISON_BATTALION_PREFIX,
    StrategicFormation,
)

STRATEGIC_FORMATION_SCHEMA_VERSION = 6
MIGRATION_RECORD_KEY = "strategic_formation_migration"
DEFAULT_MOVEMENT_STATE = "in_province"


def strategic_formation_id_for_battalion(battalion_id: str) -> str:
    """Deterministic independent-formation ID for a legacy battalion."""

    return f"sf-{battalion_id}"


def ensure_strategic_formations(state: CampaignState) -> dict:
    """Migrate legacy battalion-only saves into strategic formations.

    Rules (issue #58 PR1):
    - Do **not** invent commander entities.
    - Formation location is authoritative; battalion province is synchronized.
    - Each battalion belongs to exactly one formation.
    - IDs are deterministic; one-time migration record is stable.
    - Derived summaries refresh deterministically after migration.
    - Pending/archived battles are left untouched.
    - Dangling commander refs are cleared only for legacy pre-schema-6 saves.

    Earth3 P2/P3 campaigns already carry authored strategic-formation authority.
    They must be checked before any legacy normalizer can repair, synchronize,
    refresh, or otherwise mutate them. For those campaigns this function performs
    only the narrow formation/battalion integrity checks that the legacy migration
    itself could otherwise repair. Full P2/P3 authority authentication remains in
    the Earth3 migration/validation path, avoiding repeated full-map validation
    every time ordinary runtime code calls this compatibility helper.
    """

    incoming_schema = int(state.schema_version)

    from .earth3_bootstrap import is_earth3_p2_campaign

    if is_earth3_p2_campaign(state):
        _validate_authored_earth3_force_structure(state)
        record = state.map_metadata.get(MIGRATION_RECORD_KEY)
        if isinstance(record, dict):
            return dict(record)
        return _stable_migration_record(incoming_schema)

    legacy = incoming_schema < STRATEGIC_FORMATION_SCHEMA_VERSION

    if _already_migrated(state):
        refresh_strategic_formation_summaries(state)
        record = state.map_metadata.get(MIGRATION_RECORD_KEY)
        if not isinstance(record, dict):
            record = _stable_migration_record(incoming_schema)
            state.map_metadata[MIGRATION_RECORD_KEY] = record
        state.schema_version = max(state.schema_version, STRATEGIC_FORMATION_SCHEMA_VERSION)
        return record

    owned: dict[str, str] = {}
    for force in state.strategic_formations.values():
        for battalion_id in force.battalion_ids:
            owned[battalion_id] = force.strategic_formation_id

    for battalion in sorted(state.battalions.values(), key=lambda value: value.battalion_id):
        if battalion.battalion_id.startswith(NEUTRAL_GARRISON_BATTALION_PREFIX):
            continue
        force_id = (
            battalion.strategic_formation_id
            or owned.get(battalion.battalion_id)
            or strategic_formation_id_for_battalion(battalion.battalion_id)
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
                movement_state=DEFAULT_MOVEMENT_STATE,
                stance="standard",
                actor_id=_actor_id_for_battalion(state, battalion),
                condition_summary=battalion.condition,
                supply_summary=battalion.supply,
                experience_summary=battalion.experience,
                is_player_controlled=battalion.is_player_controlled,
                recon_capability=_migrated_recon_capability(
                    battalion.formation_id
                ),
            )
            state.strategic_formations[force_id] = force
        else:
            if battalion.battalion_id not in force.battalion_ids:
                force.battalion_ids.append(battalion.battalion_id)
            # Location authority: formation wins; pull battalion onto formation province.
            if battalion.province_id != force.province_id:
                battalion.province_id = force.province_id
            if not force.template_formation_id and battalion.formation_id:
                force.template_formation_id = battalion.formation_id
            # Legacy migration only knew province occupancy, not operational anchors.
            if force.movement_state == "at_anchor":
                force.movement_state = DEFAULT_MOVEMENT_STATE

        battalion.strategic_formation_id = force_id
        if legacy:
            # Legacy saves never had authoritative commanders. Normalize only then.
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
            battalion.strategic_formation_id = force.strategic_formation_id

    refresh_strategic_formation_summaries(state)
    state.schema_version = max(state.schema_version, STRATEGIC_FORMATION_SCHEMA_VERSION)
    # Persist a stable record once. Do not rewrite run counters on every load/save.
    if MIGRATION_RECORD_KEY not in state.map_metadata:
        state.map_metadata[MIGRATION_RECORD_KEY] = _stable_migration_record(incoming_schema)
    return state.map_metadata[MIGRATION_RECORD_KEY]


def _validate_authored_earth3_force_structure(state: CampaignState) -> None:
    """Reject exactly the authored-force damage that legacy migration could repair.

    This check is intentionally read-only and limited to strategic-formation /
    battalion identity, membership, faction, and province relationships. The full
    immutable Earth3 authority, actor, graph, and provenance checks are performed
    by the P2/P3 validators immediately around campaign migration/load.
    """

    membership: dict[str, str] = {}
    for force_id, force in state.strategic_formations.items():
        if force_id != force.strategic_formation_id:
            raise ValueError(f"Strategic formation key mismatch: {force_id}")
        for battalion_id in force.battalion_ids:
            if battalion_id in membership:
                raise ValueError(
                    f"Battalion {battalion_id} belongs to multiple strategic formations "
                    f"({membership[battalion_id]} and {force_id})"
                )
            membership[battalion_id] = force_id
            battalion = state.battalions.get(battalion_id)
            if battalion is None:
                raise ValueError(
                    f"Strategic formation {force_id} references missing battalion {battalion_id}"
                )
            if battalion.strategic_formation_id != force_id:
                raise ValueError(
                    f"Battalion {battalion_id} strategic formation membership is inconsistent"
                )
            if battalion.faction != force.faction:
                raise ValueError(
                    f"Battalion {battalion_id} faction does not match strategic formation"
                )
            if battalion.province_id != force.province_id:
                raise ValueError(
                    f"Battalion {battalion_id} province {battalion.province_id} does not match "
                    f"strategic formation province {force.province_id}"
                )

    for battalion_id, battalion in state.battalions.items():
        if battalion_id.startswith(NEUTRAL_GARRISON_BATTALION_PREFIX):
            if battalion.faction.value != "neutral" or battalion.strategic_formation_id:
                raise ValueError(
                    f"Garrison battalion {battalion_id} must stay formationless and neutral"
                )
            continue
        force_id = battalion.strategic_formation_id
        if not force_id:
            raise ValueError(
                f"Battalion {battalion_id} is not assigned to a strategic formation"
            )
        force = state.strategic_formations.get(force_id)
        if force is None:
            raise ValueError(
                f"Battalion {battalion_id} references missing strategic formation {force_id}"
            )
        if battalion_id not in force.battalion_ids:
            raise ValueError(
                f"Battalion {battalion_id} missing from strategic formation membership list"
            )
        if membership.get(battalion_id) != force_id:
            raise ValueError(
                f"Battalion {battalion_id} strategic formation membership is inconsistent"
            )


def refresh_strategic_formation_summaries(state: CampaignState) -> None:
    """Recompute deterministic aggregate summaries from current battalion members.

    Safe to call repeatedly: unchanged battalions produce an identical serialized state.
    """

    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        members = [
            state.battalions[item]
            for item in force.battalion_ids
            if item in state.battalions
        ]
        if not members:
            force.condition_summary = 0
            force.supply_summary = 0
            force.experience_summary = 0
            continue
        force.condition_summary = _average(item.condition for item in members)
        force.supply_summary = _average(item.supply for item in members)
        force.experience_summary = _average(item.experience for item in members)


def _already_migrated(state: CampaignState) -> bool:
    if state.schema_version < STRATEGIC_FORMATION_SCHEMA_VERSION:
        return False
    if not state.battalions:
        return True
    if not state.strategic_formations:
        return False
    for battalion in state.battalions.values():
        if battalion.battalion_id.startswith(NEUTRAL_GARRISON_BATTALION_PREFIX):
            continue
        force_id = battalion.strategic_formation_id
        if not force_id:
            return False
        force = state.strategic_formations.get(force_id)
        if force is None:
            return False
        if battalion.battalion_id not in force.battalion_ids:
            return False
        if battalion.province_id != force.province_id:
            return False
        if battalion.faction != force.faction:
            return False
    return True


def _stable_migration_record(incoming_schema: int) -> dict:
    return {
        "schema_version": STRATEGIC_FORMATION_SCHEMA_VERSION,
        "migrated_from_schema": min(incoming_schema, STRATEGIC_FORMATION_SCHEMA_VERSION),
        "commanders_invented": 0,
        "id_scheme": "sf-{battalion_id}",
        "default_movement_state": DEFAULT_MOVEMENT_STATE,
        "note": "Legacy independent battalions wrapped as battalion-echelon strategic formations.",
    }


def _migrated_recon_capability(template_formation_id: str) -> bool:
    from .observation import RECON_TEMPLATE_IDS

    return template_formation_id in RECON_TEMPLATE_IDS


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
