require([[/script/multiplayer/modes/utility]])
require([[/script/multiplayer/modes/utility_ce]])

-- [1.5.6] Code:X Reversion
printDebug = true

Context.SpawnSeekTimer = Context.SpawnSeekTimer or {}

-- Time from start of match AI will wait before attempting to buy a unit.
-- Attacker first buy is near-instant: official preparationTime in campaign_capture_the_flag.set
-- now gates the defense prep phase (v1.064+). Do NOT stack another 7-8 min here.
StartSpawnTime = {
    -- Bot is defender
    DefenseMin = 0 * 60 * 1000, 
    DefenseMax = 0 * 60 * 1000,
    -- Bot is attacker (prep phase controls real delay when player defends)
    AttackMin = 1 * 1000, 
    AttackMax = 1 * 1000,
}

-- Time from last purchase AI will wait before attempting to buy a new unit.
SpawnCooldownTime = {
    -- Time between each wave
    DCGWaveOffMin = 3.0 * 60 * 1000, 
    DCGWaveOffMax = 5.0 * 60 * 1000,
    -- Time between each wave (Defender)	
    DCGWaveOffMin_Defender = 3.5 * 60 * 1000, 
    DCGWaveOffMax_Defender = 5.0 * 60 * 1000,
   -- Time between each wave (Attacker)
    DCGWaveOffMin_Attacker = 3.0 * 60 * 1000, 
    DCGWaveOffMax_Attacker = 5.0 * 60 * 1000,
   -- Time between each spawn
    DCGMin = 5 * 1000, 
    DCGMax = 8 * 1000,
}

-- Number of possible units than can be in a wave attack
WaveUnit = {
    Min = 4,
    Max = 7,
    -- Defender-specific range
    Min_Defender = 3,
    Max_Defender = 5,
    -- Attacker-specific range
    Min_Attacker = 4,
    Max_Attacker = 7,
}

-- Sets time limit AI will wait for a unit it has chosen to buy if the unit is not yet available
local UnitSpawnWaitTime = 1.0 * 60000 -- 1:30min (ms) 

-- Time delay for units to get a new move order after spawn move order. Loops.
local OrderRotationPeriod = 1.75 * 60000 -- 1:45 min (ms)
-- Re-issue a move shortly after spawn in case the first order is skipped/eaten.
local SpawnOrderNudgeDelay = 5 * 1000 -- 5s

botDefender = false
botDifficultyModifier = 0
enableWaveCounter = true

-- Global reduction for all runtime AI purchase waves.
local NormalWaveSizeScale = 0.765

-- One conquest.lua runs per bot. Resolve engine-owned identities once per instance.
local myId = BotApi.Instance.playerId or 0
local firstEnemyId = 0
local defenderBotId = 0
local firstPlayerId = 0
local missionIdentityRetryPending = false

local function resolvePositiveId(primary, fallback)
	if primary and primary > 0 then return primary end
	if fallback and fallback > 0 then return fallback end
	return 0
end

local function refreshConquestIdentity()
	local conquest = BotApi.Conquest or {}
	myId = BotApi.Instance.playerId or 0
	firstEnemyId = resolvePositiveId(conquest.FirstEnemyId, BotApi.Instance.CampaignFirstEnemyId)
	defenderBotId = resolvePositiveId(conquest.DefenderBotId, BotApi.Instance.CampaignDefenderBotId)
	firstPlayerId = resolvePositiveId(conquest.FirstPlayerId, BotApi.Instance.CampaignFirstPlayerId)
end

local function isMissionAuthority()
	return firstEnemyId > 0 and myId == firstEnemyId
end

local function publishConquestIds()
	if firstEnemyId > 0 then BotApi.Scene:SetVar("id_1st_enemy", firstEnemyId) end
	if defenderBotId > 0 then BotApi.Scene:SetVar("id_defenderbot", defenderBotId) end
	if firstPlayerId > 0 then BotApi.Scene:SetVar("id_1st_player", firstPlayerId) end
end

-- Attack-side scripts need the physical side the enemy bot spawned on: the
-- dynamic campaign swaps attacker/defender spawns per mission instance, so a
-- static entry waypoint is never correct. utility.lua derives spawnSide from
-- BotApi.Instance.spawnPointName ("a1" -> "a"). One writer only: this is
-- published from the mission-authority branch alongside the perspective vars.
-- Must be a sibling of publishConquestIds (NOT nested). Nested scope made the
-- setVarsInMissionScript call resolve to nil and hard-crash enemy bot init.
local function publishEnemySpawnSide()
	local side = spawnSide
	if type(side) ~= "string" or side == "" then
		local sp = BotApi.Instance and BotApi.Instance.spawnPointName
		if type(sp) == "string" and #sp > 0 then
			side = string.sub(sp, 1, 1)
		end
	end
	local sideNum = 0
	if side == "a" or side == "A" then
		sideNum = 1
	elseif side == "b" or side == "B" then
		sideNum = 2
	end
	-- Always publish a number (never nil) so Scene:SetVar cannot native-fault.
	BotApi.Scene:SetVar("enemy_spawnside", sideNum)
	if printDebug then
		print("Print: enemy_spawnside published", sideNum, "rawSide", tostring(side), "spawnPoint", tostring(BotApi.Instance and BotApi.Instance.spawnPointName))
	end
end

local DifficultySettings = {
    easy = {
        waveScale = 0.60,
        waveGrowthScale = 0.45,
    },
    normal = {
        waveScale = 0.78,
        waveGrowthScale = 0.70,
    },
    hard = {
        waveScale = 0.95,
        waveGrowthScale = 0.90,
    },
    heroic = {
        waveScale = 1.00,
        waveGrowthScale = 1.00,
    },
}

local ActiveDifficultySettings = DifficultySettings.heroic

local function ApplyDifficultyScaling()
    local botDifficulty = BotApi.Instance.difficulty
    ActiveDifficultySettings = DifficultySettings[botDifficulty] or DifficultySettings.heroic

    if printDebug then
        print("difficulty waveScale =", ActiveDifficultySettings.waveScale, "waveGrowthScale =", ActiveDifficultySettings.waveGrowthScale)
    end
end

local conquestSpawnPointIndex = 0

-- Sequential bot spawns (v1.064+). Override default utility Spawn().
function GameModeSpawnUnit(unit, maxSquadSize)
	if BotApi.Commands.SpawnAt and BotApi.Commands:SpawnAt(unit, maxSquadSize, conquestSpawnPointIndex) then
		conquestSpawnPointIndex = conquestSpawnPointIndex + 1
		return true
	end
	-- Fallback if SpawnAt unavailable (older engine / Code:X utility path)
	return BotApi.Commands:Spawn(unit, maxSquadSize)
end

local function isAttackerOrDefender()
	-- v1.064+: explicit Conquest API (replaces fragile teamSize > 1 heuristic)
	if BotApi.Conquest and BotApi.Conquest.Attacking ~= nil then
		botDefender = not BotApi.Conquest.Attacking
	else
		botDefender = teamSize > 1
	end
	refreshConquestIdentity()
	if printDebug then
		print("DCG role", "playerId", myId, "botDefender", botDefender, "firstEnemyId", firstEnemyId, "defenderBotId", defenderBotId, "firstPlayerId", firstPlayerId, "defenderBotPurchaseHost", false)
	end
end

local function setVarsInMissionScript()
	-- Stable Conquest IDs are perspective-neutral and may be published by every bot.
	publishConquestIds()
	if not isMissionAuthority() then return false end

	-- Everything below is enemy-bot perspective and must have one writer.
	BotApi.Scene:SetVar("user_is_defender", botDefender and 0 or 1)
	publishEnemySpawnSide()

	local botNation = BotApi.Instance.army
	local botDifficulty = BotApi.Instance.difficulty
	-- Keep in sync with dcg/player_nation side map (1 rusa .. 8 pol)
	local nationMap = { rusa = 1, ukr = 2, nato = 3, csa = 4, sov = 5, prc = 6, frg = 7, pol = 8, goc_bel = 14, goc_bgr = 28, goc_blr = 69, goc_can = 60, goc_cze = 16, goc_deu = 53, goc_dnk = 62, goc_donbas = 68, goc_dprk = 67, goc_esp = 63, goc_est = 21, goc_fin = 57, goc_fra = 54, goc_gbr = 52, goc_grc = 26, goc_hrv = 29, goc_hun = 18, goc_ita = 56, goc_ltu = 19, goc_lva = 20, goc_nld = 59, goc_nor = 61, goc_pol = 55, goc_prt = 15, goc_rou = 27, goc_rus = 65, goc_srb = 70, goc_svk = 17, goc_swe = 58, goc_tur = 64, goc_ukr = 66, goc_usa = 51,
		-- legacy / alias ids
		rus = 1, ger = 2, fin = 3, usa = 3, eng = 3, jap = 6 }
	local difficultyMap = { easy = 1, normal = 2, hard = 3, heroic = 4 }
	local spawnMap = { a = 1, b = 2}
	local playerSpawnNameMap = {
		a1 = 1, a2 = 2, a3 = 3, a4 = 4,
		b1 = 5, b2 = 6, b3 = 7, b4 = 8,
	}
	-- Opposite-alliance guess for MI when {type side} fails (West vs East).
	local eastNations = { rusa = true, sov = true, prc = true, pol = true, rus = true, jap = true, goc_blr = true, goc_donbas = true, goc_dprk = true, goc_rus = true, goc_srb = true }
	local westNations = { nato = true, ukr = true, csa = true, frg = true, usa = true, eng = true, ger = true, fin = true, goc_bel = true, goc_bgr = true, goc_can = true, goc_cze = true, goc_deu = true, goc_dnk = true, goc_esp = true, goc_est = true, goc_fin = true, goc_fra = true, goc_gbr = true, goc_grc = true, goc_hrv = true, goc_hun = true, goc_ita = true, goc_ltu = true, goc_lva = true, goc_nld = true, goc_nor = true, goc_pol = true, goc_prt = true, goc_rou = true, goc_svk = true, goc_swe = true, goc_tur = true, goc_ukr = true, goc_usa = true }

	BotApi.Scene:SetVar("bot_army", nationMap[botNation] or 0)
	-- Hint only: MI dcg/player_nation remains authority when side matches.
	-- If side detection fails, MI default uses bot_army to pick the opposite bloc.
	if eastNations[botNation] then
		BotApi.Scene:SetVar("user_nation_hint", 3) -- prefer NATO/West
	elseif westNations[botNation] then
		BotApi.Scene:SetVar("user_nation_hint", 1) -- prefer RUSA/East
	else
		BotApi.Scene:SetVar("user_nation_hint", 3)
	end
	BotApi.Scene:SetVar("bot_difficulty", difficultyMap[botDifficulty] or 0)
	BotApi.Scene:SetVar("bots_spawnside", spawnMap[spawnSide] or 0)

	local playerSpawn = BotApi.Conquest and BotApi.Conquest.PlayerSpawnPoint
	if not playerSpawn or playerSpawn == "" then playerSpawn = BotApi.Instance.spawnPointName end
	BotApi.Scene:SetVar("player_spawn_name", playerSpawnNameMap[playerSpawn] or 0)
	BotApi.Scene:SetVar("enemyid", myId)

	if botDefender then
		if difficultyMap[botDifficulty] == 4 then
			botDifficultyModifier = AiDefenderCount.Attacking.difficultyModifier.heroic
		elseif difficultyMap[botDifficulty] == 3 then
			botDifficultyModifier = AiDefenderCount.Attacking.difficultyModifier.hard
		elseif difficultyMap[botDifficulty] == 2 then
			botDifficultyModifier = AiDefenderCount.Attacking.difficultyModifier.normal
		else
			botDifficultyModifier = AiDefenderCount.Attacking.difficultyModifier.easy
		end
	else
		if difficultyMap[botDifficulty] == 4 then
			botDifficultyModifier = AiDefenderCount.Defending.difficultyModifier.heroic
		elseif difficultyMap[botDifficulty] == 3 then
			botDifficultyModifier = AiDefenderCount.Defending.difficultyModifier.hard
		elseif difficultyMap[botDifficulty] == 2 then
			botDifficultyModifier = AiDefenderCount.Defending.difficultyModifier.normal
		else
			botDifficultyModifier = AiDefenderCount.Defending.difficultyModifier.easy
		end
	end

	if printDebug then print("botDifficultyModifier = ", botDifficultyModifier) end
	SetCEMissionVariables(botDefender)
	return true
end

-- Each order tick: 50% scatter flank / 50% weighted CaptureFlag.
-- Flank = real path order (uniform non-owned flag, or waypoint) so squads leave spawn and spread.
local FlankOrderChance = 0.50
local FlankWaypointChance = 0.30
local waveSpawnPossible = true
local waveSpawnActive = true
local waveUnitCount = 0
local waveNumber = 0
local waveUnitTotal
-- local waveUnitTotal = math.random(WaveUnit.Min, WaveUnit.Max)
-- local waveUnitTotal = math.random(adjustedMin, adjustedMax)
if printDebug then print("Print: waveUnitTotal", waveUnitTotal) end

-- 定义每个师的优先级调整乘数
local divisions = {
    ["inf_div"] = { attackerMultiplier = 10, defenderMultiplier = 5, mechMultiplier = 0.25,
					infantryMultiplier = 1.5, signallerMultiplier = 1.0, cannonMultiplier = 0.5, artMultiplier = 0.5, tankMultiplier = 0.75, 
					heavyMultiplier = 0.5, uniqueMultiplier = 0.25, airMultiplier = 0.5, tbgMultiplier = 0.5, ibgMultiplier = 1.0, abgMultiplier = 0.5
				  },
    ["art_div"] = { attackerMultiplier = 5, defenderMultiplier = 3, mechMultiplier = 0.25,
					infantryMultiplier = 0.75, signallerMultiplier = 2.0, cannonMultiplier = 1.5, artMultiplier = 1.5, tankMultiplier = 0.75, 
					heavyMultiplier = 0.5, uniqueMultiplier = 0.5, airMultiplier = 0.5, tbgMultiplier = 0.5, ibgMultiplier = 0.5, abgMultiplier = 1.0
				  },
    ["tank_div"] = { attackerMultiplier = 4, defenderMultiplier = 4, mechMultiplier = 0.75,
					infantryMultiplier = 0.5, signallerMultiplier = 0.5, cannonMultiplier = 0.5, artMultiplier = 0.5, tankMultiplier = 1.5, 
					heavyMultiplier = 0.75, uniqueMultiplier = 0.5, airMultiplier = 0.5, tbgMultiplier = 1.0, ibgMultiplier = 0.5, abgMultiplier = 0.5
				   },
    ["heavytank_div"] = { attackerMultiplier = 5, defenderMultiplier = 2, mechMultiplier = 0.75,
					infantryMultiplier = 0.5, signallerMultiplier = 0.5, cannonMultiplier = 0.5, artMultiplier = 0.5, tankMultiplier = 0.5, 
					heavyMultiplier = 1.5, uniqueMultiplier = 0.5, airMultiplier = 0.5, tbgMultiplier = 1.0, ibgMultiplier = 0.5, abgMultiplier = 0.5
						},
    ["air_div"] = { attackerMultiplier = 2, defenderMultiplier = 3, mechMultiplier = 0.25,
					infantryMultiplier = 0.75, signallerMultiplier = 0.75, cannonMultiplier = 0.75, artMultiplier = 0.5, tankMultiplier = 1.0, 
					heavyMultiplier = 0.75, uniqueMultiplier = 0.5, airMultiplier = 1.5, tbgMultiplier = 0.5, ibgMultiplier = 0.5, abgMultiplier = 0.5
				  },
    ["standard_div"] = { attackerMultiplier = 1, defenderMultiplier = 1, mechMultiplier = 0.5,
					infantryMultiplier = 1.0, signallerMultiplier = 0.5, cannonMultiplier = 0.75, artMultiplier = 0.5, tankMultiplier = 0.75, 
					heavyMultiplier = 0.5, uniqueMultiplier = 0.25, airMultiplier = 0.25, tbgMultiplier = 0.5, ibgMultiplier = 0.5, abgMultiplier = 0.5
					   },
    ["mech_div"] = { attackerMultiplier = 3, defenderMultiplier = 3, mechMultiplier = 1.0,
					infantryMultiplier = 1.0, signallerMultiplier = 1.0, cannonMultiplier = 0.5, artMultiplier = 0.5, tankMultiplier = 0.75, 
					heavyMultiplier = 0.5, uniqueMultiplier = 1.0, airMultiplier = 1.0, tbgMultiplier = 1.0, ibgMultiplier = 1.0, abgMultiplier = 0.5
				   },
    ["unique_div"] = { attackerMultiplier = 4, defenderMultiplier = 4, mechMultiplier = 1.25,
					infantryMultiplier = 0.75, signallerMultiplier = 1.5, cannonMultiplier = 0.75, artMultiplier = 1.0, tankMultiplier = 1.5, 
					heavyMultiplier = 1.0, uniqueMultiplier = 2.0, airMultiplier = 1.0, tbgMultiplier = 1.0, ibgMultiplier = 1.0, abgMultiplier = 1.0
				     }
}

-- 选择一个师（根据实际需求选择）
local divisionNames = {"inf_div", "art_div", "tank_div", "heavytank_div", "air_div", "standard_div", "mech_div", "unique_div"}

-- local divisionsWithProbability = {
    -- {name = "inf_div", probability = 10},  -- 10% 概率
    -- {name = "art_div", probability = 10},  -- 10% 概率
    -- {name = "tank_div", probability = 20}, -- 15% 概率
    -- {name = "heavytank_div", probability = 15}, -- 15% 概率
    -- {name = "air_div", probability = 10},  -- 10% 概率
    -- {name = "standard_div", probability = 15}, -- 15% 概率
    -- {name = "mech_div", probability = 10},  -- 10% 概率
    -- {name = "unique_div", probability = 10},  -- 10% 概率（特殊）
-- }

-- 加权随机选择函数
-- local function selectDivisionWithProbability(divisions)
    -- local totalProbability = 0
    -- for _, div in ipairs(divisions) do
        -- totalProbability = totalProbability + div.probability
    -- end

    -- local randomValue = math.random(1, totalProbability)
    -- local cumulativeProbability = 0
    -- for _, div in ipairs(divisions) do
        -- cumulativeProbability = cumulativeProbability + div.probability
        -- if randomValue <= cumulativeProbability then
            -- return div.name
        -- end
    -- end
-- end

-- local selectedDivision = divisionNames[math.random(#divisionNames)]
-- 基础随机选择
local function selectRandomDivision()
    return divisionNames[math.random(#divisionNames)]
end

-- 根据波次选择师
-- local function selectDivisionBasedOnWave(waveNumber)
    -- if waveNumber == 3 then
        -- return "art_div"
    -- elseif waveNumber == 5 then
        -- return "tank_div"
    -- elseif waveNumber == 7 then
        -- return "air_div"
    -- else
        -- return selectRandomDivision()-- selectDivisionWithProbability(divisionsWithProbability)
    -- end
-- end

-- 示例：初始随机选择师
local currentDivision = selectRandomDivision()  -- 初始随机选择师

-- 获取该师的优先级调整参数
local divisionParams = divisions[currentDivision]-- [selectedDivision]

-- 获取该师的讲述人系统
local function setDocVarsInNattorSpeak(currentDivision)
	
	local divisionsOnAi = { inf_div = 1, art_div = 2, tank_div = 3, heavytank_div = 4, air_div = 5, standard_div = 6, mech_div = 7, unique_div = 8}
	local divisionsOnMissionScript = {
		prc = { inf_div = 5, art_div = 6, tank_div = 9, heavytank_div = 9, air_div = 9, standard_div = 5, mech_div = 9, unique_div = 9},
		frg = { inf_div = 10, art_div = 6, tank_div = 11, heavytank_div = 11, air_div = 6, standard_div = 10, mech_div = 10, unique_div = 11}
	}
	local divisionNumberDebug = divisionsOnAi[currentDivision] or 0
	local botNation = BotApi.Instance and BotApi.Instance.army or ""
	local missionDivisionNumber = divisionNumberDebug
	if divisionsOnMissionScript[botNation] then
		missionDivisionNumber = divisionsOnMissionScript[botNation][currentDivision] or divisionNumberDebug
	end

	BotApi.Scene:SetVar("ai_divisions", divisionNumberDebug)
	BotApi.Scene:SetVar("bots_divisions", missionDivisionNumber)

	print("hoboe_by_ordos_debug,divisionNumber=",divisionNumberDebug) 
end

local waveNumberExtraUnits = {
    [3] = 3,  -- waveNumber 为 3 时，额外增加 5
    [5] = 5, -- waveNumber 为 5 时，额外增加 7
    [7] = 7, -- waveNumber 为 7 时，额外增加 10
    [10] = 10, -- waveNumber 为 10 时，额外增加 13
    [13] = 13, -- waveNumber 为 13 时，额外增加 15
    [15] = 15, -- waveNumber 为 15 时，额外增加 17
}

-- 自定义四舍五入函数
function math.round(x)
    return math.floor(x + 0.5)
end

-- 计算 waveUnitTotal 的函数
function calculateWaveUnitTotal()-- (currentDivision, waveNumber, botDefender)
	local ExtraUnitsValue = math.round((waveNumberExtraUnits[waveNumber] or 0) * ActiveDifficultySettings.waveGrowthScale)
	local divisionParams = divisions[currentDivision]
	local rawWaveTotal

	if botDefender then
		rawWaveTotal = math.random(WaveUnit.Min_Defender, WaveUnit.Max_Defender) + divisionParams.defenderMultiplier + ExtraUnitsValue
	else
		rawWaveTotal = math.random(WaveUnit.Min_Attacker, WaveUnit.Max_Attacker) + divisionParams.attackerMultiplier + math.round(ExtraUnitsValue/2)
	end

	waveUnitTotal = math.max(3, math.round(rawWaveTotal * ActiveDifficultySettings.waveScale * NormalWaveSizeScale))
	if printDebug then print("Print: waveUnitTotal", waveUnitTotal, "waveNumber", waveNumber, "normalWaveSizeScale", NormalWaveSizeScale) end
end

function WaveAttack()
	if not waveUnitTotal then calculateWaveUnitTotal() end
	waveSpawnPossible = true

	if waveUnitCount >= waveUnitTotal then
		waveSpawnActive = false
		waveUnitCount = 0
		waveNumber = waveNumber + 1
		calculateWaveUnitTotal()
		if printDebug then print("Print: waveNumber", waveNumber, "SelectedDivision", currentDivision) end
	else
		waveSpawnActive = true
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
	local cadence = "within-wave"

	if botDefender and firstPurchase then
		spawnTime = {Min = StartSpawnTime.DefenseMin, Max = StartSpawnTime.DefenseMax}
		cadence = "enemy-defender-opening"
	elseif firstPurchase then
		spawnTime = {Min = StartSpawnTime.AttackMin, Max = StartSpawnTime.AttackMax}
		cadence = "enemy-attacker-opening"
	elseif not waveSpawnActive then
		if botDefender then
			spawnTime = {Min = SpawnCooldownTime.DCGWaveOffMin_Defender, Max = SpawnCooldownTime.DCGWaveOffMax_Defender}
			cadence = "enemy-defender"
		else
			spawnTime = {Min = SpawnCooldownTime.DCGWaveOffMin_Attacker, Max = SpawnCooldownTime.DCGWaveOffMax_Attacker}
			cadence = "enemy-attacker"
		end
	else
		spawnTime = {Min = SpawnCooldownTime.DCGMin, Max = SpawnCooldownTime.DCGMax}
	end

	local cooldown = math.random(spawnTime.Min, spawnTime.Max)
	if printDebug then print("DCG cadence", cadence, "playerId", myId, "waveNumber", waveNumber, "cooldownSeconds", cooldown / 1000) end
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
-- NOTE: own flags must stay > 0 or GetRandomItem total becomes 0 and orders fail
-- (bot defenders often run with botDefender=false when teamSize==1).
local function calculateAttackerPriority(f, enemyTeam, team, firstEnemyFlagEncountered)
    if f.owner == enemyTeam and not firstEnemyFlagEncountered then
        firstEnemyFlagEncountered = true
        return f.priority, firstEnemyFlagEncountered
    elseif f.owner == enemyTeam then
        return f.priority, firstEnemyFlagEncountered
    elseif f.owner == team then
        return f.priority * 0.1, firstEnemyFlagEncountered
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
			local priority
			priority, firstEnemyFlagEncountered = calculateAttackerPriority(f, enemyTeam, team, firstEnemyFlagEncountered)
			return priority
		end
		return calculateDefenderPriority(f, enemyTeam, team)
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

	searchProps = {
-- Human tags
		"soldier", 
		"crew", 
		"soldier_pzscheck",
		"soldier_pzfaust",
		"soldier_atr",
		"soldier_atr_grenade",
		"soldier_bazooka",
	}
	local sceneUnits = BotApi.Scene:QueryScene(searchProps, 5)

	local unitCounts = {
		BotInfantry = 0,
		BotATInfantry = 0,
		BotTanks = 0,
	}
	
	local propertyToVariable = {
	-- Humans
		["soldier"] = {"BotInfantry"},
		["soldier_pzscheck"] = {"BotInfantry", "BotATInfantry"},
		["soldier_pzfaust"] = {"BotInfantry", "BotATInfantry"},
		["soldier_atr"] = {"BotInfantry", "BotATInfantry"},
		["soldier_atr_grenade"] = {"BotInfantry", "BotATInfantry"},
		["soldier_bazooka"] = {"BotInfantry", "BotATInfantry"},
	}
	
	local botUnits = sceneUnits[BotApi.Instance.playerId][2]
	
	for i, prop in ipairs(searchProps) do
		local count = botUnits[i]
		local variables = propertyToVariable[prop]
		if variables then
			for _, variable in ipairs(variables) do
				unitCounts[variable] = unitCounts[variable] + count
			end
		end
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

		local basePriority = t.priority
		local priorityMultiplier = 1

		-- Bot division priority change

		if unitCounts.BotInfantry < 45 then -- minimum amount of infantry
			if UnitType("Infantry") and not UnitType("Unique") then
				priorityMultiplier = priorityMultiplier * (divisionParams.infantryMultiplier)
			end
		elseif unitCounts.BotInfantry >= 80 then -- maximum amount of infantry
			if UnitType("Infantry") and not UnitType("Unique") then
				priorityMultiplier = priorityMultiplier * (divisionParams.infantryMultiplier) * 0.25
			end
		end

		if UnitType("Tankbg") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.tbgMultiplier)
		end

		if UnitType("Artbg") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.abgMultiplier)
		end

		if UnitType("Infantrybg") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.ibgMultiplier)
		end

		if UnitType("Mech") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier)
		end

		if UnitType("Cannon") and not UnitType("Artillery") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.cannonMultiplier)
		end

		if UnitType("Cannon") and UnitType("Artillery") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.artMultiplier)
		end

		if UnitType("MobileArtillery") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.artMultiplier)
		end

		if UnitType("Tank") and not UnitType("Heavy") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.tankMultiplier)
		end

		if UnitType("Tank") and UnitType("Heavy") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.heavyMultiplier)
		end

		if UnitType("Sortie") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.airMultiplier)
		end

		if UnitType("Ifv") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier) * 0.5
		end

		if UnitType("Vehicle") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier) * 0.5
		end

		if UnitType("Signaller") and not UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.signallerMultiplier)
		end

		if unitCounts.BotInfantry < 45 then -- minimum amount of infantry
			if UnitType("Infantry") and UnitType("Unique") then
				priorityMultiplier = priorityMultiplier * (divisionParams.infantryMultiplier) * (divisionParams.uniqueMultiplier)
			end
		elseif unitCounts.BotInfantry >= 80 then -- maximum amount of infantry
			if UnitType("Infantry") and UnitType("Unique") then
				priorityMultiplier = priorityMultiplier * (divisionParams.infantryMultiplier) * (divisionParams.uniqueMultiplier) * 0.25
			end
		end

		if UnitType("Tankbg") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.tbgMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Artbg") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.abgMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Infantrybg") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.ibgMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Mech") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Cannon") and not UnitType("Artillery") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.cannonMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Cannon") and UnitType("Artillery") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.artMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("MobileArtillery") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.artMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Tank") and not UnitType("Heavy") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.tankMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Tank") and UnitType("Heavy") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.heavyMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Sortie") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.airMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("Ifv") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier) * (divisionParams.uniqueMultiplier) * 0.4
		end

		if UnitType("Vehicle") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.mechMultiplier) * (divisionParams.uniqueMultiplier) * 0.4
		end

		if UnitType("Signaller") and UnitType("Unique") then
			priorityMultiplier = priorityMultiplier * (divisionParams.signallerMultiplier) * (divisionParams.uniqueMultiplier)
		end

		if UnitType("inf_div") and currentDivision == "inf_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("art_div") and currentDivision == "art_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("tank_div") and currentDivision == "tank_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("heavytank_div") and currentDivision == "heavytank_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("air_div") and currentDivision == "air_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("mech_div") and currentDivision == "mech_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		if UnitType("unique_div") and currentDivision == "unique_div" then
			priorityMultiplier = priorityMultiplier * 150
		end

		return basePriority * priorityMultiplier
	end)
end

function OnGameStart()
	isAttackerOrDefender()
	ApplyDifficultyScaling()
	CheckIfChallengeMap()
	local wroteMissionVars = setVarsInMissionScript()
	if wroteMissionVars then
		setDocVarsInNattorSpeak(currentDivision)
	elseif firstEnemyId <= 0 or defenderBotId <= 0 or firstPlayerId <= 0 then
		-- Retry once on the first quant: new Conquest IDs may settle after GameStart.
		missionIdentityRetryPending = true
	end
	OnGameStartUtility("conquest")
end

local function retryMissionIdentityOnce()
	if not missionIdentityRetryPending then return end
	missionIdentityRetryPending = false
	refreshConquestIdentity()
	local wroteMissionVars = setVarsInMissionScript()
	if wroteMissionVars then setDocVarsInNattorSpeak(currentDivision) end
	if printDebug then print("DCG identity retry", "playerId", myId, "firstEnemyId", firstEnemyId, "defenderBotId", defenderBotId, "firstPlayerId", firstPlayerId) end
end

-- Attack missions often never raise PrepTimeOver. Publish prep_inform once the
-- human is confirmed attacker so MI attack probes are not gated forever.
-- NOTE: must stay ABOVE OnGameQuant — a local defined after its caller resolves
-- to a nil global at call time and hard-crashes the bot on its first quant.
-- botDefender is THIS BOT's role: true means the bot defends, so the human is the
-- ATTACKER (SetVar("user_is_defender", botDefender and 0 or 1) right above, and
-- OnPrepTimeOver's "when player was defending, bot is attacker" branch uses
-- `not botDefender`). The early return therefore has to fire on `not botDefender`:
-- that is the human-DEFENCE mission, which runs a real 480s preparation phase and
-- must wait for OnPrepTimeOver. Publishing prep_inform there at the first quant
-- made every prep_inform consumer treat prep as already over at t=0 - it fired
-- dcg_script's dcg2/userdefend/prep_end during the player's own placement, and it
-- would let the defence-mission wave engines deploy into the prep phase.
local attackPrepInformPublished = false
local function ensureAttackPrepInform()
	if attackPrepInformPublished then return end
	if not botDefender then return end -- bot is attacker => human is defender; wait for real prep
	if not isMissionAuthority or not isMissionAuthority() then return end
	BotApi.Scene:SetVar("prep_inform", 1)
	attackPrepInformPublished = true
	if printDebug then print("Print: prep_inform set to 1 (human attack / no defense prep).") end
end

function OnGameQuant()
	retryMissionIdentityOnce()
	ensureAttackPrepInform()
	TrySpawnUnit()

	-- Always keep order timers (waypoint maps used to skip this and only got a one-shot move).
	for i, squad in pairs(BotApi.Scene.Squads) do
		if not Context.SquadTimers[squad] then
			SetSquadOrder(CaptureFlag, squad, OrderRotationPeriod)
		end
	end
end

function OnWaypoint(args)
	if not args or not args.squadId then return end
	if not BotApi.Scene:IsSquadExists(args.squadId) then return end
	-- Hand off to CaptureFlag loop so flanks/scatter apply after first waypoint.
	if not Context.SquadTimers[args.squadId] then
		SetSquadOrder(CaptureFlag, args.squadId, OrderRotationPeriod)
	else
		CaptureFlag(args.squadId)
	end
end

-- NOTE: Returns true if squad tagged "_lua_mi" / "repairing" / alert tags.
-- "_lua_alert" or "lua_alert" = squad abruptly runs into enemy force.
function IsSquadInScript(squad)
	if BotApi.Scene:IsSquadTagged(squad, "_lua_mi") or BotApi.Scene:IsSquadTagged(squad, "repairing") then
		if printDebug then print("Print: SQUADinSCRIPT thus no action squad", squad, "Player#",BotApi.Instance.playerId, "Team", team) end
		return true

	elseif BotApi.Scene:IsSquadTagged(squad, "_lua_alert") or BotApi.Scene:IsSquadTagged(squad, "lua_alert") then
		-- 60/40 SPLIT ON ENEMY CONTACT:
		-- 40%: SeekAndDestroy, 60%: hold/suppress (do nothing)
		if math.random() < 0.4 then
			BotApi.Commands:SeekAndDestroy(squad)
		else
			-- do nothing on purpose
		end
		return true
	end

	return false
end

-- MI/repair only — alert must not block a forced spawn kick.
local function IsSquadReserved(squad)
	return BotApi.Scene:IsSquadTagged(squad, "_lua_mi") or BotApi.Scene:IsSquadTagged(squad, "repairing")
end

	-- NOTE: Returns true if squad tagged "_lua_ignore" for general ignore.
function IsSquadToIgnore(squad)
	if BotApi.Scene:IsSquadTagged(squad, "_lua_ignore") then
		return true
	end
end

-- Scatter move: ~30% waypoint / ~70% uniform non-owned flag (enemy+neutral); S&D only if nothing else.
-- Ignores priority weighting so flanks fan out instead of bunching on the same objective.
local function IssueScatterOrder(squad, flags, logTag)
	local waypoints = BotApi.Scene.Waypoints
	local hasWaypoints = waypoints and #waypoints > 0

	local candidates = {}
	for _, f in pairs(flags) do
		if f.owner ~= team then
			table.insert(candidates, f)
		end
	end

	local preferWaypoint = hasWaypoints and (#candidates == 0 or math.random() <= FlankWaypointChance)
	if preferWaypoint then
		local wp = waypoints[math.random(#waypoints)]
		if printDebug then print("Print:", logTag, "waypoint", wp, "squad", squad, "Player#", BotApi.Instance.playerId) end
		return BotApi.Commands:CaptureFlag(squad, wp)
	end

	if #candidates > 0 then
		local pick = candidates[math.random(#candidates)]
		if printDebug then print("Print:", logTag, "flag", pick.name, "squad", squad, "Player#", BotApi.Instance.playerId) end
		return BotApi.Commands:CaptureFlag(squad, pick.name)
	end

	if printDebug then print("Print:", logTag, "S&D fallback squad", squad, "Player#", BotApi.Instance.playerId) end
	BotApi.Commands:SeekAndDestroy(squad)
end

function CaptureFlag(squad)
    local flags = {}
    for i, flag in pairs(BotApi.Scene.Flags) do
        table.insert(flags, {id = i, name = flag.name, priority = getDefaultFlagPriority(flag), owner = flag.occupant})
    end

    local flag = GetFlagToCapture(BotApi.Scene.Flags, getDefaultFlagPriority, flags)

    if IsSquadInScript(squad) then return end

    if IsSquadToIgnore(squad) then
        if searchDestroy > math.random() then
            if printDebug then print("Print: [see_enemy] seek by squad ", squad, "Player#", BotApi.Instance.playerId) end
            BotApi.Commands:SeekAndDestroy(squad)
        else
            -- Was idle for full OrderRotationPeriod; give a real path instead.
            IssueScatterOrder(squad, flags, "[see_enemy] scatter")
        end
        return
    end

    -- 50/50 scatter flank vs weighted CaptureFlag every order tick.
    if math.random() <= FlankOrderChance then
        IssueScatterOrder(squad, flags, "[flank order]")
        return
    end

    if not flag then
        if printDebug then print("Print: No Flags so SeekAndDestroy by squad ", squad, "Player#", BotApi.Instance.playerId) end
        BotApi.Commands:SeekAndDestroy(squad)
        return
    end

    if printDebug then print("Print: [notags] ctf by squad", squad, "Player#", BotApi.Instance.playerId, "Flag name: ", flag.name) end
    return BotApi.Commands:CaptureFlag(squad, flag.name)
end


local function IsSquadActive(squad)
	return squad ~= nil and BotApi.Scene:IsSquadExists(squad)
end

local function ScheduleSpawnOrderNudge(squad)
	if Context.SpawnSeekTimer[squad] then
		BotApi.Events:KillQuantTimer(Context.SpawnSeekTimer[squad])
		Context.SpawnSeekTimer[squad] = nil
	end
	Context.SpawnSeekTimer[squad] = BotApi.Events:SetQuantTimer(function()
		Context.SpawnSeekTimer[squad] = nil
		if not IsSquadActive(squad) then return end
		if IsSquadReserved(squad) then return end
		if printDebug then print("Print: [spawn nudge] squad", squad, "Player#", BotApi.Instance.playerId) end
		-- Force a real path (ignore alert/ignore tags for this kick only).
		local flags = {}
		for i, flag in pairs(BotApi.Scene.Flags) do
			table.insert(flags, {id = i, name = flag.name, priority = getDefaultFlagPriority(flag), owner = flag.occupant})
		end
		IssueScatterOrder(squad, flags, "[spawn nudge]")
	end, SpawnOrderNudgeDelay)
end

function OnGameSpawn(args)
    if not args or not args.squadId then return end
    local squad = args.squadId
    if not IsSquadActive(squad) then return end
	if printDebug then print("DCG spawned squad", squad, "botPlayerId", myId, "defenderBotId", defenderBotId, "waveNumber", waveNumber) end

	-- Only mark attack-started / rearrange spawns when the bot is the attacker.
	if not botDefender and not ai_attack_started then
        ai_attack_started = true
        BotApi.Scene:SetVar("ai_attack_started", 1)
        if printDebug then print("AI has started their attack!") end
        SelectAiSpawnStrategy()
    end

	-- Always register the CaptureFlag order loop (scatter uses waypoints when present).
	-- Waypoint maps used to get a single move order at spawn and never re-order,
	-- which left squads standing at the spawn line for the rest of the match.
	SetSquadOrder(CaptureFlag, squad, OrderRotationPeriod)
	ScheduleSpawnOrderNudge(squad)
end

-- v1.064+: prep phase ended (timer or Skip Preparation). Mission scripts key off prep_inform.
function OnPrepTimeOver()
	BotApi.Scene:SetVar("prep_inform", 1)
	if printDebug then print("Print: prep_inform set to 1, Player defense prep is over.") end

	-- When player was defending, bot is attacker — release attack start for CE scripts.
	if not botDefender and not ai_attack_started then
		ai_attack_started = true
		BotApi.Scene:SetVar("ai_attack_started", 1)
		if printDebug then print("AI attack released after prep time.") end
		if SelectAiSpawnStrategy then SelectAiSpawnStrategy() end
	end
end

BotApi.Events:Subscribe(BotApi.Events.GameStart, OnGameStart)
BotApi.Events:Subscribe(BotApi.Events.GameEnd, OnGameStop)
BotApi.Events:Subscribe(BotApi.Events.Quant, OnGameQuant)
BotApi.Events:Subscribe(BotApi.Events.GameSpawn, OnGameSpawn)
BotApi.Events:Subscribe(BotApi.Events.Waypoint, OnWaypoint)
if BotApi.Events.PrepTimeOver then
	BotApi.Events:Subscribe(BotApi.Events.PrepTimeOver, OnPrepTimeOver)
end
