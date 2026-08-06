"""Typed in-memory Earth3 dataset."""

from __future__ import annotations

from dataclasses import dataclass, field


CONTINENT_NAMES = {
    0: "Ocean",
    1: "Asia",
    2: "Europe",
    3: "NorthAmerica",
    4: "Oceania",
    5: "SouthAmerica",
    6: "Africa",
}


@dataclass(frozen=True, slots=True)
class Earth3Province:
    source_id: int
    ring: tuple[tuple[float, float], ...]
    label_x: float
    label_y: float
    continent_id: int
    terrain_id: int
    region_id: int
    growth: float
    base_development: int

    @property
    def continent_name(self) -> str:
        return CONTINENT_NAMES.get(self.continent_id, f"continent_{self.continent_id}")

    @property
    def is_water(self) -> bool:
        # Continent 0 is Ocean in Continents.json. Terrain id alone is not reliable.
        return self.continent_id == 0

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.ring]
        ys = [p[1] for p in self.ring]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def centroid(self) -> tuple[float, float]:
        if not self.ring:
            return 0.0, 0.0
        xs = [p[0] for p in self.ring]
        ys = [p[1] for p in self.ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)


@dataclass(slots=True)
class Earth3Dataset:
    provinces: dict[int, Earth3Province] = field(default_factory=dict)
    adjacency: dict[int, set[int]] = field(default_factory=dict)
    background_size: tuple[int, int] = (8, 4)
    background_tile: tuple[int, int] = (2220, 2150)
    num_of_provinces_declared: int = 0
    source_label: str = "Earth3"

    @property
    def canvas_size(self) -> tuple[int, int]:
        return (
            self.background_size[0] * self.background_tile[0],
            self.background_size[1] * self.background_tile[1],
        )

    def neighbors(self, province_id: int) -> set[int]:
        return set(self.adjacency.get(province_id, set()))
