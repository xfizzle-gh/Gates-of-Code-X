from __future__ import annotations

from types import SimpleNamespace

import pytest

from gates_of_codex.scenario import get_scenario
from gates_of_codex.scenario_profile import (
    ScenarioProfileError,
    ScenarioProfileIdentity,
    persisted_scenario_profile,
    require_compatible_scenario_profile,
    stamp_scenario_profile,
)


def _state(*, scenario_id: str = "ww3_2028_core") -> SimpleNamespace:
    return SimpleNamespace(map_metadata={"scenario_id": scenario_id})


def _identity(*, scenario_id: str = "ww3_2028_core") -> ScenarioProfileIdentity:
    return ScenarioProfileIdentity(
        scenario_id=scenario_id,
        scenario_version="1",
        shared_world_authority_id="earth3_ww3_2028_v1",
        actor_catalog_id="core_2028",
        actor_catalog_compatibility_version="1",
    )


def test_profile_round_trips_through_persisted_metadata() -> None:
    state = _state()
    expected = _identity()
    stamp_scenario_profile(state, expected)
    assert persisted_scenario_profile(state) == expected
    assert require_compatible_scenario_profile(state, expected) == expected


def test_profile_rejects_wrong_scenario_even_if_world_authority_matches() -> None:
    state = _state()
    stamp_scenario_profile(state, _identity(scenario_id="ww3_2028_expanded"))
    with pytest.raises(ScenarioProfileError, match="scenario_profile_id_mismatch"):
        require_compatible_scenario_profile(state, _identity())


def test_profile_rejects_actor_catalog_version_drift() -> None:
    state = _state()
    stamp_scenario_profile(state, _identity())
    incompatible = ScenarioProfileIdentity(
        scenario_id="ww3_2028_core",
        scenario_version="1",
        shared_world_authority_id="earth3_ww3_2028_v1",
        actor_catalog_id="core_2028",
        actor_catalog_compatibility_version="2",
    )
    with pytest.raises(ScenarioProfileError, match="actor_catalog_version_incompatible"):
        require_compatible_scenario_profile(state, incompatible)


def test_new_2028_profile_cannot_silently_load_unprofiled_save() -> None:
    state = _state()
    with pytest.raises(ScenarioProfileError, match="scenario_profile_missing"):
        require_compatible_scenario_profile(state, _identity())


def test_legacy_profile_migration_is_explicit_and_id_scoped() -> None:
    state = _state(scenario_id="earth3_v1")
    expected = get_scenario("earth3_v1").profile_identity()
    assert (
        require_compatible_scenario_profile(
            state,
            expected,
            allow_legacy_unprofiled=True,
        )
        == expected
    )


def test_legacy_profile_migration_rejects_wrong_persisted_id() -> None:
    state = _state(scenario_id="legacy_goe_europe")
    expected = get_scenario("earth3_v1").profile_identity()
    with pytest.raises(ScenarioProfileError, match="scenario_profile_missing"):
        require_compatible_scenario_profile(
            state,
            expected,
            allow_legacy_unprofiled=True,
        )
