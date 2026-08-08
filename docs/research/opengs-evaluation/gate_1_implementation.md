# OpenGS Gate 1 deterministic headless generator

Issue: #132  
Parent: #130  
Dependency: Gate 0 / #131

## Scope

Gate 1 creates a deterministic, PyQt-free research generator derived from the pinned OpenGS Map Tool generation approach. It does not create Gates polygon geometry, register a Godot map, replace Earth3, or begin Gate 2.

## Commands

```text
python tools/opengs_eval/gate1_generator.py validate-recipe <recipe.json>
python tools/opengs_eval/gate1_generator.py generate <recipe.json> --output <new-directory>
python tools/opengs_eval/gate1_generator.py inspect-output <directory>
python tools/opengs_eval/gate1_generator.py compare-runs <left> <right>
python tools/opengs_eval/gate1_generator.py benchmark <recipe.json> --output <new-directory> --repetitions 3
```

Generation and benchmark destinations must not already exist. Output is built and validated in a temporary sibling directory, then atomically renamed into place. Failures remove the staging directory and never mix new files with an earlier successful run.

## Determinism contract

- A root seed is mandatory.
- Every stochastic stage receives a named derived 64-bit seed.
- Initial sampling, Lloyd sampling, Lloyd empty-cell replacement, and jagged noise use separate streams.
- Lloyd streams are additionally named per connected component, so sampling consumption cannot perturb empty-cell replacement.
- Every non-empty connected component receives a seed, and impossible count requests fail before publication.
- Iteration order is explicitly stabilized where dictionaries, region IDs, components, and allocations affect output.
- Allocation uses deterministic largest-remainder logic and must exactly satisfy requested land/ocean territory and province counts.
- Nearest-seed queries apply a stable sub-pixel index tie-break and use one worker.
- Region colors come from SHA-256, not implicit randomness.
- JSON is canonical UTF-8/LF with sorted keys and fixed separators.
- PNGs contain no timestamps or ancillary metadata and use a fixed stored-deflate writer.
- Input checksums and path containment fail closed.
- Every authoritative data output receives a SHA-256 entry in the run manifest.

## Recipe authority

The version 1 recipe has a strict, closed shape. Runtime validation is an exact stdlib implementation of the committed schema contract and rejects:

- unknown fields;
- missing nullable fields such as `inputs.terrain`;
- booleans used as integers or numbers;
- wrong object/container types;
- absolute or escaping paths;
- invalid SHA-256 values;
- unsupported or impossible requested counts.

The authoritative recipe identity is the SHA-256 of canonical parsed recipe JSON, not the source file's whitespace or line endings. Semantically identical LF, CRLF, compact, and pretty-printed recipes therefore produce byte-identical authoritative outputs.

## Output and manifest authority

The authoritative byte comparison covers:

- `territories.png`
- `provinces.png`
- `territories.json`
- `provinces.json`
- `run_manifest.json`

The strict run manifest records:

- pinned upstream repository and commit;
- canonical recipe identity;
- exact input paths and checksums;
- every named derived seed;
- requested and actual counts;
- dimensions and output checksums;
- canonical generator-source hashes;
- Python, NumPy, Pillow, and SciPy versions;
- deterministic serialization and transactional-publication flags.

`inspect-output` validates the complete closed manifest shape, count consistency, paired Lloyd streams, source identity, payload checksum, exact output set, file checksums, and canonical JSON bytes. Recomputing a payload hash cannot make a structurally incomplete or provenance-invalid manifest pass.

## Upstream boundary

Pinned upstream:

```text
Thomas-Holtvedt/opengs-maptool
06e7ec8517bd45872cf44d77cb8784e5ffca49bb
version 0.3
MIT
```

`gate1_upstream_modules.json` maps each verified upstream Git blob to the actual adapted destination modules and records canonical UTF-8/LF SHA-256 hashes for those destination files. The MIT notice remains in `tools/opengs_eval/LICENSE.opengs-maptool`.

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

## Test and CI proof

A stdlib-only AST dependency-closure test remains active in normal repository CI even when optional numerical dependencies are absent. It scans every reachable Gate 1 module and rejects GUI/runtime imports, forbidden runtime names, and `default_rng` calls without explicit seeds.

The dedicated workflow installs pinned numerical dependencies on Linux and Windows and proves:

1. strict malformed-recipe rejection;
2. independent Lloyd sampling and empty-replacement streams;
3. impossible-count and empty-mask rejection;
4. failure-atomic output publication;
5. complete malformed-manifest rejection;
6. semantic recipe-formatting parity;
7. two independent byte-identical generations per operating system;
8. three repeated identical benchmark outputs per operating system;
9. Linux-to-Windows byte parity across every authoritative artifact.

## Gate 1 exit

Gate 1 is complete only when all dedicated and repository-wide checks are green, the independent reviewer has re-audited the latest head, and the owner approves the gate. Stop before Gate 2 / #133.
