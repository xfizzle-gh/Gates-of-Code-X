from __future__ import annotations

import re
import unittest
from pathlib import Path


RESOLVED_GOC_UNIT_RE = re.compile(
    r"^; resolved_unit=(.+\(goc_[^)]+\))$",
    re.MULTILINE,
)
LOCALIZATION_CONTEXT_RE = re.compile(
    r'^msgctxt "desc/squad/([^"]+)"$',
    re.MULTILINE,
)


class ExpandedNationsLocalizationCoverageTests(unittest.TestCase):
    def test_every_side_qualified_expanded_nations_unit_is_localized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        conquest = root / "resource/set/multiplayer/units/conquest"
        localization_dir = root / "localizations/default/interface/text/desc"

        required: set[str] = set()
        for path in sorted(conquest.glob("units_goc_*.set")):
            required.update(
                RESOLVED_GOC_UNIT_RE.findall(path.read_text(encoding="utf-8"))
            )

        localized: set[str] = set()
        contexts: list[str] = []
        for path in sorted(
            localization_dir.glob("desc_squad_goc_expanded_nations*.pot")
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('msgid  "???"', text, path.as_posix())
            found = LOCALIZATION_CONTEXT_RE.findall(text)
            contexts.extend(found)
            localized.update(found)

        self.assertTrue(required, "no generated goc_* purchase identities were found")
        self.assertEqual(
            [],
            sorted(required - localized),
            "side-qualified Expanded Nations purchase identities are missing localization",
        )
        self.assertEqual(
            len(contexts),
            len(set(contexts)),
            "Expanded Nations localization contexts must be unique",
        )


if __name__ == "__main__":
    unittest.main()
