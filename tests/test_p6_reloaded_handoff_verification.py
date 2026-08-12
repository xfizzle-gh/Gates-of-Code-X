from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class P6ReloadedHandoffVerificationTests(unittest.TestCase):
    def test_backend_defaults_verify_to_authoritative_pending_handoff_save(self) -> None:
        from gates_of_codex.frontend_commands import _resolve_result_save_path
        from gates_of_codex.models import Faction, PendingBattle

        save_path = r"C:\profile\campaign\gates of codex result.sav"
        pending = PendingBattle(
            battle_id="battle-reload-1",
            origin_province_id="origin",
            target_province_id="target",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[],
            defending_participants=[],
            player_faction=Faction.NATO,
            player_is_attacker=True,
            exported_save_path=save_path,
            started=True,
        )
        state = SimpleNamespace(pending_battle=pending)

        self.assertEqual(save_path, _resolve_result_save_path(state, {}))

    def test_reloaded_started_battle_can_verify_without_transient_handoff_path(self) -> None:
        source = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")

        self.assertIn("func _pending_battle_handoff_ready() -> bool:", source)
        self.assertIn(
            'return not pending.is_empty() and bool(pending.get("started", false))',
            source,
        )
        self.assertIn('["verify_result", writeback and handoff_ready]', source)

        verify_block = source.split('if button_id == "verify_result":', 1)[1].split(
            'if button_id == "import_battle":', 1
        )[0]
        self.assertIn('var verify_command := {"op": "verify_result"}', verify_block)
        self.assertIn(
            "if not _pending_battle_handoff_ready() and last_handoff_save_path.is_empty():",
            verify_block,
        )
        self.assertIn(
            'verify_command["save_path"] = last_handoff_save_path', verify_block
        )

    def test_rendered_verify_control_matches_persisted_handoff_readiness(self) -> None:
        source = (ROOT / "godot/scripts/main_perf.gd").read_text(encoding="utf-8")

        draw_block = source.split(
            "func _draw_button(id: String, label: String, x: float, y: float, enabled: bool",
            1,
        )[1].split("func _draw_color_id_overlays()", 1)[0]
        self.assertIn(
            'elif id == "verify_result" and _pending_battle_handoff_ready():',
            draw_block,
        )
        self.assertIn(
            'enabled = enabled or bool(snapshot.get("control", {}).get("enabled", false))',
            draw_block,
        )

    def test_verified_backend_identity_rehydrates_import_binding(self) -> None:
        source = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")

        capture = source.split("func _capture_verification(payload: Dictionary) -> void:", 1)[1].split(
            "func player_launch_block() -> Dictionary:", 1
        )[0]
        self.assertIn('var verified_battle_id := String(data.get("battle_id", ""))', capture)
        self.assertIn("verified_battle_id != pending_id", capture)
        self.assertIn("last_handoff_battle_id = verified_battle_id", capture)
        self.assertIn("last_handoff_save_path = last_verified_save_path", capture)

        import_block = source.split('if button_id == "import_battle":', 1)[1].split(
            "if is_pending_battle_modal_active()", 1
        )[0]
        self.assertIn('"save_path": last_verified_save_path', import_block)


if __name__ == "__main__":
    unittest.main()
