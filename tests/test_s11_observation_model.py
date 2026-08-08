from __future__ import annotations

import copy
import unittest

from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    InformationTier,
    KnowledgeRecord,
    Province,
    StrategicFormation,
)
from gates_of_codex.observation import (
    S11_CAMPAIGN_SCHEMA_VERSION,
    opaque_contact_id,
    observer_scope_id,
)
from gates_of_codex.state_io import campaign_from_dict


def _state(*, template_id: str = "nato-us-airborne") -> CampaignState:
    battalions = {
        "bn-n": Battalion(
            battalion_id="bn-n",
            faction=Faction.NATO,
            province_id="a",
            formation_id=template_id,
            roster=[BattalionRosterEntry("n", 1)],
            authorized_roster=[BattalionRosterEntry("n", 1)],
            strategic_formation_id="sf-n",
        ),
        "bn-r": Battalion(
            battalion_id="bn-r",
            faction=Faction.RUSSIA,
            province_id="b",
            formation_id="rusa-line",
            roster=[BattalionRosterEntry("r", 1)],
            authorized_roster=[BattalionRosterEntry("r", 1)],
            strategic_formation_id="sf-r",
        ),
    }
    return CampaignState(
        campaign_name="S11",
        factions={
            "nato": FactionState(Faction.NATO, is_human_controlled=True),
            "rusa": FactionState(Faction.RUSSIA),
        },
        formations={
            template_id: Formation(template_id, "N", Faction.NATO, "usa", FormationKind.AIRBORNE_BRIGADE),
            "rusa-line": Formation("rusa-line", "R", Faction.RUSSIA, "rus"),
        },
        strategic_formations={
            "sf-n": StrategicFormation(
                "sf-n", "N", Faction.NATO, "a", ForceEchelon.BATTALION,
                battalion_ids=["bn-n"], template_formation_id=template_id,
            ),
            "sf-r": StrategicFormation(
                "sf-r", "R", Faction.RUSSIA, "b", ForceEchelon.BATTALION,
                battalion_ids=["bn-r"], template_formation_id="rusa-line",
            ),
        },
        provinces={
            "a": Province("a", "A", Faction.NATO, ["b"]),
            "b": Province("b", "B", Faction.RUSSIA, ["a"]),
        },
        battalions=battalions,
        schema_version=10,
    )


class S11SchemaTests(unittest.TestCase):
    def test_every_pre_s11_schema_migrates_to_11_off_and_empty(self) -> None:
        base = _state().to_dict()
        for version in range(1, 11):
            with self.subTest(version=version):
                payload = copy.deepcopy(base)
                payload["schema_version"] = version
                loaded = campaign_from_dict(payload)
                self.assertEqual(S11_CAMPAIGN_SCHEMA_VERSION, loaded.schema_version)
                self.assertFalse(loaded.fog_of_war_enabled)
                self.assertEqual({}, loaded.knowledge_by_observer)
                self.assertTrue(loaded.strategic_formations["sf-n"].recon_capability)
                self.assertFalse(loaded.strategic_formations["sf-r"].recon_capability)


    def test_s11_migration_preserves_true_incoming_schema_for_legacy_migrations(self) -> None:
        payload = _state().to_dict()
        payload["schema_version"] = 5
        payload["battalions"]["bn-n"]["commander_id"] = "missing-legacy-commander"
        payload["strategic_formations"] = {}

        loaded = campaign_from_dict(payload)

        self.assertEqual(11, loaded.schema_version)
        self.assertIsNone(loaded.battalions["bn-n"].commander_id)
        self.assertEqual(
            5,
            loaded.map_metadata["strategic_formation_migration"][
                "migrated_from_schema"
            ],
        )

    def test_pre_s11_field_presence_fails_closed(self) -> None:
        payload = _state().to_dict()
        payload["schema_version"] = 10
        payload["fog_of_war_enabled"] = False
        with self.assertRaisesRegex(ValueError, "unexpected_s11_fields_in_pre_s11_schema"):
            campaign_from_dict(payload)

    def test_every_pre_s11_field_shape_fails_closed(self) -> None:
        base = _state().to_dict()
        variants = []

        knowledge_only = copy.deepcopy(base)
        knowledge_only["knowledge_by_observer"] = {}
        variants.append(knowledge_only)

        recon_only = copy.deepcopy(base)
        recon_only["strategic_formations"]["sf-n"]["recon_capability"] = True
        variants.append(recon_only)

        complete = copy.deepcopy(base)
        complete["fog_of_war_enabled"] = False
        complete["knowledge_by_observer"] = {}
        for row in complete["strategic_formations"].values():
            row["recon_capability"] = False
        variants.append(complete)

        for payload in variants:
            with self.subTest(fields=sorted(payload)):
                payload["schema_version"] = 10
                with self.assertRaisesRegex(
                    ValueError, "unexpected_s11_fields_in_pre_s11_schema"
                ):
                    campaign_from_dict(payload)

    def test_schema_11_requires_complete_fields(self) -> None:
        payload = _state().to_dict()
        payload["schema_version"] = 11
        with self.assertRaisesRegex(ValueError, "missing_s11_fields"):
            campaign_from_dict(payload)

    def test_schema_11_requires_per_formation_recon_and_strict_bool(self) -> None:
        state = _state()
        state.schema_version = 11
        payload = state.to_dict()
        payload["strategic_formations"]["sf-n"].pop("recon_capability")
        with self.assertRaisesRegex(ValueError, "missing_s11_recon_capability:sf-n"):
            campaign_from_dict(payload)

        payload = state.to_dict()
        payload["strategic_formations"]["sf-n"]["recon_capability"] = 1
        with self.assertRaisesRegex(ValueError, "recon_capability must be bool"):
            campaign_from_dict(payload)

    def test_future_schema_preserves_complete_s11_fields(self) -> None:
        state = _state()
        state.schema_version = 12
        state.fog_of_war_enabled = False
        state.strategic_formations["sf-n"].recon_capability = True
        loaded = campaign_from_dict(state.to_dict())
        self.assertEqual(12, loaded.schema_version)
        self.assertTrue(loaded.strategic_formations["sf-n"].recon_capability)

    def test_schema_11_preserves_explicit_recon(self) -> None:
        state = _state(template_id="non-whitelist")
        state.schema_version = 11
        state.fog_of_war_enabled = False
        state.strategic_formations["sf-n"].recon_capability = True
        payload = state.to_dict()
        loaded = campaign_from_dict(payload)
        self.assertTrue(loaded.strategic_formations["sf-n"].recon_capability)


class S11ObserverScopeTests(unittest.TestCase):
    def test_scope_is_faction_or_single_alliance(self) -> None:
        state = _state()
        self.assertEqual("faction:nato", observer_scope_id(state, Faction.NATO))
        state.alliances["blue"] = Alliance("blue", "Blue", [Faction.NATO, Faction.RUSSIA])
        self.assertEqual("alliance:blue", observer_scope_id(state, Faction.NATO))

    def test_overlapping_alliance_only_rejected_when_observer_authority_used(self) -> None:
        state = _state()
        state.alliances = {
            "one": Alliance("one", "One", [Faction.NATO, Faction.RUSSIA]),
            "two": Alliance("two", "Two", [Faction.NATO, Faction.RUSSIA]),
        }
        state.validate()  # Fog off + empty knowledge remains compatible.
        with self.assertRaisesRegex(ValueError, "ambiguous_observer_scope"):
            observer_scope_id(state, Faction.NATO)
        state.fog_of_war_enabled = True
        with self.assertRaisesRegex(ValueError, "ambiguous_observer_scope"):
            state.validate()

    def test_fog_on_requires_exactly_one_human(self) -> None:
        state = _state()
        state.fog_of_war_enabled = True
        state.factions["rusa"].is_human_controlled = True
        with self.assertRaisesRegex(ValueError, "fog_of_war_requires_single_human_faction"):
            state.validate()

    def test_nonempty_knowledge_rejects_ambiguous_alliance(self) -> None:
        state = _state()
        state.alliances = {
            "one": Alliance("one", "One", [Faction.NATO, Faction.RUSSIA]),
            "two": Alliance("two", "Two", [Faction.NATO, Faction.RUSSIA]),
        }
        scope = "faction:nato"
        opaque = opaque_contact_id(scope, "sf-r")
        record = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"contact:{opaque}",
            subject_formation_id="sf-r",
            tier=InformationTier.CONTACT,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
        )
        state.knowledge_by_observer = {scope: {record.record_key: record}}
        with self.assertRaisesRegex(ValueError, "ambiguous_observer_scope"):
            state.validate()


    def test_persisted_scope_must_match_current_coalition_authority(self) -> None:
        state = _state()
        state.alliances["blue"] = Alliance(
            "blue", "Blue", [Faction.NATO, Faction.RUSSIA]
        )
        scope = "faction:nato"
        opaque = opaque_contact_id(scope, "sf-r")
        record = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"contact:{opaque}",
            subject_formation_id="sf-r",
            tier=InformationTier.CONTACT,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
        )
        state.knowledge_by_observer = {scope: {record.record_key: record}}
        with self.assertRaisesRegex(
            ValueError, "knowledge_observer_scope_not_authoritative"
        ):
            state.validate()

    def test_known_opaque_vector_and_record_validation(self) -> None:
        value = opaque_contact_id("faction:nato", "sf-r")
        self.assertEqual(
            "contact-6ccdcd959da4e3ad92428b4b140894127da48a83adc5f84c9876447defd33d65",
            value,
        )
        record = KnowledgeRecord(
            observer_scope_id="faction:nato",
            record_key=f"contact:{value}",
            subject_formation_id="sf-r",
            tier=InformationTier.CONTACT,
            opaque_contact_id=value,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
        )
        record.validate()
        record.source_ids = ["b", "a"]
        with self.assertRaisesRegex(ValueError, "unsorted"):
            record.validate()

    def test_tier_specific_field_validation_fails_closed(self) -> None:
        scope = "faction:nato"
        subject = "sf-r"
        opaque = opaque_contact_id(scope, subject)
        contact = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"contact:{opaque}",
            subject_formation_id=subject,
            tier=InformationTier.CONTACT,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
            faction_id="rusa",
        )
        with self.assertRaisesRegex(ValueError, "contact_tier_identity_forbidden"):
            contact.validate()

        identified = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"formation:{subject}",
            subject_formation_id=subject,
            tier=InformationTier.IDENTIFIED,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
            faction_id="rusa",
            display_name="Enemy",
            echelon="battalion",
            strength_band="light",
        )
        with self.assertRaisesRegex(ValueError, "identified_tier_assessment_forbidden"):
            identified.validate()

        assessed = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"formation:{subject}",
            subject_formation_id=subject,
            tier=InformationTier.ASSESSED,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["site:obs"],
            last_seen_province_id="b",
            faction_id="rusa",
            display_name="Enemy",
            echelon="battalion",
        )
        with self.assertRaisesRegex(ValueError, "assessed_tier_bands_required"):
            assessed.validate()

        fully_observed = KnowledgeRecord(
            observer_scope_id=scope,
            record_key=f"formation:{subject}",
            subject_formation_id=subject,
            tier=InformationTier.FULLY_OBSERVED,
            opaque_contact_id=opaque,
            first_seen_turn=1,
            last_seen_turn=1,
            last_seen_tick=0,
            source_ids=["direct:sf-n"],
            last_seen_province_id="b",
            last_seen_edge_id="edge-a",
            faction_id="rusa",
            display_name="Enemy",
            echelon="battalion",
            strength_band="light",
            condition_band="high",
            supply_band="high",
        )
        with self.assertRaisesRegex(ValueError, "fully_observed_edge_progress_required"):
            fully_observed.validate()


if __name__ == "__main__":
    unittest.main()
