from __future__ import annotations

import unittest
from types import SimpleNamespace

from gates_of_codex.bridge.scn import CampaignScnBuilder, CampaignScnParser


class DeadObjectSentinelTests(unittest.TestCase):
    @staticmethod
    def _campaign_scn(*rows: str) -> str:
        return (
            "{campaign\n"
            '\t{Human "mp/nato/2022s/rifleman" 0x8000\n\t}\n'
            "\t{Inventory 0x8000\n\t}\n"
            "\t{CampaignSquads\n"
            + "\n".join(f"\t\t{row}" for row in rows)
            + "\n\t}\n}\n"
        )

    def test_mixed_live_and_dead_sentinel_keeps_only_live_object(self) -> None:
        text = self._campaign_scn('{"rifle(nato)" "stage-a" 0x8000 0xffffffff}')

        CampaignScnBuilder.validate(text)
        squads = CampaignScnParser().parse_squads(text)

        self.assertEqual(["0x8000"], squads[0].object_ids)

    def test_sentinel_only_squad_is_not_imported_as_survivor(self) -> None:
        text = self._campaign_scn('{"rifle(nato)" "stage-a" 0xFFFFFFFF}')
        pending = SimpleNamespace(
            attacking_participants=[SimpleNamespace(stage="stage-a", battalion_id="battalion-a")],
            defending_participants=[],
        )

        CampaignScnBuilder.validate(text)
        squads = CampaignScnParser().parse_squads(text)
        rosters = CampaignScnParser().survivor_rosters(text, pending)

        self.assertEqual([], squads[0].object_ids)
        self.assertNotIn("battalion-a", rosters)

    def test_missing_real_object_id_still_fails_validation(self) -> None:
        text = self._campaign_scn('{"rifle(nato)" "stage-a" 0x9999}')

        with self.assertRaisesRegex(ValueError, "Invalid object graph for 0x9999"):
            CampaignScnBuilder.validate(text)


if __name__ == "__main__":
    unittest.main()
