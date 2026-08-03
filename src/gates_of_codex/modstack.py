from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


RUNTIME_SUFFIXES = {".set", ".lua", ".inc", ".ext", ".xml", ".json"}
RUNTIME_SUBTREES = ("set", "script")
KNOWN_WORKSHOP_ORDER = ("2897299509", "3261086933", "3636883799")


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


def load_stack_config(path: str | Path) -> list[Path]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    layers = payload.get("layers", [])
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
        text = str(root).lower()
        mod_info = root / "mod.info"
        if mod_info.is_file():
            text += "\n" + mod_info.read_text(encoding="utf-8-sig", errors="replace").lower()
        if "2897299509" in text or "west81" in text or "west 81" in text:
            positions.setdefault("2897299509", index)
        if "3261086933" in text or ("code:x" in text and "overhaul" not in text and "gates of code" not in text):
            positions.setdefault("3261086933", index)
        if "3636883799" in text or "ai overhaul" in text or "conquest ai overhaul" in text:
            positions.setdefault("3636883799", index)
        if "gates-of-code-x" in text or "gates of code:x" in text:
            positions.setdefault("gates", index)
    missing = [value for value in KNOWN_WORKSHOP_ORDER if value not in positions]
    if "gates" not in positions:
        missing.append("Gates of Code:X")
    if missing:
        return False, "Missing required stack layers: " + ", ".join(missing)
    ordered = [positions[value] for value in KNOWN_WORKSHOP_ORDER] + [positions["gates"]]
    if ordered != sorted(ordered) or positions["gates"] != len(roots) - 1:
        return False, "Expected West81 -> Code:X -> Code:X AI Overhaul -> Gates of Code:X, with Gates last"
    return True, "West81 -> Code:X -> Code:X AI Overhaul -> Gates of Code:X order confirmed"


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
