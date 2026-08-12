from __future__ import annotations

from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Any, Mapping, Sequence

from .expanded_nations_models import (
    BREED_ROOT_RELATIVE,
    ExpandedNationsError,
    GENERATED_MARKER,
    sha256_bytes,
)
from .modstack import resource_root

# Cross-side breed reuse is intentionally opt-in. The engine resolves a squad
# member through the projected tactical side, so a source-side purchase rendered
# onto goc_* must also materialize the exact source breed namespace beneath the
# goc_* side. Keep the shared/default authorization deliberately narrow. Callers
# with a separately audited actor authority may pass additional exact component
# IDs explicitly; substring-derived or implicit cross-side reuse remains blocked.
_CROSS_SIDE_BREED_COMPONENTS = frozenset(
    {
        "ukraine_ildu",
        "nato_full_fallback",
        "nato_common_infantry_bridge",
        "cze_equipment_identity",
        "svk_equipment_identity",
    }
)
_INCLUDE_RE = re.compile(r'\(\s*include\s+"([^"]+)"\s*\)', re.IGNORECASE)
_TEXT_SUFFIXES = frozenset({".set", ".inc"})
_CLOSURE_DIR = "_goc_source"


def project_actor_breed_files(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
    *,
    authorized_components: Sequence[str] | None = None,
) -> dict[Path, bytes]:
    """Mirror approved source-side soldier breeds into the actor target side.

    GoH resolves a projected squad member beneath ``mp/<side>/<period>``. A
    purchase definition can therefore be syntactically valid after a side
    rewrite while still crashing when its source-side soldier breed is absent
    under the target side. Authorization is fail-closed. The shared default is
    the legacy explicit allowlist; a caller with separately audited authority
    may add exact component IDs through ``authorized_components``.

    Top-level breed names remain at the exact target paths used by squad member
    lookup. Single-source actors preserve the accepted flat include-closure
    layout. When an actor legitimately mixes multiple source sides, local include
    dependencies are copied into source-side-qualified closure namespaces and the
    projected include paths are rewritten to those closures. This preserves each
    source side's exact dependency bytes without forcing unrelated source
    families (for example NATO and UKR ``ability.inc``) to overwrite one another.
    """

    target_side = str(actor.get("tactical_side", "")).lower()
    outputs: dict[Path, bytes] = {}
    mirrored_sources: dict[Path, Path] = {}
    authorized = set(_CROSS_SIDE_BREED_COMPONENTS)
    if authorized_components is not None:
        authorized.update(str(component) for component in authorized_components if str(component))

    authorized_source_sides = {
        str(unit.get("source_side", "")).lower()
        for unit in actor.get("units", [])
        if str(unit.get("component_id", "")) in authorized
        and str(unit.get("source_side", "")).lower()
        and str(unit.get("source_side", "")).lower() != target_side
        and isinstance(unit.get("members"), Mapping)
        and bool(unit.get("members"))
    }
    namespace_dependencies = len(authorized_source_sides) > 1

    for unit in sorted(actor.get("units", []), key=lambda row: str(row.get("unit_name", ""))):
        component_id = str(unit.get("component_id", ""))
        if component_id not in authorized:
            continue
        source_side = str(unit.get("source_side", "")).lower()
        if not source_side or source_side == target_side:
            continue
        period = str(unit.get("period", "")).lower()
        members = unit.get("members", {})
        if not isinstance(members, Mapping) or not members:
            continue

        for breed in sorted(str(name) for name in members):
            source_path, source_side_root = _resolve_source_breed(
                roots,
                source_side=source_side,
                breed=breed,
                period=period,
            )
            source_relative = source_path.relative_to(source_side_root)
            _mirror_source_closure(
                roots,
                source_path=source_path,
                source_side_root=source_side_root,
                source_relative=source_relative,
                source_side=source_side,
                target_side=target_side,
                outputs=outputs,
                mirrored_sources=mirrored_sources,
                active=set(),
                root_breed=True,
                namespace_dependencies=namespace_dependencies,
            )

    return dict(sorted(outputs.items(), key=lambda item: item[0].as_posix()))


def _resolve_source_breed(
    roots: Sequence[Path],
    *,
    source_side: str,
    breed: str,
    period: str,
) -> tuple[Path, Path]:
    for priority in range(len(roots) - 1, -1, -1):
        side_root = resource_root(roots[priority]) / "set/breed/mp" / source_side
        if not side_root.is_dir():
            continue
        candidates = [
            path
            for path in side_root.rglob("*.set")
            if path.stem.casefold() == breed.casefold() and not _is_managed_projection(path)
        ]
        if not candidates:
            continue
        if period:
            period_matches = [
                path
                for path in candidates
                if period in {part.casefold() for part in path.relative_to(side_root).parts[:-1]}
            ]
            if period_matches:
                candidates = period_matches
        candidates = sorted(candidates, key=lambda path: path.as_posix().casefold())
        if len(candidates) != 1:
            locations = ", ".join(path.as_posix() for path in candidates)
            raise ExpandedNationsError(
                f"Cross-side breed {source_side}:{breed} is ambiguous at stack priority "
                f"{priority}: {locations}"
            )
        return candidates[0], side_root
    raise ExpandedNationsError(
        f"Cross-side breed source is missing: {source_side}:{breed} period={period or 'unspecified'}"
    )


def _projected_destination(
    *,
    target_side: str,
    source_side: str,
    source_relative: Path,
    root_breed: bool,
    namespace_dependencies: bool,
) -> Path:
    if root_breed or not namespace_dependencies:
        return BREED_ROOT_RELATIVE / target_side / source_relative

    parts = source_relative.parts
    if len(parts) > 1:
        return (
            BREED_ROOT_RELATIVE
            / target_side
            / parts[0]
            / _CLOSURE_DIR
            / source_side
            / Path(*parts[1:])
        )
    return BREED_ROOT_RELATIVE / target_side / _CLOSURE_DIR / source_side / source_relative


def _relative_include(from_directory: Path, destination: Path) -> str:
    return posixpath.relpath(
        PurePosixPath(destination.as_posix()).as_posix(),
        PurePosixPath(from_directory.as_posix()).as_posix(),
    )


def _mirror_source_closure(
    roots: Sequence[Path],
    *,
    source_path: Path,
    source_side_root: Path,
    source_relative: Path,
    source_side: str,
    target_side: str,
    outputs: dict[Path, bytes],
    mirrored_sources: dict[Path, Path],
    active: set[Path],
    root_breed: bool,
    namespace_dependencies: bool,
) -> None:
    resolved = source_path.resolve()
    if resolved in active:
        chain = " -> ".join(path.as_posix() for path in [*active, resolved])
        raise ExpandedNationsError(f"Cross-side breed include cycle: {chain}")
    if source_path.suffix.lower() not in _TEXT_SUFFIXES:
        raise ExpandedNationsError(f"Unsupported cross-side breed dependency: {source_path}")

    destination = _projected_destination(
        target_side=target_side,
        source_side=source_side,
        source_relative=source_relative,
        root_breed=root_breed,
        namespace_dependencies=namespace_dependencies,
    )
    if _effective_target_exists(roots, destination):
        return

    source_bytes = source_path.read_bytes()
    source_text = source_bytes.decode("utf-8-sig")
    if GENERATED_MARKER in source_text:
        raise ExpandedNationsError(
            f"Cross-side breed source resolves from an active generated projection: {source_path}"
        )

    include_rewrites: dict[str, str] = {}
    next_active = {*active, resolved}
    for include in sorted(set(_INCLUDE_RE.findall(source_text))):
        include_path = Path(include.replace("\\", "/"))
        if include_path.is_absolute():
            continue
        dependency = (source_path.parent / include_path).resolve()
        try:
            dependency_relative = dependency.relative_to(source_side_root.resolve())
        except ValueError:
            continue
        if not dependency.is_file():
            continue

        dependency_destination = _projected_destination(
            target_side=target_side,
            source_side=source_side,
            source_relative=dependency_relative,
            root_breed=False,
            namespace_dependencies=namespace_dependencies,
        )
        _mirror_source_closure(
            roots,
            source_path=dependency,
            source_side_root=source_side_root,
            source_relative=dependency_relative,
            source_side=source_side,
            target_side=target_side,
            outputs=outputs,
            mirrored_sources=mirrored_sources,
            active=next_active,
            root_breed=False,
            namespace_dependencies=namespace_dependencies,
        )
        include_rewrites[include] = _relative_include(destination.parent, dependency_destination)

    def replace_include(match: re.Match[str]) -> str:
        original = match.group(1)
        replacement = include_rewrites.get(original)
        if replacement is None:
            return match.group(0)
        return f'(include "{replacement}")'

    rendered_text = _INCLUDE_RE.sub(replace_include, source_text)
    rendered_payload = rendered_text.encode("utf-8")
    header = (
        f"{GENERATED_MARKER}\n"
        f"; cross-side-breed-source={source_side}/{source_relative.as_posix()}\n"
        f"; cross-side-breed-source-sha256={sha256_bytes(source_bytes)}\n"
    ).encode("utf-8")
    rendered = header + rendered_payload

    previous_source = mirrored_sources.get(destination)
    if previous_source is not None and previous_source.resolve() != resolved:
        raise ExpandedNationsError(
            f"Cross-side breed destination {destination} resolves from conflicting sources: "
            f"{previous_source} and {source_path}"
        )
    previous_bytes = outputs.get(destination)
    if previous_bytes is not None and previous_bytes != rendered:
        raise ExpandedNationsError(
            f"Cross-side breed destination {destination} has conflicting projected bytes"
        )
    outputs[destination] = rendered
    mirrored_sources[destination] = source_path


def _effective_target_exists(roots: Sequence[Path], destination: Path) -> bool:
    try:
        resource_relative = destination.relative_to("resource")
    except ValueError as exc:
        raise ExpandedNationsError(
            f"Cross-side breed destination is outside the resource tree: {destination}"
        ) from exc
    for priority in range(len(roots) - 1, -1, -1):
        candidate = resource_root(roots[priority]) / resource_relative
        if not candidate.is_file():
            continue
        if _is_managed_projection(candidate):
            continue
        return True
    return False


def _is_managed_projection(path: Path) -> bool:
    try:
        head = path.read_bytes()[:512].decode("utf-8-sig", errors="replace")
    except OSError:
        return False
    return GENERATED_MARKER in head
