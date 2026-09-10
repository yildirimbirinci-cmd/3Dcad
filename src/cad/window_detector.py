from __future__ import annotations

from dataclasses import dataclass
import math

import ezdxf

from cad.model import CadDocument


TOL = 1e-5
ANGLE_TOL_DEG = 3.0


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    rectangle_indices: tuple[int, int, int, int]
    layer: str
    corners: tuple
    lines: tuple
    primitive_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WindowDetectionResult:
    windows: tuple[WindowCandidate, ...]


def _points(primitive):
    return tuple(getattr(primitive, "points", ()) or ())


def _segments(primitive):
    points = _points(primitive)

    if len(points) < 2:
        return []

    result = [
        (points[i], points[i + 1])
        for i in range(len(points) - 1)
    ]

    if getattr(primitive, "closed", False) and len(points) > 2:
        result.append((points[-1], points[0]))

    return result


def _single_segment(primitive):
    segments = _segments(primitive)
    if len(segments) != 1:
        return None
    return segments[0]


def _distance(a, b):
    return math.hypot(
        float(a[0]) - float(b[0]),
        float(a[1]) - float(b[1]),
    )


def _direction(segment):
    a, b = segment
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)

    if length <= TOL:
        return None

    return dx / length, dy / length


def _parallel(seg_a, seg_b):
    ua = _direction(seg_a)
    ub = _direction(seg_b)

    if ua is None or ub is None:
        return False

    cross = abs(
        ua[0] * ub[1]
        - ua[1] * ub[0]
    )

    return cross <= math.sin(
        math.radians(ANGLE_TOL_DEG)
    )


def _perpendicular(seg_a, seg_b):
    ua = _direction(seg_a)
    ub = _direction(seg_b)

    if ua is None or ub is None:
        return False

    dot = abs(
        ua[0] * ub[0]
        + ua[1] * ub[1]
    )

    return dot <= math.sin(
        math.radians(ANGLE_TOL_DEG)
    )


def _shared_endpoint(seg_a, seg_b):
    for pa in seg_a:
        for pb in seg_b:
            if _distance(pa, pb) <= TOL:
                return True
    return False


def _endpoint_key(point, digits=5):
    return (
        round(float(point[0]), digits),
        round(float(point[1]), digits),
    )


def _build_endpoint_adjacency(document, line_indices):
    endpoint_map = {}

    for index in line_indices:
        segment = _single_segment(
            document.primitives[index]
        )

        if segment is None:
            continue

        for point in segment:
            endpoint_map.setdefault(
                _endpoint_key(point),
                [],
            ).append(index)

    adjacency = {
        index: set()
        for index in line_indices
    }

    for indices in endpoint_map.values():
        unique = list(dict.fromkeys(indices))

        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                a = unique[i]
                b = unique[j]
                adjacency[a].add(b)
                adjacency[b].add(a)

    return adjacency


def _build_rectangle(document, indices):
    if len(indices) != 4:
        return None

    segments = []

    for index in indices:
        segment = _single_segment(
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

            if _shared_endpoint(
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

    if not _parallel(s0, s2):
        return None

    if not _parallel(s1, s3):
        return None

    if not _perpendicular(s0, s1):
        return None

    if not _perpendicular(s1, s2):
        return None

    return tuple(order)


def _rectangle_candidates(document, line_indices):
    adjacency = _build_endpoint_adjacency(
        document,
        line_indices,
    )

    seen = set()

    for a in line_indices:
        for b in adjacency.get(a, ()):
            if b == a:
                continue

            for c in adjacency.get(b, ()):
                if c in (a, b):
                    continue

                for d in adjacency.get(c, ()):
                    if d in (a, b, c):
                        continue

                    if a not in adjacency.get(d, ()):
                        continue

                    key = tuple(sorted((a, b, c, d)))

                    if key in seen:
                        continue

                    seen.add(key)

                    order = _build_rectangle(
                        document,
                        key,
                    )

                    if order is None:
                        continue

                    yield tuple(
                        key[position]
                        for position in order
                    )


def _rectangle_corners(document, rectangle_indices):
    unique = {}

    for index in rectangle_indices:
        segment = _single_segment(
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
        return ()

    cx = sum(p[0] for p in points) / 4.0
    cy = sum(p[1] for p in points) / 4.0

    points.sort(
        key=lambda p: math.atan2(
            p[1] - cy,
            p[0] - cx,
        )
    )

    return tuple(points)


def _cross(a, b, p):
    return (
        (float(b[0]) - float(a[0]))
        * (float(p[1]) - float(a[1]))
        - (float(b[1]) - float(a[1]))
        * (float(p[0]) - float(a[0]))
    )


def _point_inside_or_on_rectangle(point, corners):
    crosses = []

    for i in range(4):
        a = corners[i]
        b = corners[(i + 1) % 4]
        crosses.append(_cross(a, b, point))

    has_positive = any(v > TOL for v in crosses)
    has_negative = any(v < -TOL for v in crosses)

    return not (has_positive and has_negative)


def _primitive_inside_rectangle(primitive, corners):
    points = _points(primitive)

    if len(points) < 2:
        return False

    return all(
        _point_inside_or_on_rectangle(
            point,
            corners,
        )
        for point in points
    )


def _segment_length(segment):
    a, b = segment

    return math.hypot(
        float(b[0]) - float(a[0]),
        float(b[1]) - float(a[1]),
    )


def _rectangle_short_side_and_long_reference(
    document,
    rectangle_indices,
):
    items = []

    for index in rectangle_indices:
        segment = _single_segment(
            document.primitives[index]
        )

        if segment is None:
            return None

        items.append(
            (
                _segment_length(segment),
                segment,
            )
        )

    items.sort(key=lambda item: item[0])

    short_side = (
        items[0][0] + items[1][0]
    ) * 0.5

    long_reference = items[3][1]

    return short_side, long_reference


def _drawing_units_per_cm(document):
    unit_to_metre = {
        1: 0.0254,
        2: 0.3048,
        3: 1609.344,
        4: 0.001,
        5: 0.01,
        6: 1.0,
        7: 1000.0,
        8: 2.54e-8,
        9: 2.54e-5,
        10: 0.9144,
        11: 1e-10,
        12: 1e-9,
        13: 1e-6,
        14: 0.1,
        15: 10.0,
        16: 100.0,
        17: 1e9,
    }

    try:
        dxf = ezdxf.readfile(
            str(document.parsed_path)
        )
        code = int(
            dxf.header.get(
                "$INSUNITS",
                0,
            )
            or 0
        )

        metres_per_unit = unit_to_metre.get(code)

        if metres_per_unit:
            return 0.01 / metres_per_unit
    except Exception:
        pass

    return 10.0


def _segment_midpoint(segment):
    a, b = segment

    return (
        (float(a[0]) + float(b[0])) * 0.5,
        (float(a[1]) + float(b[1])) * 0.5,
    )


def _signed_offset_from_center(
    segment,
    rectangle_center,
    long_reference,
):
    a, b = long_reference

    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)

    if length <= 1e-12:
        return 0.0

    nx = -dy / length
    ny = dx / length

    midpoint = _segment_midpoint(segment)

    return (
        (midpoint[0] - rectangle_center[0]) * nx
        + (midpoint[1] - rectangle_center[1]) * ny
    )


def detect_window_family(
    document: CadDocument,
    *args,
    **kwargs,
) -> WindowDetectionResult:
    # KURAL 1:
    # 4 ayri cizginin uclari birbirine baglanarak
    # dikdortgen olusturmasi gerekir.
    #
    # KURAL 2:
    # Dikdortgenin kisa kenari en fazla 40 cm olabilir.
    #
    # KURAL 3:
    # Dikdortgenin icinde, uzun kenarlara paralel
    # TAM OLARAK 3 cizgi bulunmak zorundadir.
    #
    # KURAL 4:
    # Bu 3 cizginin sadece ortadaki tek cizgisi secilir.
    #
    # Dikdortgeni olusturan 4 cizgi secim disidir.

    line_indices = [
        index
        for index, primitive in enumerate(
            document.primitives
        )
        if _single_segment(primitive) is not None
    ]

    max_short_side = (
        40.0
        * _drawing_units_per_cm(document)
    )

    windows = []

    for rectangle_indices in _rectangle_candidates(
        document,
        line_indices,
    ):
        corners = _rectangle_corners(
            document,
            rectangle_indices,
        )

        if len(corners) != 4:
            continue

        shape = (
            _rectangle_short_side_and_long_reference(
                document,
                rectangle_indices,
            )
        )

        if shape is None:
            continue

        short_side, long_reference = shape

        if short_side > max_short_side:
            continue

        rectangle_center = (
            sum(float(p[0]) for p in corners) / 4.0,
            sum(float(p[1]) for p in corners) / 4.0,
        )

        inside_parallel = []

        for index in line_indices:
            if index in rectangle_indices:
                continue

            primitive = document.primitives[index]

            if not _primitive_inside_rectangle(
                primitive,
                corners,
            ):
                continue

            segment = _single_segment(primitive)

            if segment is None:
                continue

            if not _parallel(
                segment,
                long_reference,
            ):
                continue

            inside_parallel.append(
                (
                    _signed_offset_from_center(
                        segment,
                        rectangle_center,
                        long_reference,
                    ),
                    index,
                )
            )

        if len(inside_parallel) != 3:
            continue

        inside_parallel.sort(
            key=lambda item: item[0]
        )

        selected_index = (
            inside_parallel[1][1]
        )

        selected_primitive = (
            document.primitives[selected_index]
        )

        layer = str(
            getattr(
                selected_primitive,
                "layer",
                "",
            )
            or ""
        )

        selected_layer_indices = []
        selected_layer_lines = []

        for index, primitive in enumerate(
            document.primitives
        ):
            primitive_layer = str(
                getattr(
                    primitive,
                    "layer",
                    "",
                )
                or ""
            )

            if primitive_layer != layer:
                continue

            selected_layer_indices.append(index)
            selected_layer_lines.extend(
                _segments(primitive)
            )

        windows.append(
            WindowCandidate(
                rectangle_indices=rectangle_indices,
                layer=layer,
                corners=tuple(corners),
                lines=tuple(
                    selected_layer_lines
                ),
                primitive_indices=tuple(
                    selected_layer_indices
                ),
            )
        )

    return WindowDetectionResult(
        windows=tuple(windows)
    )
