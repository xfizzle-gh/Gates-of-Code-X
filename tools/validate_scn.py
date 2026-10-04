"""Static checks on a generated battle save (.sav or a campaign.scn file).

Checks the object graph the game needs: unique object ids, an Inventory for every Human/Entity,
CampaignSquads rows that only reference existing ids, and a status entry naming the WF mod and region.

    python tools/validate_scn.py build/export-test/WarfighterCampaign_export_test.sav
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1])
    status = None
    if path.suffix == ".sav":
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            scn = z.read("campaign.scn").decode("utf-8", errors="replace")
            status = z.read("status").decode("utf-8", errors="replace") if "status" in names else None
    else:
        scn = path.read_text(encoding="utf-8", errors="replace")

    problems = []
    objects = re.findall(r'\{(Human|Entity)\s+"([^"]+)"\s+(0x[0-9a-fA-F]+)', scn)
    ids = [o[2].lower() for o in objects]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        problems.append(f"duplicate object ids: {sorted(dup)}")
    inventories = {i.lower() for i in re.findall(r"\{Inventory\s+(0x[0-9a-fA-F]+)", scn)}
    missing_inv = [i for i in ids if i not in inventories]
    if missing_inv:
        problems.append(f"objects without Inventory: {missing_inv}")
    squads = scn.split("{CampaignSquads", 1)
    rows = re.findall(r'\{"([^"]+)"\s+"([^"]*)"((?:\s+0x[0-9a-fA-F]+)+)\}', squads[1]) if len(squads) == 2 else []
    if not rows:
        problems.append("no CampaignSquads rows")
    referenced = set()
    for name, stage, tail in rows:
        for i in tail.split():
            referenced.add(i.lower())
            if i.lower() not in ids:
                problems.append(f"row {name} references unknown id {i}")
    orphans = [i for i in ids if i not in referenced]
    if orphans:
        problems.append(f"objects not in any squad row: {orphans}")
    if scn.count("{") != scn.count("}"):
        problems.append(f"unbalanced braces: {scn.count('{')} open, {scn.count('}')} close")
    if status is not None:
        for needle in ("mod_3809475216:0", "{region warfighter}", "{version 9}"):
            if needle not in status:
                problems.append(f"status lacks {needle}")
        if status.count("{") != status.count("}"):
            problems.append("status has unbalanced braces")

    print(f"objects: {len(objects)} ({sum(1 for o in objects if o[0] == 'Human')} human, "
          f"{sum(1 for o in objects if o[0] == 'Entity')} entity); inventories: {len(inventories)}; squad rows: {len(rows)}")
    for p in problems:
        print("PROBLEM:", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
