# Earth3 P2 Campaign Bootstrap Implementation Plan

> **Execution constraint:** Author tests before production changes, but do not
> execute tests or any CI, lint, type, compile, Godot, build, packaging, or smoke
> command. Verification in this branch is static inspection only by owner order.

**Goal:** Build a deterministic, actor-scoped Earth3 opening campaign from a
strict fixed data bundle and an injected active catalog while preserving P1 map
authority and leaving movement unavailable until P3.

**Architecture:** `earth3_bootstrap.py` loads and validates an exact-byte JSON
bundle, calls the unchanged P1 builder, materializes actor-scoped forces through
the existing faction-wiring compiler/content installer, and applies a bounded
scenario overlay. Immutable bundle/catalog/footprint provenance is persisted;
mutable campaign state is never regenerated on load.

**Tech stack:** Python dataclasses and JSON, existing Earth3 authority loader,
faction wiring compiler, strategic actor runtime, state serialization, unittest
test suite (authored only).

---

## Task 1: Author the P2 contract tests

**Files:**
- Create: `tests/test_p2_earth3_campaign_bootstrap.py`
- Modify: `tests/test_s11_cli.py`

1. Add fixture helpers that copy only fixed P2 data and P1 authority into a
   temporary root, create a deterministic resolved actor catalog, and patch
   loader seams without invoking the real game stack.
2. Author the required adversarial groups for default selection, legacy
   isolation, evidence-backed mappings, exact bytes, duplicate keys, containment,
   symlink/reparse/path substitution, schema strictness, no geometry/routes,
   actor aliases/canonical IDs, roster materialization, actor ownership, alliance
   membership, PRC dormancy, ownership, formations/battalions/commanders,
   resources/research/recruitment, sites/supply intent, objectives, deployment,
   tactical preference, footprint enforcement, no movement fallback,
   deterministic identities, round trip, evolved saves, missing stack, and
   atomic CLI publication.
3. Update generic CLI tests to choose legacy scenarios explicitly; add P2 CLI
   construction tests with an injected stack compiler seam.
4. Do not run the tests.

## Task 2: Add separated exact-byte scenario data

**Files:**
- Create: `src/gates_of_codex/data/earth3_v1/bootstrap.json`
- Create: `src/gates_of_codex/data/earth3_v1/province_mappings.json`
- Create: `src/gates_of_codex/data/earth3_v1/factions.json`
- Create: `src/gates_of_codex/data/earth3_v1/alliances.json`
- Create: `src/gates_of_codex/data/earth3_v1/ownership.json`
- Create: `src/gates_of_codex/data/earth3_v1/formations.json`
- Create: `src/gates_of_codex/data/earth3_v1/commanders.json`
- Create: `src/gates_of_codex/data/earth3_v1/sites.json`
- Create: `src/gates_of_codex/data/earth3_v1/objectives.json`
- Create: `src/gates_of_codex/data/earth3_v1/deployment_zones.json`
- Create: `src/gates_of_codex/data/earth3_v1/tactical_maps.json`
- Modify: `.gitattributes`
- Modify: `pyproject.toml`

1. Record every city mapping as an exact join between
   `earth3.locations.REQUIRED_LOCATIONS` source ID and the frozen production
   dataset row's `source_id`/stable `id`; exclude any mapping that fails.
2. Declare only scenario state and intent. Forbid geometry, adjacency, route,
   operational-node, and P1 authority override fields.
3. Keep formations actor-scoped using manifest-canonical IDs (`usa`, `deu`,
   `pol`, `ukr`, `rus`) and document the corresponding Germany, Poland,
   Ukraine, and Russia manifest actors.
4. Give every fixed file an LF checkout policy and include nested package data.
5. Derive and pin exact raw SHA-256 values after content is final; derive a
   separate canonical logical bundle digest.

## Task 3: Implement the strict bundle loader and immutable provenance

**Files:**
- Create: `src/gates_of_codex/earth3_bootstrap.py`

1. Implement one-capture fixed-file reads with canonical-root containment,
   regular-file and symlink/reparse rejection, pre/post identity checks, strict
   UTF-8, duplicate-key rejection, and exact approved raw digest matching.
2. Enforce exact file schemas and reject unknown fields, geometry-shaped keys,
   routes, adjacency, and operational nodes at any depth.
3. Load P1 authority independently and validate the mapping evidence chain,
   selectable-land footprint, uniqueness, cross-file references, and opening
   objective incompleteness.
4. Compute raw-file, logical-bundle, and footprint identities and expose a
   frozen bundle record to the builder.
5. Add a load-time validator that checks only immutable P2 provenance and normal
   state invariants; never reapplies or compares mutable opening state.

## Task 4: Materialize the actor-scoped opening state

**Files:**
- Create: `src/gates_of_codex/earth3_bootstrap.py`
- Modify: `src/gates_of_codex/strategic_actors.py` only if a narrow public
  canonical-actor helper is required

1. Accept an explicitly injected validated resource stack or compiled catalog;
   fail when neither is supplied.
2. Compile through `FactionWiringCompiler` when roots are provided. Validate
   required canonical actors and materializable categories.
3. Derive catalog provenance from canonical actor/unit/research content while
   excluding absolute source paths. Persist enough logical layer identity to
   distinguish changed content without requiring original paths later.
4. Build the P1 skeleton, install existing actor content with selected actor
   `usa`, then create actor-owned TOE templates, strategic formations,
   battalions, fictional role commanders, ownership, resources, research,
   deployment, sites, objectives, and tactical preferences.
5. Keep inherited PRC content dormant and assign no P2-specific state to it.
6. Validate the complete opening state before returning it.

## Task 5: Integrate default construction and narrow stack injection

**Files:**
- Modify: `src/gates_of_codex/scenario.py`
- Modify: `src/gates_of_codex/cli.py`

1. Route only `earth3_v1` to the P2 builder; retain both legacy builder paths and
   exact map identities.
2. Add only the construction dependency needed to pass `--stack-config` into the
   Earth3 builder. Do not add play/continue/launcher/profile/game discovery.
3. Preserve atomic save publication: all bundle, stack, roster, and campaign
   validation completes before `save_campaign` replaces the destination.

## Task 6: Enforce the scenario footprint and P3 movement boundary

**Files:**
- Modify: `src/gates_of_codex/campaign.py`
- Modify: `src/gates_of_codex/strategic.py`
- Modify: `src/gates_of_codex/play_context.py`
- Modify: `src/gates_of_codex/frontend_commands.py` if it has direct mutation
  paths
- Modify: `src/gates_of_codex/frontend.py` only for existing actionability fields,
  not presentation redesign

1. Add a small shared predicate in `earth3_bootstrap.py` for P2 footprint and
   movement authority.
2. Reject Earth3 P2 movement/attack before polygon-neighbor fallback and return
   no legal movement options while routes are intentionally absent.
3. Reject outside-footprint deployment, construction, objective, ownership,
   formation, supply-site, and control-site mutations through existing command
   seams.
4. Preserve production selectability unchanged; expose scenario actionability as
   separate metadata only.

## Task 7: Static review and publication

**Files:**
- Modify: draft PR body and issue #176 comment through GitHub CLI/API

1. Inspect the full base-to-head diff and changed-file list.
2. Compare frozen Earth3 file blobs at base and head; confirm no geometry,
   dataset, manifest, metadata, stable-ID, hash, classification, topology, or
   policy change.
3. Search the P2 data and production diff for forbidden route/adjacency/geometry
   authority, P3+, P4+, S11 PR C, #141, and #166 scope.
4. Review every test and production change statically. Do not execute or inspect
   any test, workflow, CI, lint, type, compile, Godot, build, packaging, or smoke
   command.
5. Commit intentionally, push `feat/p0-p2-earth3-campaign-bootstrap`, create one
   draft unmerged PR, comment on issue #176, and stop before P3.
