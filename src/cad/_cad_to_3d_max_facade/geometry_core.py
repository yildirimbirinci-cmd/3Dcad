from __future__ import annotations

import math


ENGINE = "CAD3D_DETERMINISTIC_GEOMETRY_CORE_V1"


def point2(
    value,
    *,
    require_sequence=False,
    require_finite=False,
):
    """
    Convert an input value to deterministic 2D coordinates.

    Policy is explicit:
    - require_sequence=True reproduces strict window parsing.
    - require_sequence=False supports permissive CAD parsing.
    - require_finite controls NaN/Inf rejection.
    """

    if require_sequence:
        if not isinstance(
            value,
            (list, tuple),
        ):
            return None

        if len(value) < 2:
            return None

    try:
        x = float(value[0])
        y = float(value[1])
    except Exception:
        return None

    if require_finite:
        if not (
            math.isfinite(x)
            and math.isfinite(y)
        ):
            return None

    return x, y


def distance2(a, b):
    return math.hypot(
        float(b[0]) - float(a[0]),
        float(b[1]) - float(a[1]),
    )


def polyline_length(
    points,
    *,
    distance_fn=distance2,
):
    return sum(
        distance_fn(a, b)
        for a, b in zip(
            points,
            points[1:],
        )
    )


def point_segment_distance(
    point,
    a,
    b,
    *,
    degenerate_epsilon=1.0e-18,
    distance_fn=distance2,
):
    px, py = point
    ax, ay = a
    bx, by = b

    dx = bx - ax
    dy = by - ay

    length_sq = (
        dx * dx
        + dy * dy
    )

    if length_sq <= degenerate_epsilon:
        return distance_fn(
            point,
            a,
        )

    t = (
        (
            (px - ax) * dx
            + (py - ay) * dy
        )
        / length_sq
    )

    t = max(
        0.0,
        min(
            1.0,
            t,
        ),
    )

    q = (
        ax + t * dx,
        ay + t * dy,
    )

    return distance_fn(
        point,
        q,
    )


def direction2(
    a,
    b,
    *,
    min_length=1.0e-9,
):
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])

    length = math.hypot(
        dx,
        dy,
    )

    if length <= min_length:
        return None

    return (
        dx / length,
        dy / length,
    )


def directions_parallel(
    direction_a,
    direction_b,
    *,
    max_angle_deg=15.0,
):
    if (
        direction_a is None
        or direction_b is None
    ):
        return False

    dot = abs(
        float(direction_a[0])
        * float(direction_b[0])
        + float(direction_a[1])
        * float(direction_b[1])
    )

    limit = math.cos(
        math.radians(
            float(max_angle_deg)
        )
    )

    return dot >= limit


def adaptive_tolerance(
    *,
    width=0.0,
    thickness=0.0,
    minimum=0.0,
    maximum=float("inf"),
    width_ratio=0.0,
    thickness_ratio=0.0,
):
    """
    Deterministic local tolerance.

    No learning, history or project identity is involved.
    Same local geometry -> same tolerance.
    """

    width = max(
        0.0,
        float(width or 0.0),
    )

    thickness = max(
        0.0,
        float(thickness or 0.0),
    )

    value = max(
        float(minimum),
        width * float(width_ratio),
        thickness * float(
            thickness_ratio
        ),
    )

    return min(
        float(maximum),
        value,
    )
