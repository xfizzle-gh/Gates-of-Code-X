# Europe–Mediterranean theatre (from working GoE map)

## Status

**Primary production direction** for the Europe–Mediterranean theatre.

- Derived from the **working interim GoE color-ID map** (not pack artwork)
- Color-ID remains authoritative for click / ownership / adjacency
- Pack calibration / affine / TPS is **research-only** and not required

## Theatre bounds (red-box framing)

Display crop is driven by **playable land bbox only** (not deep cosmetic Africa).

```text
marker playable window:
  x: -4.0 .. 3.0
  y: -0.95 .. 6.0   (+ FORCE_INCLUDE coastal Maghreb/Egypt/Levant)

display pad from playable bbox:
  north 10% / south 2% / west 3% / east 3%
```

**Frozen display extent:** `817×920` (red-box baseline; force-includes clip into this frame and must not expand it).

Outside-theatre land is a **continuous parchment underlay** (map art), not grey disabled provinces: no borders, no labels, no interaction. Only playable↔playable borders are drawn.

### Intentionally kept

- British Isles and western Europe
- Central Europe and Balkans
- Mediterranean basin
- Limited North Africa coastal belt (Maghreb / Egypt / Levant via force-include)
- Black Sea / Turkey approaches present in GoE
- Scandinavia / Baltic (expanded north)

### Intentionally excluded from the visible theatre

- Deep Sahara / sub-Saharan filler (not used to expand the canvas)
- Deep Central Asia / far-eastern filler
- Far Atlantic / Americas filler
- Large empty ocean margins

Playable set = marker window ∪ force-include coastal − force-exclude interiors, clipped to the display crop. Edge provinces may be reshaped by the crop.

## Layers

| Layer | Authority |
|---|---|
| Color-ID `province_id_map.png` + manifest | **Gameplay truth** (click, ownership, borders, adjacency) |
| `background_procedural.png` | Presentation underlay only (light neutral) |
| Campaign graph | Filtered GoE IDs + neighbors inside theatre |

## Generate + play

```powershell
python -m gates_of_codex generate-europe-mediterranean-from-goe
python -m gates_of_codex new --strategic-map europe_mediterranean_from_goe --faction nato --output live/em_goe_campaign.json
python -m gates_of_codex export-frontend live/em_goe_campaign.json --output godot/campaign_snapshot.json
```

Open Godot on `godot/project.godot` and press F5.

## Recommendation

**Use the procedural light-neutral background** for now.

- Exactly aligned to the cropped theater geometry
- Improves faction tint readability
- No rights / projection risk
- AI underlay optional later, only as a non-authoritative PNG under the same crop frame

## Relation to other maps

| map_id | Role |
|---|---|
| `interim_goe_europe` | Full working 517-province Europe fallback |
| `europe_mediterranean_from_goe` | **Main EM theatre** (this doc) |
| `europe_mediterranean_prototype` | Research path (pack/NE experiments); not production |
