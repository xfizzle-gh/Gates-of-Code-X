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
``Entity`` objects and ``{Inventory <object_id>}`` blocks into
``campaign.scn``.

The authored profile lives on ``UnitDefinition.morale_profile``. Empty means
the safe default ``regular``. Mapping never consults faction/side names,
display names, or real-world organization tokens.

AIO carrier (Phase A-3)
-----------------------
The existing Code:X AI Overhaul morale layer (Workshop ``3636883799`` morale
pack) reads a hidden inventory item on the human, then a runtime entity tag
after apply:

    militia    -> aio_marker_morale_low      -> aio_morale_low
    regular    -> aio_marker_morale_regular  -> aio_morale_regular
    contractor -> aio_marker_morale_trained  -> aio_morale_trained
    sof        -> aio_marker_morale_elite    -> aio_morale_elite
    elite      -> aio_marker_morale_elite    -> aio_morale_elite

The existing layer has only four buckets. ``sof`` and ``elite`` collapse onto
elite. Do not invent ``aio_marker_morale_sof``, ``aio_marker_morale_contractor``,
or a fifth stuff item.

Apply path (``ce_morale_marker_apply_triggers.inc``) matches
``{prop human}`` + ``{with_item {item "aio_marker_morale_*"}}``. AIO forbids
``aio_*`` tokens in breed ``{tags}``. Therefore the writable seam is the Human
``{Inventory}`` GOCX already emits. Vehicle Entity inventories stay empty of
morale markers.

Catalog ``morale_profile`` wins over any breed-copied AIO marker (for example
a Wagner/PMC breed that already has ``aio_marker_morale_trained``).

``{Tags "goc_morale_profile:*"}`` remains extra GOCX visibility / logging only.
It is not the AIO apply-trigger carrier and is not Phase A-3 proof.

Rejected hunches
----------------
- Inferring militia/contractor/sof/elite from faction, actor, or side names.
- Inferring from unit/breed/component identifiers (Wagner, Spetsnaz, Azov, …).
- Adding ``morale_profile`` to campaign-save ``Battalion`` / roster rows
  (Slice 4 / #266 save surface).
- Treating ``{Tags "goc_morale_profile:*"}`` as the AIO morale carrier.
- Inventing a fifth AIO stuff item or apply trigger.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

ALLOWED_MORALE_PROFILES = frozenset({"militia", "regular", "contractor", "sof", "elite"})
DEFAULT_MORALE_PROFILE = "regular"
MORALE_PROFILE_TAG_PREFIX = "goc_morale_profile:"
MORALE_PROFILE_LOG_PREFIX = "goc_morale_profile"

# Single authority: GOCX five-profile field -> existing AIO four-bucket marker.
AIO_MORALE_MARKER_BY_PROFILE = {
    "militia": "aio_marker_morale_low",
    "regular": "aio_marker_morale_regular",
    "contractor": "aio_marker_morale_trained",
    "sof": "aio_marker_morale_elite",
    "elite": "aio_marker_morale_elite",
}
AIO_MORALE_MARKERS = frozenset(AIO_MORALE_MARKER_BY_PROFILE.values())
AIO_MORALE_MARKER_PREFIX = "aio_marker_morale_"


class UnknownMoraleProfileError(ValueError):
    """Raised when an authored morale profile is not one of the allowed values."""


_CARRIER_TAG_RE = re.compile(
    r'\{Tags\s+"' + re.escape(MORALE_PROFILE_TAG_PREFIX) + r'([^"]+)"\s*\}'
)
_OBJECT_HEADER_RE = re.compile(
    r'\{(?P<kind>Human|Entity)\s+"[^"]+"\s+(?P<object_id>0x[0-9a-fA-F]+)',
)
_INVENTORY_HEADER_RE = re.compile(r"\{Inventory\s+(0x[0-9a-fA-F]+)")
_AIO_MARKER_ITEM_RE = re.compile(r'\{item "(aio_marker_morale_[^"]+)"')
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


def aio_morale_marker_for_profile(profile: str) -> str:
    """Return the AIO inventory item the apply trigger's ``with_item`` matches."""

    resolved = normalize_morale_profile(profile)
    return AIO_MORALE_MARKER_BY_PROFILE[resolved]


def is_aio_morale_marker_name(name: str) -> bool:
    return name in AIO_MORALE_MARKERS or name.startswith(AIO_MORALE_MARKER_PREFIX)


def apply_aio_morale_marker(items: Sequence[Any], profile: str) -> list[Any]:
    """Replace any breed-copied AIO morale marker with the catalog mapping.

    Does not mutate *items*. Catalog profile always wins, including when the
    breed already carries ``aio_marker_morale_trained`` or another bucket.
    """

    from .bridge.scn import BreedInventoryItem

    marker = aio_morale_marker_for_profile(profile)
    kept = [item for item in items if not is_aio_morale_marker_name(getattr(item, "name", ""))]
    kept.append(BreedInventoryItem(name=marker))
    return kept


def morale_profile_tag(profile: str) -> str:
    return f"{MORALE_PROFILE_TAG_PREFIX}{normalize_morale_profile(profile)}"


def morale_profile_visibility_tag_line(profile: str, *, indent: str = "\t\t") -> str:
    """Diagnostic ``{Tags}`` line. Observability only, not the AIO carrier."""

    return f'{indent}{{Tags "{morale_profile_tag(profile)}"}}'


def morale_profile_carrier_line(profile: str, *, indent: str = "\t\t") -> str:
    """Implementation alias for :func:`morale_profile_visibility_tag_line`."""

    return morale_profile_visibility_tag_line(profile, indent=indent)


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


def parse_morale_profile_visibility_tags(scn_text: str) -> list[tuple[str, str, str]]:
    """Return ``(kind, object_id, profile)`` for diagnostic GOCX ``{Tags}`` lines.

    Observability only. This is not the AIO apply-trigger carrier.
    """

    found: list[tuple[str, str, str]] = []
    for match in _OBJECT_HEADER_RE.finditer(scn_text):
        block = _extract_brace_block(scn_text, match.start())
        tag = _CARRIER_TAG_RE.search(block)
        if tag is None:
            continue
        found.append((match.group("kind"), match.group("object_id"), tag.group(1)))
    return found


def parse_morale_profile_carriers(scn_text: str) -> list[tuple[str, str, str]]:
    """Implementation alias for :func:`parse_morale_profile_visibility_tags`."""

    return parse_morale_profile_visibility_tags(scn_text)


def parse_inventory_aio_morale_markers(scn_text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Return ``(object_id, markers)`` parsed from each ``{Inventory}`` block."""

    found: list[tuple[str, tuple[str, ...]]] = []
    for match in _INVENTORY_HEADER_RE.finditer(scn_text):
        block = _extract_brace_block(scn_text, match.start())
        found.append((match.group(1), tuple(_AIO_MARKER_ITEM_RE.findall(block))))
    return found


def parse_human_aio_morale_markers(scn_text: str) -> dict[str, tuple[str, ...]]:
    """Return Human object_id -> AIO marker names from that object's Inventory."""

    human_ids = {
        match.group("object_id")
        for match in _OBJECT_HEADER_RE.finditer(scn_text)
        if match.group("kind") == "Human"
    }
    return {
        object_id: markers
        for object_id, markers in parse_inventory_aio_morale_markers(scn_text)
        if object_id in human_ids
    }


def parse_entity_aio_morale_markers(scn_text: str) -> dict[str, tuple[str, ...]]:
    entity_ids = {
        match.group("object_id")
        for match in _OBJECT_HEADER_RE.finditer(scn_text)
        if match.group("kind") == "Entity"
    }
    return {
        object_id: markers
        for object_id, markers in parse_inventory_aio_morale_markers(scn_text)
        if object_id in entity_ids
    }


def parse_morale_profile_logs(scn_text: str) -> list[dict[str, str]]:
    return [
        {
            "unit": match.group("unit"),
            "profile": match.group("profile"),
            "object_id": match.group("object_id"),
            # Legacy key: GEM object kind (human|entity), not the AIO carrier.
            "carrier": match.group("carrier"),
            "object_kind": match.group("carrier"),
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
