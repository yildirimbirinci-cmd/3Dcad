from __future__ import annotations

import math


ARC_ANGLE_TOL_DEG = 5.0


def primitive_layer(primitive) -> str:
    return str(getattr(primitive, "layer", "") or "")


def is_arc(primitive) -> bool:
    return str(
        getattr(primitive, "source_type", "") or ""
    ).upper() == "ARC"


def _pt(point):
    return float(point[0]), float(point[1])


def _distance(a, b) -> float:
    ax, ay = _pt(a)
    bx, by = _pt(b)
    return math.hypot(ax - bx, ay - by)


def _circle_center(a, b, c):
    ax, ay = _pt(a)
    bx, by = _pt(b)
    cx, cy = _pt(c)

    d = 2.0 * (
        ax * (by - cy)
        + bx * (cy - ay)
        + cx * (ay - by)
    )

    if abs(d) <= 1e-12:
        return None

    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy

    ux = (
        a2 * (by - cy)
        + b2 * (cy - ay)
        + c2 * (ay - by)
    ) / d

    uy = (
        a2 * (cx - bx)
        + b2 * (ax - cx)
        + c2 * (bx - ax)
    ) / d

    return ux, uy


def arc_geometry(primitive):
    points = tuple(
        getattr(primitive, "points", ()) or ()
    )

    if len(points) < 3:
        return None

    start = _pt(points[0])
    middle = _pt(points[len(points) // 2])
    end = _pt(points[-1])

    center = _circle_center(
        start,
        middle,
        end,
    )

    if center is None:
        return None

    radius = _distance(center, start)

    if radius <= 1e-9:
        return None

    middle_radius = _distance(center, middle)
    end_radius = _distance(center, end)

    radius_error = max(
        abs(middle_radius - radius),
        abs(end_radius - radius),
    )

    if radius_error > radius * 0.01:
        return None

    a0 = math.atan2(
        start[1] - center[1],
        start[0] - center[0],
    )
    a1 = math.atan2(
        end[1] - center[1],
        end[0] - center[0],
    )

    sweep = abs(
        math.degrees(a1 - a0)
    ) % 360.0

    if sweep > 180.0:
        sweep = 360.0 - sweep

    return {
        "start": start,
        "end": end,
        "center": (
            float(center[0]),
            float(center[1]),
        ),
        "radius": float(radius),
        "sweep_deg": float(sweep),
    }


def _segment_matches_endpoints(
    a,
    b,
    p1,
    p2,
    tol,
) -> bool:
    return (
        _distance(a, p1) <= tol
        and _distance(b, p2) <= tol
    ) or (
        _distance(a, p2) <= tol
        and _distance(b, p1) <= tol
    )


def find_leaf_line(
    document,
    arc_index: int,
    geometry,
):
    arc = document.primitives[arc_index]
    layer = primitive_layer(arc)
    tolerance = max(
        geometry["radius"] * 0.01,
        1e-6,
    )

    center = geometry["center"]

    for primitive_index, primitive in enumerate(document.primitives):
        if primitive_index == arc_index:
            continue

        if primitive_layer(primitive) != layer:
            continue

        if is_arc(primitive):
            continue

        points = tuple(
            getattr(primitive, "points", ()) or ()
        )

        for segment_index in range(len(points) - 1):
            a = _pt(points[segment_index])
            b = _pt(points[segment_index + 1])

            for endpoint in (
                geometry["start"],
                geometry["end"],
            ):
                if _segment_matches_endpoints(
                    a,
                    b,
                    center,
                    endpoint,
                    tolerance,
                ):
                    return {
                        "primitive_index": primitive_index,
                        "segment_index": segment_index,
                        "line": (a, b),
                    }

    return None


def validate_door_arc(
    document,
    arc_index: int,
):
    if arc_index < 0 or arc_index >= len(document.primitives):
        return None

    primitive = document.primitives[arc_index]

    if not is_arc(primitive):
        return None

    layer = primitive_layer(primitive)

    if not layer:
        return None

    geometry = arc_geometry(primitive)

    if geometry is None:
        return None

    if abs(
        geometry["sweep_deg"] - 90.0
    ) > ARC_ANGLE_TOL_DEG:
        return None

    leaf = find_leaf_line(
        document,
        arc_index,
        geometry,
    )

    if leaf is None:
        return None

    return {
        "arc_index": arc_index,
        "layer": layer,
        "geometry": geometry,
        "leaf_primitive_index": leaf["primitive_index"],
        "leaf_line": leaf["line"],
    }


def grab_local_door_geometry(
    document,
    validated,
):
    geometry = validated["geometry"]
    layer = validated["layer"]

    primitive_indices = []
    xs = []
    ys = []

    for index, primitive in enumerate(document.primitives):
        if primitive_layer(primitive) != layer:
            continue

        points = tuple(
            getattr(primitive, "points", ()) or ()
        )

        if len(points) < 2:
            continue

        primitive_indices.append(index)

        for x, y in points:
            xs.append(float(x))
            ys.append(float(y))

    if not primitive_indices:
        primitive_indices = [
            validated["arc_index"],
            validated["leaf_primitive_index"],
        ]

    if not xs:
        for point in (
            geometry["start"],
            geometry["end"],
            geometry["center"],
        ):
            xs.append(float(point[0]))
            ys.append(float(point[1]))

    xmin = min(xs)
    xmax = max(xs)
    ymin = min(ys)
    ymax = max(ys)

    return {
        "primitive_indices": tuple(
            sorted(set(primitive_indices))
        ),
        "bounds": (
            float(xmin),
            float(ymin),
            float(xmax),
            float(ymax),
        ),
        "center": (
            float((xmin + xmax) * 0.5),
            float((ymin + ymax) * 0.5),
        ),
        "width": float(xmax - xmin),
        "height": float(ymax - ymin),
        "arc_center": geometry["center"],
        "arc_radius": geometry["radius"],
    }