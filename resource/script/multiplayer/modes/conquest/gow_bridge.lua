-- GoW campaign bridge (probe stage).
-- Loaded by GoW's conquest.lua, which is WarFighter's conquest.lua plus one require line.
--
-- Purpose of this stage: find out, in a real battle, what the bot's Lua environment allows.
--   1. Can it read and write files outside the game folder (io.open, dofile)?
--   2. Is the Purchases table populated when this module loads, and at GameStart?
--   3. Does replacing a faction's purchase list change what the AI fields?
-- Everything is wrapped in pcall. With no context file present the module only writes a probe log
-- and changes nothing, so WarFighter behaves exactly as it does without GoW.

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

-- Loads the context the campaign application wrote for this battle, if any.
-- Expected globals in that file: GOW_BATTLE_ID (string), GOW_ENEMY_ARMY (e.g. "rus"),
-- GOW_ENEMY_UNITS (array of unit ids the enemy battalion contains).
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
	return ok and type(GOW_ENEMY_UNITS) == "table" and type(GOW_ENEMY_ARMY) == "string"
end

-- Restricts the enemy faction's purchase list to the units named in the context.
local function apply_roster(label)
	local key = "conquest." .. GOW_ENEMY_ARMY
	local list = Purchases and Purchases[key]
	if type(list) ~= "table" then
		log(label .. ": no purchase list for " .. key)
		return
	end
	local wanted = {}
	for _, unit in ipairs(GOW_ENEMY_UNITS) do
		wanted[unit] = true
	end
	local before = count_units(key)
	for _, group in pairs(list) do
		if type(group) == "table" and type(group.Units) == "table" then
			local kept = {}
			for _, entry in ipairs(group.Units) do
				if type(entry) == "table" and wanted[entry.unit] then
					kept[#kept + 1] = entry
				end
			end
			group.Units = kept
		end
	end
	log(label .. ": " .. key .. " units " .. before .. " -> " .. count_units(key))
end

function GowBridge.OnGameStart()
	pcall(function()
		log("--- GameStart")
		describe_purchases("GameStart")
		if BotApi and BotApi.Instance then
			log("bot playerId=" .. safe(BotApi.Instance.playerId) .. " army=" .. safe(BotApi.Instance.army) .. " team=" .. safe(BotApi.Instance.team))
		end
		if BotApi and BotApi.Conquest then
			log("conquest Attacking=" .. safe(BotApi.Conquest.Attacking) .. " FirstEnemyId=" .. safe(BotApi.Conquest.FirstEnemyId)
				.. " DefenderBotId=" .. safe(BotApi.Conquest.DefenderBotId) .. " FirstPlayerId=" .. safe(BotApi.Conquest.FirstPlayerId))
		end
		if GowBridge.hasContext then
			apply_roster("GameStart")
		end
	end)
end

function GowBridge.OnGameSpawn(args)
	pcall(function()
		GowBridge.spawns = (GowBridge.spawns or 0) + 1
		if GowBridge.spawns > 60 then
			return
		end
		local parts = {}
		if type(args) == "table" then
			for k, v in pairs(args) do
				parts[#parts + 1] = safe(k) .. "=" .. safe(v)
			end
		else
			parts[1] = type(args)
		end
		log("spawn " .. GowBridge.spawns .. ": " .. table.concat(parts, " "))
	end)
end

pcall(function()
	log("=== gow_bridge loaded os.time=" .. safe(os and os.time and os.time()) .. " io=" .. type(io) .. " dofile=" .. type(dofile))
	describe_purchases("load")
	GowBridge.hasContext = load_context()
	if GowBridge.hasContext then
		apply_roster("load")
	end
	if BotApi and BotApi.Events then
		BotApi.Events:Subscribe(BotApi.Events.GameStart, GowBridge.OnGameStart)
		BotApi.Events:Subscribe(BotApi.Events.GameSpawn, GowBridge.OnGameSpawn)
		log("subscribed to GameStart and GameSpawn")
	end
end)
