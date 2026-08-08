from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.cli import main as cli_main
from gates_of_codex.observation import ObservationMutationContext
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s11_detection import _site, _state


class S11PersistenceTests(unittest.TestCase):
    def test_schema_11_save_load_save_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False

            save_campaign(state, path)
            first = path.read_bytes()
            loaded = load_campaign(path)
            save_campaign(loaded, path)

            self.assertEqual(first, path.read_bytes())
            self.assertEqual(11, loaded.schema_version)
            self.assertIn("faction:nato", loaded.knowledge_by_observer)

    def test_refresh_or_validation_failure_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root)
            save_campaign(state, path)
            before = path.read_bytes()

            state.factions["rusa"].is_human_controlled = True
            with self.assertRaisesRegex(
                ValueError, "fog_of_war_requires_single_human_faction"
            ):
                save_campaign(state, path)
            self.assertEqual(before, path.read_bytes())

    def test_confirmed_removal_context_is_persisted_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            save_campaign(state, path)
            self.assertEqual(1, len(state.knowledge_by_observer["faction:nato"]))

            state.strategic_formations.pop("enemy-c")
            state.battalions.pop("bn-enemy-c")
            context = ObservationMutationContext(
                {"faction:nato": frozenset({"enemy-c"})}
            )
            save_campaign(state, path, observation_context=context)

            loaded = load_campaign(path)
            self.assertEqual({}, loaded.knowledge_by_observer["faction:nato"])

    def test_cli_frontend_export_is_read_only_for_campaign_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            snapshot = root / "snapshot.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            save_campaign(state, path)
            before = path.read_bytes()

            self.assertEqual(
                0,
                cli_main(
                    [
                        "export-frontend",
                        str(path),
                        "--output",
                        str(snapshot),
                    ]
                ),
            )
            self.assertTrue(snapshot.is_file())
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
