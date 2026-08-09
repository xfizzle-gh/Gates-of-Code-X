# Expanded Nations live acceptance gate

Native acceptance is paused pending fresh independent audit of corrected PR head `dd87c728e274980587b996e3b5c59a774450f841`.

The first Serbia activation at independently accepted head `01f7a83f33bdc0b1d90a6146e0adfdcfcbb2fc0b` stopped before game launch. The live Code:X stack contains exactly three FRG-identity purchase entries in `units_csa_era1960.set` whose operative native side is explicitly `csa`. The schema-3 correction records classification and native side separately, preserves `side(csa)`, verifies source-backed authority, and remains fail-closed for unsupported mismatches.

Implementation code completed at `87eb0366206f2517240eb1f462d606cbea6e3ef4`. Final head `dd87c728e274980587b996e3b5c59a774450f841` adds only this acceptance-status documentation. Focused workflow `31285719876` and full workflow `31285719873` pass at the final exact head.

This document does not authorize resumed testing until independent review accepts that exact head.

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
