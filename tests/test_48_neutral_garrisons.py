from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.faction_wiring import load_faction_manifest
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    NEUTRAL_GARRISON_BATTALION_PREFIX,
    Province,
)
from gates_of_codex.neutral_garrison import (
    NeutralGarrisonError,
    authority_digest,
    authority_path,
    campaign_garrison_seed,
    export_garrison_profile,
    garrison_battalion_id,
    load_garrison_authority,
    maybe_attach_neutral_garrison,
    select_neutral_garrison,
    strategic_isolation_snapshot,
    validate_garrison_authority,
    validate_units_resolvable,
)
from gates_of_codex.state_io import load_campaign, save_campaign


PARIS = "e3_0260"
KIRUNA = "e3_2893"
ATHENS = "e3_1368"
CAIRO = "e3_1490"
ALEXANDRIA = "e3_1483"
SEVASTOPOL = "e3_1205"
SARATOV = "e3_2813"
TBILISI = "e3_2722"
UNAUTHORED = "e3_0592"


class NeutralGarrisonAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = load_garrison_authority()

    def test_authority_is_closed_and_has_no_worldwide_fallback(self) -> None:
        self.assertFalse(self.authority["worldwide_fallback"])
        self.assertNotIn("neutral", self.authority["regions"])
        validate_garrison_authority(self.authority)
        digest = authority_digest(self.authority)
        self.assertEqual(64, len(digest))
        self.assertEqual(digest, authority_digest(load_garrison_authority()))

    def test_required_regions_and_named_sites_are_authored(self) -> None:
        regions = set(self.authority["regions"])
        self.assertEqual(
            {
                "north_africa",
                "middle_east",
                "balkans",
                "western_central_europe",
                "eastern_europe",
                "western_asia",
            },
            regions,
        )
        by_id = {row["province_id"]: row for row in self.authority["provinces"]}
        self.assertEqual("western_central_europe", by_id[PARIS]["neutral_garrison_region"])
        self.assertEqual("capital", by_id[PARIS]["neutral_garrison_tier"])
        self.assertEqual("ordinary", by_id[KIRUNA]["neutral_garrison_tier"])
        self.assertEqual("balkans", by_id[ATHENS]["neutral_garrison_region"])
        self.assertEqual("north_africa", by_id[CAIRO]["neutral_garrison_region"])
        self.assertEqual("eastern_europe", by_id[SEVASTOPOL]["neutral_garrison_region"])
        self.assertEqual("eastern_europe_ukr_territorial", by_id[SEVASTOPOL]["pool_family"])
        self.assertEqual("eastern_europe_ru_reserve", by_id[SARATOV]["pool_family"])
        self.assertEqual("western_asia", by_id[TBILISI]["neutral_garrison_region"])
        self.assertNotIn(UNAUTHORED, by_id)

    def test_west81_entries_retain_legacy_reserve_provenance(self) -> None:
        west81 = [
            unit
            for pool in self.authority["pools"].values()
            for unit in pool["units"]
            if unit["source_authority"] == "West81"
        ]
        self.assertTrue(west81)
        self.assertTrue(all(unit["provenance"] == "legacy_reserve" for unit in west81))
        self.assertTrue(all(unit["source_component"] == "soviet_legacy_core" for unit in west81))

    def test_ildu_is_only_in_western_central_europe(self) -> None:
        for pool_id, pool in self.authority["pools"].items():
            names = {unit["unit_name"] for unit in pool["units"]}
            if pool["region"] == "western_central_europe":
                self.assertTrue(any(name.startswith("goc_ildu_") for name in names), pool_id)
            else:
                self.assertFalse(any(name.startswith("goc_ildu_") for name in names), pool_id)
                self.assertNotIn("ukraine_ildu", {unit["source_component"] for unit in pool["units"]})

    def test_wagner_is_only_in_north_africa(self) -> None:
        for pool_id, pool in self.authority["pools"].items():
            names = {unit["unit_name"].lower() for unit in pool["units"]}
            components = {unit["source_component"] for unit in pool["units"]}
            has_wagner = "wagner_native" in components or any(
                "wgn" in name or name.startswith("sto_") for name in names
            )
            if pool["region"] == "north_africa":
                self.assertTrue(has_wagner, pool_id)
            else:
                self.assertFalse(has_wagner, pool_id)

    def test_missing_province_metadata_fails_closed(self) -> None:
        with self.assertRaisesRegex(NeutralGarrisonError, "missing garrison-region metadata"):
            select_neutral_garrison(UNAUTHORED, authority=self.authority, campaign_seed="seed")

    def test_unknown_region_and_worldwide_fallback_fail_closed(self) -> None:
        missing_region = copy.deepcopy(self.authority)
        missing_region["provinces"][0]["neutral_garrison_region"] = "atlantis"
        with self.assertRaisesRegex(NeutralGarrisonError, "unknown garrison-region"):
            validate_garrison_authority(missing_region)
        worldwide = copy.deepcopy(self.authority)
        worldwide["worldwide_fallback"] = True
        with self.assertRaisesRegex(NeutralGarrisonError, "worldwide"):
            validate_garrison_authority(worldwide)
        generic = copy.deepcopy(self.authority)
        generic["regions"]["neutral"] = {"adjacent_regions": [], "export_side": "nato"}
        with self.assertRaisesRegex(NeutralGarrisonError, "universal worldwide"):
            validate_garrison_authority(generic)

    def test_duplicate_keys_and_unknown_fields_fail_closed(self) -> None:
        path = authority_path()
        raw = path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "dup.json"
            bad.write_text(raw.replace('"issue": 48', '"issue": 48, "issue": 48', 1), encoding="utf-8")
            with self.assertRaisesRegex(NeutralGarrisonError, "duplicate JSON key"):
                load_garrison_authority(bad)
            extra = copy.deepcopy(self.authority)
            extra["unexpected"] = True
            with self.assertRaisesRegex(NeutralGarrisonError, "unknown fields"):
                validate_garrison_authority(extra)

    def test_adjacent_variation_cannot_escape_compatibility(self) -> None:
        leaked = copy.deepcopy(self.authority)
        for row in leaked["provinces"]:
            if row["province_id"] == PARIS:
                row["adjacent_variation_tags"] = ["north_africa"]
                break
        with self.assertRaisesRegex(NeutralGarrisonError, "escapes compatibility"):
            validate_garrison_authority(leaked)


class NeutralGarrisonSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = load_garrison_authority()

    def _home_selection(self, province_id: str, prefix: str):
        for index in range(512):
            selected = select_neutral_garrison(
                province_id,
                authority=self.authority,
                campaign_seed=f"{prefix}-{index:04d}",
            )
            if not selected.variation_applied:
                return selected
        self.fail(f"no home-region selection for {province_id}")

    def test_different_regions_select_different_pools(self) -> None:
        paris = self._home_selection(PARIS, "alpha")
        athens = self._home_selection(ATHENS, "alpha")
        cairo = self._home_selection(CAIRO, "alpha")
        self.assertNotEqual(paris.pool_id, athens.pool_id)
        self.assertNotEqual(paris.pool_id, cairo.pool_id)
        self.assertNotEqual(athens.pool_id, cairo.pool_id)
        self.assertEqual("western_central_europe", paris.region)
        self.assertEqual("balkans", athens.region)
        self.assertEqual("north_africa", cairo.region)
        paris_names = {unit.unit_name for unit in paris.units}
        athens_names = {unit.unit_name for unit in athens.units}
        cairo_names = {unit.unit_name for unit in cairo.units}
        self.assertTrue(any(name.startswith("goc_ildu_") for name in paris_names))
        self.assertTrue(any(name.startswith("goc_serb_") for name in athens_names))
        self.assertTrue(any("wgn" in name for name in cairo_names))
        self.assertFalse(any("wgn" in name or name.startswith("sto_") for name in athens_names))
        self.assertFalse(any(name.startswith("goc_ildu_") for name in athens_names | cairo_names))

    def test_repeated_selection_is_byte_stable(self) -> None:
        first = select_neutral_garrison(ATHENS, authority=self.authority, campaign_seed="repeat")
        second = select_neutral_garrison(ATHENS, authority=self.authority, campaign_seed="repeat")
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertEqual(
            hashlib.sha256(first.canonical_bytes()).hexdigest(),
            hashlib.sha256(second.canonical_bytes()).hexdigest(),
        )

    def test_capital_is_stronger_than_ordinary_same_region(self) -> None:
        capital = select_neutral_garrison(CAIRO, authority=self.authority, campaign_seed="tier")
        ordinary = select_neutral_garrison(ALEXANDRIA, authority=self.authority, campaign_seed="tier")
        self.assertEqual(capital.region, ordinary.region)
        self.assertEqual("capital", capital.tier)
        self.assertEqual("ordinary", ordinary.tier)
        self.assertGreater(sum(unit.quantity for unit in capital.units), sum(unit.quantity for unit in ordinary.units))
        self.assertGreater(len(capital.units), len(ordinary.units))
        self.assertTrue(any(unit.category == "tank" for unit in capital.units))
        self.assertFalse(any(unit.category == "tank" for unit in ordinary.units))

    def test_adjacent_variation_stays_inside_explicit_set(self) -> None:
        seen_regions = set()
        for seed in (f"var-{index:04d}" for index in range(256)):
            selected = select_neutral_garrison(PARIS, authority=self.authority, campaign_seed=seed)
            seen_regions.add(selected.region)
            if selected.variation_applied:
                self.assertIn(selected.variation_region, ("balkans",))
                self.assertIn(selected.region, ("balkans",))
        self.assertIn("western_central_europe", seen_regions)
        self.assertTrue(seen_regions <= {"western_central_europe", "balkans"})
        self.assertNotIn("north_africa", seen_regions)
        self.assertNotIn("middle_east", seen_regions)

    def test_unresolvable_unit_fails_closed(self) -> None:
        selected = select_neutral_garrison(ATHENS, authority=self.authority, campaign_seed="catalog")
        catalog = {unit.unit_name: True for unit in selected.units}
        validate_units_resolvable(selected.units, catalog=catalog)
        with self.assertRaisesRegex(NeutralGarrisonError, "unresolvable"):
            select_neutral_garrison(
                ATHENS,
                authority=self.authority,
                campaign_seed="catalog",
                catalog={"missing": True},
            )


class NeutralGarrisonEncounterTests(unittest.TestCase):
    def _state(self, *, seed: str = "campaign-seed") -> CampaignState:
        state = CampaignState(
            campaign_name="Issue 48 garrison",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            map_metadata={"neutral_garrison_seed": seed},
            factions={
                "nato": FactionState(Faction.NATO, resources=900, researched_keys=["keep"]),
                "ukr": FactionState(Faction.UKRAINE, resources=400),
                "rusa": FactionState(Faction.RUSSIA, resources=500),
                "neutral": FactionState(Faction.NEUTRAL, resources=0),
            },
            provinces={
                "home": Province("home", "Home", Faction.NATO, [PARIS, ATHENS, KIRUNA, "empty"]),
                PARIS: Province(
                    PARIS,
                    "Paris",
                    Faction.NEUTRAL,
                    ["home"],
                    metadata={"source_id": 260},
                ),
                ATHENS: Province(
                    ATHENS,
                    "Athens",
                    Faction.NEUTRAL,
                    ["home"],
                    metadata={"source_id": 2202},
                ),
                KIRUNA: Province(
                    KIRUNA,
                    "Kiruna",
                    Faction.NEUTRAL,
                    ["home"],
                    metadata={"source_id": 11120},
                ),
                "empty": Province("empty", "Empty", Faction.NEUTRAL, ["home"]),
            },
            battalions={
                "nato-1": Battalion(
                    "nato-1",
                    Faction.NATO,
                    "home",
                    roster=[BattalionRosterEntry("rifle(nato)", 2, category="infantry")],
                )
            },
        )
        return state

    def test_selection_does_not_mutate_strategic_state(self) -> None:
        state = self._state()
        before = strategic_isolation_snapshot(state)
        engine = CampaignEngine(state, random_seed=7)
        result = engine.move_or_attack("nato-1", PARIS)
        self.assertFalse(result.moved)
        self.assertIsNotNone(result.pending_battle)
        after = strategic_isolation_snapshot(state)
        self.assertEqual(before, after)
        self.assertEqual(Faction.NEUTRAL, state.provinces[PARIS].owner)
        self.assertIsNone(state.provinces[PARIS].metadata.get("owner_actor_id"))
        garrison_id = garrison_battalion_id(PARIS)
        self.assertTrue(garrison_id.startswith(NEUTRAL_GARRISON_BATTALION_PREFIX))
        garrison = state.battalions[garrison_id]
        self.assertEqual(Faction.NEUTRAL, garrison.faction)
        self.assertEqual("", garrison.strategic_formation_id)
        self.assertEqual(Faction.NEUTRAL, result.pending_battle.defender_faction)

    def test_unauthored_neutral_still_walks_in(self) -> None:
        state = self._state()
        engine = CampaignEngine(state, random_seed=7)
        result = engine.move_or_attack("nato-1", "empty")
        self.assertTrue(result.moved)
        self.assertIsNone(result.pending_battle)
        self.assertEqual(Faction.NATO, state.provinces["empty"].owner)

    def test_garrison_units_are_not_added_to_sovereign_recruitment(self) -> None:
        state = self._state()
        engine = CampaignEngine(state, random_seed=7)
        engine.move_or_attack("nato-1", ATHENS)
        for faction in state.factions.values():
            self.assertEqual([], faction.recruited_pool)
            self.assertEqual([], faction.reinforcement_pool)
        self.assertEqual(["keep"], state.factions["nato"].researched_keys)
        garrison = state.battalions[garrison_battalion_id(ATHENS)]
        for entry in garrison.roster:
            for faction in state.factions.values():
                if faction.faction == Faction.NEUTRAL:
                    continue
                self.assertFalse(any(item.unit_name == entry.unit_name for item in faction.recruited_pool))

    def test_ukraine_sovereign_still_excludes_ildu_wrappers(self) -> None:
        actors = {row["actor_id"]: row for row in load_faction_manifest()["actors"]}
        self.assertNotIn("ukraine_ildu", actors["ukr"]["components"])
        sevastopol = select_neutral_garrison(SEVASTOPOL, campaign_seed="ukr")
        self.assertFalse(any(unit.unit_name.startswith("goc_ildu_") for unit in sevastopol.units))
        paris = None
        for index in range(512):
            candidate = select_neutral_garrison(PARIS, campaign_seed=f"ukr-{index:04d}")
            if not candidate.variation_applied:
                paris = candidate
                break
        self.assertIsNotNone(paris)
        self.assertTrue(any(unit.unit_name.startswith("goc_ildu_") for unit in paris.units))

    def test_repeat_attack_reuses_persisted_composition(self) -> None:
        state = self._state(seed="persist")
        engine = CampaignEngine(state, random_seed=3)
        first = engine.move_or_attack("nato-1", KIRUNA)
        first_profile = export_garrison_profile(state, first.pending_battle)
        self.assertIsNotNone(first_profile)
        garrison = state.battalions[garrison_battalion_id(KIRUNA)]
        garrison.roster[0].quantity = max(1, garrison.roster[0].quantity - 1)
        remaining = [(entry.unit_name, entry.quantity) for entry in garrison.roster]
        state.pending_battle = None
        state.battalions["nato-1"].movement_remaining = 1
        state.battalions["nato-1"].combat_actions_remaining = 1
        second = engine.move_or_attack("nato-1", KIRUNA)
        self.assertFalse(second.moved)
        reused = state.battalions[garrison_battalion_id(KIRUNA)]
        self.assertIs(garrison, reused)
        self.assertEqual(remaining, [(entry.unit_name, entry.quantity) for entry in reused.roster])
        self.assertEqual(
            first_profile["selection_signature"],
            export_garrison_profile(state, second.pending_battle)["selection_signature"],
        )

    def test_defeat_does_not_respawn_full_template(self) -> None:
        state = self._state(seed="defeat")
        engine = CampaignEngine(state, random_seed=3)
        engine.move_or_attack("nato-1", KIRUNA)
        engine.apply_battle_result(Faction.NATO)
        self.assertNotIn(garrison_battalion_id(KIRUNA), state.battalions)
        runtime = state.map_metadata["neutral_garrison_runtime"]["provinces"][KIRUNA]
        self.assertTrue(runtime["defeated"])
        state.provinces[KIRUNA].owner = Faction.NEUTRAL
        state.battalions["nato-1"].province_id = "home"
        force = state.strategic_formations.get(state.battalions["nato-1"].strategic_formation_id)
        if force is not None:
            force.province_id = "home"
        state.battalions["nato-1"].movement_remaining = 1
        state.battalions["nato-1"].combat_actions_remaining = 1
        again = engine.move_or_attack("nato-1", KIRUNA)
        self.assertTrue(again.moved)
        self.assertNotIn(garrison_battalion_id(KIRUNA), state.battalions)

    def test_save_load_is_deterministic(self) -> None:
        state = self._state(seed="saveload")
        engine = CampaignEngine(state, random_seed=11)
        engine.move_or_attack("nato-1", ATHENS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "campaign.json"
            save_campaign(state, path)
            migrated = load_campaign(path)
            save_campaign(migrated, path)
            first = path.read_bytes()
            save_campaign(load_campaign(path), path)
            second = path.read_bytes()
            self.assertEqual(first, second)
            reloaded = load_campaign(path)
        self.assertEqual(Faction.NEUTRAL, reloaded.provinces[ATHENS].owner)
        garrison = reloaded.battalions[garrison_battalion_id(ATHENS)]
        self.assertEqual(Faction.NEUTRAL, garrison.faction)
        self.assertEqual("", garrison.strategic_formation_id)
        self.assertEqual(
            export_garrison_profile(state, state.pending_battle),
            export_garrison_profile(reloaded, reloaded.pending_battle),
        )

    def test_export_profile_carries_encounter_without_actor(self) -> None:
        state = self._state(seed="export")
        pending = maybe_attach_neutral_garrison(state, ATHENS, attacker=state.battalions["nato-1"])
        profile = export_garrison_profile(state, pending)
        self.assertEqual("issue_48_regional_local_garrison", profile["profile_id"])
        self.assertEqual("balkans", profile["region"])
        self.assertEqual("capital", profile["tier"])
        self.assertIn("selection_signature", profile)
        self.assertIn("legacy_reserve", profile["source_classifications"])
        self.assertTrue(any(unit["source_authority"] == "West81" for unit in profile["units"]))
        self.assertTrue(all(
            unit["provenance"] == "legacy_reserve"
            for unit in profile["units"]
            if unit["source_authority"] == "West81"
        ))
        self.assertNotIn("owner_actor_id", profile)
        self.assertFalse(any(force.actor_id for force in state.strategic_formations.values()))
        self.assertEqual(Faction.NEUTRAL, state.provinces[PARIS].owner)

    def test_seed_is_explicit_campaign_state(self) -> None:
        state = self._state(seed="named-seed")
        self.assertEqual("named-seed", campaign_garrison_seed(state))
        left = select_neutral_garrison(PARIS, campaign_seed="named-seed")
        right = select_neutral_garrison(PARIS, campaign_seed="other-seed")
        self.assertNotEqual(left.selection_signature, right.selection_signature)


if __name__ == "__main__":
    unittest.main()
