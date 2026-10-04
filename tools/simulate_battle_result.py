"""Stand-in for the game finishing a battle: bump the status counters of an exported battle save.

The game increments playedGames after every battle and wonGames when the player wins. This edits only
those two numbers in the save's `status` entry; campaign.scn is left exactly as exported (no casualties).
Use only on saves in a scratch profile. It is NOT evidence about game behaviour.

    python tools/simulate_battle_result.py <save.sav> win|loss
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


def main() -> None:
    path, outcome = Path(sys.argv[1]), sys.argv[2]
    with zipfile.ZipFile(path) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    status = entries["status"].decode("utf-8")
    played = int(re.search(r"\{playedGames (\d+)\}", status).group(1))
    won = int(re.search(r"\{wonGames (\d+)\}", status).group(1))
    status = re.sub(r"\{playedGames \d+\}", f"{{playedGames {played + 1}}}", status)
    if outcome == "win":
        status = re.sub(r"\{wonGames \d+\}", f"{{wonGames {won + 1}}}", status)
    entries["status"] = status.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in entries.items():
            z.writestr(n, data)
    print(f"{path.name}: playedGames {played} -> {played + 1}, wonGames {won} -> {won + (outcome == 'win')}")


if __name__ == "__main__":
    main()
