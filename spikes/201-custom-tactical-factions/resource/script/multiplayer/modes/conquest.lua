-- Base: GatesOfEuropa (3717998771) conquest.lua
-- Extended for #201 goc_usa/goc_fra custom tactical faction spike.
require([[/script/multiplayer/modes/utility]])

-- Time from start of match AI will wait before attempting to buy a unit.
local StartSpawnTime = {
	-- Bot is defender
	DefenseMin = 5 * 1000, 
	DefenseMax = 7 * 1000,
	-- Bot is attacker
	AttackMin = 6 * 60 * 1000, 
	AttackMax = 8 * 60 * 1000,
}

-- Time from last purchase AI will wait before attempting to buy a new unit.
local SpawnCooldownTime = {
	-- Time between each wave
	DCGWaveOffMin = 2 * 60000, 
	DCGWaveOffMax = 2.5 * 60000,
	-- Time between each spawn
	DCGMin = 2 * 1000, 
	DCGMax = 7 * 1000,
}

-- Number of possible units than can be in a wave attack
local WaveUnit = {
	Min = 7,
	Max = 10,
}

-- Sets time limit AI will wait for a unit it has chosen to buy if the unit is not yet available
local UnitSpawnWaitTime = 1.5 * 60000 -- 1:30min (ms) 

-- Time delay for units to get a new move order after spawn move order. Loops.
local OrderRotationPeriod = 2.5 * 60000 -- 2:30 min (ms)

local botDefender
enableWaveCounter = true
local function isAttackerOrDefender()
	botDefender = teamSize > 1
end

local function setVarsInMissionScript()
	if teamSize > 1 then
		BotApi.Scene:SetVar("user_is_defender", 0)
	else
		BotApi.Scene:SetVar("user_is_defender", 1)
	end

	local botNation = BotApi.Instance.army
	local botDifficulty = BotApi.Instance.difficulty
	local nationMap = {
		-- GatesOfEuropa / vanilla-era ids
		rus = 1, ger = 2, fin = 3, usa = 4, eng = 5,
		-- Code:X modern ids (AI Overhaul numbering)
		rusa = 1, ukr = 2, nato = 3, csa = 4, sov = 5, prc = 6, frg = 7, pol = 8,
		-- #201 disposable custom tactical factions
		goc_usa = 9, goc_fra = 10,
	}
	local difficultyMap = { easy = 1, normal = 2, hard = 3, heroic = 4 }

	BotApi.Scene:SetVar("bot_army", nationMap[botNation] or 0)
	BotApi.Scene:SetVar("bot_difficulty", difficultyMap[botDifficulty] or 0)

	local spawnMap = { a = 1, b = 2}
	BotApi.Scene:SetVar("bots_spawnside", spawnMap[spawnSide] or 0)

	BotApi.Scene:SetVar("enemyid", BotApi.Instance.playerId)
	BotApi.Scene:SetVar("id_1st_enemy", BotApi.Instance.CampaignFirstEnemyId)
	BotApi.Scene:SetVar("id_defenderbot", BotApi.Instance.CampaignDefenderBotId)
	BotApi.Scene:SetVar("id_1st_player", BotApi.Instance.CampaignFirstPlayerId)
end

local waveSpawnPossible
local waveSpawnActive = true
local waveUnitCount = 0
local waveNumber = 0
local waveUnitTotal = math.random(WaveUnit.Min, WaveUnit.Max)
if printDebug then print("Print: waveUnitTotal", waveUnitTotal) end
function WaveAttack()
	if not botDefender then
		waveSpawnPossible = true
	end

	if waveSpawnPossible then
		if waveUnitCount >= waveUnitTotal then
			waveUnitTotal = math.random(WaveUnit.Min, WaveUnit.Max)
			if printDebug then print("Print: waveUnitTotal", waveUnitTotal) end
			waveSpawnActive = false
			waveUnitCount = 0
			waveNumber = waveNumber + 1
			if printDebug then print("Print: waveNumber", waveNumber) end
		else
			waveSpawnActive = true
		end
	end
end

function WaveUnitCounter()
	if waveSpawnPossible then
		waveUnitCount = waveUnitCount + 1
		if printDebug then print("Print: waveUnitCount =", waveUnitCount) end
	end
end

local firstPurchase = true
function GameModeSpawnCooldown()
	WaveAttack()
	local spawnTime
	if botDefender and firstPurchase then
		spawnTime = {Min = StartSpawnTime.DefenseMin, Max = StartSpawnTime.DefenseMax}
	elseif firstPurchase then
		spawnTime = {Min = StartSpawnTime.AttackMin, Max = StartSpawnTime.AttackMax}
	elseif not waveSpawnActive then
		spawnTime = {Min = SpawnCooldownTime.DCGWaveOffMin, Max = SpawnCooldownTime.DCGWaveOffMax}
	else
		spawnTime = {Min = SpawnCooldownTime.DCGMin, Max = SpawnCooldownTime.DCGMax}
	end
	local cooldown = math.random(spawnTime.Min, spawnTime.Max)
	firstPurchase = false
	return cooldown
end

function table.shuffle(tbl)
	local rand = math.random
	for i = #tbl, 2, -1 do
	  local j = rand(i)
	  tbl[i], tbl[j] = tbl[j], tbl[i]
	end
	return tbl
end
  
-- Function to shuffle the flags table
local function shuffleFlags(flags)
	if waveNumber <= 1 then
		table.sort(flags, function(a, b) return a.name < b.name end)
	else
		table.shuffle(flags)
	end
end

-- Function to calculate flag priority for attacker
local function calculateAttackerPriority(f, enemyTeam, team, firstEnemyFlagEncountered)
    if f.owner == enemyTeam and not firstEnemyFlagEncountered then
        firstEnemyFlagEncountered = true
        return f.priority, firstEnemyFlagEncountered
    elseif f.owner == enemyTeam or f.owner == team then
        return f.priority * 0, firstEnemyFlagEncountered
    end
    return f.priority, firstEnemyFlagEncountered
end

-- Function to calculate flag priority for defender
local function calculateDefenderPriority(f, enemyTeam, team)
    if f.owner == enemyTeam then
        return f.priority * 2
    elseif f.owner == team then
        return f.priority * 0.5
    end
    return f.priority
end

function GetFlagToCapture(flagPoints, getPriority, flags)
	local alliedFlags, opponentFlags, neutralFlags, totalFlags = CalculateFlagStatistics(BotApi.Scene.Flags)
	local capturableFlags = CalculateCapturableFlags(totalFlags, alliedFlags)

	PrintFlagDebugInfo(alliedFlags, opponentFlags, neutralFlags, totalFlags, capturableFlags, teamIsLosing)
    
    searchDestroy = CalculateSearchDestroyValue(capturableFlags, alliedFlags, opponentFlags)
	
	if waveNumber <= 1 then
        shuffleFlags(flags)
    end
	local firstEnemyFlagEncountered = false

	return GetRandomItem(flags, function(f)
		if not botDefender then
			-- bot prioritize one flag (1st in flags table that is enemy)
			local priority
			priority, firstEnemyFlagEncountered = calculateAttackerPriority(f, enemyTeam, team, firstEnemyFlagEncountered)
			return priority
		else
			return calculateDefenderPriority(f, enemyTeam, team)
		end
	end)
end

function GetCurrentSpawnWaitTime()
    return UnitSpawnWaitTime
end

function GetUnitToSpawn(units)
	if not units then
		return nil
	end
	
	local unitsToSpawn = {}
	
	local income = BotApi.Commands:Income(BotApi.Instance.playerId)

	if printDebug then print("Player#".. BotApi.Instance.playerId.. " Units") end
	for i, unit in pairs(units) do
		local min_team = unit.min_team  -- not used
		local min_income = unit.min_income -- not used
		local available = BotApi.Commands:IsUnitAvailable(unit.unit)
		
		if not min_income then min_income = -1 end
		if not min_team then min_team = 0 end
		
		--if printDebug then print("------ Unit", unit.unit) end

		if teamSize >= min_team and income >= min_income and available then
			table.insert(unitsToSpawn, unit)
		end
	end

	-- TODO: instead of return nil, find the shortest tts and delay calling function again by that time 
	if #unitsToSpawn == 0 then
		return nil
	end

	return GetRandomItem(unitsToSpawn, function(t)

		-- search "type" array for specific element
		local function UnitType (val)
			for index, value in ipairs(t.type) do
				if value == val then
					return true
				end
			end
			return false
		end

		if UnitType("Squad") then
			return t.priority * 1.75
		end

		if UnitType("Cannon") then
			return t.priority * 0.80
		end

		return t.priority
	end)
end

function OnGameStart()
    isAttackerOrDefender()
    setVarsInMissionScript()
    OnGameStartUtility("conquest")
end

function OnGameQuant()
	TrySpawnUnit()

	local waypoints = BotApi.Scene.Waypoints
	if #waypoints == 0 then
		for i, squad in pairs(BotApi.Scene.Squads) do
			if not Context.SquadTimers[squad] then
				SetSquadOrder(CaptureFlag, squad, OrderRotationPeriod)
			end
		end
	end
end

function GotoNextWaypoint(squad)
	local waypoints = BotApi.Scene.Waypoints
	BotApi.Commands:CaptureFlag(squad, waypoints[math.random(#waypoints)]) --captureflag is basically gothereandattack
	if printDebug then print("Print: #captureFlag call inside GoToNextWaypoint") end
end

function OnWaypoint(args)
	if printDebug then print("Print: #GotoNextWaypoint call inside OnWaypoint") end
	GotoNextWaypoint(args.squadId)
end

-- NOTE: Returns true if squad tagged "_lua_mi" or "_lua_alert".
-- NOTE: "_lua_mi" = reserved for mission script use.
-- NOTE: "_lua_alert" = squad abruptly runs into enemy force seek&destroy.
function IsSquadInScript(squad)
	if BotApi.Scene:IsSquadTagged(squad, "_lua_mi") or BotApi.Scene:IsSquadTagged(squad, "repairing") then
		if printDebug then print("Print: SQUADinSCRIPT thus no action squad", squad, "Player#",BotApi.Instance.playerId, "Team", team) end
		return true
	elseif BotApi.Scene:IsSquadTagged(squad, "_lua_alert") then
		if printDebug then print("Print: SQUADinALERT thus seek by squad", squad, "Player#",BotApi.Instance.playerId, "Team", team) end
		BotApi.Commands:SeekAndDestroy(squad)
		return true
	end
end

	-- NOTE: Returns true if squad tagged "_lua_ignore" for general ignore.
function IsSquadToIgnore(squad)
	if BotApi.Scene:IsSquadTagged(squad, "_lua_ignore") then
		return true
	end
end

function CaptureFlag(squad)
	local flags = {}
    for i, flag in pairs(BotApi.Scene.Flags) do
        table.insert(flags, {id = i, name = flag.name, priority = getDefaultFlagPriority(flag), owner = flag.occupant})
    end
	
	local flag = GetFlagToCapture(BotApi.Scene.Flags, getDefaultFlagPriority, flags)

	if not flag then
		if printDebug then print("Print: No Flags so SeekAndDestroy by squad ", squad, "Player#", BotApi.Instance.playerId) end
		BotApi.Commands:SeekAndDestroy(squad)
		return
	end

	if IsSquadInScript(squad) then
		return
	end

	if IsSquadToIgnore(squad) then
		local rndAI = math.random()
		if searchDestroy > rndAI then
			if printDebug then print("Print: [see_enemy] seek by squad ", squad, "Player#", BotApi.Instance.playerId) end
			BotApi.Commands:SeekAndDestroy(squad)
			return
		else
			if printDebug then print("Print: [see_enemy] donothing by squad ", squad, "Player#", BotApi.Instance.playerId) end
			return
		end
	end

	if printDebug then print("Print: [notags] ctf by squad", squad, "Player#", BotApi.Instance.playerId, "Flag name: ", flag.name) end
	return BotApi.Commands:CaptureFlag(squad, flag.name)
end

function OnGameSpawn(args)
	local waypoints = BotApi.Scene.Waypoints
	if #waypoints == 0 then
		SetSquadOrder(CaptureFlag, args.squadId, OrderRotationPeriod)
	else
		GotoNextWaypoint(args.squadId)
		if printDebug then print("Print: #waypoints != 0") end
	end
end

local __GatesOfEuropaBridge_old_OnGameStop = OnGameStop

GOE_BRIDGE_ENABLED = GOE_BRIDGE_ENABLED or false
GOE_BATTLE_ID = GOE_BATTLE_ID or ""
GOE_BRIDGE_RESULT_PATH = GOE_BRIDGE_RESULT_PATH or ""
GOE_BRIDGE_CONTEXT_PATH = GOE_BRIDGE_CONTEXT_PATH or ""
GOE_BRIDGE_CONTEXT_EXPIRES_UTC = GOE_BRIDGE_CONTEXT_EXPIRES_UTC or 0

local goe_context_loaded = false
local goe_loaded_context_path = ""
local goe_result_written = false

local function goe_file_exists(path)
	if path == nil or path == "" then
		return false
	end

	local f = io.open(path, "r")

	if f then
		f:close()
		return true
	end

	return false
end

local function goe_add_context_candidate(candidates, path)
	if path ~= nil and path ~= "" then
		candidates[#candidates + 1] = path
	end
end

local function goe_try_load_context()
	if goe_context_loaded then
		return
	end

	goe_context_loaded = true

	local candidates = {}

	local userProfile = os.getenv("USERPROFILE")
	if userProfile ~= nil and userProfile ~= "" then
		goe_add_context_candidate(
			candidates,
			userProfile .. "/Documents/My Games/gates of hell/GatesOfEuropa/goe_battle_context.lua"
		)
	end

	local oneDrive = os.getenv("OneDrive")
	if oneDrive ~= nil and oneDrive ~= "" then
		goe_add_context_candidate(
			candidates,
			oneDrive .. "/Documents/My Games/gates of hell/GatesOfEuropa/goe_battle_context.lua"
		)
	end

	-- Legacy fallback for old test builds that wrote beside the executable.
	goe_add_context_candidate(candidates, "goe_battle_context.lua")

	for i = 1, #candidates do
		local context_path = candidates[i]

		if goe_file_exists(context_path) then
			local ok, err = pcall(dofile, context_path)

			if ok then
				goe_loaded_context_path = context_path

				if GOE_BRIDGE_CONTEXT_PATH == nil or GOE_BRIDGE_CONTEXT_PATH == "" then
					GOE_BRIDGE_CONTEXT_PATH = context_path
				end

				return
			else
				if printDebug then
					print("Gates of Europa bridge context failed to load: ", context_path, err)
				end
			end
		end
	end
end

local function goe_context_is_expired()
	local expiresUtc = tonumber(GOE_BRIDGE_CONTEXT_EXPIRES_UTC)

	if expiresUtc == nil or expiresUtc <= 0 then
		return false
	end

	local nowUtc = os.time()

	return nowUtc > expiresUtc
end

local function goe_delete_loaded_context()
	local path = goe_loaded_context_path

	if path == nil or path == "" then
		path = GOE_BRIDGE_CONTEXT_PATH
	end

	if path ~= nil and path ~= "" then
		pcall(os.remove, path)
	end
end

local function goe_write_line(f, key, value)
	if f then
		f:write(tostring(key) .. "=" .. tostring(value) .. "\n")
	end
end

local function goe_write_flag_summary(f)
	local alliedFlags, opponentFlags, neutralFlags, totalFlags = CalculateFlagStatistics(BotApi.Scene.Flags)
	goe_write_line(f, "alliedFlags", alliedFlags)
	goe_write_line(f, "opponentFlags", opponentFlags)
	goe_write_line(f, "neutralFlags", neutralFlags)
	goe_write_line(f, "totalFlags", totalFlags)
end

local function goe_determine_player_victory()
	local alliedFlags, opponentFlags, neutralFlags, totalFlags = CalculateFlagStatistics(BotApi.Scene.Flags)

	-- BotApi team is the bot side in this script. enemyTeam is the human/player side.
	-- Current rule: player wins if the bot has no flags and the player has at least one flag.
	return alliedFlags == 0 and opponentFlags > 0
end

local function goe_write_result_file()
	if goe_result_written then
		return
	end

	goe_try_load_context()

	if GOE_BRIDGE_ENABLED ~= true then
		return
	end

	if goe_context_is_expired() then
		return
	end

	if GOE_BATTLE_ID == nil or GOE_BATTLE_ID == "" or GOE_BATTLE_ID == "unknown" then
		return
	end

	if GOE_BRIDGE_RESULT_PATH == nil or GOE_BRIDGE_RESULT_PATH == "" then
		return
	end

	local f = io.open(GOE_BRIDGE_RESULT_PATH, "w")
	if not f then
		return
	end

	local playerWon = goe_determine_player_victory()

	goe_write_line(f, "version", 1)
	goe_write_line(f, "finished", 1)
	goe_write_line(f, "battleId", GOE_BATTLE_ID)
	goe_write_line(f, "playerWon", playerWon and 1 or 0)

	-- Debug info only. Unity should resolve the strategic result from playerWon + PendingBattleRecord.PlayerIsAttacker.
	goe_write_line(f, "gameMode", BotApi.Instance.gameMode)
	goe_write_line(f, "playerId", BotApi.Instance.playerId)
	goe_write_line(f, "army", BotApi.Instance.army)
	goe_write_line(f, "difficulty", BotApi.Instance.difficulty)
	goe_write_line(f, "team", team)
	goe_write_line(f, "enemyTeam", enemyTeam)
	goe_write_line(f, "teamSize", teamSize)
	goe_write_line(f, "spawnPoint", spawnPoint)
	goe_write_line(f, "spawnSide", spawnSide)
	goe_write_line(f, "botDefender", tostring(botDefender))
	goe_write_flag_summary(f)

	f:close()

	goe_result_written = true

	-- Prevent stale bridge contexts from affecting later normal GoH matches.
	goe_delete_loaded_context()
end

function OnGameStop(...)
	if __GatesOfEuropaBridge_old_OnGameStop then
		pcall(__GatesOfEuropaBridge_old_OnGameStop, ...)
	end

	pcall(goe_write_result_file)
end

BotApi.Events:Subscribe(BotApi.Events.GameStart, OnGameStart)
BotApi.Events:Subscribe(BotApi.Events.GameEnd, OnGameStop)
BotApi.Events:Subscribe(BotApi.Events.Quant, OnGameQuant)
BotApi.Events:Subscribe(BotApi.Events.GameSpawn, OnGameSpawn)
BotApi.Events:Subscribe(BotApi.Events.Waypoint, OnWaypoint)