from __future__ import annotations

import unittest

from gates_of_codex.cli import build_parser


class EconomyCliTests(unittest.TestCase):
    def test_research_command(self) -> None:
        args = build_parser().parse_args(
            ["research", "campaign.json", "--faction", "nato", "--key", "codex:nato:category:tank"]
        )
        self.assertEqual("research", args.command)
        self.assertEqual("nato", args.faction)

    def test_recruitment_commands(self) -> None:
        recruit = build_parser().parse_args(
            [
                "recruit",
                "campaign.json",
                "--formation",
                "nato-us-armored",
                "--unit",
                "tank(nato)",
                "--quantity",
                "2",
            ]
        )
        self.assertEqual(2, recruit.quantity)
        assign = build_parser().parse_args(
            [
                "assign-reinforcements",
                "campaign.json",
                "--formation",
                "nato-us-armored",
                "--unit",
                "tank(nato)",
            ]
        )
        self.assertEqual("assign-reinforcements", assign.command)

    def test_repair_and_status_commands(self) -> None:
        repair = build_parser().parse_args(
            ["repair", "campaign.json", "--formation", "nato-us-armored", "--points", "10"]
        )
        self.assertEqual(10, repair.points)
        status = build_parser().parse_args(["economy-status", "campaign.json", "--faction", "nato"])
        self.assertEqual("economy-status", status.command)


if __name__ == "__main__":
    unittest.main()
