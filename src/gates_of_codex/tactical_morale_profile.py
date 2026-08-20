"""Phase A tactical morale-profile mapping (#273).

This module classifies infantry/unit definitions onto the existing
Steady → Shaken → Panic → Broken morale ladder. It does not create a second
morale system and does not change pressure, shock, recovery, thresholds,
surrender, or traits.

Verified materialization seam
-----------------------------
``CampaignScnBuilder.build`` / ``ParticipantScopedCampaignScnBuilder.build``
read each participating ``Battalion.roster`` entry and the matching
``UnitDefinition`` from the scoped Code:X catalog, then write ``Human`` /
``Entity`` objects into ``campaign.scn``. Those objects are the in-repo
tactical unit carrier.

The authored profile lives on ``UnitDefinition.morale_profile``. Empty means
the safe default ``regular``. Mapping never consults faction/side names,
display names, or real-world organization tokens.

Rejected hunches
----------------
- Inferring militia/contractor/sof/elite from faction, actor, or side names.
- Inferring from unit/breed/component identifiers (Wagner, Spetsnaz, Azov, …).
- Adding ``morale_profile`` to campaign-save ``Battalion`` / roster rows
  (Slice 4 / #266 save surface).
- Inventing Code:X AI Overhaul hidden-property names. That workshop source is
  not in this repository, so its internal carrier cannot be verified here.

Carrier
-------
Gates writes one GEM ``{Tags}`` token, ``goc_morale_profile:<profile>``, onto
each materialized ``Human`` / ``Entity``. ``{Tags}`` is the existing entity
tag field already used by the tactical stack. Phase A is visibility / logging
only.
"""

from __future__ import annotations

import re
from typing import Any

ALLOWED_MORALE_PROFILES = frozenset({"militia", "regular", "contractor", "sof", "elite"})
DEFAULT_MORALE_PROFILE = "regular"
MORALE_PROFILE_TAG_PREFIX = "goc_morale_profile:"
MORALE_PROFILE_LOG_PREFIX = "goc_morale_profile"


class UnknownMoraleProfileError(ValueError):
    """Raised when an authored morale profile is not one of the allowed values."""


_CARRIER_TAG_RE = re.compile(
    r'\{Tags\s+"' + re.escape(MORALE_PROFILE_TAG_PREFIX) + r'([^"]+)"\s*\}'
)
_OBJECT_HEADER_RE = re.compile(
    r'\{(?P<kind>Human|Entity)\s+"[^"]+"\s+(?P<object_id>0x[0-9a-fA-F]+)',
)
_LOG_COMMENT_RE = re.compile(
    r"^;\s*"
    + re.escape(MORALE_PROFILE_LOG_PREFIX)
    + r"\s+unit=(?P<unit>\S+)\s+profile=(?P<profile>\S+)\s+"
    r"object=(?P<object_id>0x[0-9a-fA-F]+)\s+carrier=(?P<carrier>\S+)\s*$",
    flags=re.M,
)


def normalize_morale_profile(value: str | None) -> str:
    """Return an allowed profile. Blank/omitted becomes ``regular``.

    Unknown strings fail closed. Case and aliases are not repaired.
    """

    if value is None:
        return DEFAULT_MORALE_PROFILE
    if not isinstance(value, str):
        raise UnknownMoraleProfileError(
            f"unknown morale profile {value!r}; allowed: {sorted(ALLOWED_MORALE_PROFILES)}"
        )
    profile = value.strip()
    if not profile:
        return DEFAULT_MORALE_PROFILE
    if profile not in ALLOWED_MORALE_PROFILES:
        raise UnknownMoraleProfileError(
            f"unknown morale profile {value!r}; allowed: {sorted(ALLOWED_MORALE_PROFILES)}"
        )
    return profile


def morale_profile_from_unit_definition(definition: Any) -> str:
    """Map one catalog unit definition onto a morale profile.

    Only the explicit ``morale_profile`` field is consulted. Faction, side,
    unit name, type tags, and category are ignored so the engine cannot guess
    from organization or faction labels.
    """

    return normalize_morale_profile(getattr(definition, "morale_profile", ""))


def morale_profile_tag(profile: str) -> str:
    return f"{MORALE_PROFILE_TAG_PREFIX}{normalize_morale_profile(profile)}"


def morale_profile_carrier_line(profile: str, *, indent: str = "\t\t") -> str:
    return f'{indent}{{Tags "{morale_profile_tag(profile)}"}}'


def morale_profile_log_line(
    *,
    unit_name: str,
    profile: str,
    object_id: str,
    carrier: str,
) -> str:
    resolved = normalize_morale_profile(profile)
    return (
        f"{MORALE_PROFILE_LOG_PREFIX} unit={unit_name} profile={resolved} "
        f"object={object_id} carrier={carrier}"
    )


def morale_profile_log_comment(
    *,
    unit_name: str,
    profile: str,
    object_id: str,
    carrier: str,
) -> str:
    return "; " + morale_profile_log_line(
        unit_name=unit_name,
        profile=profile,
        object_id=object_id,
        carrier=carrier,
    )


def parse_morale_profile_carriers(scn_text: str) -> list[tuple[str, str, str]]:
    """Return ``(kind, object_id, profile)`` for each Human/Entity carrier tag."""

    found: list[tuple[str, str, str]] = []
    for match in _OBJECT_HEADER_RE.finditer(scn_text):
        block = _extract_brace_block(scn_text, match.start())
        tag = _CARRIER_TAG_RE.search(block)
        if tag is None:
            continue
        found.append((match.group("kind"), match.group("object_id"), tag.group(1)))
    return found


def parse_morale_profile_logs(scn_text: str) -> list[dict[str, str]]:
    return [
        {
            "unit": match.group("unit"),
            "profile": match.group("profile"),
            "object_id": match.group("object_id"),
            "carrier": match.group("carrier"),
        }
        for match in _LOG_COMMENT_RE.finditer(scn_text)
    ]


def _extract_brace_block(text: str, start: int) -> str:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]
