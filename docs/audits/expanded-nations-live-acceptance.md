# Expanded Nations live acceptance gate

Native acceptance is paused pending fresh independent audit of integrated PR head `1db74b115158680318f078312bacaf076c929bdf`.

The first Serbia activation at independently accepted head `01f7a83f33bdc0b1d90a6146e0adfdcfcbb2fc0b` stopped before game launch. The live Code:X stack contains exactly three FRG-identity purchase entries in `units_csa_era1960.set` whose operative native side is explicitly `csa`. The schema-3 correction records classification and native side separately, preserves `side(csa)`, verifies source-backed authority, and remains fail-closed for unsupported mismatches.

Implementation code completed at `87eb0366206f2517240eb1f462d606cbea6e3ef4`. The branch was then integrated with current main `b8f125fe484c9bf616c75b39587ed9afe3f4ca07` using a normal merge commit. Final integrated head `1db74b115158680318f078312bacaf076c929bdf` is 77 commits ahead and 0 behind main.

Focused workflow `31286626299` and full workflow `31286626305` both pass at the final integrated exact head.

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
