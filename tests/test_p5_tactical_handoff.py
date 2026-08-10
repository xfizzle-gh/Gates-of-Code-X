"""P5 regressions for the tactical handoff dependency contract (#166).

The S10 live acceptance found a generated handoff save carrying unrelated
Workshop dependency rows. Three distinct defects produced that:

* **D1** — the exporter merged the player's profile ``options.set`` mod list into
  the export, so every mod they happened to have enabled leaked in.
* **D2** — status-template selection took the newest valid ``.sav`` in the install
  directory, so an unrelated campaign could donate its ``{mods}``.
* **D3** — the status builder only replaced the ``{mods}`` block when the token
  list was truthy, so an empty list silently inherited the template's block.

These tests assert the resulting contract directly: the generated ``{mods}``
block equals the validated stack representation exactly and in order, with no
profile extras and no template extras. They deliberately do not blacklist the
two observed stale ids — a blacklist would pass while the underlying merge
remained.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.bridge.status import BattleStatusOptions, StatusBuilder
from gates_of_codex.modstack import (
    UnrepresentableStackLayer,
    stack_dependency_tokens,
)
from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.models import Faction, PendingBattle
from gates_of_codex.play_context import resolve_status_template


#: Ids observed leaking in the S10 acceptance. Used only to build adversarial
#: fixtures — never as a blacklist the implementation could satisfy trivially.
STALE_TEMPLATE_ID = "mod_2846452104:0"
STALE_PROFILE_ID = "mod_3701399761:0"


def _mod_layer(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.info").write_text(f'{{mod {{name "{name}"}}}}\n', encoding="utf-8")
    return root


def _vanilla_layer(root: Path) -> Path:
    # A vanilla resource root carries no mod.info and is exempt from {mods}.
    (root / "resource").mkdir(parents=True, exist_ok=True)
    return root


def _workshop_stack(base: Path) -> list[Path]:
    """A realistic five-layer stack mounted from Workshop folders."""
    vanilla = _vanilla_layer(base / "game")
    west81 = _mod_layer(base / "workshop" / "content" / "400750" / "2897299509", "West-81")
    codex = _mod_layer(base / "workshop" / "content" / "400750" / "3261086933", "Code-X")
    overhaul = _mod_layer(
        base / "workshop" / "content" / "400750" / "3636883799",
        "CodeX Conquest AI Overhaul 1.5",
    )
    gates = _mod_layer(
        base / "workshop" / "content" / "400750" / "3696721120", "Gates of CodeX"
    )
    return [vanilla, west81, codex, overhaul, gates]


def _mods_block(text: str) -> list[str]:
    """Parse the actual generated ``{mods}`` block, in file order."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^\s*\{mods(?:\s|\}|$)", line)),
        None,
    )
    if start is None:
        return []
    values: list[str] = []
    depth = 0
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        values.extend(re.findall(r'"([^"]+)"', lines[index]))
        if depth <= 0:
            break
    return values


def _pending_battle() -> PendingBattle:
    return PendingBattle(
        battle_id="goc-1-b714b08b42",
        origin_province_id="a",
        target_province_id="b",
        attacker_faction=Faction.NATO,
        defender_faction=Faction.RUSSIA,
        attacking_participants=[],
        defending_participants=[],
        player_faction=Faction.NATO,
        player_is_attacker=True,
    )


def _template_with_stale_mods() -> str:
    return (
        "{saveinfo\n"
        "\t{version 7}\n"
        '\t{gameVersion "1.065.0"}\n'
        "\t{timestamp 1}\n"
        '\t{name "Unrelated Galactic Conquest"}\n'
        "\t{army ger}\n"
        "\t{enemyArmy rus}\n"
        "\t{difficulty heroic}\n"
        "\t{duration 3}\n"
        "\t{resources 2}\n"
        "\t{selectedMapPoint point_2_4}\n"
        "\t{playedGames 4}\n"
        "\t{wonGames 2}\n"
        f'\t{{mods\n\t\t"{STALE_TEMPLATE_ID}"\n\t\t"{STALE_PROFILE_ID}"\n\t}}\n'
        "\t{unlockedResearch\n\t\t{\"old_key\"}\n\t}\n"
        "\t{mapPoints\n"
        "\t\t{\n"
        "\t\t\t{name point_2_4}\n"
        '\t\t\t{map "multi/old_map:campaign_capture_the_flag:4x4"}\n'
        "\t\t}\n"
        "\t}\n"
        "\t{roundsHistory}\n"
        "}\n"
    )


class StackDependencyRepresentationTests(unittest.TestCase):
    def test_workshop_layers_produce_exact_ordered_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stack = _workshop_stack(Path(temporary))
            tokens = stack_dependency_tokens(stack)

        self.assertEqual(
            [
                "mod_2897299509:0",
                "mod_3261086933:0",
                "mod_3636883799:0",
                "mod_3696721120:0",
            ],
            tokens,
        )

    def test_vanilla_root_is_exempt_from_representation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            vanilla = _vanilla_layer(base / "game")
            self.assertEqual([], stack_dependency_tokens([vanilla]))

    def test_repeated_layer_is_suppressed_without_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stack = _workshop_stack(Path(temporary))
            tokens = stack_dependency_tokens([*stack, stack[1], stack[2]])

        self.assertEqual(
            [
                "mod_2897299509:0",
                "mod_3261086933:0",
                "mod_3636883799:0",
                "mod_3696721120:0",
            ],
            tokens,
        )
        self.assertEqual(len(set(tokens)), len(tokens))

    def test_local_gates_layer_fails_closed_instead_of_guessing(self) -> None:
        """A non-Workshop mod layer has no proven saveinfo representation.

        Emitting a guessed row, or silently omitting the layer, would produce a
        dependency list that does not describe what actually loads.
        """
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stack = _workshop_stack(base)[:-1]
            local_gates = _mod_layer(base / "dev" / "gates-of-codex", "Gates of CodeX")
            with self.assertRaises(UnrepresentableStackLayer) as raised:
                stack_dependency_tokens([*stack, local_gates])

        message = str(raised.exception)
        self.assertIn("Gates of CodeX", message)
        # stack_dependency_tokens normalizes layers through the existing path
        # machinery, so the message carries the canonical path. On Windows the
        # raw temp-dir spelling is an 8.3 alias (RUNNER~1) of the same directory.
        self.assertIn(str(local_gates.resolve()), message)

    def test_workshop_id_is_read_from_the_layer_path_not_hardcoded(self) -> None:
        """A republished item must be represented by its own id."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stack = _workshop_stack(base)[:-1]
            republished = _mod_layer(
                base / "workshop" / "content" / "400750" / "4111222333",
                "Gates of CodeX",
            )
            tokens = stack_dependency_tokens([*stack, republished])

        self.assertEqual("mod_4111222333:0", tokens[-1])
        self.assertNotIn("mod_3696721120:0", tokens)


class GeneratedModsBlockTests(unittest.TestCase):
    """Assert the block the engine actually reads, parsed from the output."""

    def _build(self, mods, template: str | None = None) -> str:
        return StatusBuilder().build(
            _pending_battle(),
            BattleStatusOptions(
                "multi/4x4/test",
                template_status=template if template is not None else "",
                mods=mods,
            ),
        )

    def test_generated_block_equals_the_validated_stack_exactly_and_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tokens = stack_dependency_tokens(_workshop_stack(Path(temporary)))
        text = self._build(tokens, _template_with_stale_mods())

        self.assertEqual(tokens, _mods_block(text))

    def test_template_dependency_rows_never_survive_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tokens = stack_dependency_tokens(_workshop_stack(Path(temporary)))
        text = self._build(tokens, _template_with_stale_mods())
        block = _mods_block(text)

        self.assertNotIn(STALE_TEMPLATE_ID, block)
        self.assertNotIn(STALE_PROFILE_ID, block)
        # The template's other content must still be inherited normally.
        self.assertIn("{selectedMapPoint point_2_4}", text)

    def test_explicit_empty_list_replaces_the_template_block(self) -> None:
        """D3: the empty case is exactly when inheriting is most dangerous."""
        text = self._build([], _template_with_stale_mods())

        self.assertEqual([], _mods_block(text))
        self.assertNotIn(STALE_TEMPLATE_ID, text)
        self.assertNotIn(STALE_PROFILE_ID, text)

    def test_unspecified_mods_preserve_the_template_block(self) -> None:
        """Standalone callers that never mention dependencies keep prior behavior."""
        text = StatusBuilder().build(
            _pending_battle(),
            BattleStatusOptions(
                "multi/4x4/test", template_status=_template_with_stale_mods()
            ),
        )

        self.assertEqual([STALE_TEMPLATE_ID, STALE_PROFILE_ID], _mods_block(text))

    def test_generated_block_is_emitted_without_a_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tokens = stack_dependency_tokens(_workshop_stack(Path(temporary)))
        text = self._build(tokens)

        self.assertEqual(tokens, _mods_block(text))


def _write_save(path: Path, campaign_name: str) -> Path:
    """Write a valid Conquest save carrying a given visible campaign name."""
    status = _template_with_stale_mods().replace(
        '{name "Unrelated Galactic Conquest"}', f'{{name "{campaign_name}"}}'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    CampaignSaveArchive().write(path, status=status, campaign_scn="{campaign}\n")
    return path


def _bind_save_to_campaign(save_path: Path, campaign_path: Path) -> Path:
    """Write the adjacent .goc.json that binds a generated template to a campaign."""
    from gates_of_codex.service import BattleExportManifest, GatesOfCodeXService

    return GatesOfCodeXService().write_manifest(
        BattleExportManifest(
            battle_id="goc-prior-battle",
            campaign_path=str(campaign_path.resolve()),
            save_path=str(save_path.resolve()),
            catalog_signature="",
            played_games=0,
            won_games=0,
        )
    )


class StatusTemplateSelectionTests(unittest.TestCase):
    """#166 D2: never silently adopt an unrelated campaign save as the template."""

    def test_ambiguous_unrelated_saves_are_refused_instead_of_newest_wins(self) -> None:
        """The #166 shape: several unrelated saves, newest happens to be foreign."""
        import os

        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "campaign"
            older = _write_save(install / "conquest template.sav", "My Conquest")
            newest = _write_save(install / "galactic conquest.sav", "Galactic Conquest Wars")
            os.utime(older, (1_000_000, 1_000_000))
            os.utime(newest, (2_000_000, 2_000_000))
            with self.assertRaises(RuntimeError) as raised:
                resolve_status_template(install, install / "target.sav")

        message = str(raised.exception)
        self.assertIn("Refusing to pick a saveinfo template by modification time", message)
        self.assertIn("galactic conquest.sav", message)
        self.assertIn("--template-save", message)

    def test_single_player_created_template_is_accepted(self) -> None:
        """The documented first-run setup carries the player's own name, not ours."""
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "campaign"
            campaign = Path(temporary) / "campaign.json"
            campaign.write_text("{}", encoding="utf-8")
            only = _write_save(install / "conquest template.sav", "My Conquest")
            chosen = resolve_status_template(
                install, install / "target.sav", campaign_path=campaign
            )

        self.assertEqual(only.resolve(), chosen)

    def test_same_campaign_template_wins_over_a_newer_unrelated_save(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            campaign.write_text("{}", encoding="utf-8")
            install = root / "campaign"
            ours = _write_save(install / "ours.sav", "Gates of CodeX b714b08b")
            _bind_save_to_campaign(ours, campaign)
            newer = _write_save(install / "unrelated.sav", "Galactic Conquest Wars")
            os.utime(ours, (1_000_000, 1_000_000))
            os.utime(newer, (2_000_000, 2_000_000))
            chosen = resolve_status_template(
                install, install / "target.sav", campaign_path=campaign
            )

        self.assertEqual(ours.resolve(), chosen)

    def test_gates_template_from_another_campaign_does_not_win(self) -> None:
        """#176 requires binding to the exact campaign, not merely our name prefix."""
        import os

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            other_campaign = root / "other-campaign.json"
            for path in (campaign, other_campaign):
                path.write_text("{}", encoding="utf-8")
            install = root / "campaign"
            foreign = _write_save(install / "foreign gates.sav", "Gates of CodeX aaaaaaa1")
            _bind_save_to_campaign(foreign, other_campaign)
            ordinary = _write_save(install / "conquest template.sav", "My Conquest")
            os.utime(foreign, (2_000_000, 2_000_000))
            os.utime(ordinary, (1_000_000, 1_000_000))
            with self.assertRaises(RuntimeError) as raised:
                resolve_status_template(
                    install, install / "target.sav", campaign_path=campaign
                )

        message = str(raised.exception)
        self.assertIn("bound to this campaign", message)
        self.assertIn("foreign gates.sav", message)

    def test_gates_template_without_a_sidecar_is_not_treated_as_bound(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            campaign.write_text("{}", encoding="utf-8")
            install = root / "campaign"
            unbound = _write_save(install / "gates no sidecar.sav", "Gates of CodeX b1")
            ordinary = _write_save(install / "conquest template.sav", "My Conquest")
            os.utime(unbound, (2_000_000, 2_000_000))
            os.utime(ordinary, (1_000_000, 1_000_000))
            with self.assertRaises(RuntimeError) as raised:
                resolve_status_template(
                    install, install / "target.sav", campaign_path=campaign
                )

        self.assertIn("bound to this campaign", str(raised.exception))

    def test_explicit_template_is_always_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "campaign"
            unrelated = _write_save(install / "unrelated.sav", "Galactic Conquest Wars")
            chosen = resolve_status_template(install, install / "target.sav", unrelated)

        self.assertEqual(unrelated.resolve(), chosen)

    def test_no_candidates_still_reports_the_actionable_setup_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "campaign"
            install.mkdir(parents=True)
            with self.assertRaises(RuntimeError) as raised:
                resolve_status_template(install, install / "target.sav")

        self.assertIn("No valid Conquest saveinfo template", str(raised.exception))


if __name__ == "__main__":
    unittest.main()


class ResultVerificationAndImportTests(unittest.TestCase):
    """P5 import authority: verification-gated, bound, and applied exactly once."""

    def _prepared(self, root: Path):
        from test_s10_frontend_presentation_contract import (
            _create_prepared_contact,
            _state,
            _write_completed_external_battle,
        )

        state = _state(root)
        _create_prepared_contact(state)
        return _write_completed_external_battle(root, state)

    def test_verify_result_reports_a_verdict_without_mutating_the_campaign(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path, save_path = self._prepared(root)
            # Normalize serialization first: the fixture hand-writes ints where
            # the serializer emits floats, so an un-normalized baseline would
            # differ for reasons unrelated to the command under test.
            from gates_of_codex.state_io import load_campaign, save_campaign

            save_campaign(load_campaign(campaign_path), campaign_path)
            before = campaign_path.read_bytes()
            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "verify_result", "command_id": "v1"}],
                snapshot_path=None,
            )
            after = campaign_path.read_bytes()

        row = result["results"][0]
        self.assertEqual("verify_result", row["op"])
        self.assertTrue(row["ok"], row)
        self.assertIn("verified", row["data"])
        # Read-only: the authoritative campaign is byte-identical, and the
        # verdict consumed no exactly-once ledger slot, so a replayed battle can
        # be re-verified instead of returning a stale "duplicate" answer.
        self.assertEqual(before, after)
        self.assertNotIn("frontend_command_ledger", after.decode("utf-8"))

    def test_verification_rejects_a_result_bound_to_another_battle(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.service import GatesOfCodeXService
        from dataclasses import replace as dc_replace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path, save_path = self._prepared(root)
            service = GatesOfCodeXService()
            manifest = service.load_manifest(service.manifest_path(save_path))
            service.write_manifest(dc_replace(manifest, battle_id="some-other-battle"))

            verified = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "verify_result", "command_id": "v-bound"}],
                snapshot_path=None,
            )
            before = campaign_path.read_bytes()
            imported = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "i-bound"}],
                snapshot_path=None,
            )
            after = campaign_path.read_bytes()

        self.assertFalse(verified["results"][0]["ok"], verified)
        self.assertIn("some-other-battle", verified["results"][0]["detail"])
        self.assertFalse(imported["ok"], imported)
        self.assertEqual(before, after)

    def test_verification_rejects_a_result_bound_to_another_campaign(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.service import GatesOfCodeXService
        from dataclasses import replace as dc_replace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path, save_path = self._prepared(root)
            service = GatesOfCodeXService()
            manifest = service.load_manifest(service.manifest_path(save_path))
            service.write_manifest(
                dc_replace(manifest, campaign_path=str(root / "other-campaign.json"))
            )
            before = campaign_path.read_bytes()
            imported = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "i-camp"}],
                snapshot_path=None,
            )
            after = campaign_path.read_bytes()

        self.assertFalse(imported["ok"], imported)
        self.assertIn("other-campaign.json", imported["results"][0]["detail"])
        self.assertEqual(before, after)

    def test_accepted_import_clears_the_pending_battle_exactly_once(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.state_io import load_campaign

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path, _ = self._prepared(root)
            self.assertIsNotNone(load_campaign(campaign_path).pending_battle)

            first = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "imp-1"}],
                snapshot_path=None,
            )
            after_first = load_campaign(campaign_path)
            replayed = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "imp-1"}],
                snapshot_path=None,
            )
            after_replay = load_campaign(campaign_path)

        self.assertTrue(first["ok"], first)
        # Pending battle is cleared only by the accepted import.
        self.assertIsNone(after_first.pending_battle)
        # The replayed id is recognised and cannot apply a second result.
        self.assertTrue(replayed["ok"], replayed)
        self.assertEqual(0, replayed["commands_applied"])
        self.assertTrue(replayed["results"][0]["data"]["duplicate"])
        self.assertEqual(
            {key: value.unit_count for key, value in after_first.battalions.items()},
            {key: value.unit_count for key, value in after_replay.battalions.items()},
        )

    def test_accepted_import_refreshes_the_snapshot_from_campaign_state(self) -> None:
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.state_io import load_campaign
        import json as _json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path, _ = self._prepared(root)
            snapshot_path = root / "campaign_snapshot.json"
            result = apply_frontend_commands(
                campaign_path,
                commands=[{"op": "import_battle", "command_id": "imp-snap"}],
                snapshot_path=snapshot_path,
            )
            state = load_campaign(campaign_path)
            self.assertTrue(snapshot_path.is_file())
            snapshot = _json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"], result)
        # The refreshed snapshot reflects accepted state: no pending battle.
        self.assertIsNone(snapshot.get("pending_battle"))
        self.assertIsNone(state.pending_battle)
