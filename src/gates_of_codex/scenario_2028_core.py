from __future__ import annotations

import copy
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
CORE_2028_POWER_IDS = ("nato", "ukr", "rusa", "prc")
CORE_2028_STARTING_TREASURY = {
    "nato": 600,
    "ukr": 600,
    "rusa": 750,
    "prc": 600,
}
CORE_2028_OVERLAY_SOURCES = {
    "nato": "usa",
    "rusa": "rus",
}
CORE_2028_OVERLAY_ACTOR_IDS = frozenset(CORE_2028_OVERLAY_SOURCES)
CORE_2028_POWER_DISPLAY = {
    "nato": "NATO",
    "ukr": "Ukraine",
    "rusa": "Russia",
    "prc": "PRC",
}


def _rewrite_core_overlay_content(
    source_content: Mapping[str, Any],
    *,
    source_actor_id: str,
    target_actor_id: str,
) -> dict[str, Any]:
    rewritten = copy.deepcopy(dict(source_content))
    rewritten["actor_id"] = target_actor_id
    rewritten["display_name"] = CORE_2028_POWER_DISPLAY[target_actor_id]
    rewritten["tactical_side"] = target_actor_id
    rewritten["roster_class"] = "compatibility"
    prefix = f"actor:{source_actor_id}:"
    replacement = f"actor:{target_actor_id}:"
    units = rewritten.get("units")
    if isinstance(units, dict):
        for unit in units.values():
            if isinstance(unit, dict):
                unit["actor_id"] = target_actor_id
                unit["tactical_side"] = target_actor_id
                unit["research_options"] = [
                    str(item).replace(prefix, replacement, 1)
                    for item in unit.get("research_options", [])
                ]
    nodes = rewritten.get("research_nodes")
    if isinstance(nodes, dict):
        remapped: dict[str, Any] = {}
        for key, node in nodes.items():
            new_key = key.replace(prefix, replacement, 1) if key.startswith(prefix) else key
            if isinstance(node, dict):
                node = dict(node)
                node["key"] = str(node.get("key") or key).replace(prefix, replacement, 1)
                node["actor_id"] = target_actor_id
                node["prerequisites"] = [
                    str(item).replace(prefix, replacement, 1)
                    for item in node.get("prerequisites", [])
                ]
            remapped[new_key] = node
        rewritten["research_nodes"] = remapped
    return rewritten


def bind_core_2028_selected_actor(state: CampaignState, actor_id: str) -> None:
    """Bind Core New Campaign selection to that power's treasury.

    Earth3 bootstrap installs ``selected_actor_id=usa``. Core must not leak
    that seat: NATO/UKR/RUSA/PRC each own a distinct Core treasury that
    ``#149`` actor_economy APIs spend.
    """

    token = str(actor_id or "").strip()
    if token not in CORE_2028_POWER_IDS:
        raise Scenario2028AuthorityError(f"core_2028_actor_not_a_campaign_power:{token}")

    from .actor_economy import ACTOR_CONTENT_KEY, validate_actor_content_runtime
    from .strategic_actors import (
        ACTOR_RUNTIME_KEY,
        EngineTacticalSide,
        StrategicActorState,
        ensure_strategic_actor_runtime,
        set_selected_actor,
        validate_strategic_actor_runtime,
    )

    actors = ensure_strategic_actor_runtime(state)
    runtime = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    content = state.map_metadata.get(ACTOR_CONTENT_KEY)
    if not isinstance(runtime, dict) or not isinstance(content, dict):
        raise Scenario2028AuthorityError("core_2028_actor_runtime_missing")
    content_actors = content.get("actors")
    if not isinstance(content_actors, dict):
        raise Scenario2028AuthorityError("core_2028_actor_content_missing")

    if token not in actors:
        source_id = CORE_2028_OVERLAY_SOURCES[token]
        source_actor = actors.get(source_id)
        source_content = content_actors.get(source_id)
        if source_actor is None or not isinstance(source_content, dict):
            raise Scenario2028AuthorityError(
                f"core_2028_overlay_source_missing:{token}:{source_id}"
            )
        actors[token] = StrategicActorState(
            actor_id=token,
            display_name=CORE_2028_POWER_DISPLAY[token],
            short_name=CORE_2028_POWER_DISPLAY[token],
            actor_type="compatibility",
            coalition_id=source_actor.coalition_id,
            tactical_side=EngineTacticalSide(token),
            playable=True,
            roster_class="compatibility",
            resources=CORE_2028_STARTING_TREASURY[token],
            researched_keys=[],
        )
        content_actors[token] = _rewrite_core_overlay_content(
            source_content,
            source_actor_id=source_id,
            target_actor_id=token,
        )
        content["actor_count"] = len(content_actors)
        state.map_metadata[ACTOR_RUNTIME_KEY]["actors"] = {
            key: actors[key].to_dict() for key in sorted(actors)
        }
        validate_strategic_actor_runtime(state)
        validate_actor_content_runtime(state)

    set_selected_actor(state, token)
    actors = ensure_strategic_actor_runtime(state)
    chosen = actors[token]
    chosen.resources = CORE_2028_STARTING_TREASURY[token]
    chosen.playable = True
    chosen.is_eliminated = False
    nodes = content_actors.get(token, {}).get("research_nodes")
    if isinstance(nodes, dict):
        roots = {
            key for key, node in nodes.items()
            if isinstance(node, dict) and node.get("node_type") == "root"
        }
        chosen.researched_keys = sorted(set(chosen.researched_keys) | roots)
    current = state.map_metadata[ACTOR_RUNTIME_KEY]
    current["actors"] = {key: actors[key].to_dict() for key in sorted(actors)}
    current["selected_actor_id"] = token
    current["current_actor_id"] = token
    selected = str(current.get("selected_actor_id") or "")
    if selected != token or selected == "usa":
        raise Scenario2028AuthorityError(
            f"core_2028_selected_actor_not_bound:{selected}:{token}"
        )


def _build_earth3_base(**options: Any) -> CampaignState:
    from .earth3_bootstrap import build_earth3_v1_campaign
    from .earth3_operational import migrate_earth3_p2_to_p3
    from .operational_capture import ensure_site_control_state

    # Earth3 is the map/force substrate only. Do not persist the Earth3 victory
    # pack onto a 2028 campaign: New Campaign later stamps ww3_2028_core and
    # ensure_campaign_rules fail-closes if objective_pack_id is still earth3_v1.
    earth3_options = dict(options)
    earth3_options["finalize_campaign_rules"] = False
    state = migrate_earth3_p2_to_p3(build_earth3_v1_campaign(**earth3_options))
    ensure_site_control_state(state)
    rules = state.map_metadata.get("campaign_rules")
    if isinstance(rules, dict) and str(rules.get("objective_pack_id") or "") == "earth3_v1":
        # Construction leftover — not a persisted 2028 identity.
        state.map_metadata.pop("campaign_rules", None)
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
