"""Offline test of the GoW bridge in a real Lua runtime (lupa), with the engine stubbed.

It loads WarFighter's actual AFRF purchase list, so it proves the trimming logic against real data.
It does NOT prove engine behaviour (event wiring, when the game calls these functions).

    python tests/lua/test_gow_bridge.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent.parent
WF = Path(json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))["WF"])
BRIDGE = ROOT / "resource" / "script" / "multiplayer" / "modes" / "conquest" / "gow_bridge.lua"


def run(context: str | None, army: str = "rus"):
    home = Path(tempfile.mkdtemp())
    bridge_dir = home / "AppData" / "LocalLow" / "WarfighterCampaign" / "WarfighterCampaign" / "Bridge"
    bridge_dir.mkdir(parents=True)
    if context:
        (bridge_dir / "gow_battle_context.lua").write_text(context, encoding="utf-8")
    os.environ["USERPROFILE"] = str(home)
    lua = LuaRuntime(unpack_returned_tuples=True)
    units_dir = (WF / "resource" / "script" / "multiplayer" / "units").as_posix()
    lua.execute(f'''
        Purchases = {{}}
        BotApi = {{ Instance = {{ army = "{army}", playerId = 2 }}, Conquest = {{ Attacking = false }} }}
        local loaded = {{}}
        local function path_of(module) return "{units_dir}" .. module:gsub("^/script/multiplayer/units", "") .. ".lua" end
        function module_exists(module) local f = io.open(path_of(module), "r"); if f then f:close(); return true end; return false end
        local real_require = require
        function require(module)
            if not loaded[module] then loaded[module] = true; dofile(path_of(module)) end
        end
        queue_size = -1
        function OnGameStartUtility(suffix)   -- stand-in for the game's: require, then build the queue
            local module = "/script/multiplayer/units/" .. BotApi.Instance.army .. "/" .. suffix .. "." .. BotApi.Instance.army
            if module_exists(module) then require(module) end
            local n = 0
            for _, group in pairs(Purchases[suffix .. "." .. BotApi.Instance.army] or {{}}) do n = n + #group.Units end
            queue_size = n
        end
        spawned = {{}}
        function GameModeSpawnUnit(unit, max) spawned[#spawned + 1] = unit; return true end
    ''')
    lua.execute(f'dofile("{BRIDGE.as_posix()}")')
    lua.execute('OnGameStartUtility("conquest"); GameModeSpawnUnit("squad1(rus)", 4)')
    g = lua.globals()
    log = (bridge_dir / "gow_probe.txt").read_text(encoding="utf-8")
    return g.queue_size, len(g.spawned), log


def main() -> int:
    ok = True
    full, spawned, log = run(None)
    print(f"no context: queue {full} units, spawned {spawned}")
    ok &= full > 50 and spawned == 1 and "purchase 1: squad1(rus)" in log

    ctx = 'GOW_BATTLE_ID = "t"\nGOW_ENEMY_ARMY = "rus"\nGOW_ENEMY_UNITS = { "squad1(rus)", "t-72b3" }\n'
    trimmed, spawned, log = run(ctx)
    print(f"context for rus: queue {trimmed} units, spawned {spawned}")
    ok &= trimmed == 2 and spawned == 1 and "units " in log

    other, _, log = run(ctx.replace('"rus"', '"pla"'))
    print(f"context for another army: queue {other} units (must equal the untrimmed {full})")
    ok &= other == full and "list left alone" in log

    print("OK" if ok else "FAILED")
    if not ok:
        print(log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
