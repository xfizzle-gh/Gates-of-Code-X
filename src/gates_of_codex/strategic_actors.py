from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .faction_wiring_manifest import load_faction_manifest, validate_faction_manifest
from .goc_tactical_army_registry import (
    campaign_faction_token_for_side,
    supported_tactical_sides,
)
from .models import CampaignState, Faction

ACTOR_RUNTIME_SCHEMA_VERSION = 1
CAMPAIGN_SCHEMA_VERSION = 9
ACTOR_RUNTIME_KEY = "strategic_actor_runtime"
ACTOR_MIGRATION_KEY = "strategic_actor_migration"
SUPPORTED_ACTOR_TYPES = {
    "sovereign",
    "separatist",
    "expeditionary",
    "auxiliary",
    "pmc",
    "volunteer",
    "compatibility",
}
SUPPORTED_ROSTER_CLASSES = {
    "full_national",
    "national_hybrid",
    "coalition_fallback",
    "proxy_hybrid",
    "nonstate",
    "compatibility",
    "strategic_only",
}
ACTOR_ALIASES = {
    "nato": "nato",
    "usa": "usa",
    "us": "usa",
    "eng": "gbr",
    "uk": "gbr",
    "gbr": "gbr",
    "ger": "deu",
    "deu": "deu",
    "frg": "deu",
    "fra": "fra",
    "france": "fra",
    "pol": "pol",
    "ita": "ita",
    "fin": "fin",
    "swe": "swe",
    "nld": "nld",
    "can": "can",
    "nor": "nor",
    "dnk": "dnk",
    "esp": "esp",
    "tur": "tur",
    "bel": "bel",
    "belgium": "bel",
    "prt": "prt",
    "portugal": "prt",
    "cze": "cze",
    "czech": "cze",
    "svk": "svk",
    "slovakia": "svk",
    "hun": "hun",
    "hungary": "hun",
    "ltu": "ltu",
    "lithuania": "ltu",
    "lva": "lva",
    "latvia": "lva",
    "est": "est",
    "estonia": "est",
    "aut": "aut",
    "austria": "aut",
    "che": "che",
    "switzerland": "che",
    "irl": "irl",
    "ireland": "irl",
    "isl": "isl",
    "iceland": "isl",
    "rusa": "rus",
    "rus": "rus",
    "russia": "rus",
    "ukr": "ukr",
    "ukraine": "ukr",
    "prc": "prc",
    "china": "prc",
    "kor": "dprk",
    "kpa": "dprk",
    "dprk": "dprk",
    "ldpr": "donbas",
    "dnr": "donbas",
    "lnr": "donbas",
    "donbas": "donbas",
    "blr": "blr",
    "belarus": "blr",
    "serb": "srb",
    "srb": "srb",
    "wagner": "wagner",
    "ildu": "ukr_ildu",
}


class EngineTacticalSide:
    """Engine/DC army token (core side or production goc_*).

    Equality and hashing are identity/token-based only. Campaign province and
    force ownership use core Faction values via explicit ``campaign_faction()``
    conversion at ownership call sites — never via cross-type equality.
    """

    __slots__ = ("value",)

    def __init__(self, value: str | Faction | EngineTacticalSide) -> None:
        if isinstance(value, EngineTacticalSide):
            token = value.value
        elif isinstance(value, Faction):
            token = value.value
        else:
            token = str(value or "").strip().lower()
        allowed = set(supported_tactical_sides()) | {Faction.NEUTRAL.value}
        if token not in allowed:
            raise ValueError(f"Invalid tactical side: {token}")
        self.value = token

    def campaign_faction(self) -> Faction:
        return Faction(campaign_faction_token_for_side(self.value))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EngineTacticalSide):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"EngineTacticalSide({self.value!r})"


@dataclass(slots=True)
class StrategicActorState:
    actor_id: str
    display_name: str
    short_name: str
    actor_type: str
    coalition_id: str
    tactical_side: EngineTacticalSide
    host_actor_id: str | None = None
    playable: bool = True
    roster_class: str = "compatibility"
    resources: int = 1000
    researched_keys: list[str] = field(default_factory=list)
    is_human_controlled: bool = False
    is_eliminated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tactical_side, EngineTacticalSide):
            self.tactical_side = EngineTacticalSide(self.tactical_side)

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.actor_id):
            raise ValueError(f"Invalid strategic actor ID: {self.actor_id}")
        if not self.display_name.strip() or not self.short_name.strip():
            raise ValueError(f"Strategic actor {self.actor_id} must have display names")
        if self.actor_type not in SUPPORTED_ACTOR_TYPES:
            raise ValueError(f"Strategic actor {self.actor_id} has invalid actor type {self.actor_type}")
        if self.roster_class not in SUPPORTED_ROSTER_CLASSES:
            raise ValueError(f"Strategic actor {self.actor_id} has invalid roster class {self.roster_class}")
        if not self.coalition_id.strip():
            raise ValueError(f"Strategic actor {self.actor_id} has no coalition")
        if self.host_actor_id == self.actor_id:
            raise ValueError(f"Strategic actor {self.actor_id} cannot host itself")
        if self.resources < 0:
            raise ValueError(f"Strategic actor {self.actor_id} has negative resources")
        if len(self.researched_keys) != len(set(self.researched_keys)):
            raise ValueError(f"Strategic actor {self.actor_id} has duplicate research keys")
        if not isinstance(self.tactical_side, EngineTacticalSide):
            raise ValueError(f"Strategic actor {self.actor_id} has invalid tactical side type")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tactical_side"] = self.tactical_side.value
        payload["campaign_faction"] = self.tactical_side.campaign_faction().value
        payload["researched_keys"] = sorted(set(self.researched_keys))
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrategicActorState":
        actor = cls(
            actor_id=str(value["actor_id"]),
            display_name=str(value["display_name"]),
            short_name=str(value.get("short_name") or value["display_name"]),
            actor_type=str(value.get("actor_type", "compatibility")),
            coalition_id=str(value.get("coalition_id", "unaligned")),
            tactical_side=EngineTacticalSide(value["tactical_side"]),
            host_actor_id=(None if value.get("host_actor_id") in (None, "") else str(value["host_actor_id"])),
            playable=bool(value.get("playable", True)),
            roster_class=str(value.get("roster_class", "compatibility")),
            resources=int(value.get("resources", 1000)),
            researched_keys=sorted(set(str(item) for item in value.get("researched_keys", []))),
            is_human_controlled=bool(value.get("is_human_controlled", False)),
            is_eliminated=bool(value.get("is_eliminated", False)),
        )
        actor.validate()
        return actor


def ensure_strategic_actor_runtime(state: CampaignState) -> dict[str, StrategicActorState]:
    """Load or explicitly install the actor runtime without changing unrelated saves.

    This function is intentionally not called by the normal force/schema migration path.
    Actor state is created only when an actor-aware API or CLI command is used.
    """

    raw = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if isinstance(raw, dict) and raw.get("schema_version") == ACTOR_RUNTIME_SCHEMA_VERSION:
        actors = _parse_actor_rows(raw.get("actors", {}))
        selected = str(raw.get("selected_actor_id") or "")
        current = str(raw.get("current_actor_id") or selected)
    else:
        actors = _compatibility_actors(state)
        selected = state.selected_faction.value
        current = state.current_faction.value
        state.map_metadata[ACTOR_MIGRATION_KEY] = {
            "schema_version": ACTOR_RUNTIME_SCHEMA_VERSION,
            "mode": "legacy_tactical_faction_compatibility",
            "actors_created": sorted(actors),
            "note": "Legacy tactical factions retained as compatibility strategic actors.",
        }
    if not actors:
        raise ValueError("Campaign must contain at least one strategic actor")

    _normalize_force_actor_ids(state, actors)
    _normalize_province_actor_ids(state, actors)

    selected = _runtime_actor_for_side_or_any(
        actors,
        candidate_id=selected,
        tactical_side=state.selected_faction,
        require_playable=True,
    )
    state.selected_faction = actors[selected].tactical_side.campaign_faction()

    current = _runtime_actor_for_side_or_any(
        actors,
        candidate_id=current,
        tactical_side=state.current_faction,
        require_playable=False,
    )
    state.current_faction = actors[current].tactical_side.campaign_faction()

    _apply_human_control(state, actors, selected)
    _write_runtime(state, actors, selected_actor_id=selected, current_actor_id=current)
    validate_strategic_actor_runtime(state)
    state.schema_version = max(state.schema_version, CAMPAIGN_SCHEMA_VERSION)
    return actors


def install_bundled_strategic_actors(
    state: CampaignState,
    *,
    selected_actor_id: str | None = None,
) -> dict[str, StrategicActorState]:
    manifest = load_faction_manifest()
    validate_faction_manifest(manifest)
    existing = ensure_strategic_actor_runtime(state)
    actors: dict[str, StrategicActorState] = {}
    for row in manifest["actors"]:
        actor_id = row["actor_id"]
        side = EngineTacticalSide(row["tactical_side"])
        prior = existing.get(actor_id)
        tactical_state = state.factions.get(side.campaign_faction().value)
        actors[actor_id] = StrategicActorState(
            actor_id=actor_id,
            display_name=row["display_name"],
            short_name=row.get("short_name", row["display_name"]),
            actor_type=row["actor_type"],
            coalition_id=row["coalition_id"],
            tactical_side=side,
            host_actor_id=row.get("host_actor_id"),
            playable=bool(row["playable"]),
            roster_class=row["roster_class"],
            resources=(prior.resources if prior else (tactical_state.resources if tactical_state else 1000)),
            researched_keys=(list(prior.researched_keys) if prior else []),
            is_human_controlled=False,
            is_eliminated=(prior.is_eliminated if prior else False),
        )

    selected = selected_actor_id or _catalog_actor_for_legacy_selection(actors, state.selected_faction)
    if selected not in actors:
        raise KeyError(f"Unknown strategic actor: {selected}")
    if not actors[selected].playable:
        raise ValueError(f"Strategic actor {selected} is not independently playable")

    _normalize_force_actor_ids(state, actors)
    _normalize_province_actor_ids(state, actors)
    state.selected_faction = actors[selected].tactical_side.campaign_faction()
    state.current_faction = actors[selected].tactical_side.campaign_faction()
    _apply_human_control(state, actors, selected)
    _write_runtime(state, actors, selected_actor_id=selected, current_actor_id=selected)
    state.map_metadata[ACTOR_MIGRATION_KEY] = {
        "schema_version": ACTOR_RUNTIME_SCHEMA_VERSION,
        "mode": "bundled_faction_catalog",
        "manifest_sha256": _manifest_signature(manifest),
        "actor_count": len(actors),
        "note": "Strategic actors installed from the audited faction-wiring manifest.",
    }
    validate_strategic_actor_runtime(state)
    state.schema_version = max(state.schema_version, CAMPAIGN_SCHEMA_VERSION)
    return actors


def strategic_actors(state: CampaignState) -> dict[str, StrategicActorState]:
    return ensure_strategic_actor_runtime(state)


def selected_actor(state: CampaignState) -> StrategicActorState:
    actors = ensure_strategic_actor_runtime(state)
    actor_id = state.map_metadata[ACTOR_RUNTIME_KEY]["selected_actor_id"]
    return actors[actor_id]


def set_selected_actor(state: CampaignState, actor_id: str) -> StrategicActorState:
    actors = ensure_strategic_actor_runtime(state)
    if actor_id not in actors:
        raise KeyError(f"Unknown strategic actor: {actor_id}")
    actor = actors[actor_id]
    if not actor.playable:
        raise ValueError(f"Strategic actor {actor_id} is not independently playable")
    _apply_human_control(state, actors, actor_id)
    state.selected_faction = actor.tactical_side.campaign_faction()
    state.current_faction = actor.tactical_side.campaign_faction()
    _write_runtime(state, actors, selected_actor_id=actor_id, current_actor_id=actor_id)
    validate_strategic_actor_runtime(state)
    return actor


def province_actor_id(state: CampaignState, province_id: str) -> str | None:
    province = state.provinces[province_id]
    raw = province.metadata.get("owner_actor_id")
    if raw:
        return str(raw)
    actors = ensure_strategic_actor_runtime(state)
    if province.owner == Faction.NEUTRAL:
        return None
    return _fallback_actor_for_side(actors, province.owner)


def assign_province_actor(state: CampaignState, province_id: str, actor_id: str | None) -> None:
    province = state.provinces[province_id]
    if actor_id is None:
        province.metadata.pop("owner_actor_id", None)
        return
    actors = ensure_strategic_actor_runtime(state)
    actor = actors.get(actor_id)
    if actor is None:
        raise KeyError(f"Unknown strategic actor: {actor_id}")
    if province.owner != actor.tactical_side.campaign_faction():
        raise ValueError(
            f"Province {province_id} tactical owner {province.owner.value} does not match actor {actor_id} "
            f"side {actor.tactical_side.value} (campaign {actor.tactical_side.campaign_faction().value})"
        )
    province.metadata["owner_actor_id"] = actor_id


def assign_strategic_formation_actor(state: CampaignState, formation_id: str, actor_id: str) -> None:
    actors = ensure_strategic_actor_runtime(state)
    actor = actors.get(actor_id)
    if actor is None:
        raise KeyError(f"Unknown strategic actor: {actor_id}")
    force = state.strategic_formations[formation_id]
    if force.faction != actor.tactical_side.campaign_faction():
        raise ValueError(
            f"Formation {formation_id} tactical side {force.faction.value} does not match actor {actor_id} "
            f"side {actor.tactical_side.value} (campaign {actor.tactical_side.campaign_faction().value})"
        )
    force.actor_id = actor_id
    validate_strategic_actor_runtime(state)


def strategic_actor_snapshot(state: CampaignState) -> dict[str, Any]:
    actors = ensure_strategic_actor_runtime(state)
    runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
    return {
        "schema_version": ACTOR_RUNTIME_SCHEMA_VERSION,
        "selected_actor_id": runtime["selected_actor_id"],
        "current_actor_id": runtime["current_actor_id"],
        "actors": [actors[key].to_dict() for key in sorted(actors)],
    }


def validate_strategic_actor_runtime(state: CampaignState) -> None:
    raw = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Campaign strategic actor runtime is missing")
    actors = _parse_actor_rows(raw.get("actors", {}))
    if not actors:
        raise ValueError("Campaign must contain at least one strategic actor")
    for actor_id, actor in actors.items():
        actor.validate()
        if actor_id != actor.actor_id:
            raise ValueError(f"Strategic actor key mismatch: {actor_id}")
        campaign_side = actor.tactical_side.campaign_faction().value
        if campaign_side not in state.factions:
            raise ValueError(
                f"Strategic actor {actor_id} references missing campaign faction {campaign_side} "
                f"(engine side {actor.tactical_side.value})"
            )
        if actor.host_actor_id and actor.host_actor_id not in actors:
            raise ValueError(f"Strategic actor {actor_id} references missing host {actor.host_actor_id}")
        if actor.host_actor_id and actors[actor.host_actor_id].coalition_id != actor.coalition_id:
            raise ValueError(f"Strategic actor {actor_id} host coalition mismatch")
    selected = str(raw.get("selected_actor_id") or "")
    current = str(raw.get("current_actor_id") or "")
    if selected not in actors or not actors[selected].playable:
        raise ValueError("Campaign selected_actor_id must reference a playable actor")
    if current not in actors:
        raise ValueError("Campaign current_actor_id must reference an actor")
    if state.selected_faction != actors[selected].tactical_side.campaign_faction():
        raise ValueError("Selected strategic actor tactical side does not match selected_faction")
    if state.current_faction != actors[current].tactical_side.campaign_faction():
        raise ValueError("Current strategic actor tactical side does not match current_faction")
    human = sorted(actor.actor_id for actor in actors.values() if actor.is_human_controlled)
    if human != [selected]:
        raise ValueError("Exactly the selected strategic actor must be human controlled")
    for force in state.strategic_formations.values():
        if not force.actor_id:
            continue
        actor = actors.get(force.actor_id)
        if actor is None:
            raise ValueError(f"Strategic formation {force.strategic_formation_id} references missing actor {force.actor_id}")
        if actor.tactical_side.campaign_faction() != force.faction:
            raise ValueError(f"Strategic formation {force.strategic_formation_id} actor tactical-side mismatch")
    for province in state.provinces.values():
        actor_id = province.metadata.get("owner_actor_id")
        if not actor_id:
            continue
        actor = actors.get(str(actor_id))
        if actor is None:
            raise ValueError(f"Province {province.province_id} references missing strategic actor {actor_id}")
        if actor.tactical_side.campaign_faction() != province.owner:
            raise ValueError(f"Province {province.province_id} actor tactical-side mismatch")


def _compatibility_actors(state: CampaignState) -> dict[str, StrategicActorState]:
    actors: dict[str, StrategicActorState] = {}
    display_names = {
        Faction.NATO: "NATO Compatibility Actor",
        Faction.UKRAINE: "Ukraine",
        Faction.RUSSIA: "Russia Compatibility Actor",
        Faction.PRC: "People's Republic of China",
    }
    for faction_state in state.factions.values():
        side = faction_state.faction
        if side == Faction.NEUTRAL:
            continue
        actor_id = side.value
        actors[actor_id] = StrategicActorState(
            actor_id=actor_id,
            display_name=display_names.get(side, side.value.upper()),
            short_name=display_names.get(side, side.value.upper()),
            actor_type="compatibility",
            coalition_id=_coalition_for_side(state, side),
            tactical_side=EngineTacticalSide(side),
            playable=True,
            roster_class="compatibility",
            resources=faction_state.resources,
            researched_keys=list(faction_state.researched_keys),
            is_human_controlled=False,
            is_eliminated=faction_state.is_eliminated,
        )
    return actors


def _parse_actor_rows(raw: Any) -> dict[str, StrategicActorState]:
    if not isinstance(raw, dict):
        raise ValueError("Strategic actor rows must be an object")
    return {str(key): StrategicActorState.from_dict(value) for key, value in raw.items()}


def _write_runtime(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
    *,
    selected_actor_id: str,
    current_actor_id: str,
) -> None:
    state.map_metadata[ACTOR_RUNTIME_KEY] = {
        "schema_version": ACTOR_RUNTIME_SCHEMA_VERSION,
        "selected_actor_id": selected_actor_id,
        "current_actor_id": current_actor_id,
        "actors": {key: actors[key].to_dict() for key in sorted(actors)},
    }


def _apply_human_control(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
    selected_actor_id: str,
) -> None:
    selected = actors[selected_actor_id]
    selected_campaign = selected.tactical_side.campaign_faction()
    for actor in actors.values():
        actor.is_human_controlled = actor.actor_id == selected_actor_id
    for faction_state in state.factions.values():
        faction_state.is_human_controlled = faction_state.faction == selected_campaign


def _normalize_force_actor_ids(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
) -> None:
    for force in state.strategic_formations.values():
        candidate = _resolve_actor_alias(force.actor_id, actors, force.faction)
        if candidate is None:
            candidate = _fallback_actor_for_side(actors, force.faction)
        force.actor_id = candidate


def _normalize_province_actor_ids(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
) -> None:
    for province in state.provinces.values():
        raw = province.metadata.get("owner_actor_id")
        if raw in (None, ""):
            continue
        candidate = _resolve_actor_alias(str(raw), actors, province.owner)
        if candidate is None:
            if province.owner == Faction.NEUTRAL:
                province.metadata.pop("owner_actor_id", None)
                continue
            candidate = _fallback_actor_for_side(actors, province.owner)
        province.metadata["owner_actor_id"] = candidate


def _matches_campaign_side(actor: StrategicActorState, tactical_side: Faction) -> bool:
    return actor.tactical_side.campaign_faction() == tactical_side


def _resolve_actor_alias(
    value: str,
    actors: Mapping[str, StrategicActorState],
    tactical_side: Faction,
) -> str | None:
    raw = str(value or "").strip().lower()
    candidates = [raw, ACTOR_ALIASES.get(raw, "")]
    for candidate in candidates:
        actor = actors.get(candidate)
        if actor is not None and _matches_campaign_side(actor, tactical_side):
            return candidate
    return None


def _runtime_actor_for_side_or_any(
    actors: Mapping[str, StrategicActorState],
    *,
    candidate_id: str,
    tactical_side: Faction,
    require_playable: bool,
) -> str:
    candidate = actors.get(candidate_id)
    if (
        candidate is not None
        and _matches_campaign_side(candidate, tactical_side)
        and (candidate.playable or not require_playable)
    ):
        return candidate_id
    matching = sorted(
        actor.actor_id
        for actor in actors.values()
        if _matches_campaign_side(actor, tactical_side) and (actor.playable or not require_playable)
    )
    if matching:
        return matching[0]
    fallback = sorted(
        actor.actor_id
        for actor in actors.values()
        if actor.playable or not require_playable
    )
    if not fallback:
        qualifier = "playable " if require_playable else ""
        raise ValueError(f"Campaign has no {qualifier}strategic actor")
    return fallback[0]


def _fallback_actor_for_side(
    actors: Mapping[str, StrategicActorState],
    tactical_side: Faction,
) -> str:
    preferred = {
        Faction.NATO: ("nato", "usa", "gbr", "deu"),
        Faction.UKRAINE: ("ukr",),
        Faction.RUSSIA: ("rusa", "rus", "dprk", "blr"),
        Faction.PRC: ("prc",),
    }
    for actor_id in preferred.get(tactical_side, ()):
        if actor_id in actors and actors[actor_id].playable:
            return actor_id
    matching = sorted(
        actor.actor_id
        for actor in actors.values()
        if _matches_campaign_side(actor, tactical_side) and actor.playable
    )
    if not matching:
        raise ValueError(f"No playable strategic actor maps to tactical side {tactical_side.value}")
    return matching[0]


def _catalog_actor_for_legacy_selection(
    actors: Mapping[str, StrategicActorState],
    tactical_side: Faction,
) -> str:
    return _fallback_actor_for_side(actors, tactical_side)


def _coalition_for_side(state: CampaignState, side: Faction) -> str:
    for alliance in state.alliances.values():
        if side in alliance.factions:
            return alliance.alliance_id
    return "unaligned"


def _manifest_signature(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
