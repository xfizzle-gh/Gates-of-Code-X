from __future__ import annotations

import re
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_presentation import (
    project_actor_presentation,
    render_actor_research_localization,
)


ARMY_TITLE_RE = re.compile(r'\{title\s+"([^"]+)"\}')
POT_ENTRY_RE = re.compile(
    r'msgctxt "([^"]+)"\s*\nmsgid\s+"([^"]*)"\s*\nmsgstr\s+"([^"]*)"',
    re.MULTILINE,
)
RESEARCH_CONTEXT_RE = re.compile(r'^msgctxt "(dcg/research/[^"]+)"$', re.MULTILINE)


class ExpandedNationsConquestLocalizationTests(unittest.TestCase):
    def test_every_goc_army_title_has_root_localization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        army_dir = root / "resource/set/multiplayer/armies"
        catalog = (
            root
            / "localizations/default/interface/text/dlg_mp_goc_expanded_nations.pot"
        )

        required: set[str] = set()
        for path in sorted(army_dir.glob("goc_*.set")):
            matches = ARMY_TITLE_RE.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(matches), path.as_posix())
            required.add(matches[0])

        text = catalog.read_text(encoding="utf-8")
        entries = {
            context: (msgid, msgstr)
            for context, msgid, msgstr in POT_ENTRY_RE.findall(text)
        }
        localized = {key for key in entries if key.startswith("mp/army/goc_")}

        self.assertTrue(required, "no goc_* army title keys were found")
        self.assertEqual(
            [],
            sorted(required - localized),
            "Expanded Nations army-selection labels are missing localization",
        )
        self.assertEqual(
            [],
            sorted(localized - required),
            "army localization contains stale goc_* title keys",
        )
        for key in sorted(required):
            msgid, msgstr = entries[key]
            self.assertTrue(msgid.strip(), key)
            self.assertEqual(msgid, msgstr, key)
            self.assertNotEqual("???", msgid.strip(), key)

    def test_active_research_localization_uses_final_purchase_ids(self) -> None:
        actor = {
            "actor_id": "fixture",
            "display_name": "Fixture Force",
            "research_nodes": [
                {
                    "key": "actor:fixture:root",
                    "display_name": "Fixture Force",
                    "unlock_units": [],
                },
                {
                    "key": "actor:fixture:qualified",
                    "display_name": "Fixture Anti-Tank Team",
                    "unlock_units": ["squad_fixture_at(goc_fixture)"],
                },
                {
                    "key": "actor:fixture:bare",
                    "display_name": "Fixture Vehicle",
                    "unlock_units": ["fixture_vehicle"],
                },
            ],
        }

        text = render_actor_research_localization(actor)
        self.assertEqual(
            {
                "dcg/research/squad_fixture_at(goc_fixture)",
                "dcg/research/fixture_vehicle",
            },
            set(RESEARCH_CONTEXT_RE.findall(text)),
        )
        self.assertIn('msgid "Fixture Anti-Tank Team"', text)
        self.assertIn('msgid "Fixture Vehicle"', text)
        self.assertNotIn("???", text)

        outputs = project_actor_presentation(actor, [])
        self.assertEqual(1, len(outputs))
        relative, payload = next(iter(outputs.items()))
        self.assertEqual(
            "localizations/default/interface/text/dcg_research_goc_active_actor.pot",
            relative.as_posix(),
        )
        self.assertEqual(text, payload.decode("utf-8"))

    def test_research_localization_rejects_unreadable_or_duplicate_nodes(self) -> None:
        with self.assertRaisesRegex(ValueError, "no readable display name"):
            render_actor_research_localization(
                {
                    "actor_id": "fixture",
                    "research_nodes": [
                        {
                            "key": "actor:fixture:bad",
                            "display_name": "???",
                            "unlock_units": ["bad(goc_fixture)"],
                        }
                    ],
                }
            )

        with self.assertRaisesRegex(ValueError, "duplicate purchase ID"):
            render_actor_research_localization(
                {
                    "actor_id": "fixture",
                    "research_nodes": [
                        {
                            "key": "actor:fixture:a",
                            "display_name": "One",
                            "unlock_units": ["same(goc_fixture)"],
                        },
                        {
                            "key": "actor:fixture:b",
                            "display_name": "Two",
                            "unlock_units": ["same(goc_fixture)"],
                        },
                    ],
                }
            )

    def test_canonical_active_army_labels_are_human_readable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (
            root
            / "localizations/default/interface/text/dlg_mp_goc_expanded_nations.pot"
        ).read_text(encoding="utf-8")
        entries = {
            context: msgid
            for context, msgid, _msgstr in POT_ENTRY_RE.findall(text)
        }
        expected = {
            "mp/army/goc_blr": "Belarus",
            "mp/army/goc_can": "Canada",
            "mp/army/goc_deu": "Germany",
            "mp/army/goc_donbas": "Donbas Forces",
            "mp/army/goc_dprk": "North Korea",
            "mp/army/goc_esp": "Spain",
            "mp/army/goc_fin": "Finland",
            "mp/army/goc_fra": "France",
            "mp/army/goc_gbr": "United Kingdom",
            "mp/army/goc_ita": "Italy",
            "mp/army/goc_nld": "Netherlands",
            "mp/army/goc_nor": "Norway",
            "mp/army/goc_pol": "Poland",
            "mp/army/goc_rus": "Russia",
            "mp/army/goc_srb": "Serbia",
            "mp/army/goc_swe": "Sweden",
            "mp/army/goc_tur": "Turkey",
            "mp/army/goc_ukr": "Ukraine",
            "mp/army/goc_usa": "United States",
        }
        for key, label in expected.items():
            self.assertEqual(label, entries.get(key), key)


if __name__ == "__main__":
    unittest.main()
