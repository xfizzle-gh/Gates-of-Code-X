from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

AUTHENTICATED_TEXT_PATHS = {
    "config/earth3/p3_operational_authority.json",
    "docs/audits/p3-first-corridor-route-inventory.json",
    "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
    "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
    "src/gates_of_codex/data/earth3_v1/sites.json",
}


def test_authenticated_p3_text_inputs_are_forced_to_lf_on_checkout() -> None:
    rules = {
        line.strip()
        for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    for relative_path in AUTHENTICATED_TEXT_PATHS:
        if relative_path.startswith("src/gates_of_codex/data/earth3_v1/"):
            expected = "src/gates_of_codex/data/earth3_v1/*.json text eol=lf"
        else:
            expected = f"{relative_path} text eol=lf"
        assert expected in rules, (
            f"authenticated P3 input must be LF-pinned for cross-platform exact-byte "
            f"validation: {relative_path}"
        )
