# Expanded Nations live acceptance gate

Native acceptance is paused pending fresh independent audit of the current integrated PR head.

The first Serbia activation stopped before game launch on a live Code:X legacy side conflict. Exactly three FRG-identity purchase entries in `units_csa_era1960.set` carry explicit native `side(csa)`. The schema-3 correction records classification and native side separately, preserves the native side, verifies source-backed authority, and remains fail-closed for unsupported mismatches.

The exact current PR head, current main SHA, and exact-head workflows are recorded on PR #172 and native-acceptance issue #177. This document intentionally avoids pinning a mutable SHA.

Native testing remains blocked until independent review accepts the current exact head.

## Representative matrix

| Actor | Tactical side | Expected native roster boundary | Status |
|---|---|---|---|
| Serbia (`srb`) | `rusa` | Serbian actor projection only | blocked pending re-audit |
| DPRK (`dprk`) | `rusa` | DPRK projection only, no Russian-only recruitment | pending Serbia |
| Russia (`rus`) | `rusa` | Russian projection only | pending Serbia |
| France (`fra`) | `nato` | French projection only, no German-only recruitment | pending Serbia |
| Germany (`deu`) | `nato` | German projection only, no French-only recruitment | pending Serbia |
| Ukraine (`ukr`) | `ukr` | Ukraine plus declared ILDU component only | pending Serbia |
| PRC (`prc`) | `prc` | PRC modern content plus separate legacy/reserve research branch | pending Serbia |

Each representative test must confirm:

1. the expected units appear in native Conquest recruitment;
2. another actor sharing the same tactical side does not leak into recruitment;
3. the generated research tree loads;
4. at least one representative unit can be purchased and spawned;
5. `game.log` contains no projection-related missing definition, breed, item, weapon, or entity error;
6. non-selected opponent and legacy purchase definitions remain available;
7. `-Core` removes the projection and restores canonical Code:X behavior.
