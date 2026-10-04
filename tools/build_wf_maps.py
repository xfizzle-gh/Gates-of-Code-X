"""Build the tactical map catalog and battle export settings for WarFighter.

Maps come from WF's map_points.set (Warfighter region) plus data/maps_pending.json. A map is only
catalogued if its campaign_capture_the_flag .mi and .info really exist in the installed WF mod.
Landscape and texmod are read from the map's .info.

Rewrites in campaign/Assets/MonoBehaviour: GohConquestMapCatalog, GohStatusExportSettings,
GohSaveExportSettings. Report: build/wf-maps-report.json.

    python tools/build_wf_maps.py
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = Path(json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))["WF"])
ASSETS = ROOT / "campaign" / "Assets" / "MonoBehaviour"
MODE = "campaign_capture_the_flag"


def set_field(text: str, name: str, value: str) -> str:
    new, n = re.subn(rf"(?m)^(\s+){name}:.*$", lambda m: f"{m.group(1)}{name}: {value}".rstrip(), text, count=1)
    if n != 1:
        raise SystemExit(f"field not found: {name}")
    return new


def main() -> None:
    settings = json.loads((ROOT / "data" / "export_settings.json").read_text(encoding="utf-8"))
    pending = json.loads((ROOT / "data" / "maps_pending.json").read_text(encoding="utf-8"))["maps"]

    mp = (WF / "resource" / "set" / "dynamic_campaign" / "map_points.set").read_text(encoding="utf-8", errors="replace")
    wf_region = mp.split("{Warfighter", 1)[1].split("{Ostfront", 1)[0]
    listed = re.findall(r'"multi/([^":]+):' + MODE + '"', wf_region)

    pak = zipfile.ZipFile(WF / "resource" / "map.pak")
    in_pak = set(pak.namelist())

    def read_entry(map_id: str, ext: str):
        name = f"map/multi/{map_id}/{MODE}.{ext}"
        loose = WF / "resource" / name
        if loose.exists():
            return loose.read_bytes()
        return pak.read(name) if name in in_pak else None

    report = {"catalogued": [], "listedButMissingFiles": [], "pending": [], "pendingNowAvailable": []}
    entries = []
    candidates = [(m, "wf") for m in listed] + [(p["id"], "pending") for p in pending if p["id"] not in listed]
    for map_id, origin in candidates:
        mi, info = read_entry(map_id, "mi"), read_entry(map_id, "info")
        if mi is None or info is None:
            (report["pending"] if origin == "pending" else report["listedButMissingFiles"]).append(map_id)
            continue
        text = info.decode("utf-8", errors="replace")
        landscape = (re.search(r"\{landscape\s+(\w+)\}", text) or [None, ""])[1]
        texmod = (re.search(r"\{texMod\s+(\w+)\}", text, re.I) or [None, ""])[1]
        if origin == "pending":
            report["pendingNowAvailable"].append(map_id)
        report["catalogued"].append({"id": map_id, "landscape": landscape, "texmod": texmod, "origin": origin})
        entries.append((map_id, landscape, texmod))

    def entry_yaml(indent: str, e) -> str:
        map_id, landscape, texmod = e
        lines = [f"- MapId: {map_id}", f"  RawMapPoint: multi/{map_id}:{MODE}", "  Pool: 0", "  Region: 0", "  MapPack: 0",
                 f"  Landscape: {landscape}", f"  Texmod: {texmod}", f"  GameMode: {MODE}", f"  Size: {settings['mapSize']}"]
        return "".join(indent + ln + "\n" for ln in lines)

    cat = ASSETS / "GohConquestMapCatalog.asset"
    head = cat.read_text(encoding="utf-8").split("  Pools:", 1)[0]
    cat.write_text(
        head + "  Pools:\n  - PoolName: 0\n    Region: 0\n    MapPack: 0\n    Maps:\n"
        + "".join(entry_yaml("    ", e) for e in entries)
        + "  Maps:\n" + "".join(entry_yaml("  ", e) for e in entries), encoding="utf-8", newline="\n")

    st = ASSETS / "GohStatusExportSettings.asset"
    t = st.read_text(encoding="utf-8")
    for k, v in (("SaveNamePrefix", settings["saveNamePrefix"]), ("GameVersion", settings["gameVersion"]),
                 ("Region", settings["region"]), ("DefaultGameMode", settings["gameMode"]),
                 ("DefaultMapSize", settings["mapSize"])):
        t = set_field(t, k, v)
    st.write_text(t, encoding="utf-8", newline="\n")

    sv = ASSETS / "GohSaveExportSettings.asset"
    t = sv.read_text(encoding="utf-8")
    t = set_field(t, "TargetProfileDirectory", "")  # was the original author's own profile path
    t = set_field(t, "SaveFileName", settings["saveFileName"])
    sv.write_text(t, encoding="utf-8", newline="\n")

    out = ROOT / "build" / "wf-maps-report.json"
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    by_land = {}
    for e in report["catalogued"]:
        by_land[e["landscape"] or "?"] = by_land.get(e["landscape"] or "?", 0) + 1
    print(f"maps catalogued: {len(entries)} ({', '.join(f'{k}={v}' for k, v in sorted(by_land.items()))})")
    print(f"listed in map_points.set but files missing: {len(report['listedButMissingFiles'])}")
    print(f"pending import: {len(report['pending'])}; pending now available: {len(report['pendingNowAvailable'])}")
    print("report:", out)


if __name__ == "__main__":
    main()
