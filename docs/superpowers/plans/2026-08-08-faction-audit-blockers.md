# Faction Audit Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate issue #150's scanner, effective-definition, PRC provenance, and Windows stack blockers while preserving the 24-actor zero-error/zero-warning activation gate.

**Architecture:** A shared stateful GoH entry scanner feeds both catalog scanners and a typed `EffectiveDefinitionIndex`. The compiler validates typed references and terminal provenance, the PRC manifest separates a labeled West81 reserve branch, and the Windows stack config expands five required environment variables with fail-closed identity/order checks.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `enum`, `pathlib`, `re`, `zipfile`, `json`, and `unittest`; GoH `.set`, `.inc`, `.reg`, `.def`, and ZIP-compatible `.pak` resources.

## Global Constraints

- Starting point is PR #144 head `e17f516a888f6152f0cae922c01ba211db1adb77` on `fix/150-faction-audit-blockers`.
- Do not merge any PR or modify PR #147, PR #149, or the independent audit worktree.
- Do not weaken the zero-error or zero-warning activation gate.
- Do not copy Code:X or West81 assets or definitions into this repository.
- Do not commit any machine-specific stack path, including the current fix worktree path.
- Preserve exact stack order: Vanilla, West81, Code:X, Code:X AI Overhaul, Gates of Code:X.
- Stop and report diagnostics if live compilation is not exactly 24 actors, zero errors, and zero warnings.

## File Structure

- Create `src/gates_of_codex/goh_source.py`: bounded stateful GoH entry/token scanner and structured diagnostics.
- Create `src/gates_of_codex/effective_definitions.py`: typed candidates, references, aliases, precedence, archives, and resolutions.
- Modify `src/gates_of_codex/codex/catalog.py` and `src/gates_of_codex/faction_wiring_scan.py`: consume the shared scanner and retain typed references.
- Modify `src/gates_of_codex/faction_wiring_types.py`: typed references and terminal provenance on `SourceUnit`.
- Modify `src/gates_of_codex/faction_wiring_components.py` and `faction_wiring_compiler.py`: typed asset lookup and modern-only enforcement.
- Modify `src/gates_of_codex/faction_wiring_models.py`, `faction_wiring_manifest.py`, `faction_wiring_actors.py`, and `faction_wiring_report.py`: component policy and visible reserve research branch.
- Modify faction data JSON: exact PRC regular/reserve split.
- Modify `src/gates_of_codex/modstack.py` and `config/mod-stack.windows.json`: environment expansion and fail-closed stack identity.
- Create focused parser/index tests and extend faction/configuration tests.
- Update README and audit/acceptance documentation.

---

### Task 1: Shared stateful GoH source scanner

**Files:**
- Create: `src/gates_of_codex/goh_source.py`
- Create: `tests/test_goh_source_parser.py`

**Interfaces:**
- Produces: `SourceLocation`, `SourceDiagnostic`, `MacroCall`, `SourceEntry`, `SourceScanResult`, and `scan_source_entries(text: str, source: str) -> SourceScanResult`.
- Guarantees: bounded capture, exact line/column, supported GoH comments only, quote-aware balance, and deterministic recovery.

- [ ] **Step 1: Write scanner tests for numbered and block forms**

```python
def test_numbered_and_unnumbered_vehicle_entity_macros_are_tokenized(self):
    result = scan_source_entries(
        '("mixed" side(nato) name(test) vehicle(apc) vehicle1(apc1) vehicle2(apc2) '
        'entity(radar) entity1(radar1))\n',
        "fixture.set",
    )
    self.assertEqual([], result.diagnostics)
    self.assertEqual(
        [("vehicle", "apc"), ("vehicle1", "apc1"), ("vehicle2", "apc2"),
         ("entity", "radar"), ("entity1", "radar1")],
        [(call.name, call.value) for call in result.entries[0].calls if call.family in {"vehicle", "entity"}],
    )

def test_block_vehicle_and_entity_forms_remain_supported(self):
    result = scan_source_entries('{"tank" {vehicle "m1"} {entity "radar"}}\n', "fixture.set")
    self.assertEqual("tank", result.entries[0].name)
    self.assertEqual(["m1", "radar"], [call.value for call in result.entries[0].calls])
```

- [ ] **Step 2: Run the scanner tests and verify RED**

Run: `python -m unittest tests.test_goh_source_parser -v`

Expected: import failure for `gates_of_codex.goh_source`.

- [ ] **Step 3: Implement scanner data types and bounded state machine**

```python
MAX_ENTRY_CHARS = 1_000_000
MAX_NESTING_DEPTH = 256

@dataclass(frozen=True, slots=True)
class SourceLocation:
    source: str
    line: int
    column: int

@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    code: str
    message: str
    location: SourceLocation
    captured: str

@dataclass(frozen=True, slots=True)
class MacroCall:
    name: str
    family: str
    ordinal: int | None
    value: str
    location: SourceLocation

@dataclass(frozen=True, slots=True)
class SourceEntry:
    name: str
    form: str
    macro_kind: str
    raw: str
    location: SourceLocation
    calls: Sequence[MacroCall]

@dataclass(frozen=True, slots=True)
class SourceScanResult:
    entries: Sequence[SourceEntry]
    diagnostics: Sequence[SourceDiagnostic]
```

Implement `scan_source_entries(text: str, source: str) -> SourceScanResult` with character-by-character quote/comment/depth tracking. Treat only `;` and `//` outside quotes as comments. Recognize a proven top-level `{` block or `("macro_kind"` macro start, then recover at the next proven start after malformed input.

- [ ] **Step 4: Add multiline, comments, quotes, and recovery tests**

```python
def test_multiline_name_and_nested_syntax_are_captured(self):
    text = '''("squad_with2types_conquest" side(rusa)\n
name(kor_inf_rifle) ; current GoH comment\n
c1(kor_lead:1) c2(kor_rifle:7) note("ignore ( { )"))\n'''
    entry = scan_source_entries(text, "units_rusa.set").entries[0]
    self.assertEqual("kor_inf_rifle", entry.name)
    self.assertEqual(1, entry.location.line)

def test_unterminated_entry_recovers_without_swallowing_next_definition(self):
    text = '("broken" name(broken) vehicle(x)\n{"valid" {vehicle "valid_entity"}}\n'
    result = scan_source_entries(text, "broken.set")
    self.assertEqual("unterminated_entry", result.diagnostics[0].code)
    self.assertEqual((2, 1), (result.entries[-1].location.line, result.entries[-1].location.column))
    self.assertEqual("valid", result.entries[-1].name)
```

- [ ] **Step 5: Run scanner tests and verify GREEN**

Run: `python -m unittest tests.test_goh_source_parser -v`

Expected: all parser tests pass with deterministic diagnostics.

- [ ] **Step 6: Commit scanner**

```powershell
git add src/gates_of_codex/goh_source.py tests/test_goh_source_parser.py
git commit -m "feat(factions): add stateful GoH source scanner"
```

---

### Task 2: Integrate the shared scanner into both unit catalogs

**Files:**
- Modify: `src/gates_of_codex/codex/catalog.py`
- Modify: `src/gates_of_codex/faction_wiring_scan.py`
- Modify: `src/gates_of_codex/faction_wiring_types.py`
- Modify: `tests/test_goh_macro_catalog.py`
- Modify: `tests/test_faction_wiring.py`

**Interfaces:**
- Consumes: `scan_source_entries` and parsed `MacroCall` tokens from Task 1.
- Produces: `DefinitionReference` values on every `SourceUnit` and correct multiline/numbered compositions.

- [ ] **Step 1: Add failing catalog tests for numbered and multiline macros**

```python
def test_numbered_vehicle_and_entity_macros_do_not_infer_the_squad_name(self):
    self._write_source(
        '("recon" side(nato) name(recon_mix) crew1(driver:1) '
        'vehicle1(apc_one) vehicle2(apc_two) entity1(sensor_one))\n'
    )
    unit = CodeXCatalogScanner().scan(self.root).units["recon_mix"]
    self.assertEqual(["apc_one", "apc_two", "sensor_one"], unit.vehicles)
    self.assertNotIn("recon_mix", unit.vehicles)

def test_multiline_name_continuation_retains_members(self):
    self._write_source('(\"squad_with2types_conquest\" side(rusa)\nname(kor_inf_rifle)\nc1(lead:1) c2(rifle:7))\n')
    self.assertEqual({"lead": 1, "rifle": 7}, CodeXCatalogScanner().scan(self.root).units["kor_inf_rifle"].members)
```

- [ ] **Step 2: Run focused catalog tests and verify RED**

Run: `python -m unittest tests.test_goh_macro_catalog tests.test_faction_wiring -v`

Expected: numbered macros infer the squad name and multiline entries lose members.

- [ ] **Step 3: Add typed references to `SourceUnit`**

```python
class ReferenceKind(str, Enum):
    VEHICLE_ENTITY = "vehicle_entity"
    PURCHASE_UNIT = "purchase_unit"
    STRATEGIC_CALL_IN = "strategic_call_in"
    INTERACTION_OBJECT = "interaction_object"

@dataclass(frozen=True, slots=True)
class DefinitionReference:
    identifier: str
    kind: ReferenceKind
    source: str
    line: int
    column: int

@dataclass(slots=True)
class SourceUnit:
    definition_references: list[DefinitionReference] = field(default_factory=list)
```

Update `_copy_unit` and `_merge_unit` to copy/deduplicate these references without serializing them into the existing public unit payload.

- [ ] **Step 4: Replace both duplicated `_source_entries` implementations**

Use `scan_source_entries`, filter macro calls by exact family, and classify vehicle/entity tokens as `VEHICLE_ENTITY` unless the entry's explicit macro kind and action syntax prove `STRATEGIC_CALL_IN`. Preserve existing vehicle-wrapper name inference only when no explicit vehicle/entity macro exists at all.

- [ ] **Step 5: Run catalog and faction tests and verify GREEN**

Run: `python -m unittest tests.test_goh_source_parser tests.test_goh_macro_catalog tests.test_faction_wiring -v`

Expected: all pass; vehicle/entity block support remains green.

- [ ] **Step 6: Commit catalog integration**

```powershell
git add src/gates_of_codex/codex/catalog.py src/gates_of_codex/faction_wiring_scan.py src/gates_of_codex/faction_wiring_types.py tests/test_goh_macro_catalog.py tests/test_faction_wiring.py
git commit -m "fix(factions): parse numbered and multiline source macros"
```

---

### Task 3: Typed effective-definition index with full provenance

**Files:**
- Create: `src/gates_of_codex/effective_definitions.py`
- Create: `tests/test_effective_definition_index.py`

**Interfaces:**
- Consumes: ordered normalized roots, shared source scanner, and `SourceUnitIndex` definitions.
- Produces: `DefinitionKind`, `DefinitionCandidate`, `AliasHop`, `DefinitionResolution`, `DefinitionAmbiguity`, and `EffectiveDefinitionIndex.build(roots).resolve(identifier, reference_kind)`.

- [ ] **Step 1: Write failing tests for kinds and the reference matrix**

```python
def test_call_in_cannot_satisfy_vehicle_lookup(self):
    index = self.index_with_candidate("support_id", DefinitionKind.STRATEGIC_CALL_IN)
    resolution = index.resolve("support_id", ReferenceKind.VEHICLE_ENTITY)
    self.assertFalse(resolution.ok)

def test_vehicle_cannot_satisfy_call_in_lookup(self):
    index = self.index_with_candidate("tank_id", DefinitionKind.VEHICLE_ENTITY)
    resolution = index.resolve("tank_id", ReferenceKind.STRATEGIC_CALL_IN)
    self.assertFalse(resolution.ok)

def test_interaction_reference_alone_does_not_create_candidate(self):
    self.write("layer/resource/set/interaction_entity/test.inc", '{"declared" {spawn "referenced_only"}}\n')
    index = EffectiveDefinitionIndex.build([self.root / "layer"])
    self.assertTrue(index.resolve("declared", ReferenceKind.INTERACTION_OBJECT).ok)
    self.assertFalse(index.resolve("referenced_only", ReferenceKind.INTERACTION_OBJECT).ok)
```

- [ ] **Step 2: Run index tests and verify RED**

Run: `python -m unittest tests.test_effective_definition_index -v`

Expected: import failure for `effective_definitions`.

- [ ] **Step 3: Implement typed candidates and explicit matrix**

```python
class DefinitionKind(str, Enum):
    VEHICLE_ENTITY = "vehicle_entity"
    PURCHASE_UNIT_WRAPPER = "purchase_unit_wrapper"
    STRATEGIC_CALL_IN = "strategic_call_in"
    INTERACTION_OBJECT = "interaction_object"
    REGISTRY_ALIAS = "registry_alias"

REFERENCE_TERMINAL_KINDS = {
    ReferenceKind.VEHICLE_ENTITY: frozenset({DefinitionKind.VEHICLE_ENTITY}),
    ReferenceKind.PURCHASE_UNIT: frozenset({DefinitionKind.PURCHASE_UNIT_WRAPPER}),
    ReferenceKind.STRATEGIC_CALL_IN: frozenset({DefinitionKind.STRATEGIC_CALL_IN}),
    ReferenceKind.INTERACTION_OBJECT: frozenset({DefinitionKind.INTERACTION_OBJECT}),
}

@dataclass(frozen=True, slots=True)
class DefinitionCandidate:
    identifier: str
    kind: DefinitionKind
    layer: str
    priority: int
    path: str
    line: int
    column: int
    packed: bool
    parser_form: str
    source_order: int
    alias_target: str = ""
```

Store candidates by exact identifier and expose immutable candidate chains sorted by explicit layer/origin/location fields for reporting only.

- [ ] **Step 4: Add packed, loose, layer, and same-layer collision tests**

Create ZIP fixtures with `zipfile.ZipFile(archive_path, "w")` containing `entity/test/packed.def`. Assert:

- the proven loose overlay wins a packed collision within one layer;
- identical loose duplicates are retained and deduplicated semantically;
- conflicting loose candidates at the same effective priority are ambiguous;
- a later layer wins over an earlier layer;
- Gates wins over Code:X through layer priority;
- candidate chains remain byte-for-byte stable across two builds.

- [ ] **Step 5: Implement archive and explicit declaration scanners**

Scan, in deterministic layer order:

- `entity/**/*.def` members in every ZIP-compatible `.pak`;
- loose `entity/**/*.def`;
- explicit rows in `set/registry/*.reg`;
- explicit top-level rows in `set/interaction_entity/**/*.inc`;
- explicit inherited/control rows in supported `.set` files;
- purchase-ready unit wrapper rows;
- explicit strategic/off-map declaration shapes.

Do not index body references, spawn targets, include arguments, or arbitrary macro arguments as candidates.

- [ ] **Step 6: Add exact/case/alias tests**

Add these exact test methods, each with a minimal fixture and explicit assertions on status, candidates, and terminal provenance: `test_exact_match_precedes_alias`, `test_explicit_source_case_alias_resolves`, `test_unique_file_stem_alias_is_recorded_as_registry_alias`, `test_ambiguous_case_collision_is_blocking`, `test_unrelated_casefold_lookup_does_not_fallback`, `test_alias_cycle_is_reported`, `test_dangling_alias_is_reported`, `test_alias_depth_is_bounded`, and `test_alias_chain_retains_terminal_provenance`.

- [ ] **Step 7: Implement recursive aliases and terminal provenance**

Resolve exact names first. Materialize case aliases only from explicit source aliases or a unique indexed `.def` file stem referenced by source data. Traverse `REGISTRY_ALIAS` candidates with a visited set and fixed maximum depth. Return both alias declarations and the terminal candidate. Treat multiple case-folded terminals as ambiguity.

- [ ] **Step 8: Run index tests and verify GREEN**

Run: `python -m unittest tests.test_effective_definition_index -v`

Expected: every definition-kind, collision, archive, case, and alias test passes.

- [ ] **Step 9: Commit definition index**

```powershell
git add src/gates_of_codex/effective_definitions.py tests/test_effective_definition_index.py
git commit -m "feat(factions): add typed effective definition index"
```

---

### Task 4: Compiler integration and required/optional severity

**Files:**
- Modify: `src/gates_of_codex/faction_wiring_compiler.py`
- Modify: `src/gates_of_codex/faction_wiring_components.py`
- Modify: `tests/test_faction_wiring.py`

**Interfaces:**
- Consumes: `EffectiveDefinitionIndex`, `DefinitionReference`, and exact reference matrix.
- Produces: typed resolution errors retaining original identifier and candidate chain.

- [ ] **Step 1: Add failing integration tests for all requested outcomes**

Add fixture definitions for a packed inherited entity, explicit interaction object, explicit strategic call-in, and missing ID. Assert:

```python
self.assertEqual(0, required_valid_payload["error_count"])
self.assertEqual(0, required_valid_payload["warning_count"])
self.assertIn("missing vehicle/entity IDs: missing_id", required_missing_payload["problems"][0]["message"])
self.assertEqual("error", required_missing_payload["problems"][0]["severity"])
self.assertEqual("warning", optional_missing_payload["problems"][0]["severity"])
```

- [ ] **Step 2: Run focused compiler tests and verify RED**

Run: `python -m unittest tests.test_faction_wiring -v`

Expected: valid packed/interaction/call-in fixtures are rejected by the old narrow set.

- [ ] **Step 3: Construct and use `EffectiveDefinitionIndex`**

```python
self.definition_index = EffectiveDefinitionIndex.build(self.roots, unit_index=self.unit_index)
```

Replace `_vehicle_exists` with `_definition_problem(reference)`. Resolve the reference's exact `ReferenceKind`; format missing, dangling alias, cycle, wrong-kind, and ambiguity diagnostics with the original spelling and full candidate locations.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_effective_definition_index tests.test_faction_wiring -v`

Expected: all pass; optional and required selector severities remain unchanged.

- [ ] **Step 5: Run the live compiler once as an intermediate diagnostic**

Run with five direct `--stack` arguments and distinct ignored outputs.

Expected intermediate result: 24 actors, scanner/index false positives removed. Record any remaining diagnostics; do not suppress them.

- [ ] **Step 6: Commit compiler integration**

```powershell
git add src/gates_of_codex/faction_wiring_compiler.py src/gates_of_codex/faction_wiring_components.py tests/test_faction_wiring.py
git commit -m "fix(factions): validate typed effective definitions"
```

---

### Task 5: PRC modern-only and labeled legacy reserve branch

**Files:**
- Modify: `src/gates_of_codex/faction_wiring_models.py`
- Modify: `src/gates_of_codex/faction_wiring_manifest.py`
- Modify: `src/gates_of_codex/faction_wiring_components.py`
- Modify: `src/gates_of_codex/faction_wiring_actors.py`
- Modify: `src/gates_of_codex/faction_wiring_report.py`
- Modify: `src/gates_of_codex/data/faction_components.json`
- Modify: `src/gates_of_codex/data/faction_actors.json`
- Modify: `docs/audits/faction-judgment-calls.md`
- Modify: `tests/test_faction_audit_adjustments.py`
- Modify: `tests/test_faction_wiring.py`

**Interfaces:**
- Component fields: `provenance_policy: "modern_only" | "legacy_explicit" | "mixed"` and optional `research_label: str`.
- `_ResolvedComponent` retains policy/label; generated research creates an explicit component root for labeled components.

- [ ] **Step 1: Add failing manifest and provenance tests**

```python
def test_prc_legacy_reserve_contains_exactly_the_audited_rows(self):
    expected = {
        "artillery_barrage_light_prc",
        "artillery_barrage_medium_prc",
        "artillery_barrage_rocket_prc",
        "artillery_barrage_smoke_prc",
        "mortar_barrage_light_prc",
        "mortar_barrage_medium_prc",
        "mortar_barrage_smoke_prc",
        "paradrop_supply_prc",
        "ptl-02",
        "t62_545",
        "type80",
        "ztz852",
        "ztz853",
        "ztz96a",
    }
    manifest = load_faction_manifest()
    reserve = manifest["components"]["prc_legacy_reserve"]
    actual = {unit for selector in reserve["selectors"] for unit in selector["units"]}
    self.assertEqual(expected, actual)
    self.assertEqual("PRC Legacy / Reserve Equipment", reserve["research_label"])

def test_terminal_west81_candidate_cannot_enter_modern_only_component(self):
    payload = self.compile_fixture_with_west81_terminal_in_prc_regular()
    self.assertTrue(any("modern-only" in problem["message"] for problem in payload["problems"]))
```

Implement `compile_fixture_with_west81_terminal_in_prc_regular` in the test class by creating ordered Code:X and West81 fixture roots, selecting a West81-terminal wrapper from a `modern_only` component, and invoking the existing test compiler helper. Do not mock the provenance result.

- [ ] **Step 2: Run provenance tests and verify RED**

Run: `python -m unittest tests.test_faction_audit_adjustments tests.test_faction_wiring -v`

Expected: missing reserve component/metadata and no modern-only enforcement.

- [ ] **Step 3: Extend manifest/component models**

Allow only the exact new fields, validate their enums/non-empty labels, and populate `_ResolvedComponent(component_id, provenance_policy, research_label)`.

After typed unit resolution, enforce `modern_only` using terminal candidate provenance. Emit a blocking error naming the unit, terminal layer, terminal path, and alias chain.

- [ ] **Step 4: Split the PRC data exactly**

Add `exclude_regex` covering the fourteen identifiers to every `prc_regular` research selector that can reach them. Add an exact-selector `prc_legacy_reserve` with `source_side: "prc"`, `provenance_policy: "legacy_explicit"`, and the exact label. Add the component after `prc_regular` in the PRC actor and update its note to describe the separate reserve branch.

- [ ] **Step 5: Create a visible component research root**

For units belonging to a component with `research_label`, create:

```python
ResolvedResearchNode(
    key=f"actor:{actor_id}:component:{_slug(component_id)}",
    actor_id=actor_id,
    node_type="component",
    display_name=research_label,
    cost=0,
    prerequisites=[root_key],
    component_id=component_id,
)
```

Key generated category nodes by `(component_id, category, tier)` and parent the first tier to the component root, preventing silent blending with regular PLA categories.

- [ ] **Step 6: Update report and judgment-call documentation**

Render component research labels in PRC details. Add a PRC section with source evidence (the fourteen terminal West81 winners), inference (historical/reserve branch), confidence, and best alternative (replace with authoritative Code:X rows if supplied later).

- [ ] **Step 7: Run provenance tests and verify GREEN**

Run: `python -m unittest tests.test_faction_audit_adjustments tests.test_faction_wiring -v`

Expected: exact fourteen-row reserve split, visible label, correct categories, terminal West81 provenance, and blocking modern-only injection test.

- [ ] **Step 8: Commit PRC split**

```powershell
git add src/gates_of_codex/faction_wiring_models.py src/gates_of_codex/faction_wiring_manifest.py src/gates_of_codex/faction_wiring_components.py src/gates_of_codex/faction_wiring_actors.py src/gates_of_codex/faction_wiring_report.py src/gates_of_codex/data/faction_components.json src/gates_of_codex/data/faction_actors.json docs/audits/faction-judgment-calls.md tests/test_faction_audit_adjustments.py tests/test_faction_wiring.py
git commit -m "fix(factions): isolate PRC legacy reserve provenance"
```

---

### Task 6: Portable fail-closed Windows stack configuration

**Files:**
- Modify: `src/gates_of_codex/modstack.py`
- Modify: `config/mod-stack.windows.json`
- Modify: `tests/test_mod_stack.py`
- Modify: `README.md`
- Modify: `docs/live-acceptance.md`
- Modify: `docs/faction-wiring.md`
- Modify: `docs/audits/faction-wiring-source-audit.md`

**Interfaces:**
- `load_stack_config(path, *, environ: Mapping[str, str] | None = None) -> list[Path]` expands `${NAME}` explicitly and validates the complete layer contract.
- No directory search, fallback, or Workshop guessing.

- [ ] **Step 1: Add the explicit failing configuration matrix**

Add tests named:

```python
test_expands_all_required_environment_variables
test_rejects_missing_environment_variable
test_rejects_unresolved_placeholder
test_rejects_nonexistent_root
test_rejects_incorrect_mod_identity
test_rejects_duplicate_layer_or_normalized_root
test_rejects_incorrect_layer_order
test_validates_vanilla_sentinel_paths
test_accepts_active_worktree_as_final_gates_layer
test_rejects_unrelated_workshop_package
test_never_falls_back_or_guesses_workshop_paths
```

The unrelated-package fixture writes `{mod {name "Imperium vs Xenos Conquest"}}` and must fail even if the directory name is `3700832981`.

- [ ] **Step 2: Run stack tests and verify RED**

Run: `python -m unittest tests.test_mod_stack -v`

Expected: old loader leaves placeholders unresolved and accepts no identity contract.

- [ ] **Step 3: Implement exact expansion and validation**

Add `ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")`, `MOD_INFO_NAME_RE = re.compile(r'\{name\s+"([^"]+)"\}', re.I)`, and the signature `load_stack_config(path: str | Path, *, environ: Mapping[str, str] | None = None) -> list[Path]`.

Require exactly five roles in exact order. Expand every placeholder from the passed mapping or `os.environ`; reject missing/unresolved values before path conversion. Resolve paths, reject duplicates/nonexistent roots, validate Vanilla sentinel relative paths, then compare exact `mod.info` names against configured accepted-name arrays.

- [ ] **Step 4: Replace machine paths in the checked-in config**

```json
{
  "name": "Gates of Code:X live stack",
  "layers": [
    {"role":"vanilla","name":"Vanilla","path":"${GOH_VANILLA_ROOT}","sentinels":["resource/entity","resource/gamelogic.pak"]},
    {"role":"west81","name":"West81","path":"${WEST81_ROOT}","accepted_mod_names":["West-81"]},
    {"role":"codex","name":"Code:X","path":"${CODEX_ROOT}","accepted_mod_names":["Code-X"]},
    {"role":"codex_ai_overhaul","name":"Code:X AI Overhaul","path":"${CODEX_AI_OVERHAUL_ROOT}","accepted_mod_names":["CodeX Conquest AI Overhaul 1.5"]},
    {"role":"gates_codex","name":"Gates of Code:X","path":"${GATES_CODEX_ROOT}","accepted_mod_names":["Gates of CodeX","Gates of Code:X"]}
  ]
}
```

- [ ] **Step 5: Document PowerShell setup**

Document assignments using generic placeholders such as `D:\SteamLibrary`, with `GATES_CODEX_ROOT` pointing to the user's active clone/worktree variable. Do not write the current absolute fix path into tracked files.

- [ ] **Step 6: Run configuration tests and verify GREEN**

Run: `python -m unittest tests.test_mod_stack -v`

Expected: all eleven matrix cases pass.

- [ ] **Step 7: Commit portable configuration**

```powershell
git add src/gates_of_codex/modstack.py config/mod-stack.windows.json tests/test_mod_stack.py README.md docs/live-acceptance.md docs/faction-wiring.md docs/audits/faction-wiring-source-audit.md
git commit -m "fix(stack): validate portable Windows layer identities"
```

---

### Task 7: Full verification, review, commit consolidation, push, and issue report

**Files:**
- Create ignored outputs: `live_150_correction_validation/run1.json`, `run1.md`, `run2.json`, `run2.md`
- Modify only if diagnostics require a test-first correction.

**Interfaces:**
- Produces the final 24/0/0 deterministic evidence and delivery report.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m unittest tests.test_goh_source_parser tests.test_effective_definition_index tests.test_goh_macro_catalog tests.test_faction_wiring tests.test_faction_audit_adjustments tests.test_mod_stack -v
```

Expected: all focused tests pass, zero failures/errors.

- [ ] **Step 2: Run complete repository suite**

Run: `python -m unittest discover -s tests -v`

Expected: all repository tests pass; only documented expected skips remain.

- [ ] **Step 3: Run campaign, actor, economy, tactical, wrapper, and breed preflights**

Run:

```powershell
python -m unittest tests.test_campaign_play_loop tests.test_economy tests.test_economy_cli tests.test_faction_wrapper_units tests.test_materializable_units tests.test_breed_loadouts tests.test_operational_s6_interception tests.test_gates_of_codex -v
```

Expected: zero failures and no unexpected warnings.

- [ ] **Step 4: Set the five local environment variables without committing them**

Set `GOH_VANILLA_ROOT`, `WEST81_ROOT`, `CODEX_ROOT`, `CODEX_AI_OVERHAUL_ROOT`, and `GATES_CODEX_ROOT` in the validation shell. The final variable points to the active worktree.

- [ ] **Step 5: Run the live compiler twice**

```powershell
python -m gates_of_codex.faction_wiring --stack-config .\config\mod-stack.windows.json --output .\live_150_correction_validation\run1.json --summary .\live_150_correction_validation\run1.md
python -m gates_of_codex.faction_wiring --stack-config .\config\mod-stack.windows.json --output .\live_150_correction_validation\run2.json --summary .\live_150_correction_validation\run2.md
```

Expected both times: `actor_count = 24`, `error_count = 0`, `warning_count = 0`.

- [ ] **Step 6: Compare outputs byte-for-byte**

```powershell
$json1 = (Get-FileHash .\live_150_correction_validation\run1.json -Algorithm SHA256).Hash
$json2 = (Get-FileHash .\live_150_correction_validation\run2.json -Algorithm SHA256).Hash
$md1 = (Get-FileHash .\live_150_correction_validation\run1.md -Algorithm SHA256).Hash
$md2 = (Get-FileHash .\live_150_correction_validation\run2.md -Algorithm SHA256).Hash
if ($json1 -ne $json2 -or $md1 -ne $md2) { throw "Faction compiler output is nondeterministic" }
```

- [ ] **Step 7: Verify non-regression acceptance inventory**

Confirm from fresh tests/output:

- all fourteen `goc_*` wrappers materialize;
- `kor_crew`, `fr_spotter`, and `rus114_marksman` final definitions resolve;
- Code:X Core files remain inherited and unchanged;
- no canonical Code:X conquest file exists in the Gates overlay;
- no upstream assets were copied;
- no validation bypass or gate weakening appears in the diff.

- [ ] **Step 8: Request independent code review and address findings**

Review the complete diff against the design spec and issue #150. Fix Critical and Important findings test-first, then rerun Steps 1–7.

- [ ] **Step 9: Verify branch state and final diff**

Run:

```powershell
git status --short --branch
git diff --check e17f516a888f6152f0cae922c01ba211db1adb77..HEAD
git diff --stat e17f516a888f6152f0cae922c01ba211db1adb77..HEAD
```

Expected: clean tracked worktree after final commits and no whitespace errors.

- [ ] **Step 10: Push without merging**

```powershell
git push -u origin fix/150-faction-audit-blockers
```

- [ ] **Step 11: Post the implementation report to issue #150**

Report exact commit SHA, files changed, test commands/results, live 24/0/0 counts, JSON/Markdown hash equality, remaining warnings/blockers, exact PRC reserve decision, and portable stack correction. Do not modify independent audit artifacts.
