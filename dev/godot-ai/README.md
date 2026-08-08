# Godot AI development integration

This integration gives approved MCP clients direct access to the live Gates of CodeX Godot editor for scene inspection, UI work, play-test input, screenshots, logs, and Godot-side tests.

It is development tooling only. It is not gameplay AI, campaign logic, a Gates of Hell integration layer, or part of the Workshop payload.

## Pinned dependency

The approved source is recorded in `lock.json`:

- repository: `hi-godot/godot-ai`
- version: `3.1.3`
- commit: `22678e5f9b038d7203d6b43b0aae20a5417c500e`

The setup script fetches that exact Git commit and copies only `plugin/addons/godot_ai` into the ignored local path `godot/addons/godot_ai`.

Do not use the plugin self-updater. Dependency updates must change `lock.json` in a reviewed PR and repeat the integration smoke checks.

## Install

From the repository root in PowerShell:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\dev\godot-ai\setup.ps1
```

The script:

1. reads the reviewed lock file;
2. fetches the exact pinned commit with Git;
3. verifies the checked-out commit and plugin version;
4. installs the addon under the ignored Godot addon path;
5. records the local installation under ignored `.godot-ai/` state;
6. warns when `uv` or `uvx` is unavailable.

Install `uv` before configuring an MCP client if the script reports it missing.

## Open the editor privately

Use the launcher so both the plugin-managed server and client-owned attach bridge inherit the telemetry opt-out:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\dev\godot-ai\open-editor.ps1 `
  -GodotPath "C:\path\to\Godot_v4.7-stable_win64.exe"
```

`-GodotPath` can be omitted when `godot`, `godot4`, or `GOC_GODOT` resolves the executable.

On first use:

1. Open **Project > Project Settings > Plugins**.
2. Enable **Godot AI**.
3. Open the Godot AI dock.
4. Configure **Grok Build**, Codex, Claude Code, or another approved MCP client.
5. Confirm the client targets the Gates of CodeX editor session before any write.

The plugin enablement remains a normal local Godot project preference. The addon itself and its runtime state are ignored by Git.

## Approved Gates workflows

Good uses include:

- inspect the current scene and node hierarchy;
- create or refactor scene-based HUD and management controls;
- run the strategic frontend and inject deterministic input sequences;
- capture the editor viewport or running game framebuffer;
- inspect editor, parser, and game logs;
- inspect runtime nodes and UI elements;
- run project-owned Godot test suites;
- produce screenshots and diagnostics for PR review;
- repeat map fitting, zooming, province-selection, and formation-panel smoke paths.

The custom Earth3 renderer, campaign authority, map geometry, Python backend, and Gates of Hell handoff remain owned by the existing repository code and test contracts.

## Agent rules

Every implementation agent using Godot AI must:

1. work in a dedicated branch or worktree;
2. activate the correct Gates editor session before writes;
3. inspect Git status and diff before and after editor mutations;
4. avoid broad scene rewrites when a narrow change is sufficient;
5. treat an interrupted or transport-unknown mutation as unknown, not failed;
6. never retry an unknown mutation without inspecting the resulting project state;
7. run the existing Python and Godot checks relevant to the changed area;
8. provide screenshots and logs as evidence, not as a substitute for tests;
9. keep the PR draft until independent review is complete;
10. never enable LAN access or persistent off-editor server lifetime for routine work.

## Workshop and release boundary

Everything under `dev/` is excluded from `tools/deploy_workshop_test.ps1`. The local addon path is ignored and therefore cannot be copied by the tracked-file deployment manifest.

The shipped game and Workshop item must not contain:

- `dev/godot-ai/`;
- `.godot-ai/`;
- `godot/addons/godot_ai/`;
- Godot AI client configuration;
- Godot AI telemetry or runtime state.

## Remove or reset

Remove the installed addon:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\dev\godot-ai\setup.ps1 `
  -Remove
```

Remove both the addon and cached pinned checkout:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\dev\godot-ai\setup.ps1 `
  -Remove `
  -Clean
```

Use `-Clean` without `-Remove` to force a fresh exact-commit fetch and reinstall.

## Required integration smoke

Before accepting a dependency update, verify on Windows with Godot 4.7:

1. setup completes from a clean checkout;
2. the installed `plugin.cfg` reports the locked version;
3. the editor opens through `open-editor.ps1`;
4. the plugin connects to the intended Gates session;
5. the approved MCP client can read editor state and scene hierarchy;
6. the client can run and stop `godot/main.tscn`;
7. keyboard or action input can fit the map and select a province;
8. editor and game screenshots return successfully;
9. editor and game logs are readable;
10. no addon or `dev/` files appear in a Workshop deployment dry run;
11. the normal repository test suite remains green.
