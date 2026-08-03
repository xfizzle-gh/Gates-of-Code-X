from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import PendingBattle


@dataclass(slots=True)
class BattleStatusOptions:
    map_name: str
    difficulty: str = "normal"
    period: str = "2022s"
    resources: int = 1000
    research: list[str] = field(default_factory=list)
    played_games: int = 0
    won_games: int = 0


@dataclass(frozen=True, slots=True)
class StatusResult:
    played_games: int
    won_games: int

    def player_won_since(self, previous: "StatusResult") -> bool:
        return self.won_games > previous.won_games


class StatusBuilder:
    VERSION = 9

    def build(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        player = pending.player_faction.value
        enemy = pending.defender_faction.value if pending.player_is_attacker else pending.attacker_faction.value
        research = " ".join(f'"{key}"' for key in options.research)
        return (
            "{status\n"
            f"\t{{version {self.VERSION}}}\n"
            f'\t{{map "{options.map_name}"}}\n'
            f'\t{{difficulty "{options.difficulty}"}}\n'
            f'\t{{period "{options.period}"}}\n'
            f'\t{{playerArmy "{player}"}}\n'
            f'\t{{enemyArmy "{enemy}"}}\n'
            f"\t{{resources {options.resources}}}\n"
            f"\t{{playedGames {options.played_games}}}\n"
            f"\t{{wonGames {options.won_games}}}\n"
            f"\t{{research {research}}}\n"
            f'\t{{gocBattleId "{pending.battle_id}"}}\n'
            f"\t{{playerAttacking {1 if pending.player_is_attacker else 0}}}\n"
            "}\n"
        )

    def parse_result(self, text: str) -> StatusResult:
        return StatusResult(
            played_games=self._number(text, "playedGames"),
            won_games=self._number(text, "wonGames"),
        )

    @staticmethod
    def _number(text: str, key: str) -> int:
        match = re.search(r"\{" + re.escape(key) + r"\s+(\d+)\}", text)
        return int(match.group(1)) if match else 0
