# P2 Earth3 Campaign Bootstrap Design

## Scope

P2 applies a strict, declarative opening-state overlay to the unchanged P1
`build_earth3_campaign()` authority skeleton. The `earth3_v1` scenario registry
entry invokes the new builder; both legacy scenarios remain unchanged. P2 adds
no geometry, adjacency, operational nodes, route edges, launcher flow, or P3+
content.

## Fixed scenario data and provenance

Scenario content lives in separated JSON files under
`src/gates_of_codex/data/earth3_v1/`. A dedicated loader captures each file's
raw bytes once, rejects duplicate keys, symlinks/reparse points, containment
escapes, and observable path substitution, then parses only the captured bytes.
Each raw file digest and a canonical logical bundle digest are persisted as
immutable bootstrap provenance. CRLF changes, missing or added terminal bytes,
and equivalent textual rewrites change raw identity.

The loader cannot override the P1 map manifest, dataset, geometry, stable IDs,
classifications, hashes, topology, land/water policy, or selectability. P1 and
P2 loaders remain conceptually separate.

## Proven footprint

City-to-province mappings are admitted only through a traceable evidence record
that joins the committed Earth3 licensed location source ID to the committed
stable-ID map. Centroid proximity and visual inference are not authority. A
mapping that cannot satisfy this chain is excluded rather than substituted.

The proposed bounded Central Europe--Baltic--Ukraine footprint is Berlin,
Tallinn, Riga, Vilnius, Kyiv, Odesa, Kherson, Zaporizhzhia, Rostov-on-Don,
Luhansk, and Donetsk, subject to that evidence check. P2 preserves production
selectability and records a separate scenario-actionable footprint. Outside
provinces remain valid and inspectable but cannot be P2 ownership, formation,
deployment, construction, objective, supply-site, control-site, movement, or
attack targets.

## Actors, alliances, and forces

The human NATO seat uses strategic actor `usa`. NATO-side formations remain
actor-scoped and use the manifest's canonical IDs: `usa` (United States), `deu`
(Germany), `pol` (Poland), and `ukr` (Ukraine). Ukraine retains its existing
UKR tactical side and receives an explicit alliance relationship with NATO.
Russia uses manifest actor `rus` and its existing tactical side. Actor ownership governs every
formation, roster, research state, economy, recruitment pool, and provenance
record even when actors share a faction.

Any dormant PRC runtime row inherited from existing installation compatibility
is not an active P2 participant and receives no P2 territory, forces,
commanders, deployment, objectives, sites, roster, meaningful resources, or
research progression.

Rosters and required research are materialized deterministically from an
explicitly injected, validated active stack/catalog. Missing authority or an
unmaterializable required unit fails clearly. Stable catalog provenance is
content-derived and does not require original absolute stack paths. Only the
narrow campaign-construction dependency may be threaded through an existing
stack-config seam; no P4 launcher behavior is added.

## Opening state

Separate scenario files declare names, ownership, actor-owned formations and
battalions, deployment zones, modest resources, actor research intent, strategic
sites, supply-hub intent, incomplete objectives, and tactical-map preferences.
All identifiers are deterministic. Scenario-authored commanders use explicit
fictional/role labels supported by the existing schema and receive no invented
traits, bonuses, or mechanics.

Sites and hubs express ownership and future intent only. Objectives may name
future capture goals but neither validation nor presentation claims current
connectivity. The opening outcome is explicitly incomplete.

## No-movement boundary

P2 stores formation province locations and intended endpoints but creates no
route or adjacency authority. It does not enable structural polygon-neighbor
fallback. Campaign commands fail closed for Earth3 P2 movement and attacks until
P3 supplies a reviewed route batch. The opening campaign state is coherent, but
operational maneuver is intentionally unavailable.

## Validation and save behavior

Creation validates the exact bundle, evidence-backed footprint, unique and
selectable land references, actor/faction/alliance consistency, ownership,
formations, battalions, commanders, nonempty materializable rosters, research
closure, economy/recruitment scope, sites, objectives, supply intent,
deployment, tactical preferences, and absence of route/geometry fields.

Saves persist immutable bootstrap ID, schema version, raw and logical bundle
identities, footprint identity, and active catalog identity. Loading validates
only this immutable provenance plus normal campaign schema. It never reapplies
the opening bootstrap, restores mutable ownership or forces, reruns roster
installation, compares evolved state to opening JSON, or requires original
absolute stack paths. Legacy saves are unaffected.

## Verification boundary

Adversarial tests are authored before production implementation for the full P2
contract, including exact bytes, path security, mappings, actor scope,
footprint enforcement, save evolution, deterministic provenance, and the P3
movement boundary. Per owner direction, this implementation session performs
static review only and runs or inspects no tests, CI, workflow, lint, type,
compile, Godot, build, packaging, or smoke command.
