from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import (
    Battalion,
    BattalionRosterEntry,
    BattleParticipant,
    CampaignState,
    Faction,
    NEUTRAL_GARRISON_BATTALION_PREFIX,
    PendingBattle,
    Province,
)


AUTHORITY_RELATIVE = Path("src/gates_of_codex/data/neutral_garrisons/authority.json")
AUTHORITY_SCHEMA = "gates.neutral_garrison.v1"
AUTHORITY_SCHEMA_VERSION = 1
RUNTIME_KEY = "neutral_garrison_runtime"
RUNTIME_SCHEMA_VERSION = 1
PROFILE_ID = "issue_48_regional_local_garrison"
TIERS = ("ordinary", "strategic", "capital")
TIER_STRENGTH = {"ordinary": 1, "strategic": 2, "capital": 3}
WEST81_AUTHORITY = "West81"
FORBIDDEN_WORLDWIDE_POOL = "neutral"
_ALLOWED_TOP_LEVEL = frozenset(
    {
        "schema",
        "schema_version",
        "issue",
        "worldwide_fallback",
        "adjacent_variation_threshold_milli",
        "regions",
        "pools",
        "provinces",
    }
)
_ALLOWED_REGION_FIELDS = frozenset({"adjacent_regions", "export_side"})
_ALLOWED_POOL_FIELDS = frozenset({"region", "tier", "units"})
_ALLOWED_UNIT_FIELDS = frozenset(
    {
        "unit_name",
        "quantity",
        "category",
        "source_component",
        "provenance",
        "source_authority",
    }
)
_ALLOWED_PROVINCE_FIELDS = frozenset(
    {
        "province_id",
        "source_id",
        "location_key",
        "neutral_garrison_region",
        "neutral_garrison_tier",
        "pool_family",
        "allowed_pool_tags",
        "adjacent_variation_tags",
    }
)
_ALLOWED_PROVENANCE = frozenset({"legacy_reserve", "encounter_authorized"})
_EXPORT_SIDES = frozenset({"nato", "ukr", "rusa", "prc"})


class NeutralGarrisonError(ValueError):
    """Fail-closed garrison authority or selection error."""


@dataclass(frozen=True, slots=True)
class GarrisonUnit:
    unit_name: str
    quantity: int
    category: str
    source_component: str
    provenance: str
    source_authority: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_name": self.unit_name,
            "quantity": self.quantity,
            "category": self.category,
            "source_component": self.source_component,
            "provenance": self.provenance,
            "source_authority": self.source_authority,
        }


@dataclass(frozen=True, slots=True)
class GarrisonSelection:
    province_id: str
    source_id: int
    location_key: str
    region: str
    tier: str
    pool_family: str
    pool_id: str
    profile_id: str
    variation_applied: bool
    variation_region: str
    selection_signature: str
    export_side: str
    units: tuple[GarrisonUnit, ...]
    source_classifications: tuple[str, ...]
    allowed_pool_tags: tuple[str, ...]
    adjacent_variation_tags: tuple[str, ...]
    authority_digest: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "adjacent_variation_tags": list(self.adjacent_variation_tags),
            "allowed_pool_tags": list(self.allowed_pool_tags),
            "authority_digest": self.authority_digest,
            "export_side": self.export_side,
            "location_key": self.location_key,
            "pool_family": self.pool_family,
            "pool_id": self.pool_id,
            "profile_id": self.profile_id,
            "province_id": self.province_id,
            "region": self.region,
            "selection_signature": self.selection_signature,
            "source_classifications": list(self.source_classifications),
            "source_id": self.source_id,
            "tier": self.tier,
            "units": [unit.to_dict() for unit in self.units],
            "variation_applied": self.variation_applied,
            "variation_region": self.variation_region,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_canonical_dict())


def garrison_battalion_id(province_id: str) -> str:
    return f"{NEUTRAL_GARRISON_BATTALION_PREFIX}{province_id}"


def is_garrison_battalion_id(battalion_id: str) -> bool:
    return str(battalion_id or "").startswith(NEUTRAL_GARRISON_BATTALION_PREFIX)


def authority_path(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    return (root / AUTHORITY_RELATIVE).resolve()


_AUTHORITY_CACHE: dict[str, dict[str, Any]] = {}


def load_garrison_authority(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else authority_path()
    cache_key = str(target)
    cached = _AUTHORITY_CACHE.get(cache_key)
    if cached is not None and path is None:
        return cached
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise NeutralGarrisonError(f"neutral garrison authority is missing: {target}") from exc
    payload = _strict_json_object(raw, label=str(target))
    validate_garrison_authority(payload)
    if path is None:
        _AUTHORITY_CACHE[cache_key] = payload
    return payload


def validate_garrison_authority(payload: Mapping[str, Any]) -> None:
    unknown = set(payload) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise NeutralGarrisonError(
            f"neutral garrison authority has unknown fields: {sorted(unknown)}"
        )
    if payload.get("schema") != AUTHORITY_SCHEMA:
        raise NeutralGarrisonError("neutral garrison authority schema is not recognized")
    if payload.get("schema_version") != AUTHORITY_SCHEMA_VERSION:
        raise NeutralGarrisonError("neutral garrison authority schema_version is unsupported")
    if payload.get("issue") != 48:
        raise NeutralGarrisonError("neutral garrison authority issue marker must be 48")
    if payload.get("worldwide_fallback") is not False:
        raise NeutralGarrisonError("worldwide neutral garrison fallback is forbidden")
    threshold = payload.get("adjacent_variation_threshold_milli")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 0 <= threshold <= 1000:
        raise NeutralGarrisonError("adjacent_variation_threshold_milli must be an int 0..1000")
    regions = payload.get("regions")
    if not isinstance(regions, dict) or not regions:
        raise NeutralGarrisonError("neutral garrison regions must be a nonempty object")
    for region_id, region in regions.items():
        _validate_region(str(region_id), region, known_regions=set(regions))
    if FORBIDDEN_WORLDWIDE_POOL in regions:
        raise NeutralGarrisonError("universal worldwide neutral region is forbidden")
    pools = payload.get("pools")
    if not isinstance(pools, dict) or not pools:
        raise NeutralGarrisonError("neutral garrison pools must be a nonempty object")
    for pool_id, pool in pools.items():
        _validate_pool(str(pool_id), pool, known_regions=set(regions))
    provinces = payload.get("provinces")
    if not isinstance(provinces, list) or not provinces:
        raise NeutralGarrisonError("neutral garrison provinces must be a nonempty array")
    seen_ids: set[str] = set()
    seen_sources: set[int] = set()
    for index, row in enumerate(provinces):
        _validate_province_row(
            row,
            index=index,
            regions=regions,
            known_pools=set(pools),
            seen_ids=seen_ids,
            seen_sources=seen_sources,
        )


def authority_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def campaign_garrison_seed(state: CampaignState) -> str:
    metadata = state.map_metadata if isinstance(state.map_metadata, dict) else {}
    for key in ("neutral_garrison_seed", "campaign_seed"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return str(state.campaign_name or "")


def select_neutral_garrison(
    province_id: str,
    *,
    authority: Mapping[str, Any] | None = None,
    campaign_seed: str = "",
    catalog: Mapping[str, Any] | None = None,
) -> GarrisonSelection:
    payload = authority if authority is not None else load_garrison_authority()
    validate_garrison_authority(payload)
    row = _province_row(payload, province_id)
    region_id = str(row["neutral_garrison_region"])
    tier = str(row["neutral_garrison_tier"])
    family = str(row["pool_family"])
    adjacent_tags = tuple(str(item) for item in row["adjacent_variation_tags"])
    digest = authority_digest(payload)
    signature = _selection_signature(
        campaign_seed=campaign_seed,
        province_id=str(row["province_id"]),
        source_id=int(row["source_id"]),
        region=region_id,
        tier=tier,
        pool_family=family,
        adjacent_tags=adjacent_tags,
        authority_digest=digest,
    )
    variation_region = ""
    variation_applied = False
    selected_family = family
    selected_region = region_id
    threshold = int(payload["adjacent_variation_threshold_milli"])
    roll = int.from_bytes(bytes.fromhex(signature[:4]), "big") % 1000
    if adjacent_tags and roll < threshold:
        pick = int.from_bytes(bytes.fromhex(signature[4:8]), "big") % len(adjacent_tags)
        candidate = adjacent_tags[pick]
        region_spec = payload["regions"][region_id]
        allowed = tuple(str(item) for item in region_spec["adjacent_regions"])
        if candidate not in allowed:
            raise NeutralGarrisonError(
                f"adjacent variation {candidate!r} is not compatible with {region_id}"
            )
        candidate_family = _family_for_region(payload, candidate)
        selected_family = candidate_family
        selected_region = candidate
        variation_region = candidate
        variation_applied = True
    pool_id = f"{selected_family}.{tier}"
    pools = payload["pools"]
    if pool_id not in pools:
        raise NeutralGarrisonError(
            f"garrison pool {pool_id!r} is not authored for province {province_id}"
        )
    pool = pools[pool_id]
    if str(pool["region"]) != selected_region:
        raise NeutralGarrisonError(
            f"garrison pool {pool_id} region {pool['region']!r} does not match {selected_region}"
        )
    if str(pool["tier"]) != tier:
        raise NeutralGarrisonError(f"garrison pool {pool_id} tier mismatch")
    units = tuple(_unit_from_payload(item) for item in pool["units"])
    if not units:
        raise NeutralGarrisonError(f"garrison pool {pool_id} has no units")
    _reject_cross_world_leak(selected_region, units)
    validate_units_resolvable(units, catalog=catalog)
    classifications = tuple(sorted({unit.provenance for unit in units}))
    export_side = str(payload["regions"][selected_region]["export_side"])
    return GarrisonSelection(
        province_id=str(row["province_id"]),
        source_id=int(row["source_id"]),
        location_key=str(row["location_key"]),
        region=selected_region,
        tier=tier,
        pool_family=selected_family,
        pool_id=pool_id,
        profile_id=PROFILE_ID,
        variation_applied=variation_applied,
        variation_region=variation_region,
        selection_signature=signature,
        export_side=export_side,
        units=units,
        source_classifications=classifications,
        allowed_pool_tags=tuple(str(item) for item in row["allowed_pool_tags"]),
        adjacent_variation_tags=adjacent_tags,
        authority_digest=digest,
    )


def validate_units_resolvable(
    units: Iterable[GarrisonUnit],
    *,
    catalog: Mapping[str, Any] | None = None,
) -> None:
    seen: set[str] = set()
    for unit in units:
        if unit.unit_name in seen:
            raise NeutralGarrisonError(f"garrison pool repeats unit {unit.unit_name}")
        seen.add(unit.unit_name)
        if catalog is not None and unit.unit_name not in catalog:
            raise NeutralGarrisonError(
                f"garrison unit is unresolvable: {unit.unit_name}"
            )


def province_has_garrison_metadata(
    province_id: str,
    *,
    authority: Mapping[str, Any] | None = None,
) -> bool:
    payload = authority if authority is not None else load_garrison_authority()
    return any(
        isinstance(row, dict) and str(row.get("province_id")) == province_id
        for row in payload.get("provinces", [])
    )


def garrison_is_defeated(state: CampaignState, province_id: str) -> bool:
    record = _runtime_province(state, province_id)
    return bool(record.get("defeated"))


def maybe_attach_neutral_garrison(
    state: CampaignState,
    province_id: str,
    *,
    attacker: Battalion,
    authority: Mapping[str, Any] | None = None,
    catalog: Mapping[str, Any] | None = None,
) -> PendingBattle | None:
    province = state.provinces.get(province_id)
    if province is None:
        raise NeutralGarrisonError(f"unknown province for garrison encounter: {province_id}")
    if province.owner != Faction.NEUTRAL:
        return None
    payload = authority if authority is not None else load_garrison_authority()
    if not province_has_garrison_metadata(province_id, authority=payload):
        return None
    if garrison_is_defeated(state, province_id):
        return None
    existing = state.battalions.get(garrison_battalion_id(province_id))
    if existing is not None and existing.unit_count <= 0:
        _mark_defeated(state, province_id)
        return None
    if state.pending_battle is not None:
        raise NeutralGarrisonError("pending battle already exists")
    selection = _selection_for_state(
        state,
        province,
        authority=payload,
        catalog=catalog,
    )
    battalion = _ensure_garrison_battalion(state, province, selection)
    pending = PendingBattle(
        battle_id=_deterministic_battle_id(state, province_id, selection.selection_signature),
        origin_province_id=attacker.province_id,
        target_province_id=province_id,
        attacker_faction=attacker.faction,
        defender_faction=Faction.NEUTRAL,
        attacking_participants=[
            BattleParticipant(attacker.battalion_id, attacker.faction, "stage_1", True)
        ],
        defending_participants=[
            BattleParticipant(battalion.battalion_id, Faction.NEUTRAL, "stage_2", True)
        ],
        player_faction=state.selected_faction,
        player_is_attacker=attacker.faction == state.selected_faction,
    )
    state.pending_battle = pending
    _store_encounter_record(state, pending.battle_id, selection)
    return pending


def sync_neutral_garrison_after_battle(
    state: CampaignState,
    pending: PendingBattle,
    winner: Faction,
) -> None:
    defender_ids = [
        item.battalion_id
        for item in pending.defending_participants
        if is_garrison_battalion_id(item.battalion_id)
    ]
    if not defender_ids:
        return
    province_id = pending.target_province_id
    runtime = _runtime(state)
    provinces = runtime.setdefault("provinces", {})
    record = dict(provinces.get(province_id) or {})
    battalion = state.battalions.get(defender_ids[0])
    if winner == pending.attacker_faction or battalion is None or battalion.unit_count <= 0:
        record["defeated"] = True
        record["readiness_milli"] = 0
        record["roster"] = []
        if battalion is not None and battalion.battalion_id in state.battalions:
            del state.battalions[battalion.battalion_id]
    else:
        record["defeated"] = False
        record["readiness_milli"] = max(0, min(1000, battalion.condition * 10))
        record["roster"] = [
            {"unit_name": entry.unit_name, "quantity": entry.quantity, "category": entry.category}
            for entry in battalion.roster
        ]
        record["condition"] = battalion.condition
    provinces[province_id] = record
    runtime["provinces"] = _sorted_mapping(provinces)
    state.map_metadata[RUNTIME_KEY] = runtime


def export_garrison_profile(state: CampaignState, pending: PendingBattle | None = None) -> dict[str, Any] | None:
    battle = pending if pending is not None else state.pending_battle
    runtime = _runtime(state)
    payload = None
    if battle is not None:
        encounters = runtime.get("encounters")
        if isinstance(encounters, dict) and isinstance(encounters.get(battle.battle_id), dict):
            payload = encounters[battle.battle_id]
        elif any(is_garrison_battalion_id(item.battalion_id) for item in battle.defending_participants):
            record = _runtime_province(state, battle.target_province_id)
            if isinstance(record.get("selection"), dict):
                payload = record["selection"]
                _store_encounter_record(state, battle.battle_id, _selection_from_runtime(payload))
    if not isinstance(payload, dict):
        return None
    return json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def strategic_isolation_snapshot(state: CampaignState) -> dict[str, Any]:
    factions = {
        key: {
            "resources": int(row.resources),
            "researched_keys": list(row.researched_keys),
            "recruited_pool": [
                {"unit_name": item.unit_name, "quantity": item.quantity}
                for item in row.recruited_pool
            ],
            "reinforcement_pool": [
                {
                    "unit_name": item.unit_name,
                    "quantity": item.quantity,
                    "formation_id": item.formation_id,
                }
                for item in row.reinforcement_pool
            ],
        }
        for key, row in sorted(state.factions.items())
    }
    provinces = {
        key: {
            "owner": province.owner.value,
            "owner_actor_id": province.metadata.get("owner_actor_id"),
        }
        for key, province in sorted(state.provinces.items())
    }
    actors = (state.map_metadata.get("strategic_actor_runtime") or {})
    return {
        "alliances": {
            key: [faction.value for faction in alliance.factions]
            for key, alliance in sorted(state.alliances.items())
        },
        "factions": factions,
        "provinces": provinces,
        "selected_actor_id": actors.get("selected_actor_id") if isinstance(actors, dict) else None,
        "current_actor_id": actors.get("current_actor_id") if isinstance(actors, dict) else None,
    }


def _selection_for_state(
    state: CampaignState,
    province: Province,
    *,
    authority: Mapping[str, Any],
    catalog: Mapping[str, Any] | None,
) -> GarrisonSelection:
    runtime_record = _runtime_province(state, province.province_id)
    if runtime_record.get("selection"):
        payload = runtime_record["selection"]
        if not isinstance(payload, dict):
            raise NeutralGarrisonError("persisted garrison selection is invalid")
        return _selection_from_runtime(payload)
    source_id = province.metadata.get("source_id")
    row = _province_row(authority, province.province_id)
    if source_id not in (None, "") and int(source_id) != int(row["source_id"]):
        raise NeutralGarrisonError(
            f"province {province.province_id} source_id does not match garrison authority"
        )
    selection = select_neutral_garrison(
        province.province_id,
        authority=authority,
        campaign_seed=campaign_garrison_seed(state),
        catalog=catalog,
    )
    _store_province_selection(state, selection)
    return selection


def _ensure_garrison_battalion(
    state: CampaignState,
    province: Province,
    selection: GarrisonSelection,
) -> Battalion:
    battalion_id = garrison_battalion_id(province.province_id)
    existing = state.battalions.get(battalion_id)
    if existing is not None:
        if existing.faction != Faction.NEUTRAL:
            raise NeutralGarrisonError(f"{battalion_id} is not a neutral garrison")
        if existing.strategic_formation_id:
            raise NeutralGarrisonError(f"{battalion_id} must not have a strategic formation")
        return existing
    runtime_record = _runtime_province(state, province.province_id)
    roster_payload = runtime_record.get("roster")
    if isinstance(roster_payload, list) and roster_payload:
        roster = [
            BattalionRosterEntry(
                unit_name=str(item["unit_name"]),
                quantity=int(item["quantity"]),
                category=str(item.get("category") or "unknown"),
            )
            for item in roster_payload
        ]
        condition = int(runtime_record.get("condition") or 100)
    else:
        roster = [
            BattalionRosterEntry(unit.unit_name, unit.quantity, category=unit.category)
            for unit in selection.units
        ]
        condition = 100
    battalion = Battalion(
        battalion_id=battalion_id,
        faction=Faction.NEUTRAL,
        province_id=province.province_id,
        roster=roster,
        condition=max(10, min(100, condition)),
    )
    battalion.validate()
    state.battalions[battalion_id] = battalion
    return battalion


def _store_province_selection(state: CampaignState, selection: GarrisonSelection) -> None:
    runtime = _runtime(state)
    provinces = runtime.setdefault("provinces", {})
    record = dict(provinces.get(selection.province_id) or {})
    record.update(
        {
            "defeated": False,
            "province_id": selection.province_id,
            "readiness_milli": 1000,
            "selection": selection.to_canonical_dict(),
        }
    )
    provinces[selection.province_id] = record
    runtime["provinces"] = _sorted_mapping(provinces)
    state.map_metadata[RUNTIME_KEY] = runtime


def _store_encounter_record(
    state: CampaignState,
    battle_id: str,
    selection: GarrisonSelection,
) -> None:
    runtime = _runtime(state)
    encounters = runtime.setdefault("encounters", {})
    encounters[battle_id] = selection.to_canonical_dict()
    runtime["encounters"] = _sorted_mapping(encounters)
    state.map_metadata[RUNTIME_KEY] = runtime


def _runtime(state: CampaignState) -> dict[str, Any]:
    raw = state.map_metadata.get(RUNTIME_KEY)
    if raw is None:
        payload = {"schema_version": RUNTIME_SCHEMA_VERSION, "encounters": {}, "provinces": {}}
        state.map_metadata[RUNTIME_KEY] = payload
        return payload
    if not isinstance(raw, dict):
        raise NeutralGarrisonError("neutral_garrison_runtime must be an object")
    if raw.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise NeutralGarrisonError("neutral_garrison_runtime schema_version is unsupported")
    return raw


def _runtime_province(state: CampaignState, province_id: str) -> dict[str, Any]:
    runtime = state.map_metadata.get(RUNTIME_KEY)
    if not isinstance(runtime, dict):
        return {}
    provinces = runtime.get("provinces")
    if not isinstance(provinces, dict):
        return {}
    record = provinces.get(province_id)
    return dict(record) if isinstance(record, dict) else {}


def _mark_defeated(state: CampaignState, province_id: str) -> None:
    runtime = _runtime(state)
    provinces = runtime.setdefault("provinces", {})
    record = dict(provinces.get(province_id) or {})
    record["defeated"] = True
    record["readiness_milli"] = 0
    provinces[province_id] = record
    runtime["provinces"] = _sorted_mapping(provinces)
    state.map_metadata[RUNTIME_KEY] = runtime


def _selection_from_runtime(payload: Mapping[str, Any]) -> GarrisonSelection:
    units = tuple(_unit_from_payload(item) for item in payload.get("units") or ())
    if not units:
        raise NeutralGarrisonError("persisted garrison selection has no units")
    return GarrisonSelection(
        province_id=str(payload["province_id"]),
        source_id=int(payload["source_id"]),
        location_key=str(payload["location_key"]),
        region=str(payload["region"]),
        tier=str(payload["tier"]),
        pool_family=str(payload["pool_family"]),
        pool_id=str(payload["pool_id"]),
        profile_id=str(payload["profile_id"]),
        variation_applied=bool(payload["variation_applied"]),
        variation_region=str(payload.get("variation_region") or ""),
        selection_signature=str(payload["selection_signature"]),
        export_side=str(payload["export_side"]),
        units=units,
        source_classifications=tuple(str(item) for item in payload.get("source_classifications") or ()),
        allowed_pool_tags=tuple(str(item) for item in payload.get("allowed_pool_tags") or ()),
        adjacent_variation_tags=tuple(str(item) for item in payload.get("adjacent_variation_tags") or ()),
        authority_digest=str(payload["authority_digest"]),
    )


def _province_row(payload: Mapping[str, Any], province_id: str) -> dict[str, Any]:
    matches = [
        row
        for row in payload.get("provinces", [])
        if isinstance(row, dict) and str(row.get("province_id")) == province_id
    ]
    if not matches:
        raise NeutralGarrisonError(
            f"missing garrison-region metadata for province {province_id}"
        )
    if len(matches) != 1:
        raise NeutralGarrisonError(f"duplicate garrison metadata for province {province_id}")
    return matches[0]


def _family_for_region(payload: Mapping[str, Any], region_id: str) -> str:
    if f"{region_id}.ordinary" in payload["pools"]:
        return region_id
    families = sorted(
        {
            str(pool_id).rsplit(".", 1)[0]
            for pool_id, pool in payload["pools"].items()
            if str(pool.get("region")) == region_id
        }
    )
    if not families:
        raise NeutralGarrisonError(f"no garrison pool family exists for region {region_id}")
    return families[0]


def _unit_from_payload(item: Mapping[str, Any]) -> GarrisonUnit:
    if not isinstance(item, dict):
        raise NeutralGarrisonError("garrison unit must be an object")
    return GarrisonUnit(
        unit_name=str(item["unit_name"]),
        quantity=int(item["quantity"]),
        category=str(item["category"]),
        source_component=str(item["source_component"]),
        provenance=str(item["provenance"]),
        source_authority=str(item["source_authority"]),
    )


def _validate_region(region_id: str, region: Any, *, known_regions: set[str]) -> None:
    if not region_id:
        raise NeutralGarrisonError("invalid garrison region id")
    if not isinstance(region, dict):
        raise NeutralGarrisonError(f"garrison region {region_id} must be an object")
    unknown = set(region) - _ALLOWED_REGION_FIELDS
    if unknown:
        raise NeutralGarrisonError(
            f"garrison region {region_id} has unknown fields: {sorted(unknown)}"
        )
    adjacent = region.get("adjacent_regions")
    if not isinstance(adjacent, list) or any(not isinstance(item, str) for item in adjacent):
        raise NeutralGarrisonError(f"garrison region {region_id} adjacent_regions must be strings")
    if adjacent != sorted(adjacent) or len(set(adjacent)) != len(adjacent):
        raise NeutralGarrisonError(
            f"garrison region {region_id} adjacent_regions must be unique and sorted"
        )
    if region_id in adjacent:
        raise NeutralGarrisonError(f"garrison region {region_id} cannot be adjacent to itself")
    if any(item not in known_regions for item in adjacent):
        raise NeutralGarrisonError(f"garrison region {region_id} references unknown adjacent region")
    if str(region.get("export_side")) not in _EXPORT_SIDES:
        raise NeutralGarrisonError(f"garrison region {region_id} has invalid export_side")


def _validate_pool(pool_id: str, pool: Any, *, known_regions: set[str]) -> None:
    if not isinstance(pool, dict):
        raise NeutralGarrisonError(f"garrison pool {pool_id} must be an object")
    unknown = set(pool) - _ALLOWED_POOL_FIELDS
    if unknown:
        raise NeutralGarrisonError(f"garrison pool {pool_id} has unknown fields: {sorted(unknown)}")
    region = str(pool.get("region") or "")
    tier = str(pool.get("tier") or "")
    if region not in known_regions:
        raise NeutralGarrisonError(f"garrison pool {pool_id} has unknown region {region}")
    if tier not in TIERS:
        raise NeutralGarrisonError(f"garrison pool {pool_id} has unknown tier {tier}")
    if not pool_id.endswith(f".{tier}"):
        raise NeutralGarrisonError(f"garrison pool id {pool_id} does not match tier {tier}")
    units = pool.get("units")
    if not isinstance(units, list) or not units:
        raise NeutralGarrisonError(f"garrison pool {pool_id} must list units")
    seen: set[str] = set()
    for item in units:
        if not isinstance(item, dict):
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit must be an object")
        unknown_unit = set(item) - _ALLOWED_UNIT_FIELDS
        if unknown_unit:
            raise NeutralGarrisonError(
                f"garrison pool {pool_id} unit has unknown fields: {sorted(unknown_unit)}"
            )
        name = str(item.get("unit_name") or "").strip()
        if not name:
            raise NeutralGarrisonError(f"garrison pool {pool_id} has an empty unit_name")
        if name in seen:
            raise NeutralGarrisonError(f"garrison pool {pool_id} repeats unit {name}")
        seen.add(name)
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit {name} quantity is invalid")
        if not str(item.get("category") or "").strip():
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit {name} category is required")
        if not str(item.get("source_component") or "").strip():
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit {name} source_component is required")
        provenance = str(item.get("provenance") or "")
        if provenance not in _ALLOWED_PROVENANCE:
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit {name} provenance is invalid")
        source_authority = str(item.get("source_authority") or "")
        if not source_authority:
            raise NeutralGarrisonError(f"garrison pool {pool_id} unit {name} source_authority is required")
        if source_authority == WEST81_AUTHORITY and provenance != "legacy_reserve":
            raise NeutralGarrisonError(
                f"West81 unit {name} must retain legacy_reserve provenance"
            )
    _reject_cross_world_leak(region, (_unit_from_payload(item) for item in units))


def _validate_province_row(
    row: Any,
    *,
    index: int,
    regions: Mapping[str, Any],
    known_pools: set[str],
    seen_ids: set[str],
    seen_sources: set[int],
) -> None:
    if not isinstance(row, dict):
        raise NeutralGarrisonError(f"garrison province row {index} must be an object")
    unknown = set(row) - _ALLOWED_PROVINCE_FIELDS
    if unknown:
        raise NeutralGarrisonError(
            f"garrison province row {index} has unknown fields: {sorted(unknown)}"
        )
    province_id = str(row.get("province_id") or "")
    if not province_id.startswith("e3_"):
        raise NeutralGarrisonError(f"garrison province row {index} province_id is invalid")
    if province_id in seen_ids:
        raise NeutralGarrisonError(f"duplicate garrison province_id {province_id}")
    seen_ids.add(province_id)
    source_id = row.get("source_id")
    if not isinstance(source_id, int) or isinstance(source_id, bool) or source_id < 0:
        raise NeutralGarrisonError(f"garrison province {province_id} source_id is invalid")
    if source_id in seen_sources:
        raise NeutralGarrisonError(f"duplicate garrison source_id {source_id}")
    seen_sources.add(source_id)
    if not str(row.get("location_key") or "").strip():
        raise NeutralGarrisonError(f"garrison province {province_id} location_key is required")
    region = str(row.get("neutral_garrison_region") or "")
    if region not in regions:
        raise NeutralGarrisonError(
            f"unknown garrison-region metadata for province {province_id}: {region}"
        )
    tier = str(row.get("neutral_garrison_tier") or "")
    if tier not in TIERS:
        raise NeutralGarrisonError(f"garrison province {province_id} has unknown tier {tier}")
    family = str(row.get("pool_family") or "")
    pool_id = f"{family}.{tier}"
    if pool_id not in known_pools:
        raise NeutralGarrisonError(
            f"garrison province {province_id} pool {pool_id} is not authored"
        )
    tags = row.get("allowed_pool_tags")
    adjacent = row.get("adjacent_variation_tags")
    if not isinstance(tags, list) or any(not isinstance(item, str) or not item for item in tags):
        raise NeutralGarrisonError(f"garrison province {province_id} allowed_pool_tags is invalid")
    if tags != sorted(tags) or len(set(tags)) != len(tags):
        raise NeutralGarrisonError(
            f"garrison province {province_id} allowed_pool_tags must be unique and sorted"
        )
    if not isinstance(adjacent, list) or any(not isinstance(item, str) for item in adjacent):
        raise NeutralGarrisonError(
            f"garrison province {province_id} adjacent_variation_tags is invalid"
        )
    if adjacent != sorted(adjacent) or len(set(adjacent)) != len(adjacent):
        raise NeutralGarrisonError(
            f"garrison province {province_id} adjacent_variation_tags must be unique and sorted"
        )
    allowed_adjacent = set(regions[region]["adjacent_regions"])
    if any(item not in regions for item in adjacent):
        raise NeutralGarrisonError(
            f"garrison province {province_id} adjacent tag is not an authored region"
        )
    illegal = [item for item in adjacent if item not in allowed_adjacent]
    if illegal:
        raise NeutralGarrisonError(
            f"garrison province {province_id} adjacent variation escapes compatibility: {illegal}"
        )
    if region in adjacent:
        raise NeutralGarrisonError(
            f"garrison province {province_id} cannot list its own region as adjacent variation"
        )


def _reject_cross_world_leak(region: str, units: Iterable[GarrisonUnit]) -> None:
    names = {unit.unit_name.lower() for unit in units}
    components = {unit.source_component for unit in units}
    if region in {"balkans", "western_central_europe"}:
        if any("wgn" in name or name.startswith("sto_") for name in names) or "wagner_native" in components:
            raise NeutralGarrisonError(
                f"{region} garrison must not include Wagner/Africa PMC content"
            )
    if region == "western_central_europe":
        if any(name.startswith("goc_serb_") for name in names):
            raise NeutralGarrisonError("western_central_europe must not use Balkan serb squads as the home pool")
    if region in {"north_africa", "middle_east", "western_asia", "balkans", "eastern_europe"}:
        if any(name.startswith("goc_ildu_") for name in names) or "ukraine_ildu" in components:
            raise NeutralGarrisonError(
                f"{region} garrison must not include ILDU compatibility wrappers"
            )


def _selection_signature(
    *,
    campaign_seed: str,
    province_id: str,
    source_id: int,
    region: str,
    tier: str,
    pool_family: str,
    adjacent_tags: tuple[str, ...],
    authority_digest: str,
) -> str:
    payload = {
        "adjacent_variation_tags": list(adjacent_tags),
        "authority_digest": authority_digest,
        "campaign_seed": campaign_seed,
        "pool_family": pool_family,
        "province_id": province_id,
        "region": region,
        "source_id": source_id,
        "tier": tier,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _deterministic_battle_id(state: CampaignState, province_id: str, signature: str) -> str:
    material = _canonical_json_bytes(
        {
            "campaign_name": state.campaign_name,
            "province_id": province_id,
            "signature": signature,
            "turn_number": state.turn_number,
        }
    )
    return f"goc-48-{hashlib.sha256(material).hexdigest()[:12]}"


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sorted_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in sorted(payload)}


def _strict_json_object(raw_bytes: bytes, *, label: str) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise NeutralGarrisonError(f"{label} contains duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        parsed = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=pairs_hook)
    except NeutralGarrisonError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NeutralGarrisonError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise NeutralGarrisonError(f"{label} must be a JSON object")
    return parsed
