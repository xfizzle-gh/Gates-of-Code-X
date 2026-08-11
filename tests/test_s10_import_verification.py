from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex.frontend_commands import _apply_import_battle


class S10ImportVerificationTests(unittest.TestCase):
    def test_failed_stack_verification_prevents_import_and_mutation(self) -> None:
        """A stack-verification failure must block import and mutate nothing.

        The manifest here is bound to this exact campaign, save and battle — as
        every real manifest is, since ``BattleExportManifest`` requires all three
        — so the only thing under test is the stack verdict. An unbound stub
        would be refused by the identity gate instead, and this test would pass
        for the wrong reason.
        """
        campaign_path = Path("campaign.json").resolve()
        save_path = Path("completed.sav").resolve()
        pending = SimpleNamespace(
            exported_save_path=str(save_path), battle_id="goc-battle-1"
        )
        state = SimpleNamespace(
            pending_battle=pending,
            map_metadata={"resource_stack": ["stack-root"]},
            code_x_directory="",
        )
        manifest = SimpleNamespace(
            resource_stack=["stack-root"],
            battle_id="goc-battle-1",
            campaign_path=str(campaign_path),
            save_path=str(save_path),
        )
        failure = SimpleNamespace(
            ok=False,
            errors=["Installed acceptance save was not rewritten by GoH"],
        )

        with (
            patch(
                "gates_of_codex.service.GatesOfCodeXService.load_manifest",
                return_value=manifest,
            ),
            patch(
                "gates_of_codex.stack_acceptance.verify_stack_result",
                return_value=failure,
            ) as verify_result,
            patch(
                "gates_of_codex.service.GatesOfCodeXService.import_battle"
            ) as import_battle,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "GoH result verification failed: Installed acceptance save was not rewritten by GoH",
            ):
                _apply_import_battle(
                    campaign_path,
                    state,
                    {"save_path": str(save_path)},
                )

        verify_result.assert_called_once()
        import_battle.assert_not_called()
        self.assertIs(state.pending_battle, pending)

    def test_an_unbound_manifest_is_refused_before_stack_verification(self) -> None:
        """The identity gate runs first, so content checks never see it."""
        campaign_path = Path("campaign.json").resolve()
        save_path = Path("completed.sav").resolve()
        state = SimpleNamespace(
            pending_battle=SimpleNamespace(
                exported_save_path=str(save_path), battle_id="goc-battle-1"
            ),
            map_metadata={"resource_stack": ["stack-root"]},
            code_x_directory="",
        )
        # Names another tactical save: the binding Verify previously never read.
        manifest = SimpleNamespace(
            resource_stack=["stack-root"],
            battle_id="goc-battle-1",
            campaign_path=str(campaign_path),
            save_path=str(Path("someone-elses.sav").resolve()),
        )

        with (
            patch(
                "gates_of_codex.service.GatesOfCodeXService.load_manifest",
                return_value=manifest,
            ),
            patch(
                "gates_of_codex.stack_acceptance.verify_stack_result"
            ) as verify_result,
            patch(
                "gates_of_codex.service.GatesOfCodeXService.import_battle"
            ) as import_battle,
        ):
            with self.assertRaisesRegex(ValueError, "different tactical save|belongs to tactical save"):
                _apply_import_battle(
                    campaign_path, state, {"save_path": str(save_path)}
                )

        verify_result.assert_not_called()
        import_battle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
