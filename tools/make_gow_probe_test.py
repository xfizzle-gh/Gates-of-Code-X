"""Prepare the GoW bridge probe test.

Builds a battle save that requires WarFighter AND GoW, and writes a battle context restricting the
enemy (AFRF) to two unit types. After the battle, read the probe log:
  %USERPROFILE%\\AppData\\LocalLow\\WarfighterCampaign\\WarfighterCampaign\\Bridge\\gow_probe.txt

    python tools/make_gow_probe_test.py             # writes build/gow-probe/GoW_probe_test.sav + context
"""
from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "build" / "export-test" / "WarfighterCampaign_export_test.sav"
OUT = ROOT / "build" / "gow-probe" / "GoW_probe_test.sav"
BRIDGE = Path(os.environ["USERPROFILE"]) / "AppData" / "LocalLow" / "WarfighterCampaign" / "WarfighterCampaign" / "Bridge"
GOW_MOD = f"mod_{ROOT.name}:0"
ENEMY_UNITS = ["squad1(rus)", "t-72b3"]


def main() -> None:
    with zipfile.ZipFile(SRC) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    status = entries["status"].decode("utf-8")
    if GOW_MOD not in status:
        status = re.sub(r'("mod_3809475216:0")', r'\1\n\t\t"' + GOW_MOD + '"', status, count=1)
    status = re.sub(r'\{name "[^"]*"\}', '{name "GoW_probe_test"}', status, count=1)
    entries["status"] = status.encode("utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in entries.items():
            z.writestr(n, data)

    BRIDGE.mkdir(parents=True, exist_ok=True)
    units = ", ".join('"' + u + '"' for u in ENEMY_UNITS)
    (BRIDGE / "gow_battle_context.lua").write_text(
        "-- Written by tools/make_gow_probe_test.py\n"
        'GOW_BATTLE_ID = "gow_probe_test"\n'
        'GOW_ENEMY_ARMY = "rus"\n'
        f"GOW_ENEMY_UNITS = {{ {units} }}\n", encoding="utf-8", newline="\n")
    probe = BRIDGE / "gow_probe.txt"
    if probe.exists():
        probe.unlink()
    print("save:", OUT)
    print("mods in status:", re.findall(r'"(mod_[^"]+)"', status))
    print("context:", BRIDGE / "gow_battle_context.lua", "-> enemy rus limited to", ENEMY_UNITS)


if __name__ == "__main__":
    main()
