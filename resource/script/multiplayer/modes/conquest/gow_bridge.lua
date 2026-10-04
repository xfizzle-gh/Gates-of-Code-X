-- GoW campaign bridge.
-- Loaded by GoW's conquest.lua, which is WarFighter's conquest.lua plus one require line.
--
-- The campaign application writes a small Lua file before each battle describing the enemy battalion
-- (which units, how many). This module makes WarFighter's conquest AI field that battalion:
--   * its purchase list is trimmed to the battalion's unit types;
--   * no unit type can be bought more often than the battalion has of it;
--   * the defender's opening garrison is capped to a share of the battalion, so the rest can only
--     arrive later through WarFighter's own reinforcement phases (counterattacks, attacker waves),
--     which enter from the bot's spawn side of the map.
-- With no context file, or a context for another faction, nothing is changed and WarFighter behaves
-- exactly as it does without GoW. Everything GoW adds runs inside pcall.
--
-- Verified in game on 2026-10-04: the bot's Lua can read and write files under the user profile;
-- the engine keeps one handler per event, so this module wraps globally-named functions instead of
-- subscribing; trimming the list before OnGameStartUtility builds the queue does restrict purchases.

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
--   GOW_BATTLE_ID      string
--   GOW_ENEMY_ARMY     WF army tag of the AI side, e.g. "rus"
--   GOW_ENEMY_ROSTER   { ["unit id"] = count, ... }   the enemy battalion
--   GOW_OPENING_SHARE  0..1, share of the battalion a defending AI may place as its opening garrison
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
	log("context dofile ok=" .. tostring(ok) .. " err=" .. safe(err) .. " battle=" .. safe(GOW_BATTLE_ID) .. " army=" .. safe(GOW_ENEMY_ARMY))
	return ok and type(GOW_ENEMY_ROSTER) == "table" and type(GOW_ENEMY_ARMY) == "string"
end

local function remaining_total()
	local total = 0
	for _, n in pairs(GowBridge.remaining or {}) do
		total = total + n
	end
	return total
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
		for unit, n in pairs(GowBridge.remaining or {}) do
			f:write("remaining " .. unit .. "=" .. n .. "\n")
		end
		f:close()
	end)
end

-- Restricts the faction's purchase list to the battalion's unit types and arms the per-unit budget.
local function apply_roster(key)
	local list = Purchases and Purchases[key]
	if type(list) ~= "table" then
		log("no purchase list for " .. key)
		return
	end
	local before = count_units(key)
	local known = {}
	for _, group in pairs(list) do
		if type(group) == "table" and type(group.Units) == "table" then
			local kept = {}
			for _, entry in ipairs(group.Units) do
				if type(entry) == "table" and GOW_ENEMY_ROSTER[entry.unit] then
					kept[#kept + 1] = entry
					known[entry.unit] = true
				end
			end
			group.Units = kept
		end
	end
	GowBridge.remaining = {}
	local total = 0
	for unit, n in pairs(GOW_ENEMY_ROSTER) do
		if known[unit] then
			GowBridge.remaining[unit] = n
			total = total + n
		else
			log("roster unit not in the AI purchase list, ignored: " .. safe(unit) .. " x" .. safe(n))
		end
	end
	GowBridge.total = total
	local share = tonumber(GOW_OPENING_SHARE) or 0.4
	GowBridge.openingQuota = math.max(1, math.floor(total * share + 0.5))
	GowBridge.active = total > 0
	log(key .. " unit types " .. before .. " -> " .. count_units(key) .. "; battalion size " .. total .. "; opening quota " .. GowBridge.openingQuota)
	write_state()
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

-- Loads the faction's purchase list and builds the AI's buying queue from it.
wrap_global("OnGameStartUtility", function(original, suffix)
	pcall(function()
		local army = BotApi.Instance.army
		log("--- battle start: bot playerId=" .. safe(BotApi.Instance.playerId) .. " army=" .. safe(army)
			.. " attacking=" .. safe(BotApi.Conquest and BotApi.Conquest.Attacking))
		-- Load the list now so it can be trimmed before the game builds its queue; the game's own
		-- require of the same module afterwards is then a no-op.
		local module = [[/script/multiplayer/units/]] .. army .. "/" .. suffix .. "." .. army
		if module_exists(module) then
			require(module)
		end
		if GowBridge.hasContext and GOW_ENEMY_ARMY == army then
			apply_roster(suffix .. "." .. army)
		elseif GowBridge.hasContext then
			log("context is for army " .. safe(GOW_ENEMY_ARMY) .. ", this bot is " .. safe(army) .. "; list left alone")
		end
	end)
	return original(suffix)
end)

-- Chooses the next unit to buy. Only unit types the battalion still has are offered.
wrap_global("GetUnitToSpawn", function(original, units)
	if not GowBridge.active or type(units) ~= "table" then
		return original(units)
	end
	local allowed = {}
	for _, unit in pairs(units) do
		if type(unit) == "table" and (GowBridge.remaining[unit.unit] or 0) > 0 then
			allowed[#allowed + 1] = unit
		end
	end
	if #allowed == 0 then
		return nil
	end
	return original(allowed)
end)

-- Performs every purchase.
wrap_global("GameModeSpawnUnit", function(original, unit, maxSquadSize)
	local result = original(unit, maxSquadSize)
	pcall(function()
		if result then
			GowBridge.purchased = (GowBridge.purchased or 0) + 1
			if GowBridge.active and GowBridge.remaining[unit] then
				GowBridge.remaining[unit] = math.max(0, GowBridge.remaining[unit] - 1)
			end
			log("purchase " .. GowBridge.purchased .. ": " .. safe(unit) .. " phase=" .. safe(ConquestState and ConquestState.purchasePhase)
				.. " left=" .. remaining_total())
			write_state()
		end
	end)
	return result
end)

-- Sizes every purchase phase (opening garrison, counterattack burst, attacker wave).
if type(ConquestWaves) == "table" and type(ConquestWaves.StartPurchasePhase) == "function" then
	local original_phase = ConquestWaves.StartPurchasePhase
	ConquestWaves.StartPurchasePhase = function(phase, target)
		local capped = target
		pcall(function()
			if GowBridge.active and type(target) == "number" then
				local limit = remaining_total()
				if phase == "defender_opening" then
					limit = math.min(limit, GowBridge.openingQuota)
				end
				capped = math.min(target, limit)
				log("phase " .. safe(phase) .. " target " .. target .. " -> " .. capped .. " (battalion left " .. remaining_total() .. ")")
			end
		end)
		return original_phase(phase, capped)
	end
	log("wrapped ConquestWaves.StartPurchasePhase")
else
	log("ConquestWaves.StartPurchasePhase not found; phase sizes not capped")
end

pcall(function()
	log("=== gow_bridge loaded os.time=" .. safe(os and os.time and os.time()))
	GowBridge.hasContext = load_context()
end)
