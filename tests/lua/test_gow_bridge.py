"""Offline test of the GoW bridge in a real Lua runtime (lupa), with the engine stubbed.

It loads WarFighter's actual AFRF purchase list, so the unit ids are real.
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
    fake_time = 1000
    os.time = function() return fake_time end
    Purchases = {{}}
    unavailable = {{}}
    BotApi = {{ Instance = {{ army = "{army}", playerId = 2 }}, Conquest = {{ Attacking = false }},
               Commands = {{ IsUnitAvailable = function(self, unit) return not unavailable[unit] end }} }}
    ConquestState = {{ botDefender = true }}
    ConquestBattleResult = {{ IsWinnerDecided = function() return false end }}
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
    function GetUnitToSpawn(units)        -- stand-in: buy the first offered unit that is available
        for _, u in ipairs(units) do if BotApi.Commands:IsUnitAvailable(u.unit) then return u end end
        return nil
    end
    function GameModeSpawnUnit(unit, max) return true end
    function TrySpawnUnit() end
    ConquestWaves = {{}}
    phases = {{}}
    function ConquestWaves.StartPurchasePhase(phase, target)
        ConquestState.purchasePhase = phase
        phases[#phases + 1] = phase .. "=" .. tostring(target)
    end
    function buy(n)
        local bought = {{}}
        for i = 1, n do
            local pick = GetUnitToSpawn(queue)
            if not pick then break end
            if GameModeSpawnUnit(pick.unit, 4) then bought[#bought + 1] = pick.unit end
        end
        return bought
    end
'''


def make(context: str | None, army: str = "rus"):
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
    return lua, bridge_dir


def main() -> int:
    ok = True

    lua, d = make(None)
    lua.execute('ConquestWaves.StartPurchasePhase("defender_opening", 20)')
    phases = list(lua.globals().phases.values())
    print("no context:", phases)
    ok &= phases == ["defender_opening=20"]

    ctx = ('GOW_BATTLE_ID = "t"\nGOW_ENEMY_ARMY = "rus"\nGOW_STRENGTH = 0.8\nGOW_OPENING_SHARE = 0.5\n'
           'GOW_REINFORCE_INTERVAL = 180\nGOW_REINFORCE_BURST = 5\n'
           'GOW_ENEMY_TYPES = { "squad2(rus)", "t-72b3" }\n')
    lua, d = make(ctx)
    g = lua.globals()
    lua.execute('ConquestWaves.StartPurchasePhase("defender_opening", 20)')
    print("strength 0.8, share 0.5:", list(g.phases.values()), "reserve", g.GowBridge.reserve)
    ok &= list(g.phases.values()) == ["defender_opening=8"] and g.GowBridge.reserve == 8

    bought = list(g.buy(3).values())
    print("preferred types buyable:", bought)
    ok &= bought == ["squad2(rus)"] * 3

    lua.execute('unavailable["squad2(rus)"] = true; unavailable["t-72b3"] = true')
    bought = list(g.buy(2).values())
    print("preferred types NOT buyable -> falls back to the full list:", bought)
    ok &= len(bought) == 2 and all(b not in ("squad2(rus)", "t-72b3") for b in bought)

    # opening finishes; reserve is released on a timer
    lua.execute('ConquestState.defenderOpeningFinished = true; ConquestState.purchasePhase = nil; TrySpawnUnit()')
    ok &= len(list(g.phases.values())) == 1
    lua.execute('fake_time = fake_time + 100; TrySpawnUnit()')
    ok &= len(list(g.phases.values())) == 1                      # too early
    lua.execute('fake_time = fake_time + 100; TrySpawnUnit()')
    print("after 200s:", list(g.phases.values()), "reserve", g.GowBridge.reserve)
    ok &= list(g.phases.values())[-1] == "defender_counterattack=5" and g.GowBridge.reserve == 3
    lua.execute('fake_time = fake_time + 200; TrySpawnUnit()')
    ok &= len(list(g.phases.values())) == 2                      # a phase is still running: no new burst
    lua.execute('ConquestState.purchasePhase = nil; TrySpawnUnit()')
    print("second burst:", list(g.phases.values()), "reserve", g.GowBridge.reserve)
    ok &= list(g.phases.values())[-1] == "defender_counterattack=3" and g.GowBridge.reserve == 0
    lua.execute('ConquestState.purchasePhase = nil; fake_time = fake_time + 500; TrySpawnUnit()')
    ok &= len(list(g.phases.values())) == 3                      # reserve empty: nothing more
    # a native flag-loss counterattack is scaled, not swallowed
    lua.execute('ConquestState.purchasePhase = nil; ConquestWaves.StartPurchasePhase("defender_counterattack", 5)')
    ok &= list(g.phases.values())[-1] == "defender_counterattack=4"
    state = (d / "gow_battle_state.txt").read_text(encoding="utf-8")
    ok &= "purchased=5" in state

    lua, d = make(ctx.replace('"rus"\n', '"pla"\n'))
    lua.execute('ConquestWaves.StartPurchasePhase("defender_opening", 20)')
    print("context for another army:", list(lua.globals().phases.values()))
    ok &= list(lua.globals().phases.values()) == ["defender_opening=20"]

    print("OK" if ok else "FAILED")
    if not ok:
        print((d / "gow_probe.txt").read_text(encoding="utf-8"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
