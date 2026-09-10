from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

Point2D = tuple[float, float]
RGB = tuple[int, int, int]


@dataclass(slots=True)
class CadPolyline:
    points: tuple[Point2D, ...]
    layer: str
    color: RGB
    closed: bool = False
    source_type: str = ""
    group_id: str | None = None
    block_key: str | None = None


@dataclass(slots=True)
class CadText:
    text: str
    position: Point2D
    height: float
    rotation: float
    layer: str
    color: RGB
    source_type: str = ""
    group_id: str | None = None
    block_key: str | None = None


@dataclass(slots=True)
class CadDocument:
    source_path: Path
    parsed_path: Path
    primitives: list[CadPolyline] = field(default_factory=list)
    texts: list[CadText] = field(default_factory=list)
    entity_counts: dict[str, int] = field(default_factory=dict)
    skipped_counts: dict[str, int] = field(default_factory=dict)
    layers: set[str] = field(default_factory=set)

    @property
    def bounds(self) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []

        for primitive in self.primitives:
            for x, y in primitive.points:
                xs.append(x)
                ys.append(y)

        for text in self.texts:
            x, y = text.position
            xs.append(x)
            ys.append(y)

        if not xs:
            return None

        return min(xs), min(ys), max(xs), max(ys)
