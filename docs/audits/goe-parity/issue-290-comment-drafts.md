# Paste-ready #290 comments

Historical paste-ready drafts from the audit session (files were local-only at draft time). The six files in this directory are now the committed audit artifacts. Inner START/COMPLETION text is unchanged.

This environment cannot POST issue comments (GitHub 403: personal access token / integration lacks `issues: write`). Paste these onto https://github.com/xfizzle-gh/Gates-of-Code-X/issues/290 if desired.

No implementation PR was opened during the audit session.

---

## START (Phase 0)

```markdown
## Phase 0 START — audit-only freeze

This is an **audit/reconciliation session only**. No implementation PR is being opened. No parked PRs (#274, #208, #165, #158, #154, #63, #54) will be reopened. P11 / morale / #273 Phase B–C / #185 production work will not be resumed.

### Exact main SHA

e830d694d68325b3764fc2c20ede3c40400ab6f0

Verified after `git fetch origin main`. Local HEAD equals origin/main.

### Local repository path

this checkout (cloud-agent workspace root; machine-specific absolute path omitted)

Linux cloud-agent checkout. `AGENTS.md` is not present at repository root. Nested skills used: `.agents/skills/`.

### Active feature PRs

None open.

### GoE source found (preliminary; completed inventory in local audit files)

No Windows E:/C: Steam tree, no installed Gates of Europa, no Gates of Hell, no Workshop mounts.

Repository contains derived geography extracts only (517-graph, marker/IdColor, color-ID textures) plus GitHub issue UI descriptions. Collaborator #65 building tables are not GoE source.

Audit artifacts are local under `docs/audits/goe-parity/` and were not pushed.
```

---

## COMPLETION

```markdown
## Audit complete — stop for owner review

Exact main: `e830d694d68325b3764fc2c20ede3c40400ab6f0`  
Local repo: this checkout  
Audit-only. No implementation PR. Parked PRs not reopened.

### Source inventory

GoE **geography extracts only**. Missing on this machine: live GoE, Steam/Workshop, research trees, economy tables, recruitment/TOE, buildings from GoE, saves. Do not guess those loops.

Local: `docs/audits/goe-parity/goe-source-inventory.md`

### KEEP / REWORK / REPLACE (summary)

- KEEP: Earth3, actor-identity architecture, save/load, Auto-Resolve, Godot shell, GoH bridge, catalog compiler, operational movement, Core P9 pack, bounded Forward Depot.
- KEEP_AND_POLISH: Godot UX, battalion presentation, Continue, AI same-verbs.
- REWORK: research/economy/recruit **player contract** (Core `nato` vs `usa`/`pol` treasuries), dual supply, force/repair/refresh latency class.
- REPLACE: nothing as a repo rewrite.
- NOT_BUILT: GoE-parity research/economy (source missing), #65 city-builder as next plan, merge/split, #46 unit-pools artifacts, P11.
- INTENTIONALLY_DIFFERENT: Earth3 vs GoE 517 map; national actors; Auto-Resolve-only campaigns; Code:X/West81 content.

Full matrix: `docs/audits/goe-parity/goe-parity-matrix.md`  
Machine JSON: `docs/audits/goe-parity/goe-parity-machine.json`

### Latency

Godot input→visible: UNKNOWN (no Godot).  
Warm move+commit: 923 ms. Force panel one-shot: 2.6 s. Research/recruit: fail after ~5 s load (`nato` vs `usa` keys). Repair/refresh: ~48 s full snapshot on this VM.  
#266 1.0–1.6 s table does not cover the everyday force loop.

`docs/audits/goe-parity/current-main-latency.md`

### First vertical slice

Instant verbs + one treasury + real earn/spend + one unlock → recruit → assign → move → End Turn → Auto-Resolve on production Earth3 Core. Not #65, not P11, not a map rewrite.

### Unresolved owner decisions

GoE source mount; Core command vs economy actor; week-turn confirmation; income before GoE files; whether Code:X trees are v1 research; #65 parked; later #46 audit-tool PR; commit of these files; owner-Windows Godot timings; P11 stay parked.

Stop. Do not implement until review.
```
