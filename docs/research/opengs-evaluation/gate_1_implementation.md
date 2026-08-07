# OpenGS Gate 1 deterministic headless generator

Issue: #132  
Parent: #130  
Dependency: Gate 0 / #131

## Scope

Gate 1 creates a deterministic, PyQt-free research generator derived from the pinned OpenGS Map Tool generation approach. It does not create Gates polygon geometry, register a Godot map, replace Earth3, or begin Gate 2.

## Commands

```text
python tools/opengs_eval/gate1_generator.py validate-recipe <recipe.json>
python tools/opengs_eval/gate1_generator.py generate <recipe.json> --output <directory>
python tools/opengs_eval/gate1_generator.py inspect-output <directory>
python tools/opengs_eval/gate1_generator.py compare-runs <left> <right>
python tools/opengs_eval/gate1_generator.py benchmark <recipe.json> --output <directory> --repetitions 3
```

## Determinism contract

- A root seed is mandatory.
- Every stochastic stage receives a named derived 64-bit seed.
- Territory and province sampling, Lloyd sampling, empty-cell replacement, and jagged noise have separate seed names.
- Iteration order is explicitly sorted where dictionaries, region IDs, components, and allocations affect output.
- Allocation uses deterministic largest-remainder logic.
- Nearest-seed queries apply a stable sub-pixel index tie-break and use one worker.
- Region colors come from SHA-256, not an implicit random generator.
- JSON is canonical UTF-8 with sorted keys and fixed separators.
- PNGs contain no timestamps or ancillary metadata and use fixed compression settings.
- Input checksums fail closed.
- Every output receives a SHA-256 entry in the run manifest.

## Recipe authority

The version 1 recipe records:

- recipe ID;
- explicit root seed;
- relative input paths and SHA-256 hashes;
- requested land and ocean territory/province counts;
- Lloyd iteration count;
- density strength and ocean-density policy;
- land/ocean jagged flags and amplitude.

Paths must remain under the recipe directory. Terrain may be omitted. Terrain classification intentionally remains center-sampled in Gate 1 because full-area terrain coverage belongs to Gate 2.

## Output authority

The authoritative byte comparison covers:

- `territories.png`
- `provinces.png`
- `territories.json`
- `provinces.json`
- `run_manifest.json`

The manifest records the pinned upstream commit, recipe checksum, input checksums, every named derived seed, output counts, dimensions, output checksums, and determinism flags.

## Upstream boundary

Pinned upstream:

```text
Thomas-Holtvedt/opengs-maptool
06e7ec8517bd45872cf44d77cb8784e5ffca49bb
version 0.3
MIT
```

The adapted concepts and exact source Git blob IDs are listed in `gate1_upstream_modules.json`. The existing MIT notice remains in `tools/opengs_eval/LICENSE.opengs-maptool`.

Excluded from Gate 1:

- PyQt and file dialogs;
- OpenGS Godot runtime;
- JFA compute borders;
- runtime map-mode textures;
- runtime labels;
- editor UX integration;
- polygon rings, holes, multipart geometry, triangles, adjacency, borders, anchors, and spatial indexes;
- operational, supply, air, command, political, and ownership regions;
- Earth3 production changes.

## CI proof

The dedicated workflow:

1. creates a checksummed synthetic input set in a clean workspace;
2. validates the recipe;
3. generates two independent outputs on Linux and compares every authoritative byte;
4. repeats the same proof on Windows;
5. uploads one output from each platform;
6. compares Linux output against Windows output byte for byte;
7. runs a three-repetition benchmark and requires identical manifests.

## Gate 1 exit

Gate 1 is complete only when:

- no implicit randomness remains;
- no display-server or GUI dependency exists;
- recipe and run schemas are versioned;
- input validation fails closed;
- two clean workspaces are byte-identical;
- Linux and Windows authoritative outputs are byte-identical;
- Earth3 and the production runtime remain unchanged.

Stop for owner review. Do not begin Gate 2 automatically.
