from __future__ import annotations

from pathlib import Path

import pytest

from gates_of_codex.actor_economy import (
    actor_recruitment_offers,
    available_actor_research,
    purchase_actor_research,
)
from gates_of_codex.player_shell import continue_campaign, create_new_campaign, resolve_campaign_paths
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID, get_scenario
from gates_of_codex.scenario_2028_core import CORE_2028_POWER_IDS

# Earth3 national wallets plus the selected Core overlay, folded once.
# NATO: 600 overlay + usa 600 + deu 450 + pol 450 = 2100
# RUSA: 750 overlay + rus 750 = 1500
# UKR/PRC: selected start only. If this starting stack is later judged
# unsuitable, that is an explicit balance issue — not a reason to hide money.
CORE_2028_FOLDED_STARTING_TREASURY = {
    "nato": 2100,
    "ukr": 600,
    "rusa": 1500,
    "prc": 600,
}
from gates_of_codex.scenario_selection import apply_new_campaign_actor, persisted_actor_id
from gates_of_codex.state_io import save_campaign
from gates_of_codex.strategic_actors import ACTOR_RUNTIME_KEY, selected_actor
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


def _runtime(state) -> dict:
    runtime = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    assert isinstance(runtime, dict)
    return runtime


def _actor_resources(state, actor_id: str) -> int:
    return int(_runtime(state)["actors"][actor_id]["resources"])


def _spend_selected_research(state):
    actor = selected_actor(state)
    options = available_actor_research(state, actor.actor_id)
    payable = [item for item in options if item.cost > 0 and item.cost <= actor.resources]
    assert payable, (actor.actor_id, [(item.key, item.cost) for item in options], actor.resources)
    chosen = min(payable, key=lambda item: (item.cost, item.key))
    return purchase_actor_research(state, actor.actor_id, chosen.key)


@pytest.mark.parametrize("actor_id", CORE_2028_POWER_IDS)
def test_core_2028_selected_power_owns_and_spends_its_treasury(tmp_path: Path, actor_id: str) -> None:
    paths = resolve_campaign_paths(tmp_path / f"core_{actor_id}.json")
    state = create_new_campaign(
        paths=paths,
        faction=actor_id,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )

    assert get_scenario(DEFAULT_SCENARIO_ID).status == "production"
    assert state.map_metadata["scenario_id"] == "ww3_2028_core"
    assert state.map_metadata["scenario_status"] == "production"
    runtime = _runtime(state)
    assert runtime["selected_actor_id"] == actor_id
    assert runtime["selected_actor_id"] != "usa"
    assert persisted_actor_id(state) == actor_id
    assert selected_actor(state).actor_id == actor_id
    assert selected_actor(state).resources == CORE_2028_FOLDED_STARTING_TREASURY[actor_id]
    usa_before = (
        int(runtime["actors"]["usa"]["resources"]) if "usa" in runtime["actors"] else None
    )

    before = {
        power: _actor_resources(state, power)
        for power in CORE_2028_POWER_IDS
        if power in runtime["actors"]
    }
    assert before[actor_id] == CORE_2028_FOLDED_STARTING_TREASURY[actor_id]

    purchase = _spend_selected_research(state)
    assert purchase.actor_id == actor_id
    assert purchase.resources_remaining == before[actor_id] - purchase.cost
    assert selected_actor(state).resources == purchase.resources_remaining
    assert _runtime(state)["selected_actor_id"] == actor_id
    for power, amount in before.items():
        if power == actor_id:
            assert _actor_resources(state, power) == amount - purchase.cost
        else:
            assert _actor_resources(state, power) == amount
    if usa_before is not None:
        assert _actor_resources(state, "usa") == usa_before

    save_campaign(state, paths.campaign)
    continued = continue_campaign(paths=paths)
    assert continued.map_metadata["scenario_id"] == "ww3_2028_core"
    assert continued.map_metadata["scenario_status"] == "production"
    assert persisted_actor_id(continued) == actor_id
    assert _runtime(continued)["selected_actor_id"] == actor_id
    assert _runtime(continued)["selected_actor_id"] != "usa"
    assert selected_actor(continued).resources == purchase.resources_remaining


def test_expanded_2028_selected_actor_owns_treasury_and_roster(tmp_path: Path) -> None:
    paths = resolve_campaign_paths(tmp_path / "expanded_pol.json")
    state = create_new_campaign(
        paths=paths,
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    apply_new_campaign_actor(state, "ww3_2028_expanded", "pol")

    assert state.map_metadata["scenario_id"] == "ww3_2028_expanded"
    assert state.map_metadata["scenario_status"] == "development"
    runtime = _runtime(state)
    assert runtime["selected_actor_id"] == "pol"
    assert runtime["selected_actor_id"] != "usa"
    assert persisted_actor_id(state) == "pol"
    assert selected_actor(state).actor_id == "pol"

    force = next(
        (
            item
            for item in state.strategic_formations.values()
            if item.actor_id == "pol"
        ),
        None,
    )
    assert force is not None
    offers = actor_recruitment_offers(state, force.strategic_formation_id)
    assert offers
    assert {offer.actor_id for offer in offers} == {"pol"}
    assert all("usa" not in offer.unit_name for offer in offers)
    assert any("pol" in offer.unit_name for offer in offers)

    usa_before = _actor_resources(state, "usa") if "usa" in runtime["actors"] else None
    pol_before = selected_actor(state).resources
    purchase = _spend_selected_research(state)
    assert purchase.actor_id == "pol"
    assert selected_actor(state).resources == pol_before - purchase.cost
    if usa_before is not None:
        assert _actor_resources(state, "usa") == usa_before

    save_campaign(state, paths.campaign)
    continued = continue_campaign(paths=paths)
    assert persisted_actor_id(continued) == "pol"
    assert continued.map_metadata["scenario_id"] == "ww3_2028_expanded"
    assert _runtime(continued)["selected_actor_id"] == "pol"
    assert selected_actor(continued).resources == purchase.resources_remaining
