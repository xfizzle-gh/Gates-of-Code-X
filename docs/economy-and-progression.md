# Economy and progression

## Purpose

The economy layer converts the installed Code:X catalog into persistent strategic progression without copying a fixed private roster into Gates of CodeX.

## Catalog-derived unit economy

Every scanned Code:X unit receives persistent campaign metadata:

- strategic faction
- category
- purchase cost
- recurring maintenance cost
- repair cost per condition point
- required research keys
- doctrine identifier
- manpower estimate

Purchase values are deterministic estimates derived from the unit category, squad manpower, vehicle count, and Code:X doctrine-cost metadata. They are campaign balance values, not claims about native Code:X skirmish prices.

## Research

Each faction receives a catalog-derived research graph.

Core infantry is available at campaign start. Other categories use these prerequisite chains:

- Recon requires Core Forces.
- Vehicles require Core Forces.
- IFVs require Vehicles.
- Tanks require IFVs.
- Artillery requires Core Forces.
- Air defense requires Core Forces.

Code:X doctrine-tagged units also require a doctrine research node generated from their Lua metadata. Research is paid from the owning faction's resources and remains separate between coalition allies.

Starter formations may possess equipment beyond the currently completed research graph. This represents deployed starting equipment. New purchases and casualty replacements for that equipment remain subject to the faction's research state.

## Formation recruitment pools

A formation's pool is restricted by:

- its strategic faction
- its preferred categories
- basic infantry availability
- completed category and doctrine research

The formation layer therefore creates different purchasing identities for armored, airborne, mechanized, artillery-support, naval-infantry, and expeditionary formations while continuing to use Code:X as the authoritative unit source.

## Reinforcement reserve

Purchased units enter a persistent faction reinforcement reserve assigned to a specific formation. They are not added directly to the tactical roster.

Assigning a reserve unit follows this order:

1. Fill losses below the formation's authorized strength.
2. Use any remaining quantity to expand authorized strength.

This allows the same system to represent casualty replacement and long-term formation growth.

## Condition and repairs

Every battalion has condition from 0 to 100.

Combat reduces condition in addition to removing units. Condition affects auto-resolve strength. A formation at 20 condition or below cannot move until repaired.

Repairs require:

- at least 50 supply
- no active encirclement
- sufficient faction resources

Repair costs scale with the current roster and each unit's catalog-derived repair value.

## Income and maintenance

At the end of a complete four-faction round:

1. Each faction receives resource income from provinces it directly controls.
2. Maintenance is calculated from every active unit in that faction's formations.
3. Maintenance is deducted from faction resources.
4. A maintenance shortfall reduces formation condition.
5. Supply and action points refresh for the next round.

Coalition allies retain separate resources, research, reinforcement reserves, and maintenance obligations.

## Strategic AI

Before movement, a non-player faction deterministically attempts to:

1. purchase an available research node
2. repair its weakest damaged supplied formation
3. recruit and assign one unlocked unit to its weakest formation
4. execute strategic movement and attacks

The behavior is intentionally deterministic for repeatable tests and saved-campaign debugging. More sophisticated doctrine and theater priorities remain a later balance pass.

## Frontend contract

Frontend schema version 3 exposes:

- faction resources, last-round income, and maintenance
- completed and available research
- persistent reinforcement reserves
- all research nodes
- formation recruitment offers and lock reasons
- current and authorized rosters
- replacement deficits
- formation condition and repair requirements

Godot remains a presentation client. Python remains authoritative for validation, spending, research, recruitment, assignment, and repair mutations.
