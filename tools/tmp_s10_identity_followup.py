from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    ROOT / "godot/scripts/presentation/map_markers.gd",
    '''\t\tstrength,
\t\tpresentation_overlay,
\t\tformation_id
\t)''',
    '''\t\tstrength,
\t\tpresentation_overlay,
\t\tfalse,
\t\tformation_id
\t)''',
    "forward exact formation ID to correct resolver parameter",
)

replace_once(
    ROOT / "godot/scripts/tools/operational_presentation_scene_test.gd",
    '''\t_check_eq(modal.get("defender_names", []), ["Red"], "modal names defending formation")''',
    '''\t_check_eq(modal.get("defender_names", []), ["Red", "Red Two"], "modal names every defending formation")''',
    "update multi-formation modal expectation",
)

print("S10 exact identity follow-up applied")
