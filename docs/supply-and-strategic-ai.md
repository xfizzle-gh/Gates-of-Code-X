# Supply, encirclement, and strategic AI

## Coalition movement

NATO and Ukraine can move through each other's controlled territory. Russia and PRC can do the same. Moving through allied territory does not transfer ownership, and allied battalions may not stack in the same province.

Retreats may use empty allied provinces. A formation can therefore fall back through coalition territory without converting that territory to its own faction.

## Supply sources and routes

Initial faction supply sources are:

- NATO: Sussex, Wester Ems, Warszawa
- Ukraine: Lwow, Zhytomyr
- Russia: Minsk, Leningrad
- PRC: province_0501 in the provisional Central Asian area

Supply routes traverse provinces controlled by the formation's faction or one of its coalition allies. Coalition members can use each other's valid supply sources, but their resources and formations remain separate.

At a round rollover:

- supplied formations recover 20 supply, up to 100
- isolated formations lose 25 supply
- isolation increments `encircled_turns`
- restored supply resets `encircled_turns` to zero
- formations at zero supply cannot move or attack that round
- starting on the third isolated turn, formations at 25 supply or less lose one unit per round

These values are initial balance constants and can be tuned independently from the save format.

## Strategic AI

The deterministic strategic AI processes each formation once per faction turn. It prioritizes:

1. adjacent hostile battalions
2. adjacent neutral provinces
3. adjacent hostile-controlled empty provinces
4. movement through friendly coalition territory toward the nearest hostile front
5. holding when no legal route is available

Battles initiated by AI factions are auto-resolved immediately. A numeric seed makes equivalent campaign states reproducible in tests and debugging.

## Command line

```powershell
gates-of-codex supply-status campaign.json
gates-of-codex supply-status campaign.json --faction nato --refresh
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7 --advance-turn
```

`--advance-turn` is accepted only when the selected AI faction is the campaign's current faction.

## Frontend contract

Frontend schema version 2 adds:

- faction supply reach counts
- province supply-source faction tags
- formation `is_in_supply`
- formation `encircled_turns`

The Godot frontend can display these values without duplicating route calculations.
