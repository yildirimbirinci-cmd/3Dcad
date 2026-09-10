from __future__ import annotations

import math
from dataclasses import dataclass

from cad.model import CadDocument
from cad.window_rulebook import find_window_rectangles


@dataclass(frozen=True, slots=True)
class Segment:
    a: tuple[float, float]
    b: tuple[float, float]
    length: float
    angle: float
    mx: float
    my: float


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    corners: tuple = ()
    lines: tuple = ()
    score: float = 0.0
    source_segment_count: int = 0
    layer_id: str = ""
    group_id: str | None = None
    block_key: str | None = None
    shape_ratio: float = 0.0
    segment_lengths_norm: tuple = ()
    spacing_norm: tuple = ()
    topology_signature: tuple = ()


@dataclass(frozen=True, slots=True)
class WindowFamilyResult:
    seed: WindowCandidate
    windows: tuple[WindowCandidate, ...]
    memory_similarity: float = 0.0
    learned_new_example: bool = False


def _segments(document: CadDocument) -> list[Segment]:
    result: list[Segment] = []

    for primitive in document.primitives:
        source_type = str(
            getattr(primitive, "source_type", "") or ""
        ).upper()

        if source_type and source_type not in {
            "LINE",
            "LWPOLYLINE",
            "POLYLINE",
        }:
            continue

        points = primitive.points

        if len(points) < 2:
            continue

        pairs = list(zip(points, points[1:]))

        if primitive.closed and len(points) > 2 and points[-1] != points[0]:
            pairs.append((points[-1], points[0]))

        for p0, p1 in pairs:
            dx = float(p1[0] - p0[0])
            dy = float(p1[1] - p0[1])
            length = math.hypot(dx, dy)

            if length <= 1e-9:
                continue

            result.append(
                Segment(
                    a=(float(p0[0]), float(p0[1])),
                    b=(float(p1[0]), float(p1[1])),
                    length=length,
                    angle=math.atan2(dy, dx),
                    mx=(float(p0[0]) + float(p1[0])) * 0.5,
                    my=(float(p0[1]) + float(p1[1])) * 0.5,
                )
            )

    return result


def _candidate_from_rectangle(rect) -> WindowCandidate:
    corners = (
        (rect.x0, rect.y0),
        (rect.x1, rect.y0),
        (rect.x1, rect.y1),
        (rect.x0, rect.y1),
    )

    lines = (
        (corners[0], corners[1]),
        (corners[1], corners[2]),
        (corners[2], corners[3]),
        (corners[3], corners[0]),
    )

    width = max(rect.x1 - rect.x0, 1e-9)
    height = max(rect.y1 - rect.y0, 1e-9)

    return WindowCandidate(
        corners=corners,
        lines=lines,
        score=float(len(rect.inner_lines)),
        source_segment_count=len(rect.inner_lines),
        shape_ratio=max(width, height) / min(width, height),
    )


def detect_all_windows(
    document: CadDocument,
) -> list[WindowCandidate]:
    segments = _segments(document)
    rectangles = find_window_rectangles(segments)

    return [
        _candidate_from_rectangle(rect)
        for rect in rectangles
    ]


def detect_one_window(
    document: CadDocument,
) -> WindowCandidate | None:
    windows = detect_all_windows(document)
    return windows[0] if windows else None


def detect_window_family(
    document: CadDocument,
) -> WindowFamilyResult | None:
    windows = detect_all_windows(document)

    if not windows:
        return None

    return WindowFamilyResult(
        seed=windows[0],
        windows=tuple(windows),
    )
