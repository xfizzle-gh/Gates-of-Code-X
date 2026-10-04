-- GoW campaign bridge.
-- Loaded by GoW's conquest.lua, which is WarFighter's conquest.lua plus one require line.
--
-- The campaign application writes a small Lua file before each battle describing the enemy battalion.
-- This module shapes WarFighter's conquest AI around it:
--   * battle size stays WarFighter's own, multiplied by the battalion's strength;
--   * the battalion's unit types are preferred whenever any of them can be bought right now, and the
--     AI's full list is used otherwise, so a purchase phase can never stall with nothing to buy;
--   * a defending AI places only a share of its opening garrison at the start. The rest is held in
--     reserve and released in timed bursts, which spawn at the bot's side of the map and march in.
--     WarFighter's own flag-loss counterattacks still happen on top of that.
-- With no context file, or a context for another faction, nothing is changed and WarFighter behaves
-- exactly as it does without GoW. Everything GoW adds runs inside pcall.
--
-- Verified in game on 2026-10-04:
--   * the bot's Lua can read and write files under the user profile;
--   * the engine keeps one handler per event, so this module wraps globally-named functions;
--   * trimming to a hard per-unit roster starved the battle (4 units instead of 20) and stalled the
--     reinforcement phase when the remaining roster units were not buyable. Hence strength scaling
--     and the soft preference above.

GowBridge = GowBridge or {}


local function bridge_dir()
	local profile = os and os.getenv and os.getenv("USERPROFILE")
	if not profile or profile == "" then
		return nil
	end
	-- The campaign application's own data folder; it creates the Bridge directory.
	return profile .. "/AppData/LocalLow/WarfighterCampaign/WarfighterCampaign/Bridge/"
end

local function log(line)
	pcall(function()
		local dir = bridge_dir()
		if not dir or not io or not io.open then
			return
		end
		local f = io.open(dir .. "gow_probe.txt", "a")
		if f then
			f:write(tostring(line) .. "\n")
			f:close()
		end
	end)
end

local function count_units(key)
	local total = 0
	local list = Purchases and Purchases[key]
	if type(list) == "table" then
		for _, group in pairs(list) do
			if type(group) == "table" and type(group.Units) == "table" then
				total = total + #group.Units
			end
		end
	end
	return total
end

local function describe_purchases(label)
	if type(Purchases) ~= "table" then
		log(label .. ": Purchases is " .. type(Purchases))
		return
	end
	local parts = {}
	for key, _ in pairs(Purchases) do
		parts[#parts + 1] = tostring(key) .. "=" .. count_units(key)
	end
	table.sort(parts)
	log(label .. ": Purchases keys: " .. table.concat(parts, ", "))
end

local function safe(value)
	local ok, result = pcall(function() return tostring(value) end)
	return ok and result or "?"
end

-- Loads the context the campaign application wrote for this battle, if any. Expected globals:
--   GOW_BATTLE_ID           string
--   GOW_ENEMY_ARMY          WF army tag of the AI side, e.g. "rus"
--   GOW_STRENGTH            multiplier on WarFighter's own purchase budgets (1.0 = a normal battle)
--   GOW_ENEMY_TYPES         optional array of unit ids the battalion is made of (a preference)
--   GOW_OPENING_SHARE       0..1, share of a defending AI's opening placed at the start
--   GOW_REINFORCE_INTERVAL  seconds between timed reinforcement bursts
--   GOW_REINFORCE_BURST     budget of one burst
local function load_context()
	local dir = bridge_dir()
	if not dir then
		log("no USERPROFILE; context not loaded")
		return false
	end
	local path = dir .. "gow_battle_context.lua"
	local f = io.open(path, "r")
	if not f then
		log("no context file at " .. path)
		return false
	end
	f:close()
	local ok, err = pcall(dofile, path)
	log("context dofile ok=" .. tostring(ok) .. " err=" .. safe(err) .. " battle=" .. safe(GOW_BATTLE_ID) .. " army=" .. safe(GOW_ENEMY_ARMY)
		.. " strength=" .. safe(GOW_STRENGTH))
	return ok and type(GOW_ENEMY_ARMY) == "string"
end

local function now()
	return (os and os.time and os.time()) or 0
end

local function write_state()
	pcall(function()
		local dir = bridge_dir()
		local f = dir and io.open(dir .. "gow_battle_state.txt", "w")
		if not f then
			return
		end
		f:write("battleId=" .. safe(GOW_BATTLE_ID) .. "\n")
		f:write("purchased=" .. safe(GowBridge.purchased or 0) .. "\n")
		f:write("reserve=" .. safe(GowBridge.reserve or 0) .. "\n")
		for unit, n in pairs(GowBridge.bought or {}) do
			f:write("bought " .. unit .. "=" .. n .. "\n")
		end
		f:close()
	end)
end

local function activate()
	GowBridge.strength = math.max(0.25, math.min(2.0, tonumber(GOW_STRENGTH) or 1.0))
	GowBridge.share = math.max(0.1, math.min(1.0, tonumber(GOW_OPENING_SHARE) or 0.5))
	GowBridge.interval = math.max(30, tonumber(GOW_REINFORCE_INTERVAL) or 180)
	GowBridge.burst = math.max(1, tonumber(GOW_REINFORCE_BURST) or 5)
	GowBridge.preferred = {}
	local count = 0
	if type(GOW_ENEMY_TYPES) == "table" then
		for _, unit in ipairs(GOW_ENEMY_TYPES) do
			GowBridge.preferred[unit] = true
			count = count + 1
		end
	end
	GowBridge.hasPreference = count > 0
	GowBridge.reserve = 0
	GowBridge.bought = {}
	GowBridge.active = true
	log("active: strength " .. GowBridge.strength .. ", opening share " .. GowBridge.share .. ", preferred types " .. count
		.. ", reinforcements every " .. GowBridge.interval .. "s, burst " .. GowBridge.burst)
end

local function wrap_global(name, wrapper)
	local original = _G[name]
	if type(original) ~= "function" then
		log(name .. " is " .. type(original) .. "; not wrapped")
		return
	end
	_G[name] = function(...)
		return wrapper(original, ...)
	end
	log("wrapped " .. name)
end

-- Battle start: the game loads the faction's purchase list and builds the AI's buying queue.
wrap_global("OnGameStartUtility", function(original, suffix)
	pcall(function()
		local army = BotApi.Instance.army
		log("--- battle start: bot playerId=" .. safe(BotApi.Instance.playerId) .. " army=" .. safe(army)
			.. " attacking=" .. safe(BotApi.Conquest and BotApi.Conquest.Attacking))
		if GowBridge.hasContext and GOW_ENEMY_ARMY == army then
			activate()
		elseif GowBridge.hasContext then
			log("context is for army " .. safe(GOW_ENEMY_ARMY) .. ", this bot is " .. safe(army) .. "; AI left alone")
		end
	end)
	return original(suffix)
end)

-- Chooses the next unit to buy. Prefer the battalion's own unit types when any is buyable now.
wrap_global("GetUnitToSpawn", function(original, units)
	if not GowBridge.active or not GowBridge.hasPreference or type(units) ~= "table" then
		return original(units)
	end
	local preferred = {}
	pcall(function()
		for _, unit in pairs(units) do
			if type(unit) == "table" and GowBridge.preferred[unit.unit] and BotApi.Commands:IsUnitAvailable(unit.unit) then
				preferred[#preferred + 1] = unit
			end
		end
	end)
	if #preferred > 0 then
		local pick = original(preferred)
		if pick then
			return pick
		end
	end
	return original(units)
end)

-- Performs every purchase.
wrap_global("GameModeSpawnUnit", function(original, unit, maxSquadSize)
	local result = original(unit, maxSquadSize)
	pcall(function()
		if result then
			GowBridge.purchased = (GowBridge.purchased or 0) + 1
			if GowBridge.active then
				GowBridge.bought[unit] = (GowBridge.bought[unit] or 0) + 1
			end
			log("purchase " .. GowBridge.purchased .. ": " .. safe(unit) .. " phase=" .. safe(ConquestState and ConquestState.purchasePhase)
				.. (GowBridge.active and GowBridge.preferred[unit] and " (battalion type)" or ""))
			write_state()
		end
	end)
	return result
end)

-- Sizes every purchase phase (opening garrison, counterattack burst, attacker wave).
if type(ConquestWaves) == "table" and type(ConquestWaves.StartPurchasePhase) == "function" then
	local original_phase = ConquestWaves.StartPurchasePhase
	ConquestWaves.StartPurchasePhase = function(phase, target)
		local sized = target
		pcall(function()
			if not GowBridge.active or type(target) ~= "number" or GowBridge.releasing then
				return
			end
			sized = math.max(1, math.floor(target * GowBridge.strength + 0.5))
			if phase == "defender_opening" then
				local opening = math.max(1, math.floor(sized * GowBridge.share + 0.5))
				GowBridge.reserve = GowBridge.reserve + (sized - opening)
				sized = opening
			end
			log("phase " .. safe(phase) .. " budget " .. target .. " -> " .. sized .. " (reserve " .. GowBridge.reserve .. ")")
			write_state()
		end)
		return original_phase(phase, sized)
	end
	log("wrapped ConquestWaves.StartPurchasePhase")
else
	log("ConquestWaves.StartPurchasePhase not found; phase sizes not changed")
end

-- Runs every quant. Releases the defender's reserve in timed bursts once the opening is complete and
-- no other purchase phase is running. A burst is an ordinary counterattack-type phase, so WarFighter
-- finishes it and gives the new squads their normal orders.
wrap_global("TrySpawnUnit", function(original)
	pcall(function()
		if not GowBridge.active or (GowBridge.reserve or 0) <= 0 or type(ConquestState) ~= "table" then
			return
		end
		if not ConquestState.botDefender or not ConquestState.defenderOpeningFinished
			or ConquestState.defenderOpeningGarrisonReadyPending or ConquestState.purchasePhase then
			return
		end
		if ConquestBattleResult and ConquestBattleResult.IsWinnerDecided and ConquestBattleResult.IsWinnerDecided() then
			return
		end
		local t = now()
		if not GowBridge.nextRelease then
			GowBridge.nextRelease = t + GowBridge.interval
			log("opening complete; first reinforcement burst in " .. GowBridge.interval .. "s")
			return
		end
		if t < GowBridge.nextRelease then
			return
		end
		local budget = math.min(GowBridge.reserve, GowBridge.burst)
		GowBridge.reserve = GowBridge.reserve - budget
		GowBridge.nextRelease = t + GowBridge.interval
		log("reinforcement burst: budget " .. budget .. " (reserve left " .. GowBridge.reserve .. ")")
		GowBridge.releasing = true
		local ok, err = pcall(ConquestWaves.StartPurchasePhase, "defender_counterattack", budget)
		GowBridge.releasing = false
		if not ok then
			log("burst failed to start: " .. safe(err))
		end
		write_state()
	end)
	return original()
end)

pcall(function()
	log("=== gow_bridge loaded os.time=" .. safe(now()))
	GowBridge.hasContext = load_context()
end)
