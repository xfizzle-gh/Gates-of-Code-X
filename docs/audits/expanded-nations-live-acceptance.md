# Expanded Nations live acceptance gate

This document is intentionally incomplete until owner testing is performed against the exact implementation head.

## Representative matrix

| Actor | Tactical side | Expected native roster boundary | Status |
|---|---|---|---|
| Serbia (`srb`) | `rusa` | Serbian actor projection only | pending |
| DPRK (`dprk`) | `rusa` | DPRK projection only, no Russian-only recruitment | pending |
| Russia (`rus`) | `rusa` | Russian projection only | pending |
| France (`fra`) | `nato` | French projection only, no German-only recruitment | pending |
| Germany (`deu`) | `nato` | German projection only, no French-only recruitment | pending |
| Ukraine (`ukr`) | `ukr` | Ukraine plus declared ILDU component only | pending |
| PRC (`prc`) | `prc` | PRC modern content plus separate legacy/reserve research branch | pending |

Each representative test must confirm:

1. the expected units appear in native Conquest recruitment;
2. another actor sharing the same tactical side does not leak into recruitment;
3. the generated research tree loads;
4. at least one representative unit can be purchased and spawned;
5. `game.log` contains no projection-related missing definition, breed, item, weapon, or entity error;
6. `-Core` removes the projection and restores canonical Code:X behavior.
