from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex.frontend_commands import _apply_import_battle


class S10ImportVerificationTests(unittest.TestCase):
    def test_failed_stack_verification_prevents_import_and_mutation(self) -> None:
        pending = SimpleNamespace(exported_save_path="completed.sav")
        state = SimpleNamespace(
            pending_battle=pending,
            map_metadata={"resource_stack": ["stack-root"]},
            code_x_directory="",
        )
        manifest = SimpleNamespace(resource_stack=["stack-root"])
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
                    Path("campaign.json"),
                    state,
                    {"save_path": "completed.sav"},
                )

        verify_result.assert_called_once()
        import_battle.assert_not_called()
        self.assertIs(state.pending_battle, pending)


if __name__ == "__main__":
    unittest.main()
