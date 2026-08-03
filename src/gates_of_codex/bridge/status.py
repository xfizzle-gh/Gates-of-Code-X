from __future__ import annotations

import re
import time
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
    template_status: str = ""
    game_version: str = "1.065.0"
    campaign_name: str = "Gates of CodeX Acceptance"
    timestamp: int = 0
    mp: int = 1000
    sp: int = 100
    ap: int = 100
    rp: int = 100
    seed: int = 3024224791
    duration: int = 4
    fog_of_war: str = "fog_realistic"
    manual_control_mode: int = 3
    selected_map_point: str = "point_0_0"
    region: str = "ostfront"
    mods: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StatusResult:
    played_games: int
    won_games: int

    def player_won_since(self, previous: "StatusResult") -> bool:
        return self.won_games > previous.won_games


class StatusBuilder:
    """Build and patch the internal ``status`` entry of a Conquest save.

    The archive member is named ``status``, but the SDL document inside it must
    begin with ``{saveinfo``. GoH enumerates every Conquest save when the menu is
    opened, so a malformed root record crashes the entire Conquest dialog.
    """

    SAVEINFO_VERSION = 7

    def build(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        if options.template_status:
            return self._patch_template(pending, options)
        return self._build_fallback(pending, options)

    def _patch_template(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        text = self.validate(options.template_status)
        player = pending.player_faction.value
        enemy = pending.defender_faction.value if pending.player_is_attacker else pending.attacker_faction.value
        timestamp = options.timestamp or int(time.time())

        replacements = {
            "timestamp": str(timestamp),
            "mp": str(options.mp),
            "sp": str(options.sp),
            "ap": str(options.ap),
            "rp": str(options.rp),
            "seed": str(options.seed),
            "name": self._quoted(options.campaign_name),
            "army": player,
            "enemyArmy": enemy,
            "difficulty": options.difficulty,
            "duration": str(options.duration),
            "resources": str(options.resources),
            "fogofwar": options.fog_of_war,
            "manualControlMode": str(options.manual_control_mode),
            "selectedMapPoint": options.selected_map_point,
            "playedGames": str(options.played_games),
            "wonGames": str(options.won_games),
        }
        for key, value in replacements.items():
            text = self._set_scalar(text, key, value)

        text = self._set_presence(text, "attacking", pending.player_is_attacker)
        text = self._replace_block(text, "unlockedResearch", [f'{{"{value}"}}' for value in options.research])
        if options.mods:
            text = self._replace_block(text, "mods", [self._quoted(value) for value in options.mods])
        return self.validate(text)

    def _build_fallback(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        player = pending.player_faction.value
        enemy = pending.defender_faction.value if pending.player_is_attacker else pending.attacker_faction.value
        timestamp = options.timestamp or int(time.time())
        own_alliance = "allies" if player in {"nato", "ukr"} else "axis"
        enemy_alliance = "axis" if own_alliance == "allies" else "allies"
        lines = [
            "{saveinfo",
            f"\t{{version {self.SAVEINFO_VERSION}}}",
            f'\t{{gameVersion "{options.game_version}"}}',
            f"\t{{timestamp {timestamp}}}",
        ]
        if options.mods:
            lines.append("\t{mods")
            lines.extend(f'\t\t"{value}"' for value in options.mods)
            lines.append("\t}")
        lines.extend(
            [
                f"\t{{mp {options.mp}}}",
                f"\t{{sp {options.sp}}}",
                f"\t{{ap {options.ap}}}",
                f"\t{{rp {options.rp}}}",
                f"\t{{seed {options.seed}}}",
                f'\t{{name "{options.campaign_name}"}}',
                f"\t{{army {player}}}",
                f"\t{{ownAlliance {own_alliance}}}",
                f"\t{{enemyAlliance {enemy_alliance}}}",
                f"\t{{enemyArmy {enemy}}}",
                f"\t{{difficulty {options.difficulty}}}",
                f"\t{{duration {options.duration}}}",
                f"\t{{resources {options.resources}}}",
                f"\t{{fogofwar {options.fog_of_war}}}",
                f"\t{{manualControlMode {options.manual_control_mode}}}",
                f"\t{{selectedMapPoint {options.selected_map_point}}}",
            ]
        )
        if pending.player_is_attacker:
            lines.append("\t{attacking}")
        lines.extend(
            [
                f"\t{{region {options.region}}}",
                f"\t{{playedGames {options.played_games}}}",
                f"\t{{wonGames {options.won_games}}}",
                "\t{unlockedResearch",
            ]
        )
        lines.extend(f'\t\t{{"{value}"}}' for value in options.research)
        lines.extend(["\t}", "}"])
        return self.validate("\n".join(lines) + "\n")

    def parse_result(self, text: str) -> StatusResult:
        self.validate(text)
        return StatusResult(
            played_games=self._number(text, "playedGames"),
            won_games=self._number(text, "wonGames"),
        )

    @staticmethod
    def validate(text: str) -> str:
        normalized = text.lstrip("\ufeff\r\n\t ")
        if not normalized.startswith("{saveinfo"):
            first = normalized.splitlines()[0] if normalized else "<empty>"
            raise ValueError(f"Invalid Conquest status root; expected '{{saveinfo', found {first!r}")
        if normalized.count("{") != normalized.count("}"):
            raise ValueError("Invalid Conquest status document: unbalanced braces")
        return normalized if normalized.endswith("\n") else normalized + "\n"

    @staticmethod
    def _number(text: str, key: str) -> int:
        match = re.search(r"\{" + re.escape(key) + r"\s+(\d+)\}", text)
        return int(match.group(1)) if match else 0

    @classmethod
    def _set_scalar(cls, text: str, key: str, value: str) -> str:
        line = f"\t{{{key} {value}}}"
        pattern = re.compile(rf"(?m)^[ \t]*\{{{re.escape(key)}(?:\s+[^{{}}\r\n]*)?\}}[ \t]*$")
        if pattern.search(text):
            return pattern.sub(line, text, count=1)
        return cls._insert_before_close(text, line)

    @classmethod
    def _set_presence(cls, text: str, key: str, present: bool) -> str:
        pattern = re.compile(rf"(?m)^[ \t]*\{{{re.escape(key)}\}}[ \t]*\r?\n?")
        text = pattern.sub("", text)
        return cls._insert_before_close(text, f"\t{{{key}}}") if present else text

    @classmethod
    def _replace_block(cls, text: str, key: str, values: list[str]) -> str:
        lines = text.splitlines()
        start = next((index for index, line in enumerate(lines) if re.match(rf"^\s*\{{{re.escape(key)}(?:\s|\}})", line)), None)
        block = [f"\t{{{key}", *[f"\t\t{value}" for value in values], "\t}"]
        if start is None:
            return cls._insert_before_close(text, "\n".join(block))
        depth = 0
        end = start
        for index in range(start, len(lines)):
            depth += lines[index].count("{") - lines[index].count("}")
            end = index
            if depth <= 0:
                break
        return "\n".join([*lines[:start], *block, *lines[end + 1 :]]) + "\n"

    @staticmethod
    def _insert_before_close(text: str, line: str) -> str:
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            raise ValueError("Invalid Conquest status document: missing closing brace")
        return stripped[:-1].rstrip() + "\n" + line + "\n}\n"

    @staticmethod
    def _quoted(value: str) -> str:
        return '"' + value.replace('"', "'") + '"'
