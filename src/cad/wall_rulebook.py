from __future__ import annotations

from math import hypot


TOL = 1e-6


def primitive_layer(primitive) -> str:
    return str(getattr(primitive, "layer", "") or "")


def primitive_segments(primitive):
    points = tuple(getattr(primitive, "points", ()) or ())

    if len(points) < 2:
        return ()

    segments = []

    for a, b in zip(points, points[1:]):
        segments.append(
            (
                (float(a[0]), float(a[1])),
                (float(b[0]), float(b[1])),
            )
        )

    if getattr(primitive, "closed", False) and len(points) > 2:
        a = points[-1]
        b = points[0]
        segments.append(
            (
                (float(a[0]), float(a[1])),
                (float(b[0]), float(b[1])),
            )
        )

    return tuple(segments)


def point_segment_distance(point, a, b) -> float:
    px, py = point
    ax, ay = a
    bx, by = b

    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy

    if length_sq <= TOL * TOL:
        return hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))

    qx = ax + t * dx
    qy = ay + t * dy

    return hypot(px - qx, py - qy)


def segments_touch(a1, a2, b1, b2) -> bool:
    return (
        point_segment_distance(a1, b1, b2) <= TOL
        or point_segment_distance(a2, b1, b2) <= TOL
        or point_segment_distance(b1, a1, a2) <= TOL
        or point_segment_distance(b2, a1, a2) <= TOL
    )


def primitive_touches_segments(primitive, target_segments) -> bool:
    own_segments = primitive_segments(primitive)

    for a1, a2 in own_segments:
        for b1, b2 in target_segments:
            if segments_touch(a1, a2, b1, b2):
                return True

    return False


def door_primitive_indices(door_candidates) -> set[int]:
    result = set()

    for candidate in door_candidates or ():
        for index in getattr(candidate, "display_primitive_indices", ()) or ():
            if isinstance(index, int):
                result.add(index)

    return result


def window_primitive_indices(window_candidates) -> set[int]:
    result = set()

    for candidate in window_candidates or ():
        for index in getattr(candidate, "primitive_indices", ()) or ():
            if isinstance(index, int):
                result.add(index)

    return result


def primitive_indices_to_segments(document, primitive_indices):
    result = []

    for index in primitive_indices:
        if 0 <= index < len(document.primitives):
            result.extend(
                primitive_segments(document.primitives[index])
            )

    return tuple(result)
