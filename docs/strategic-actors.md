# Strategic actor runtime

The campaign now distinguishes strategic countries and military actors from the four Code:X tactical export sides.

## Runtime contract

Strategic actor state is persisted under:

```text
map_metadata.strategic_actor_runtime
```

Each actor stores:

- actor ID and display names
- actor type
- strategic coalition
- Code:X tactical side
- optional host actor
- independent-playability flag
- roster classification
- treasury
- researched actor-scoped keys
- human-control and elimination state

The tactical side remains one of:

```text
nato
ukr
rusa
prc
```

Strategic actor IDs are never written to GoH fields that require a tactical side.

## Compatibility migration

Legacy four-faction campaigns are migrated deterministically to compatibility actors:

```text
nato
ukr
rusa
prc
```

No national identity is guessed during legacy migration. The complete audited actor catalog is installed only through an explicit install operation.

The migration is idempotent and records its mode under:

```text
map_metadata.strategic_actor_migration
```

## Installing and selecting actors

List the bundled actors:

```powershell
gates-of-codex-actors list --playable-only
```

Install the catalog into an existing campaign and select France:

```powershell
gates-of-codex-actors install .\campaign.json --actor fra
```

Select North Korea later:

```powershell
gates-of-codex-actors select .\campaign.json --actor dprk
```

France selects the `nato` tactical side. North Korea selects the `rusa` tactical side. Their strategic actor IDs, rosters, research, resources, and ownership identity remain separate.

Print the persisted state:

```powershell
gates-of-codex-actors snapshot .\campaign.json
```

## Ownership

Province strategic ownership is stored as:

```text
province.metadata.owner_actor_id
```

Tactical ownership remains in `province.owner`. The runtime rejects any province whose strategic actor resolves to a different tactical side.

Strategic formations already carry `actor_id`. Migration normalizes legacy formation nation tags through explicit aliases and otherwise falls back to a compatible actor on the same tactical side. It never changes the formation's tactical faction.

## Hosted actors

The bundled catalog validates these host relationships:

```text
ukr_ildu          -> ukr
kpa_expeditionary -> rus
wagner            -> rus
```

Hosted actors must exist, cannot host themselves, and must share their host's strategic coalition.

## Current scope

This slice establishes actor identity, persistence, selection, ownership validation, and backward migration. Actor-specific recruitment/economy consumption and final Europe province assignment are separate stacked slices under #45.
