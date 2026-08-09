from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict
from typing import Any, Mapping

from .models import CampaignState, Faction, InformationTier, KnowledgeRecord

S11_CAMPAIGN_SCHEMA_VERSION = 11
RECON_TEMPLATE_IDS = frozenset(
    {
        "nato-us-airborne",
        "nato-gbr-battlegroup",
        "ukr-air-assault",
        "rusa-vdv",
    }
)
S11_TOP_LEVEL_FIELDS = frozenset({"fog_of_war_enabled", "knowledge_by_observer"})


def prepare_s11_payload(data: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Validate the raw discriminator and return a schema-11 payload copy."""
    payload = copy.deepcopy(dict(data))
    incoming = max(1, int(payload.get("schema_version", 1)))
    strategic = payload.get("strategic_formations", {})
    if not isinstance(strategic, dict):
        raise ValueError("strategic_formations must be an object")
    top_present = any(name in payload for name in S11_TOP_LEVEL_FIELDS)
    recon_present = any(
        isinstance(row, dict) and "recon_capability" in row
        for row in strategic.values()
    )
    if incoming < S11_CAMPAIGN_SCHEMA_VERSION:
        if top_present or recon_present:
            raise ValueError("unexpected_s11_fields_in_pre_s11_schema")
        payload["fog_of_war_enabled"] = False
        payload["knowledge_by_observer"] = {}
        for row in strategic.values():
            if not isinstance(row, dict):
                raise ValueError("strategic formation row must be an object")
            template_id = str(row.get("template_formation_id", "") or "")
            row["recon_capability"] = template_id in RECON_TEMPLATE_IDS
        # Preserve the true incoming discriminator until the established
        # schema-6/7/8 migrations have run. campaign_from_dict() raises the
        # final value to 11 only after those legacy migrations complete.
        return payload, incoming

    missing = [name for name in sorted(S11_TOP_LEVEL_FIELDS) if name not in payload]
    if missing:
        raise ValueError(f"missing_s11_fields:{','.join(missing)}")
    for key, row in strategic.items():
        if not isinstance(row, dict) or "recon_capability" not in row:
            raise ValueError(f"missing_s11_recon_capability:{key}")
    return payload, incoming


def ensure_s11_schema(state: CampaignState, *, migrated_from_pre_s11: bool = False) -> None:
    if migrated_from_pre_s11:
        state.fog_of_war_enabled = False
        state.knowledge_by_observer = {}
        apply_recon_migration_defaults(state)
    state.schema_version = max(state.schema_version, S11_CAMPAIGN_SCHEMA_VERSION)


def apply_recon_migration_defaults(state: CampaignState) -> None:
    for force in state.strategic_formations.values():
        force.recon_capability = force.template_formation_id in RECON_TEMPLATE_IDS


def knowledge_record_from_dict(value: Mapping[str, Any]) -> KnowledgeRecord:
    if not isinstance(value, Mapping):
        raise ValueError("knowledge record must be an object")
    try:
        tier = InformationTier(str(value["tier"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid_knowledge_tier") from exc
    record = KnowledgeRecord(
        observer_scope_id=str(value.get("observer_scope_id", "")),
        record_key=str(value.get("record_key", "")),
        subject_formation_id=str(value.get("subject_formation_id", "")),
        tier=tier,
        opaque_contact_id=str(value.get("opaque_contact_id", "")),
        first_seen_turn=int(value.get("first_seen_turn", 0)),
        last_seen_turn=int(value.get("last_seen_turn", 0)),
        last_seen_tick=int(value.get("last_seen_tick", 0)),
        source_ids=[str(item) for item in value.get("source_ids", [])],
        current=value.get("current", True),
        last_seen_province_id=str(value.get("last_seen_province_id", "") or ""),
        last_seen_node_id=str(value.get("last_seen_node_id", "") or ""),
        last_seen_edge_id=str(value.get("last_seen_edge_id", "") or ""),
        last_seen_progress_milli=(
            None if value.get("last_seen_progress_milli") is None
            else int(value["last_seen_progress_milli"])
        ),
        last_seen_direction=str(value.get("last_seen_direction", "") or ""),
        faction_id=str(value.get("faction_id", "") or ""),
        actor_id=str(value.get("actor_id", "") or ""),
        display_name=str(value.get("display_name", "") or ""),
        echelon=str(value.get("echelon", "") or ""),
        strength_band=str(value.get("strength_band", "") or ""),
        condition_band=str(value.get("condition_band", "") or ""),
        supply_band=str(value.get("supply_band", "") or ""),
    )
    record.validate()
    return record


def knowledge_record_to_dict(record: KnowledgeRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["tier"] = record.tier.value
    return payload


def opaque_contact_id(observer_scope: str, subject_formation_id: str) -> str:
    raw = (
        "goc-s11-contact-v1\0"
        + observer_scope
        + "\0"
        + subject_formation_id
    ).encode("utf-8")
    return "contact-" + hashlib.sha256(raw).hexdigest()


def observer_scope_id(state: CampaignState, faction: Faction) -> str:
    memberships = sorted(
        alliance.alliance_id
        for alliance in state.alliances.values()
        if faction in alliance.factions
    )
    if len(memberships) > 1:
        raise ValueError("ambiguous_observer_scope_multiple_alliances")
    return f"alliance:{memberships[0]}" if memberships else f"faction:{faction.value}"


def observer_factions(state: CampaignState, faction: Faction) -> frozenset[Faction]:
    scope = observer_scope_id(state, faction)
    if scope.startswith("faction:"):
        return frozenset({faction})
    alliance = state.alliances[scope.split(":", 1)[1]]
    return frozenset(alliance.factions)


def validate_s11_observer_authority(
    state: CampaignState,
    *,
    observer_requested: bool = False,
    validate_records: bool = True,
) -> None:
    if not isinstance(state.fog_of_war_enabled, bool):
        raise ValueError("fog_of_war_enabled must be bool")
    if not isinstance(state.knowledge_by_observer, dict):
        raise ValueError("knowledge_by_observer must be an object")
    has_records = any(bool(rows) for rows in state.knowledge_by_observer.values())
    if state.fog_of_war_enabled:
        human = [row for row in state.factions.values() if row.is_human_controlled]
        if len(human) != 1:
            raise ValueError("fog_of_war_requires_single_human_faction")
    if state.fog_of_war_enabled or has_records or observer_requested:
        for faction in state.factions.values():
            observer_scope_id(state, faction.faction)

    if not validate_records:
        return

    seen_subjects: dict[str, set[str]] = {}
    for scope, rows in state.knowledge_by_observer.items():
        if not isinstance(scope, str) or not scope.strip() or not isinstance(rows, dict):
            raise ValueError("invalid_knowledge_observer_store")
        if not rows:
            _validate_persisted_observer_scope_shape(state, scope)
            continue
        _validate_persisted_observer_scope(state, scope)
        subjects = seen_subjects.setdefault(scope, set())
        for key, record in rows.items():
            if not isinstance(record, KnowledgeRecord):
                raise ValueError("knowledge record must be KnowledgeRecord")
            record.validate()
            if key != record.record_key or scope != record.observer_scope_id:
                raise ValueError("knowledge_record_store_key_mismatch")
            if record.subject_formation_id in subjects:
                raise ValueError("duplicate_knowledge_subject")
            subjects.add(record.subject_formation_id)
            expected_opaque = opaque_contact_id(scope, record.subject_formation_id)
            if record.opaque_contact_id != expected_opaque:
                raise ValueError("opaque_contact_digest_mismatch")
            if record.tier == InformationTier.CONTACT:
                if record.record_key != f"contact:{expected_opaque}":
                    raise ValueError("contact_record_key_mismatch")
            elif record.record_key != f"formation:{record.subject_formation_id}":
                raise ValueError("formation_record_key_mismatch")


def _validate_persisted_observer_scope_shape(
    state: CampaignState, scope: str
) -> None:
    """Validate an empty store key without deriving coalition authority."""
    kind, separator, authority_id = scope.partition(":")
    if separator != ":" or not authority_id:
        raise ValueError("invalid_knowledge_observer_scope")
    if kind == "faction" and authority_id in state.factions:
        return
    if kind == "alliance" and authority_id in state.alliances:
        return
    raise ValueError("invalid_knowledge_observer_scope")

def _validate_persisted_observer_scope(
    state: CampaignState, scope: str
) -> None:
    kind, separator, authority_id = scope.partition(":")
    if separator != ":" or not authority_id:
        raise ValueError("invalid_knowledge_observer_scope")
    if kind == "faction":
        if authority_id not in state.factions:
            raise ValueError("invalid_knowledge_observer_scope")
        faction = Faction(authority_id)
        if observer_scope_id(state, faction) != scope:
            raise ValueError("knowledge_observer_scope_not_authoritative")
        return
    if kind == "alliance":
        alliance = state.alliances.get(authority_id)
        if alliance is None:
            raise ValueError("invalid_knowledge_observer_scope")
        if any(observer_scope_id(state, faction) != scope for faction in alliance.factions):
            raise ValueError("knowledge_observer_scope_not_authoritative")
        return
    raise ValueError("invalid_knowledge_observer_scope")


from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ObservationMutationContext:
    confirmed_removed_formation_ids_by_observer: Mapping[str, frozenset[str]] = field(
        default_factory=dict
    )


def merge_observation_mutation_contexts(
    *contexts: ObservationMutationContext | None,
) -> ObservationMutationContext:
    merged: dict[str, set[str]] = {}
    for context in contexts:
        if context is None:
            continue
        for scope, subject_ids in (
            context.confirmed_removed_formation_ids_by_observer.items()
        ):
            merged.setdefault(scope, set()).update(subject_ids)
    return ObservationMutationContext(
        {
            scope: frozenset(sorted(subject_ids))
            for scope, subject_ids in sorted(merged.items())
            if subject_ids
        }
    )


def capture_observation_removal_witnesses(
    state: CampaignState,
    subject_formation_ids: set[str] | frozenset[str],
    *,
    participating_factions: set[Faction] | frozenset[Faction] = frozenset(),
    authoritative_witness_factions: set[Faction] | frozenset[Faction] = frozenset(),
) -> dict[str, frozenset[str]]:
    """Capture observer scopes that can confirm each subject before deletion."""
    subjects = frozenset(str(item) for item in subject_formation_ids if str(item))
    if not subjects:
        return {}
    if not state.fog_of_war_enabled and not any(
        bool(rows) for rows in state.knowledge_by_observer.values()
    ):
        return {subject_id: frozenset() for subject_id in subjects}

    representatives: dict[str, Faction] = {}
    for faction_id in sorted(state.factions):
        faction = Faction(faction_id)
        representatives.setdefault(observer_scope_id(state, faction), faction)

    result: dict[str, set[str]] = {subject_id: set() for subject_id in subjects}
    participant_set = frozenset(participating_factions)
    explicit_set = frozenset(authoritative_witness_factions)
    for scope, representative in sorted(representatives.items()):
        coalition = observer_factions(state, representative)
        blanket_witness = bool(
            coalition.intersection(participant_set)
            or coalition.intersection(explicit_set)
        )
        current = project_operational_observation(state, representative)
        persisted = state.knowledge_by_observer.get(scope, {})
        persisted_by_subject = {
            row.subject_formation_id: row for row in persisted.values()
        }
        for subject_id in subjects:
            observed = current.get(subject_id)
            prior = persisted_by_subject.get(subject_id)
            fully_observed = (
                observed is not None
                and observed.tier == InformationTier.FULLY_OBSERVED
            ) or (
                prior is not None
                and prior.current
                and prior.tier == InformationTier.FULLY_OBSERVED
            )
            if blanket_witness or fully_observed:
                result[subject_id].add(scope)
    return {
        subject_id: frozenset(sorted(scopes))
        for subject_id, scopes in sorted(result.items())
    }


_TIER_RANK = {
    InformationTier.UNKNOWN: 0,
    InformationTier.CONTACT: 1,
    InformationTier.IDENTIFIED: 2,
    InformationTier.ASSESSED: 3,
    InformationTier.FULLY_OBSERVED: 4,
}


def combine_detection_tier(*, direct: bool, recon_count: int, site_count: int) -> InformationTier:
    if direct:
        return InformationTier.FULLY_OBSERVED
    if recon_count <= 0 and site_count <= 0:
        return InformationTier.UNKNOWN
    if recon_count <= 0 and site_count == 1:
        return InformationTier.CONTACT
    if recon_count <= 0 and site_count >= 2:
        return InformationTier.IDENTIFIED
    if recon_count == 1 and site_count <= 0:
        return InformationTier.IDENTIFIED
    return InformationTier.ASSESSED


def reduce_tier_for_ambush(tier: InformationTier) -> InformationTier:
    if tier == InformationTier.FULLY_OBSERVED:
        return tier
    order = [
        InformationTier.UNKNOWN,
        InformationTier.CONTACT,
        InformationTier.IDENTIFIED,
        InformationTier.ASSESSED,
    ]
    return order[max(0, order.index(tier) - 1)]


def project_operational_observation(
    state: CampaignState,
    observer_faction: Faction,
) -> dict[str, KnowledgeRecord]:
    """Pure current observation projection. Never mutates ``state``."""
    validate_s11_observer_authority(
        state, observer_requested=True, validate_records=False
    )
    scope = observer_scope_id(state, observer_faction)
    coalition = observer_factions(state, observer_faction)
    graph, nodes_by_id, edges_by_id, incident = _graph_indexes_for_observation(state)
    recon_sources = _recon_source_coverage(
        state, coalition, graph=graph, edges_by_id=edges_by_id, incident=incident
    )
    site_sources = _site_source_coverage(
        state, coalition, graph=graph, nodes_by_id=nodes_by_id, incident=incident
    )
    current_tick = _operational_tick(state)
    from .operational_contact import formation_is_combat_capable

    observations: dict[str, KnowledgeRecord] = {}
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda item: item.strategic_formation_id,
    ):
        if force.faction in coalition or not formation_is_combat_capable(state, force):
            continue
        direct, direct_sources = _direct_contact_sources(
            state,
            force,
            coalition,
            graph_available=graph is not None,
        )
        location_tokens = (
            _location_tokens(force)
            if graph is not None
            else {f"province:{force.province_id}"}
        )
        recon_ids = sorted(
            source_id
            for source_id, covered in recon_sources.items()
            if location_tokens & covered
        )
        site_ids = sorted(
            source_id
            for source_id, covered in site_sources.items()
            if location_tokens & covered
        )
        tier = combine_detection_tier(
            direct=direct,
            recon_count=len(recon_ids),
            site_count=len(site_ids),
        )
        if (
            not direct
            and tier != InformationTier.UNKNOWN
            and str(force.stance or "") == "ambush"
            and force.ambush_ready_tick is not None
        ):
            tier = reduce_tier_for_ambush(tier)
        if tier == InformationTier.UNKNOWN:
            continue
        sources = sorted(
            [f"direct:{item}" for item in direct_sources]
            + [f"recon:{item}" for item in recon_ids]
            + [f"site:{item}" for item in site_ids]
        )
        observations[force.strategic_formation_id] = _record_from_force(
            state,
            scope=scope,
            force=force,
            tier=tier,
            source_ids=sources,
            current_tick=current_tick,
        )
    return observations


def refresh_all_observer_knowledge(
    state: CampaignState,
    mutation_context: ObservationMutationContext | None = None,
) -> None:
    """Refresh persisted observer knowledge exactly once at a mutation/save boundary."""
    if not state.fog_of_war_enabled and not any(state.knowledge_by_observer.values()):
        return
    context = mutation_context or ObservationMutationContext()
    representatives: dict[str, Faction] = {}
    for faction_id in sorted(state.factions):
        faction = Faction(faction_id)
        scope = observer_scope_id(state, faction)
        representatives.setdefault(scope, faction)
    unknown_context_scopes = set(
        context.confirmed_removed_formation_ids_by_observer
    ) - set(representatives)
    if unknown_context_scopes:
        raise ValueError(
            "unknown_observation_mutation_scope:"
            + ",".join(sorted(unknown_context_scopes))
        )

    next_store: dict[str, dict[str, KnowledgeRecord]] = {}
    for scope, faction in sorted(representatives.items()):
        existing = state.knowledge_by_observer.get(scope, {})
        by_subject = {row.subject_formation_id: copy.deepcopy(row) for row in existing.values()}
        current = project_operational_observation(state, faction)
        confirmed_removed = set(
            context.confirmed_removed_formation_ids_by_observer.get(scope, frozenset())
        )
        for subject_id in confirmed_removed:
            by_subject.pop(subject_id, None)
        for subject_id, prior in list(by_subject.items()):
            if subject_id not in current:
                # A subject that disappeared while previously fully observed is a
                # witnessed removal. Unseen lower-tier disappearances remain stale.
                if (
                    subject_id not in state.strategic_formations
                    and prior.current
                    and prior.tier == InformationTier.FULLY_OBSERVED
                ):
                    by_subject.pop(subject_id, None)
                    continue
                prior.current = False
        for subject_id, observed in current.items():
            prior = by_subject.get(subject_id)
            by_subject[subject_id] = _merge_current_observation(observed, prior)
        rows: dict[str, KnowledgeRecord] = {}
        opaque_subjects: dict[str, str] = {}
        for subject_id, record in sorted(by_subject.items()):
            expected = opaque_contact_id(scope, subject_id)
            previous = opaque_subjects.get(expected)
            if previous is not None and previous != subject_id:
                raise ValueError("opaque_contact_collision")
            opaque_subjects[expected] = subject_id
            record.observer_scope_id = scope
            record.opaque_contact_id = expected
            if record.tier == InformationTier.CONTACT:
                record.record_key = f"contact:{expected}"
            else:
                record.record_key = f"formation:{subject_id}"
            if record.record_key in rows:
                raise ValueError("duplicate_knowledge_record_key")
            rows[record.record_key] = record
        next_store[scope] = rows
    state.knowledge_by_observer = next_store
    validate_s11_observer_authority(state)


def current_and_last_known_records(
    state: CampaignState,
    observer_faction: Faction,
) -> tuple[dict[str, KnowledgeRecord], list[KnowledgeRecord]]:
    projected = project_operational_observation(state, observer_faction)
    scope = observer_scope_id(state, observer_faction)
    persisted = state.knowledge_by_observer.get(scope, {})
    persisted_by_subject = {
        row.subject_formation_id: row for row in persisted.values()
    }
    current = {
        subject_id: _merge_current_observation(
            observed, persisted_by_subject.get(subject_id)
        )
        for subject_id, observed in projected.items()
    }
    stale = [
        copy.deepcopy(row)
        for row in persisted.values()
        if row.subject_formation_id not in current
    ]
    stale.sort(key=lambda row: row.record_key)
    return current, stale


def _merge_current_observation(
    observed: KnowledgeRecord,
    prior: KnowledgeRecord | None,
) -> KnowledgeRecord:
    merged = copy.deepcopy(observed)
    if prior is None:
        return merged
    merged.first_seen_turn = prior.first_seen_turn
    if (
        _TIER_RANK[prior.tier] >= _TIER_RANK[InformationTier.IDENTIFIED]
        and _TIER_RANK[merged.tier] < _TIER_RANK[InformationTier.IDENTIFIED]
    ):
        merged.tier = InformationTier.IDENTIFIED
        merged.record_key = f"formation:{merged.subject_formation_id}"
        merged.faction_id = prior.faction_id
        merged.actor_id = prior.actor_id
        merged.display_name = prior.display_name
        merged.echelon = prior.echelon
        merged.strength_band = ""
        merged.condition_band = ""
        merged.supply_band = ""
        merged.last_seen_progress_milli = None
        merged.last_seen_direction = ""
    return merged


def _record_from_force(
    state: CampaignState,
    *,
    scope: str,
    force: Any,
    tier: InformationTier,
    source_ids: list[str],
    current_tick: int,
) -> KnowledgeRecord:
    opaque = opaque_contact_id(scope, force.strategic_formation_id)
    key = (
        f"contact:{opaque}"
        if tier == InformationTier.CONTACT
        else f"formation:{force.strategic_formation_id}"
    )
    record = KnowledgeRecord(
        observer_scope_id=scope,
        record_key=key,
        subject_formation_id=force.strategic_formation_id,
        tier=tier,
        opaque_contact_id=opaque,
        first_seen_turn=state.turn_number,
        last_seen_turn=state.turn_number,
        last_seen_tick=current_tick,
        source_ids=source_ids,
        current=True,
        last_seen_province_id=force.province_id,
    )
    position = force.position
    if position is not None:
        if position.mode == "at_node":
            record.last_seen_node_id = str(position.node_id or "")
        elif position.mode == "on_edge":
            record.last_seen_edge_id = str(position.edge_id or "")
            if tier == InformationTier.FULLY_OBSERVED:
                record.last_seen_progress_milli = int(position.progress_milli)
            if _TIER_RANK[tier] >= _TIER_RANK[InformationTier.ASSESSED]:
                record.last_seen_direction = str(position.facing_node_id or "")
    if _TIER_RANK[tier] >= _TIER_RANK[InformationTier.IDENTIFIED]:
        record.faction_id = force.faction.value
        record.actor_id = force.actor_id
        record.display_name = force.display_name
        record.echelon = force.echelon.value
    if _TIER_RANK[tier] >= _TIER_RANK[InformationTier.ASSESSED]:
        record.strength_band = _strength_band(state, force)
        record.condition_band = _percent_band(force.condition_summary)
        record.supply_band = _percent_band(force.supply_summary)
    return record


def _strength_band(state: CampaignState, force: Any) -> str:
    total = sum(
        state.battalions[item].unit_count
        for item in force.battalion_ids
        if item in state.battalions
    )
    if total <= 2:
        return "light"
    if total <= 6:
        return "medium"
    return "heavy"


def _percent_band(value: int) -> str:
    if value < 34:
        return "low"
    if value < 67:
        return "medium"
    return "high"


def _operational_tick(state: CampaignState) -> int:
    raw = state.map_metadata.get("operational_clock")
    if not isinstance(raw, dict):
        return 0
    value = raw.get("global_tick", 0)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _graph_indexes_for_observation(
    state: CampaignState,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, set[str]]]:
    from .operational_position import load_operational_graph_for_state

    graph = load_operational_graph_for_state(state)
    if graph is None:
        return None, {}, {}, {}
    nodes = {
        str(row.get("node_id")): row
        for row in graph.get("nodes", [])
        if isinstance(row, dict) and row.get("node_id")
    }
    edges = {
        str(row.get("edge_id")): row
        for row in graph.get("edges", [])
        if isinstance(row, dict) and row.get("edge_id")
    }
    incident: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge_id, edge in edges.items():
        a, b = str(edge.get("a") or ""), str(edge.get("b") or "")
        if a:
            incident.setdefault(a, set()).add(edge_id)
        if b:
            incident.setdefault(b, set()).add(edge_id)
    return graph, nodes, edges, incident


def _location_tokens(force: Any) -> set[str]:
    position = force.position
    if position is None:
        return {f"province:{force.province_id}"}
    if position.mode == "at_node" and position.node_id:
        return {f"node:{position.node_id}"}
    if position.mode == "on_edge" and position.edge_id:
        return {f"edge:{position.edge_id}"}
    return {f"province:{force.province_id}"}


def _recon_source_coverage(
    state: CampaignState,
    coalition: frozenset[Faction],
    *,
    graph: dict[str, Any] | None,
    edges_by_id: dict[str, dict[str, Any]],
    incident: dict[str, set[str]],
) -> dict[str, set[str]]:
    from .operational_contact import formation_is_combat_capable

    result: dict[str, set[str]] = {}
    for force in state.strategic_formations.values():
        if (
            force.faction not in coalition
            or not force.recon_capability
            or not formation_is_combat_capable(state, force)
        ):
            continue
        tokens: set[str] = set()
        if graph is None or force.position is None:
            tokens.add(f"province:{force.province_id}")
            province = state.provinces.get(force.province_id)
            if province is not None:
                tokens.update(f"province:{item}" for item in province.neighbors)
        elif force.position.mode == "at_node" and force.position.node_id:
            node_id = str(force.position.node_id)
            tokens.add(f"node:{node_id}")
            for edge_id in incident.get(node_id, set()):
                tokens.add(f"edge:{edge_id}")
                edge = edges_by_id.get(edge_id, {})
                other = str(edge.get("b") if edge.get("a") == node_id else edge.get("a") or "")
                if other:
                    tokens.add(f"node:{other}")
        elif force.position.mode == "on_edge" and force.position.edge_id:
            edge_id = str(force.position.edge_id)
            tokens.add(f"edge:{edge_id}")
            edge = edges_by_id.get(edge_id, {})
            for node_id in (str(edge.get("a") or ""), str(edge.get("b") or "")):
                if node_id:
                    tokens.add(f"node:{node_id}")
        result[force.strategic_formation_id] = tokens
    return result


def _site_source_coverage(
    state: CampaignState,
    coalition: frozenset[Faction],
    *,
    graph: dict[str, Any] | None,
    nodes_by_id: dict[str, dict[str, Any]],
    incident: dict[str, set[str]],
) -> dict[str, set[str]]:
    from .operational_capture import get_site_control_state

    control = get_site_control_state(state)
    result: dict[str, set[str]] = {}
    if graph is None:
        for storage_key, control_row in sorted(control.items()):
            if not isinstance(control_row, dict):
                continue
            site_id = str(
                control_row.get("authored_site_id") or storage_key or ""
            )
            province_id = str(control_row.get("province_id") or "")
            if (
                not site_id
                or control_row.get("authored_site") is not True
                or str(control_row.get("site_kind") or "")
                not in {"observation", "command"}
                or control_row.get("synthetic_anchor_control_site") is True
                or not province_id
                or province_id not in state.provinces
            ):
                continue
            try:
                owner = Faction(str(control_row.get("controller_faction")))
            except (TypeError, ValueError):
                continue
            if owner not in coalition:
                continue
            covered = {f"province:{province_id}"}
            covered.update(
                f"province:{neighbor_id}"
                for neighbor_id in state.provinces[province_id].neighbors
            )
            result.setdefault(site_id, set()).update(covered)
        return result

    for site in graph.get("sites", []):
        if not isinstance(site, dict):
            continue
        site_id = str(site.get("site_id") or "")
        node_id = str(site.get("route_node_id") or "")
        metadata = site.get("metadata") if isinstance(site.get("metadata"), dict) else {}
        if (
            not site_id
            or str(site.get("kind") or "") not in {"observation", "command"}
            or not node_id
            or node_id not in nodes_by_id
            or metadata.get("synthetic_anchor_control_site") is True
        ):
            continue
        control_row = control.get(site_id)
        if control_row is None:
            continue
        raw_owner = control_row.get("controller_faction")
        try:
            owner = Faction(str(raw_owner))
        except (TypeError, ValueError):
            continue
        if owner not in coalition:
            continue
        tokens = {f"node:{node_id}"}
        for edge_id in incident.get(node_id, set()):
            tokens.add(f"edge:{edge_id}")
            edge = next(
                (
                    row
                    for row in graph.get("edges", [])
                    if isinstance(row, dict) and str(row.get("edge_id")) == edge_id
                ),
                {},
            )
            other = str(edge.get("b") if edge.get("a") == node_id else edge.get("a") or "")
            if other:
                tokens.add(f"node:{other}")
        result[site_id] = tokens
    return result


def _direct_contact_sources(
    state: CampaignState,
    target: Any,
    coalition: frozenset[Faction],
    *,
    graph_available: bool,
) -> tuple[bool, list[str]]:
    from .operational_contact import formation_is_combat_capable

    sources: list[str] = []
    if graph_available:
        target_node = (
            str(target.position.node_id or "")
            if target.position is not None
            and target.position.mode == "at_node"
            else ""
        )
        if target_node:
            for force in state.strategic_formations.values():
                if (
                    force.faction in coalition
                    and formation_is_combat_capable(state, force)
                    and force.position is not None
                    and force.position.mode == "at_node"
                    and str(force.position.node_id or "") == target_node
                ):
                    sources.append(force.strategic_formation_id)
    else:
        for force in state.strategic_formations.values():
            if (
                force.faction in coalition
                and formation_is_combat_capable(state, force)
                and force.province_id == target.province_id
            ):
                sources.append(force.strategic_formation_id)
    pending = state.pending_battle
    if pending is not None:
        participant_battalions = {
            row.battalion_id
            for row in pending.attacking_participants + pending.defending_participants
        }
        if any(item in participant_battalions for item in target.battalion_ids):
            for force in state.strategic_formations.values():
                if (
                    force.faction in coalition
                    and formation_is_combat_capable(state, force)
                    and any(
                        item in participant_battalions for item in force.battalion_ids
                    )
                ):
                    sources.append(force.strategic_formation_id)
    return bool(sources), sorted(set(sources))
