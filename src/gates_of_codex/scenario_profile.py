from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import CampaignState


SCENARIO_PROFILE_SCHEMA = "gates-of-codex.scenario-profile"
SCENARIO_PROFILE_VERSION = 1
SCENARIO_PROFILE_METADATA_KEY = "scenario_profile"


class ScenarioProfileError(ValueError):
    """Persisted scenario identity is absent, unknown, or incompatible."""


@dataclass(frozen=True, slots=True)
class ScenarioProfileIdentity:
    scenario_id: str
    scenario_version: str
    shared_world_authority_id: str = ""
    actor_catalog_id: str = ""
    actor_catalog_compatibility_version: str = ""

    def validate(self) -> None:
        if not self.scenario_id.strip():
            raise ScenarioProfileError("scenario_profile_scenario_id_required")
        if not self.scenario_version.strip():
            raise ScenarioProfileError("scenario_profile_version_required")
        for name, value in (
            ("shared_world_authority_id", self.shared_world_authority_id),
            ("actor_catalog_id", self.actor_catalog_id),
            ("actor_catalog_compatibility_version", self.actor_catalog_compatibility_version),
        ):
            if not isinstance(value, str):
                raise ScenarioProfileError(f"scenario_profile_{name}_must_be_string")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": SCENARIO_PROFILE_SCHEMA,
            "version": SCENARIO_PROFILE_VERSION,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "shared_world_authority_id": self.shared_world_authority_id,
            "actor_catalog_id": self.actor_catalog_id,
            "actor_catalog_compatibility_version": self.actor_catalog_compatibility_version,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScenarioProfileIdentity":
        if payload.get("schema") != SCENARIO_PROFILE_SCHEMA:
            raise ScenarioProfileError("scenario_profile_schema_mismatch")
        if payload.get("version") != SCENARIO_PROFILE_VERSION:
            raise ScenarioProfileError("scenario_profile_contract_version_mismatch")
        identity = cls(
            scenario_id=_required_string(payload, "scenario_id"),
            scenario_version=_required_string(payload, "scenario_version"),
            shared_world_authority_id=_optional_string(payload, "shared_world_authority_id"),
            actor_catalog_id=_optional_string(payload, "actor_catalog_id"),
            actor_catalog_compatibility_version=_optional_string(
                payload, "actor_catalog_compatibility_version"
            ),
        )
        identity.validate()
        return identity


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioProfileError(f"scenario_profile_{key}_required")
    return value.strip()


def _optional_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ScenarioProfileError(f"scenario_profile_{key}_must_be_string")
    return value.strip()


def stamp_scenario_profile(state: CampaignState, identity: ScenarioProfileIdentity) -> None:
    state.map_metadata[SCENARIO_PROFILE_METADATA_KEY] = identity.to_dict()


def persisted_scenario_profile(state: CampaignState) -> ScenarioProfileIdentity | None:
    payload = state.map_metadata.get(SCENARIO_PROFILE_METADATA_KEY)
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ScenarioProfileError("scenario_profile_metadata_must_be_object")
    return ScenarioProfileIdentity.from_mapping(payload)


def require_compatible_scenario_profile(
    state: CampaignState,
    expected: ScenarioProfileIdentity,
    *,
    allow_legacy_unprofiled: bool = False,
) -> ScenarioProfileIdentity:
    actual = persisted_scenario_profile(state)
    if actual is None:
        if allow_legacy_unprofiled and state.map_metadata.get("scenario_id") == expected.scenario_id:
            return expected
        raise ScenarioProfileError("scenario_profile_missing")
    if actual.scenario_id != expected.scenario_id:
        raise ScenarioProfileError(
            f"scenario_profile_id_mismatch:{actual.scenario_id}:{expected.scenario_id}"
        )
    if actual.scenario_version != expected.scenario_version:
        raise ScenarioProfileError(
            "scenario_profile_version_incompatible:"
            f"{actual.scenario_version}:{expected.scenario_version}"
        )
    if actual.shared_world_authority_id != expected.shared_world_authority_id:
        raise ScenarioProfileError("scenario_profile_world_authority_incompatible")
    if actual.actor_catalog_id != expected.actor_catalog_id:
        raise ScenarioProfileError("scenario_profile_actor_catalog_incompatible")
    if (
        actual.actor_catalog_compatibility_version
        != expected.actor_catalog_compatibility_version
    ):
        raise ScenarioProfileError("scenario_profile_actor_catalog_version_incompatible")
    return actual
