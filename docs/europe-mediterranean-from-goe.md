# Europe–Mediterranean theatre (from working GoE map)

## Status

**Primary production direction** for the Europe–Mediterranean theatre.

- Derived from the **working interim GoE color-ID map** (not pack artwork)
- Color-ID remains authoritative for click / ownership / adjacency
- Pack calibration / affine / TPS is **research-only** and not required

## Theatre bounds (GoE marker space)

```text
x: -4.2 .. 3.2
y: -2.2 .. 5.0
```

### Intentionally kept

- British Isles and western Europe
- Central Europe and Balkans
- Mediterranean basin
- Limited North Africa (Maghreb / Egypt coastal belt as present in GoE)
- Limited Near East / Black Sea approaches as present in GoE
- Scandinavia / Baltic as present in GoE framing

### Intentionally excluded from the visible theatre

- Deep Central Asia / far-eastern filler
- Deep sub-Saharan Africa
- Far Atlantic / Americas filler
- Extreme arctic filler outside useful Scandinavia framing

Exact kept set = provinces whose GoE `marker_anchor` falls inside the marker bounds above **and** that retain pixels after the ID-map crop.

## Layers

| Layer | Authority |
|---|---|
| Color-ID `province_id_map.png` + manifest | **Gameplay truth** (click, ownership, borders, adjacency) |
| `background_procedural.png` | Presentation underlay only (light neutral) |
| Campaign graph | Filtered GoE IDs + neighbors inside theatre |

## Generate + play

```powershell
python -m gates_of_codex generate-europe-mediterranean-from-goe
python -m gates_of_codex new --map europe_mediterranean_from_goe --faction nato --output live/em_goe_campaign.json
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
