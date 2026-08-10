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
from gates_of_codex.models import Faction, PendingBattle


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
        self.assertIn(str(local_gates), message)

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


if __name__ == "__main__":
    unittest.main()
