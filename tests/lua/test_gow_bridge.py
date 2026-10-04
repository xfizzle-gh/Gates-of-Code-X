"""Offline test of the GoW bridge in a real Lua runtime (lupa), with the engine stubbed.

It loads WarFighter's actual AFRF purchase list, so it proves the roster logic against real data.
It does NOT prove engine behaviour (when and how the game calls these functions).

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

STUBS = '''
    Purchases = {{}}
    BotApi = {{ Instance = {{ army = "{army}", playerId = 2 }}, Conquest = {{ Attacking = false }} }}
    ConquestState = {{}}
    local loaded = {{}}
    local function path_of(module) return "{units_dir}" .. module:gsub("^/script/multiplayer/units", "") .. ".lua" end
    function module_exists(module) local f = io.open(path_of(module), "r"); if f then f:close(); return true end; return false end
    function require(module) if not loaded[module] then loaded[module] = true; dofile(path_of(module)) end end
    queue = {{}}
    function OnGameStartUtility(suffix)   -- stand-in for the game's: require, then build the queue
        local module = "/script/multiplayer/units/" .. BotApi.Instance.army .. "/" .. suffix .. "." .. BotApi.Instance.army
        if module_exists(module) then require(module) end
        queue = {{}}
        for _, group in pairs(Purchases[suffix .. "." .. BotApi.Instance.army] or {{}}) do
            for _, u in ipairs(group.Units) do queue[#queue + 1] = u end
        end
    end
    function GetUnitToSpawn(units) return units[1] end       -- stand-in: buy the first offered unit
    function GameModeSpawnUnit(unit, max) return true end
    ConquestWaves = {{}}
    phase_targets = {{}}
    function ConquestWaves.StartPurchasePhase(phase, target)
        ConquestState.purchasePhase = phase
        phase_targets[#phase_targets + 1] = phase .. "=" .. tostring(target)
    end
    -- drive: start a phase, then keep buying until the AI is offered nothing or the target is met
    function run_phase(phase, target)
        ConquestWaves.StartPurchasePhase(phase, target)
        local real_target = tonumber(phase_targets[#phase_targets]:match("=(%d+)"))
        local bought = {{}}
        for i = 1, real_target do
            local pick = GetUnitToSpawn(queue)
            if not pick then break end
            if GameModeSpawnUnit(pick.unit, 4) then bought[#bought + 1] = pick.unit end
        end
        return bought
    end
'''


def run(context: str | None, army: str = "rus"):
    home = Path(tempfile.mkdtemp())
    bridge_dir = home / "AppData" / "LocalLow" / "WarfighterCampaign" / "WarfighterCampaign" / "Bridge"
    bridge_dir.mkdir(parents=True)
    if context:
        (bridge_dir / "gow_battle_context.lua").write_text(context, encoding="utf-8")
    os.environ["USERPROFILE"] = str(home)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUBS.format(army=army, units_dir=(WF / "resource" / "script" / "multiplayer" / "units").as_posix()))
    lua.execute(f'dofile("{BRIDGE.as_posix()}")')
    lua.execute('OnGameStartUtility("conquest")')
    run_phase = lua.globals().run_phase
    opening = list(run_phase("defender_opening", 20).values())
    burst1 = list(run_phase("defender_counterattack", 5).values())
    burst2 = list(run_phase("defender_counterattack", 5).values())
    log = (bridge_dir / "gow_probe.txt").read_text(encoding="utf-8")
    state = bridge_dir / "gow_battle_state.txt"
    return len(lua.globals().queue), opening, burst1, burst2, log, state.read_text(encoding="utf-8") if state.exists() else ""


def main() -> int:
    ok = True
    size, opening, b1, b2, log, _ = run(None)
    print(f"no context: queue {size} unit types; opening {len(opening)}, bursts {len(b1)}+{len(b2)}")
    ok &= size > 50 and len(opening) == 20 and len(b1) == 5 and len(b2) == 5

    ctx = ('GOW_BATTLE_ID = "t"\nGOW_ENEMY_ARMY = "rus"\n'
           'GOW_ENEMY_ROSTER = { ["squad1(rus)"] = 5, ["t-72b3"] = 2, ["not_a_real_unit"] = 9 }\nGOW_OPENING_SHARE = 0.4\n')
    size, opening, b1, b2, log, state = run(ctx)
    total = opening + b1 + b2
    print(f"roster 5 squads + 2 tanks: queue {size} types; opening {len(opening)}, bursts {len(b1)}+{len(b2)}; bought {sorted(total)}")
    ok &= size == 2 and len(opening) == 3 and len(total) == 7
    ok &= total.count("squad1(rus)") == 5 and total.count("t-72b3") == 2
    ok &= "not_a_real_unit" in log and "purchased=7" in state

    size_other, opening, b1, b2, log, _ = run(ctx.replace('"rus"\n', '"pla"\n'))
    print(f"context for another army: queue {size_other} types, opening {len(opening)} (untouched)")
    ok &= size_other > 50 and len(opening) == 20 and "list left alone" in log

    print("OK" if ok else "FAILED")
    if not ok:
        print(log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
