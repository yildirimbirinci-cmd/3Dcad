from __future__ import annotations

import math

TOL = 1e-5
ANGLE_TOL_DEG = 3.0


def primitive_points(primitive):
    return tuple(getattr(primitive, "points", ()) or ())


def primitive_segments(primitive):
    points = primitive_points(primitive)

    if len(points) < 2:
        return []

    segments = [
        (points[i], points[i + 1])
        for i in range(len(points) - 1)
    ]

    if getattr(primitive, "closed", False) and len(points) > 2:
        segments.append((points[-1], points[0]))

    return segments


def primitive_single_segment(primitive):
    segments = primitive_segments(primitive)

    if len(segments) != 1:
        return None

    return segments[0]


def point_distance(a, b):
    return math.hypot(
        float(a[0]) - float(b[0]),
        float(a[1]) - float(b[1]),
    )


def segment_direction(segment):
    a, b = segment

    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)

    if length <= TOL:
        return None

    return dx / length, dy / length


def segments_parallel(seg_a, seg_b):
    ua = segment_direction(seg_a)
    ub = segment_direction(seg_b)

    if ua is None or ub is None:
        return False

    cross = abs(
        ua[0] * ub[1]
        - ua[1] * ub[0]
    )

    return cross <= math.sin(
        math.radians(ANGLE_TOL_DEG)
    )


def segments_perpendicular(seg_a, seg_b):
    ua = segment_direction(seg_a)
    ub = segment_direction(seg_b)

    if ua is None or ub is None:
        return False

    dot = abs(
        ua[0] * ub[0]
        + ua[1] * ub[1]
    )

    return dot <= math.sin(
        math.radians(ANGLE_TOL_DEG)
    )


def segment_shared_endpoint(seg_a, seg_b, tol=TOL):
    for pa in seg_a:
        for pb in seg_b:
            if point_distance(pa, pb) <= tol:
                return True

    return False


def build_rectangle_from_four_lines(document, indices):
    if len(indices) != 4:
        return None

    segments = []

    for index in indices:
        segment = primitive_single_segment(
            document.primitives[index]
        )

        if segment is None:
            return None

        segments.append(segment)

    adjacency = []

    for i in range(4):
        neighbors = []

        for j in range(4):
            if i == j:
                continue

            if segment_shared_endpoint(
                segments[i],
                segments[j],
            ):
                neighbors.append(j)

        if len(neighbors) != 2:
            return None

        adjacency.append(neighbors)

    order = [0]
    previous = None
    current = 0

    for _ in range(3):
        choices = [
            n
            for n in adjacency[current]
            if n != previous
            and n not in order
        ]

        if not choices:
            return None

        nxt = choices[0]
        order.append(nxt)
        previous, current = current, nxt

    if order[0] not in adjacency[order[-1]]:
        return None

    s0 = segments[order[0]]
    s1 = segments[order[1]]
    s2 = segments[order[2]]
    s3 = segments[order[3]]

    if not segments_parallel(s0, s2):
        return None

    if not segments_parallel(s1, s3):
        return None

    if not segments_perpendicular(s0, s1):
        return None

    if not segments_perpendicular(s1, s2):
        return None

    return tuple(order)


def rectangle_corners(document, rectangle_indices):
    unique = {}

    for index in rectangle_indices:
        segment = primitive_single_segment(
            document.primitives[index]
        )

        if segment is None:
            continue

        for point in segment:
            key = (
                round(float(point[0]), 6),
                round(float(point[1]), 6),
            )

            unique[key] = (
                float(point[0]),
                float(point[1]),
            )

    points = list(unique.values())

    if len(points) != 4:
        return tuple(points)

    cx = sum(point[0] for point in points) / 4.0
    cy = sum(point[1] for point in points) / 4.0

    points.sort(
        key=lambda point: math.atan2(
            point[1] - cy,
            point[0] - cx,
        )
    )

    return tuple(points)


def _polygon_cross(a, b, p):
    return (
        (float(b[0]) - float(a[0]))
        * (float(p[1]) - float(a[1]))
        - (float(b[1]) - float(a[1]))
        * (float(p[0]) - float(a[0]))
    )


def point_inside_or_on_rectangle(point, corners, tol=TOL):
    if len(corners) != 4:
        return False

    crosses = []

    for i in range(4):
        a = corners[i]
        b = corners[(i + 1) % 4]

        crosses.append(
            _polygon_cross(
                a,
                b,
                point,
            )
        )

    has_positive = any(
        value > tol
        for value in crosses
    )

    has_negative = any(
        value < -tol
        for value in crosses
    )

    return not (
        has_positive
        and has_negative
    )


def primitive_inside_rectangle(
    primitive,
    corners,
):
    points = primitive_points(primitive)

    if len(points) < 2:
        return False

    return all(
        point_inside_or_on_rectangle(
            point,
            corners,
        )
        for point in points
    )
