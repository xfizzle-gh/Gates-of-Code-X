# Actor-scoped rosters, research, and economy

This layer makes the compiled national rosters operational inside a campaign.

It is installed explicitly from a live `gates-of-codex-factions` output. The repository does not bundle Code:X or West81 source data.

## Install flow

First compile the current installed mod stack:

```powershell
gates-of-codex-factions `
  --stack-config .\config\mod-stack.windows.json `
  --output .\docs\audits\resolved-factions.live.json `
  --summary .\docs\audits\resolved-factions.live.md
```

Then install the actor catalog and resolved content into a campaign:

```powershell
gates-of-codex-actor-economy install `
  .\campaign.json `
  .\docs\audits\resolved-factions.live.json `
  --actor fra
```

Installation requires:

- the resolved-faction schema from the committed compiler
- exactly the same actor set as the strategic actor runtime
- zero resolution errors
- zero warnings unless `--allow-warnings` is explicitly supplied
- actor-scoped, acyclic research
- materializable units only
- tactical sides restricted to `nato`, `ukr`, `rusa`, and `prc`

## Actor isolation

Two countries may export through the same tactical side while remaining economically and technologically separate.

Examples:

```text
France  -> nato
Germany -> nato

Russia      -> rusa
North Korea -> rusa
Belarus     -> rusa
Donbas      -> rusa
Serbia      -> rusa
```

Recruitment is authorized by `StrategicFormation.actor_id`, not only by tactical faction. A French formation cannot recruit a German unit unless that unit is also present in France's compiled roster.

## Research

Resolved research is converted into actor-scoped strategic research.

```text
strategic cost = max(50, source cost * 50)
root cost      = 0
```

The multiplier preserves relative Code:X progression while converting small tactical research values into the campaign resource scale.

Existing battalion units are handled conservatively during installation:

- if the unit belongs to the actor roster, its cheapest research path and prerequisites are granted
- if the unit is outside the actor roster, it is retained as grandfathered equipment
- every grandfathered unit is recorded under `migration_exceptions`
- grandfathered units cannot be newly recruited unless later added to the actor roster

## Unit economy

Strategic purchase cost is derived deterministically from:

- category base cost
- manpower estimate from squad members
- referenced vehicle count
- tier
- source research cost

Maintenance is 3.5 percent of purchase cost, rounded upward. Repair cost per condition point is 0.25 percent of purchase cost, rounded upward.

These are Gates strategic costs. They do not overwrite Code:X unit costs, research values, or asset definitions.

## Reinforcements

Actor purchases use an actor-scoped reinforcement pool stored under:

```text
map_metadata.actor_content_runtime.reinforcement_pool
```

The pool key is:

```text
actor_id + strategic_formation_id + unit_name
```

It does not use the legacy tactical-faction reinforcement pool because countries sharing `nato` or `rusa` must not share purchased units.

Commands:

```powershell
gates-of-codex-actor-economy research-list campaign.json --actor fra

gates-of-codex-actor-economy research-buy campaign.json `
  --actor fra `
  --key actor:fra:generated:unit:leclerc

gates-of-codex-actor-economy offers campaign.json `
  --formation sf-example

gates-of-codex-actor-economy buy campaign.json `
  --formation sf-example `
  --unit leclerc `
  --quantity 1

gates-of-codex-actor-economy assign campaign.json `
  --formation sf-example `
  --battalion battalion-example `
  --unit leclerc `
  --quantity 1
```

## Round economy

Actor income is derived only from provinces with an explicit matching:

```text
province.metadata.owner_actor_id
```

Unassigned provinces do not silently pay every country that shares their tactical side. This prevents NATO-wide or RUSA-wide treasury duplication before final national province ownership is authored.

Maintenance is charged to the actor owning each strategic formation. A maintenance shortfall applies the existing five-point battalion condition penalty.

## Backward compatibility

Legacy campaigns and the four-faction economy remain unchanged until actor content is explicitly installed. Normal force migration does not create actor content or change unrelated save bytes.
