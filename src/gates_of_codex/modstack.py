from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable, Mapping


RUNTIME_SUFFIXES = {".set", ".lua", ".inc", ".ext", ".xml", ".json"}
RUNTIME_SUBTREES = ("set", "script")
KNOWN_WORKSHOP_ORDER = ("2897299509", "3261086933", "3636883799")
STACK_ROLE_ORDER = (
    "vanilla",
    "west81",
    "codex",
    "codex_ai_overhaul",
    "gates_codex",
)
ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
MOD_INFO_NAME_RE = re.compile(r'\{name\s+"([^"]+)"\}', re.I)


def mod_root(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    return path.parent if path.name.lower() == "resource" else path


def resource_root(value: str | Path) -> Path:
    root = mod_root(value)
    candidate = root / "resource"
    return candidate if candidate.is_dir() else root


def normalize_stack(values: Iterable[str | Path]) -> list[Path]:
    result: list[Path] = []
    for value in values:
        root = mod_root(value)
        if root not in result:
            result.append(root)
    return result


def load_stack_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> list[Path]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    layers = payload.get("layers", [])
    if not isinstance(layers, list) or not layers:
        raise ValueError(f"Stack config has no layers: {source}")
    if any(isinstance(layer, dict) and "role" in layer for layer in layers):
        return _load_validated_stack_config(source, layers, environ=environ)

    # Legacy ad-hoc configs remain readable for internal fixtures and explicit
    # one-off tooling. The checked-in Windows config uses the validated role
    # contract above and therefore never guesses or falls back.
    values: list[Path] = []
    for layer in layers:
        raw = layer.get("path") if isinstance(layer, dict) else layer
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (source.parent / candidate).resolve()
        values.append(candidate)
    return normalize_stack(values)


def _load_validated_stack_config(
    source: Path,
    layers: list[object],
    *,
    environ: Mapping[str, str] | None,
) -> list[Path]:
    if len(layers) != len(STACK_ROLE_ORDER) or not all(isinstance(layer, dict) for layer in layers):
        raise ValueError(
            "Validated stack config requires exactly five object layers in "
            f"this order: {', '.join(STACK_ROLE_ORDER)}"
        )
    roles = tuple(str(layer.get("role", "")) for layer in layers)
    if roles != STACK_ROLE_ORDER:
        duplicates = sorted({role for role in roles if roles.count(role) > 1 and role})
        detail = f"; duplicate roles={duplicates}" if duplicates else ""
        raise ValueError(
            "Stack layer order must be exactly "
            f"{' -> '.join(STACK_ROLE_ORDER)}; got {' -> '.join(roles)}{detail}"
        )

    environment = os.environ if environ is None else environ
    roots: list[Path] = []
    seen: dict[Path, str] = {}
    for layer in layers:
        role = str(layer["role"])
        raw_path = layer.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError(f"Stack layer {role} requires a non-empty path")
        expanded = _expand_environment_path(raw_path, environment, role=role)
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = source.parent / candidate
        root = mod_root(candidate)
        if not root.is_dir():
            raise FileNotFoundError(f"Stack layer {role} does not exist: {root}")
        if root in seen:
            raise ValueError(
                f"Stack layers {seen[root]} and {role} resolve to the same root: {root}"
            )
        seen[root] = role
        _validate_layer_identity(root, layer, role=role)
        roots.append(root)
    return roots


def _expand_environment_path(
    value: str,
    environ: Mapping[str, str],
    *,
    role: str,
) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        replacement = environ.get(name)
        if replacement is None or not str(replacement).strip():
            missing.append(name)
            return match.group(0)
        return str(replacement)

    expanded = ENV_PLACEHOLDER_RE.sub(replace, value)
    if missing:
        raise ValueError(
            f"Stack layer {role} is missing required environment variables: "
            + ", ".join(sorted(set(missing)))
        )
    if "${" in expanded or ENV_PLACEHOLDER_RE.search(expanded):
        raise ValueError(f"Stack layer {role} contains an unresolved placeholder: {expanded}")
    return expanded


def _validate_layer_identity(root: Path, layer: Mapping[str, object], *, role: str) -> None:
    if role == "vanilla":
        sentinels = layer.get("sentinels")
        if not isinstance(sentinels, list) or not sentinels or not all(
            isinstance(item, str) and item for item in sentinels
        ):
            raise ValueError("Vanilla stack layer requires non-empty sentinel paths")
        missing = [item for item in sentinels if not (root / item).exists()]
        if missing:
            raise ValueError(
                f"Vanilla root {root} is missing required sentinels: {', '.join(missing)}"
            )
        return

    accepted = layer.get("accepted_mod_names")
    if not isinstance(accepted, list) or not accepted or not all(
        isinstance(item, str) and item for item in accepted
    ):
        raise ValueError(f"Stack layer {role} requires accepted_mod_names")
    mod_info = root / "mod.info"
    if not mod_info.is_file():
        raise ValueError(f"Stack layer {role} has no mod.info: {root}")
    text = mod_info.read_text(encoding="utf-8-sig", errors="replace")
    match = MOD_INFO_NAME_RE.search(text)
    if match is None:
        raise ValueError(f"Stack layer {role} mod.info has no name: {mod_info}")
    actual = match.group(1)
    if actual not in accepted:
        raise ValueError(
            f"Stack layer {role} has wrong product identity {actual!r}; "
            f"accepted={accepted!r}; root={root}"
        )


def resolve_stack(
    values: Iterable[str | Path] | None = None,
    *,
    config: str | Path | None = None,
    fallback: str | Path | None = None,
) -> list[Path]:
    combined: list[str | Path] = []
    if config:
        combined.extend(load_stack_config(config))
    if values:
        combined.extend(values)
    if not combined and fallback:
        combined.append(fallback)
    return normalize_stack(combined)


def validate_stack_paths(values: Iterable[str | Path]) -> list[str]:
    errors: list[str] = []
    roots = normalize_stack(values)
    if not roots:
        return ["Mod stack is empty"]
    for index, root in enumerate(roots, start=1):
        if not root.is_dir():
            errors.append(f"Stack layer {index} does not exist: {root}")
            continue
        resources = resource_root(root)
        if not resources.is_dir():
            errors.append(f"Stack layer {index} has no resource directory: {root}")
    return errors


def validate_known_order(values: Iterable[str | Path]) -> tuple[bool, str]:
    roots = normalize_stack(values)
    positions: dict[str, int] = {}
    for index, root in enumerate(roots):
        path_text = str(root).casefold()
        mod_name = _mod_info_name(root)
        if "2897299509" in path_text or mod_name in {"West-81", "West81"}:
            positions.setdefault("2897299509", index)
        if "3261086933" in path_text or mod_name in {"Code-X", "Code:X"}:
            positions.setdefault("3261086933", index)
        if "3636883799" in path_text or mod_name in {
            "CodeX Conquest AI Overhaul",
            "CodeX Conquest AI Overhaul 1.5",
        }:
            positions.setdefault("3636883799", index)
        if mod_name in {"Gates of CodeX", "Gates of Code:X"}:
            positions.setdefault("gates", index)
    missing = [value for value in KNOWN_WORKSHOP_ORDER if value not in positions]
    if "gates" not in positions:
        missing.append("Gates of CodeX")
    if missing:
        return False, "Missing required stack layers: " + ", ".join(missing)
    ordered = [positions[value] for value in KNOWN_WORKSHOP_ORDER] + [positions["gates"]]
    if ordered != sorted(ordered) or positions["gates"] != len(roots) - 1:
        return False, "Expected West81 -> Code:X -> Code:X AI Overhaul -> Gates of CodeX, with Gates last"
    return True, "West81 -> Code:X -> Code:X AI Overhaul -> Gates of CodeX order confirmed"


def _mod_info_name(root: Path) -> str:
    mod_info = root / "mod.info"
    if not mod_info.is_file():
        return ""
    match = MOD_INFO_NAME_RE.search(
        mod_info.read_text(encoding="utf-8-sig", errors="replace")
    )
    return match.group(1) if match else ""


def stack_signature(values: Iterable[str | Path]) -> str:
    roots = normalize_stack(values)
    digest = hashlib.sha256()
    for index, root in enumerate(roots):
        digest.update(f"layer:{index}:{root.name}\n".encode("utf-8"))
        mod_info = root / "mod.info"
        if mod_info.is_file():
            digest.update(b"mod.info\0")
            digest.update(mod_info.read_bytes())
        resources = resource_root(root)
        # The base game is represented by path identity. Runtime compatibility hashes focus
        # on mod scripts and sets, including the AI Overhaul, without reading all map media.
        if not mod_info.is_file() or not resources.is_dir():
            continue
        for subtree_name in RUNTIME_SUBTREES:
            subtree = resources / subtree_name
            if not subtree.is_dir():
                continue
            for path in sorted(subtree.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in RUNTIME_SUFFIXES:
                    continue
                relative = path.relative_to(resources).as_posix()
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
    return digest.hexdigest()


def stack_to_strings(values: Iterable[str | Path]) -> list[str]:
    return [str(path) for path in normalize_stack(values)]


def stack_mod_tokens(values: Iterable[str | Path]) -> list[str]:
    """Return GoH saveinfo mod tokens for workshop layers in the stack.

    Format matches engine saves: ``mod_<workshopId>:0``. Vanilla resource roots
    and non-workshop paths are skipped.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for root in normalize_stack(values):
        workshop_id = ""
        for part in root.parts:
            if part.isdigit() and len(part) >= 8:
                workshop_id = part
        if not workshop_id or workshop_id in seen:
            continue
        seen.add(workshop_id)
        tokens.append(f"mod_{workshop_id}:0")
    return tokens
