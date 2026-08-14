from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..models import PendingBattle

_CORE_ARMIES = frozenset({"nato", "ukr", "rusa", "prc"})


def pending_tactical_armies(pending: PendingBattle) -> tuple[str, str]:
    """Resolve GoH {army}/{enemyArmy} without leaking strategic-neutral identity."""
    player = str(pending.player_faction.value)
    if pending.player_is_attacker:
        enemy = str(pending.tactical_defender_side or pending.defender_faction.value)
    else:
        enemy = str(pending.attacker_faction.value)
    if player not in _CORE_ARMIES:
        raise ValueError(f"tactical player army is not a core Code:X side: {player}")
    if enemy not in _CORE_ARMIES:
        raise ValueError(f"tactical enemy army is not a core Code:X side: {enemy}")
    if player == enemy:
        raise ValueError(f"tactical armies must be distinct, got {player} vs {enemy}")
    return player, enemy


@dataclass(slots=True)
class BattleStatusOptions:
    map_name: str
    difficulty: str = "normal"
    period: str = "2022s"
    # GoH treats {resources N} as a preset enum (commonly 0-3), not CP.
    resources: int = 2
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
    # Duration is also a small preset index in real Conquest saves.
    duration: int = 3
    fog_of_war: str = "fog_realistic"
    manual_control_mode: int = 3
    selected_map_point: str = "point_0_0"
    region: str = "ostfront"
    # ``None`` means the caller did not specify dependencies and the template
    # block is preserved. An explicit list -- including an empty one -- always
    # replaces it, so a handoff can never inherit template dependencies (#166).
    mods: list[str] | None = None
    preserve_template_map_point: bool = True
    preserve_template_campaign_options: bool = True


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
    _SCALAR_KEYS = (
        "version",
        "gameVersion",
        "timestamp",
        "mp",
        "sp",
        "ap",
        "rp",
        "seed",
        "name",
        "army",
        "ownAlliance",
        "enemyAlliance",
        "enemyArmy",
        "difficulty",
        "duration",
        "resources",
        "fogofwar",
        "manualControlMode",
        "selectedMapPoint",
        "region",
        "playedGames",
        "wonGames",
    )

    def build(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        if options.template_status:
            return self._patch_template(pending, options)
        return self._build_fallback(pending, options)

    def _patch_template(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        text = self.validate(options.template_status)
        player, enemy = pending_tactical_armies(pending)
        timestamp = options.timestamp or int(time.time())

        replacements = {
            "timestamp": str(timestamp),
            "name": self._quoted(options.campaign_name),
            "army": player,
            "enemyArmy": enemy,
            "playedGames": str(options.played_games),
            "wonGames": str(options.won_games),
        }
        if not options.preserve_template_campaign_options:
            # Only override when explicitly requested. Real saves store small enum
            # indices for resources/duration; stuffing CP-scale values crashes load
            # with "Invalid Resource Value" in eCampaignOptions.
            replacements.update(
                {
                    "mp": str(options.mp),
                    "sp": str(options.sp),
                    "ap": str(options.ap),
                    "rp": str(options.rp),
                    "seed": str(options.seed),
                    "difficulty": options.difficulty,
                    "duration": str(self._clamp_duration(options.duration)),
                    "resources": str(self._clamp_resources(options.resources)),
                    "fogofwar": options.fog_of_war,
                    "manualControlMode": str(options.manual_control_mode),
                }
            )
        if not options.preserve_template_map_point:
            replacements["selectedMapPoint"] = options.selected_map_point
        for key, value in replacements.items():
            text = self._set_scalar(text, key, value)

        text = self._set_presence(text, "attacking", pending.player_is_attacker)
        text = self._replace_block(text, "unlockedResearch", [f'{{"{value}"}}' for value in options.research])
        if options.mods is not None:
            text = self._replace_block(text, "mods", [self._quoted(value) for value in options.mods])
        if options.map_name:
            text = self._set_selected_point_map(text, options.map_name)
        return self.validate(text)

    def _build_fallback(self, pending: PendingBattle, options: BattleStatusOptions) -> str:
        player, enemy = pending_tactical_armies(pending)
        timestamp = options.timestamp or int(time.time())
        own_alliance = "allies" if player in {"nato", "ukr"} else "axis"
        enemy_alliance = "axis" if own_alliance == "allies" else "allies"
        map_spec = self._format_map_spec(options.map_name)
        lines = [
            "{saveinfo",
            f"\t{{version {self.SAVEINFO_VERSION}}}",
            f'\t{{gameVersion "{options.game_version}"}}',
            f"\t{{timestamp {timestamp}}}",
        ]
        if options.mods is not None:
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
                f"\t{{duration {self._clamp_duration(options.duration)}}}",
                f"\t{{resources {self._clamp_resources(options.resources)}}}",
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
        lines.extend(
            [
                "\t}",
                "\t{mapPoints",
                "\t\t{",
                f"\t\t\t{{name {options.selected_map_point}}}",
                "\t\t\t{landscape wood}",
                "\t\t\t{gamemode campaign_capture_the_flag}",
                "\t\t\t{ownerTeam a}",
                "\t\t\t{adjacentMaps}",
                '\t\t\t{risk ""}',
                "\t\t\t{reward none}",
                f'\t\t\t{{map "{map_spec}"}}',
                "\t\t\t{texmod camo}",
                "\t\t}",
                "\t}",
                "\t{roundsHistory}",
                "}",
            ]
        )
        return self.validate("\n".join(lines) + "\n")

    def parse_result(self, text: str) -> StatusResult:
        self.validate(text)
        return StatusResult(
            played_games=self._number(text, "playedGames"),
            won_games=self._number(text, "wonGames"),
        )

    @classmethod
    def validate(cls, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff\n\t ")
        if not normalized.startswith("{saveinfo"):
            first = normalized.splitlines()[0] if normalized else "<empty>"
            raise ValueError(f"Invalid Conquest status root; expected '{{saveinfo', found {first!r}")
        if normalized.count("{") != normalized.count("}"):
            raise ValueError("Invalid Conquest status document: unbalanced braces")
        cls._reject_duplicate_scalars(normalized)
        return normalized if normalized.endswith("\n") else normalized + "\n"

    @classmethod
    def _reject_duplicate_scalars(cls, text: str) -> None:
        # Only top-level saveinfo keys (single indent). Nested mapPoints use {name ...} too.
        for key in cls._SCALAR_KEYS:
            matches = re.findall(rf"(?m)^\t\{{{re.escape(key)}(?:\s|\}})", text)
            if len(matches) > 1:
                raise ValueError(
                    f"Invalid Conquest status document: duplicate '{{{key}' entries "
                    f"({len(matches)}). GoH crashes the Load Conquest dialog on malformed saveinfo."
                )

    @staticmethod
    def _number(text: str, key: str) -> int:
        match = re.search(r"\{" + re.escape(key) + r"\s+(\d+)\}", text)
        return int(match.group(1)) if match else 0

    @classmethod
    def _set_scalar(cls, text: str, key: str, value: str) -> str:
        line = f"\t{{{key} {value}}}"
        # Top-level saveinfo only. Nested mapPoints also use {name ...}.
        pattern = re.compile(rf"(?m)^\t\{{{re.escape(key)}(?:\s+[^{{\}}\r\n]*)?\}}[ \t]*$")
        matches = list(pattern.finditer(text))
        if not matches:
            return cls._insert_before_close(text, line)
        if len(matches) > 1:
            raise ValueError(f"Refusing to patch ambiguous saveinfo key '{{{key}' ({len(matches)} matches)")
        start, end = matches[0].span()
        return text[:start] + line + text[end:]

    @classmethod
    def _set_presence(cls, text: str, key: str, present: bool) -> str:
        pattern = re.compile(rf"(?m)^\t\{{{re.escape(key)}\}}[ \t]*\n?")
        text = pattern.sub("", text)
        return cls._insert_before_close(text, f"\t{{{key}}}") if present else text

    @classmethod
    def _replace_block(cls, text: str, key: str, values: list[str]) -> str:
        lines = text.splitlines()
        start = next(
            (
                index
                for index, line in enumerate(lines)
                if re.match(rf"^\s*\{{{re.escape(key)}(?:\s|\}}|$)", line)
            ),
            None,
        )
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

    @classmethod
    def _set_selected_point_map(cls, text: str, map_name: str) -> str:
        point_match = re.search(r"(?m)^[ \t]*\{selectedMapPoint\s+(\S+)\}[ \t]*$", text)
        if point_match is None:
            return text
        point_name = point_match.group(1)
        name_pattern = re.compile(rf"(?m)^[ \t]*\{{name {re.escape(point_name)}\}}[ \t]*$")
        name_match = name_pattern.search(text)
        if name_match is None:
            raise ValueError(
                f"selectedMapPoint {point_name!r} is missing from mapPoints; "
                "GoH crashes when the active point cannot be resolved"
            )
        rest = text[name_match.end() :]
        next_name = re.search(r"(?m)^[ \t]*\{name\s+\S+\}[ \t]*$", rest)
        map_match = re.search(r'\{map\s+"([^"]*)"\}', rest)
        if map_match is None or (next_name is not None and map_match.start() > next_name.start()):
            raise ValueError(f"mapPoints entry {point_name!r} has no {{map}} field")
        existing = map_match.group(1)
        suffix = existing[existing.find(":") :] if ":" in existing else ":campaign_capture_the_flag:4x4"
        replacement = '{map "' + cls._format_map_spec(map_name, suffix) + '"}'
        absolute_start = name_match.end() + map_match.start()
        absolute_end = name_match.end() + map_match.end()
        return text[:absolute_start] + replacement + text[absolute_end:]

    @staticmethod
    def _format_map_spec(map_name: str, suffix: str = ":campaign_capture_the_flag:4x4") -> str:
        cleaned = map_name.strip().strip('"')
        if not cleaned:
            raise ValueError("map_name is empty")
        if ":" in cleaned:
            return cleaned
        return cleaned + suffix

    @staticmethod
    def _clamp_resources(value: int) -> int:
        return min(max(int(value), 0), 3)

    @staticmethod
    def _clamp_duration(value: int) -> int:
        return min(max(int(value), 0), 4)

    @staticmethod
    def _insert_before_close(text: str, line: str) -> str:
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            raise ValueError("Invalid Conquest status document: missing closing brace")
        # Prefer inserting before the final saveinfo close, after roundsHistory when present.
        return stripped[:-1].rstrip() + "\n" + line + "\n}\n"

    @staticmethod
    def _quoted(value: str) -> str:
        return '"' + value.replace('"', "'") + '"'
