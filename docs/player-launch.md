# Player launch and continuation shell

`gates-of-codex play` is the single player-facing entry point. It replaces the
developer sequence of `new` → `export-frontend` → manual Godot launch → manual
snapshot replacement.

```powershell
gates-of-codex play --new --stack-config config\mod-stack.windows.json
gates-of-codex play --continue
```

## What one player action does

1. Validates the intended active mod stack.
2. Resolves (and creates) a predictable campaign directory.
3. For `--new`, builds the authoritative `earth3_v1` campaign on
   `earth3_europe_mediterranean`.
4. Persists the single authoritative Python campaign save.
5. Generates the Godot frontend snapshot from that campaign.
6. Clears any stale command queue left by an interrupted session.
7. Launches the Godot strategic application against the generated snapshot.
8. Records the campaign as the remembered campaign for `--continue`.

## Options

| Option | Meaning |
| --- | --- |
| `--new` / `--continue` | Required, mutually exclusive |
| `--campaign <path>` | Campaign directory or campaign `.json` file |
| `--faction <id>` | `nato`, `ukr`, `rusa`, `prc` (Earth3 is fixed to `nato`) |
| `--difficulty <id>` | `easy`, `normal`, `hard` — recorded on the campaign |
| `--fog-of-war on\|off` | Defaults to `off` for initial playable campaigns |
| `--stack-config <path>` | Validated active mod-stack config |
| `--game <path>` | Gates of Hell install directory |
| `--profile <path>` | Gates of Hell profile directory |
| `--tactical-map <id>` | Preferred tactical map |
| `--scenario <id>` | Defaults to `earth3_v1`; legacy scenarios and the debug `earth3_native_acceptance` fixture must be named |
| `--godot <path>` | Godot 4 executable (or `GATES_OF_CODEX_GODOT`) |
| `--godot-project <path>` | Godot project directory |
| `--force-new` | Replace an existing campaign at the resolved path |
| `--no-launch` | Prepare campaign and snapshot without starting Godot |
| `--json` | Print the machine-readable result |

## Campaign directory

Without `--campaign`, the campaign lives in a predictable per-user location:

- Windows: `%LOCALAPPDATA%\GatesOfCodeX\campaigns\earth3_v1`
- Other platforms: `$XDG_DATA_HOME/gates-of-codex/campaigns/earth3_v1`
- Override both with `GATES_OF_CODEX_HOME`

The directory holds exactly three files:

| File | Role |
| --- | --- |
| `campaign.json` | The single authoritative campaign state |
| `campaign_snapshot.json` | Derived presentation/input state for Godot |
| `frontend_commands.json` | Godot's command inbox |

`<player home>/last_campaign.json` remembers the most recent campaign so
`--continue` works with no arguments. It holds a path only, never game state.

## Authority rules

- The Python campaign file is the only authoritative campaign state. The Godot
  snapshot is always regenerated from it and is never read back as authority.
  Continue Campaign reopens the campaign; it never derives one from a snapshot.
- Production never falls back to a GoE-derived map. Legacy scenarios require an
  explicit `--scenario legacy_goe_europe` (or
  `legacy_goe_europe_mediterranean`).
- Missing or mismatched Earth3 assets, an invalid stack config, or a
  non-existent `--game`/`--profile` directory fail with an actionable error
  instead of being replaced by a discovered substitute.

## Command safety

Every mutation issued by the Godot shell carries a `command_id`. The backend
keeps a bounded ledger of accepted ids on the campaign itself, so:

- a legal command applies exactly once;
- a replayed id is recognised and ignored;
- a rejected command leaves the campaign and the published snapshot byte-identical
  to the last accepted state — an earlier success in the same batch is discarded
  with it;
- `handoff` and `import_battle` commit through their own service transaction and
  therefore may not share a batch with other commands;
- the campaign is committed atomically before the snapshot is published, so an
  interrupted run leaves the previously accepted snapshot in place. Continue
  Campaign (or Refresh) regenerates it from accepted campaign state.

## In the Godot strategic application

The command panel shows the application name and version, the scenario, the
current strategic turn, the save path, and the selected/current faction. New
Campaign and Continue Campaign are player actions in the panel; New Campaign
replaces authoritative state and requires a confirming second press. Controls
that cause authoritative mutation disable themselves while a mutation is in
flight.
