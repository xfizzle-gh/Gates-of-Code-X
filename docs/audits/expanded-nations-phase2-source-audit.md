# Expanded Nations Phase 2 source audit

Status: **PENDING LIVE-STACK AUDIT**
Parent: #189
Audit issue: #190
Phase 2 branch: `feat/189-expanded-nations-phase2`
Initial stacked base: `c59cbc247c565071d458c5724d9be626fcdf7dc0`

This document is a required evidence template. Do not convert planning hypotheses into findings without inspecting the effective installed source stack.

## Exact audit environment

Fill all fields before accepting any roster selector.

```text
Audit date/time:
Auditor:
Repository head:
Python version:
Vanilla root:
Vanilla signature/timestamp:
West81 root:
West81 signature/timestamp:
Code:X root:
Code:X signature/timestamp:
Code:X AI Overhaul root:
Code:X AI Overhaul signature/timestamp:
Gates root used for final-layer source:
Gates signature/head:
```

Required load order:

1. Vanilla
2. West81
3. Code:X
4. Code:X AI Overhaul
5. Gates of Code:X

## Disposition vocabulary

Use exactly one final disposition for every candidate actor represented in the authoritative theatre:

- `full_national`: complete source-backed national military suitable for normal play.
- `national_hybrid`: national identity/equipment plus explicit audited gap-fill component.
- `coalition_fallback`: playable strategic actor using an explicitly labeled coalition roster because national content is insufficient.
- `regional_fallback`: playable strategic actor using a geographically appropriate non-national fallback approved by the owner.
- `strategic_only`: actor exists for ownership/diplomacy/persistence but has no authorized sovereign recruitment tree.
- `excluded`: not represented by authoritative theatre data or intentionally omitted with documented reason.

## Per-actor audit table

| Actor | Theatre present? | Disposition | Tactical side | National infantry | National equipment | Research roots | Gap-fill | Legacy/reserve | Cross-side reuse | Confidence | Blocking issue |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| grc |  |  |  |  |  |  |  |  |  |  |  |
| rou |  |  |  |  |  |  |  |  |  |  |  |
| bgr |  |  |  |  |  |  |  |  |  |  |  |
| hun |  |  |  |  |  |  |  |  |  |  |  |
| cze |  |  |  |  |  |  |  |  |  |  |  |
| svk |  |  |  |  |  |  |  |  |  |  |  |
| bel |  |  |  |  |  |  |  |  |  |  |  |
| prt |  |  |  |  |  |  |  |  |  |  |  |
| hrv |  |  |  |  |  |  |  |  |  |  |  |
| ltu |  |  |  |  |  |  |  |  |  |  |  |
| lva |  |  |  |  |  |  |  |  |  |  |  |
| est |  |  |  |  |  |  |  |  |  |  |  |
| aut |  |  |  |  |  |  |  |  |  |  |  |
| che |  |  |  |  |  |  |  |  |  |  |  |
| irl |  |  |  |  |  |  |  |  |  |  |  |
| svn |  |  |  |  |  |  |  |  |  |  |  |
| bih |  |  |  |  |  |  |  |  |  |  |  |
| mne |  |  |  |  |  |  |  |  |  |  |  |
| alb |  |  |  |  |  |  |  |  |  |  |  |
| mkd |  |  |  |  |  |  |  |  |  |  |  |
| mda |  |  |  |  |  |  |  |  |  |  |  |
| isl |  |  |  |  |  |  |  |  |  |  |  |
| cyp |  |  |  |  |  |  |  |  |  |  |  |
| mlt |  |  |  |  |  |  |  |  |  |  |  |
| geo |  |  |  |  |  |  |  |  |  |  |  |
| arm |  |  |  |  |  |  |  |  |  |  |  |
| aze |  |  |  |  |  |  |  |  |  |  |  |
| isr |  |  |  |  |  |  |  |  |  |  |  |
| lbn |  |  |  |  |  |  |  |  |  |  |  |
| syr |  |  |  |  |  |  |  |  |  |  |  |
| jor |  |  |  |  |  |  |  |  |  |  |  |
| irq |  |  |  |  |  |  |  |  |  |  |  |
| mar |  |  |  |  |  |  |  |  |  |  |  |
| dza |  |  |  |  |  |  |  |  |  |  |  |
| tun |  |  |  |  |  |  |  |  |  |  |  |
| lby |  |  |  |  |  |  |  |  |  |  |  |
| egy |  |  |  |  |  |  |  |  |  |  |  |

## Per-actor evidence block

Copy this section once per represented actor.

### `<actor_id>` / `<display name>`

**Authoritative theatre presence**

- Province/country authority:
- Evidence path/record:

**National personnel evidence**

- Breed families:
- Purchase-ready squads:
- Source files/layers:
- Materialization notes:

**National equipment evidence**

- Transport/IFV/APC:
- Armor/anti-armor:
- Artillery:
- Air defense:
- Logistics/support:
- Aviation if relevant:
- Source files/layers:

**Research evidence**

- Native research roots:
- Mixed/multinational containers inspected:
- Filter boundary required:

**Legacy/reserve evidence**

- West81 rows:
- Why each row is geographically/nationally appropriate:

**Cross-side reuse**

- Source tactical side:
- Target tactical side:
- Exact units:
- Required native materialization test:

**Recommended final component wiring**

```json
{
  "actor_id": "",
  "disposition": "",
  "tactical_side": "",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment call**

- Confidence:
- Inference:
- Best alternative:
- Blocking gaps:

## Audit-wide rejection rules

Reject a proposed playable roster when any of these are true:

- national identity is based only on a filename guess or substring;
- required personnel breeds do not resolve;
- vehicle/entity references do not resolve;
- the proposal silently imports another sovereign country's national infantry;
- West81 content is presented as modern Code:X national authority;
- cross-side infantry is accepted without a live target-side materialization obligation;
- a strategic-only country is made playable only to increase faction count;
- PMC/militia/foreign-volunteer encounter content is treated as a sovereign national army without direct evidence.

## Completion checklist

- [ ] exact source environment recorded
- [ ] authoritative theatre presence resolved for every candidate
- [ ] all represented candidates have one disposition
- [ ] every exact selector/root has source evidence
- [ ] all legacy rows explicitly marked
- [ ] all cross-side rows enumerated
- [ ] JSON candidate ledger updated
- [ ] #190 comment posted with summary and exact head
- [ ] no upstream mod modified
- [ ] no Phase 2 roster implementation started before the relevant evidence was accepted
