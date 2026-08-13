from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from .earth3_fixture_authority import FIXTURE_SCENARIO_ID, apply_earth3_native_acceptance_fixture
from .models import CampaignState
from .state_io import campaign_from_dict


DEFAULT_SCENARIO_ID = "earth3_v1"


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    map_id: str
    builder: Callable[..., CampaignState]
    status: str
    required_asset_authority: tuple[str, ...]
    display_name: str


def _build_earth3(**options) -> CampaignState:
    from .earth3_bootstrap import build_earth3_v1_campaign
    from .earth3_operational import migrate_earth3_p2_to_p3
    from .operational_capture import ensure_site_control_state

    # Keep the direct Earth3 bootstrap builder frozen at P2. Production scenario
    # construction adds P3 only through the separately authenticated atomic
    # migration, so P2 content remains independently reproducible and testable.
    state = migrate_earth3_p2_to_p3(build_earth3_v1_campaign(**options))
    # Initialize mutable P3 control rows only after migration/authentication. The
    # authored graph retains actor provenance; controller rows use tactical sides.
    ensure_site_control_state(state)
    return state


def _build_legacy_goe_europe(**options) -> CampaignState:
    from .europe import build_goe_europe_campaign

    if options:
        raise TypeError(f"legacy_goe_europe does not accept builder options: {sorted(options)}")
    return build_goe_europe_campaign()


def _build_legacy_goe_europe_mediterranean(**options) -> CampaignState:
    from .europe_mediterranean_from_goe import build_europe_mediterranean_from_goe_campaign

    return build_europe_mediterranean_from_goe_campaign(**options)


SCENARIO_REGISTRY = MappingProxyType(
    {
        "earth3_v1": ScenarioDefinition(
            scenario_id="earth3_v1",
            map_id="earth3_europe_mediterranean",
            builder=_build_earth3,
            status="production",
            required_asset_authority=(
                "config/earth3/production_authority.json",
                "config/earth3/p3_operational_authority.json",
                "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json",
                "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
                "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json",
                "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
                "src/gates_of_codex/data/earth3_v1/*.json",
            ),
            display_name="Earth3 Europe–Mediterranean v1 Campaign Bootstrap",
        ),
        "legacy_goe_europe": ScenarioDefinition(
            scenario_id="legacy_goe_europe",
            map_id="goe_europe_alpha_graph_v1",
            builder=_build_legacy_goe_europe,
            status="legacy",
            required_asset_authority=("gates_of_codex/data/goe_graph_*.b85",),
            display_name="Legacy GoE Europe",
        ),
        "legacy_goe_europe_mediterranean": ScenarioDefinition(
            scenario_id="legacy_goe_europe_mediterranean",
            map_id="europe_mediterranean_from_goe",
            builder=_build_legacy_goe_europe_mediterranean,
            status="legacy",
            required_asset_authority=(
                "godot/assets/maps/europe_mediterranean/from_goe/map_manifest.json",
            ),
            display_name="Legacy Europe–Mediterranean from GoE",
        ),
        FIXTURE_SCENARIO_ID: ScenarioDefinition(
            scenario_id=FIXTURE_SCENARIO_ID,
            map_id="earth3_europe_mediterranean",
            builder=_build_earth3,
            status="debug",
            required_asset_authority=(
                "config/earth3/production_authority.json",
                "config/earth3/p3_operational_authority.json",
                "godot/assets/maps/earth3_europe_mediterranean/map_manifest.json",
                "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
                "godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json",
                "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
                "src/gates_of_codex/data/earth3_v1/*.json",
                "src/gates_of_codex/data/earth3_native_acceptance/fixture_manifest.json",
            ),
            display_name="Earth3 Native Acceptance Fixture",
        ),
    }
)


def scenario_ids() -> tuple[str, ...]:
    return tuple(SCENARIO_REGISTRY)


def get_scenario(scenario_id: str) -> ScenarioDefinition:
    try:
        return SCENARIO_REGISTRY[scenario_id]
    except KeyError as exc:
        valid = ", ".join(scenario_ids())
        raise ValueError(
            f"Unknown scenario ID {scenario_id!r}; expected one of: {valid}"
        ) from exc


def build_scenario(scenario_id: str = DEFAULT_SCENARIO_ID, **builder_options) -> CampaignState:
    definition = get_scenario(scenario_id)
    state = definition.builder(**builder_options)
    if state.map_id != definition.map_id:
        raise ValueError(
            f"Scenario {scenario_id} built map {state.map_id!r}; expected {definition.map_id!r}"
        )
    state.map_metadata["scenario_id"] = definition.scenario_id
    state.map_metadata["scenario_status"] = definition.status
    state.map_metadata["scenario_display_name"] = definition.display_name
    state.map_metadata["scenario_required_asset_authority"] = list(
        definition.required_asset_authority
    )
    if definition.scenario_id == FIXTURE_SCENARIO_ID:
        apply_earth3_native_acceptance_fixture(state)
    return state


def load_scenario(path: str | Path) -> CampaignState:
    return campaign_from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def load_bundled_scenario(
    scenario_id: str = DEFAULT_SCENARIO_ID,
    **builder_options,
) -> CampaignState:
    return build_scenario(scenario_id, **builder_options)


def load_legacy_test_scenario() -> CampaignState:
    resource = files("gates_of_codex").joinpath("data/four_faction.json")
    return campaign_from_dict(json.loads(resource.read_text(encoding="utf-8")))
