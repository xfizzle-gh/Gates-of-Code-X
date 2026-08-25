from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "godot/scripts/main_stack_panel.gd"
PAGE = 4


def visible_move_slice(options: list[str], scroll: int, page: int = PAGE) -> tuple[list[str], int]:
    max_scroll = max(len(options) - page, 0)
    scroll = min(max(scroll, 0), max_scroll)
    return options[scroll : scroll + page], scroll


class GodotMoveListScrollContractTests(unittest.TestCase):
    def test_live_panel_pages_legal_move_buttons(self) -> None:
        source = STACK.read_text(encoding="utf-8")
        self.assertIn("const MOVE_LIST_PAGE := 4", source)
        self.assertIn("move_list_scroll", source)
        self.assertIn("_visible_move_options", source)
        self.assertIn("options.slice(move_list_scroll", source)
        self.assertIn('"move:%s" % tid', source)
        self.assertIn("_move_scroll_up_rect", source)
        self.assertIn("_move_scroll_down_rect", source)
        self.assertIn("_move_list_rect", source)
        self.assertIn("MOUSE_BUTTON_WHEEL_UP", source)
        self.assertIn("MOUSE_BUTTON_WHEEL_DOWN", source)
        self.assertNotIn("shown >= 4", source)
        self.assertNotIn("click the map to order", source)
        self.assertIn(
            "Order locked until it resolves — no new order this turn.",
            source,
        )

    def test_short_list_shows_every_destination(self) -> None:
        options = ["a", "b", "c"]
        visible, scroll = visible_move_slice(options, 0)
        self.assertEqual(scroll, 0)
        self.assertEqual(visible, options)

    def test_first_page_hides_later_destinations(self) -> None:
        options = [f"d{i:02d}" for i in range(12)]
        visible, scroll = visible_move_slice(options, 0)
        self.assertEqual(scroll, 0)
        self.assertEqual(visible, options[:PAGE])
        self.assertNotIn(options[PAGE], visible)
        self.assertNotIn(options[-1], visible)

    def test_later_page_reaches_a_middle_destination(self) -> None:
        options = [f"d{i:02d}" for i in range(12)]
        visible, scroll = visible_move_slice(options, 5)
        self.assertEqual(scroll, 5)
        self.assertEqual(visible, options[5:9])
        self.assertIn("d05", visible)
        self.assertNotIn("d00", visible)

    def test_scroll_clamps_to_last_page(self) -> None:
        options = [f"d{i:02d}" for i in range(12)]
        visible, scroll = visible_move_slice(options, 99)
        self.assertEqual(scroll, 8)
        self.assertEqual(visible, options[-PAGE:])
        self.assertIn(options[-1], visible)


if __name__ == "__main__":
    unittest.main()
