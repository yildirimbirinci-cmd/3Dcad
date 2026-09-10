from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import ezdxf

from cad.model import CadDocument
from cad.wall_rulebook import (
    door_primitive_indices,
    primitive_indices_to_segments,
    primitive_layer,
    primitive_segments,
    primitive_touches_segments,
    window_primitive_indices,
)


_ENDPOINT_TOL = 1e-6
_PARALLEL_TOL = 1e-3


@dataclass(frozen=True, slots=True)
class WallCandidate:
    primitive_index: int
    layer: str


def _primitive_endpoints(primitive):
    points = tuple(getattr(primitive, "points", ()) or ())

    if len(points) < 2:
        return None

    a = points[0]
    b = points[-1]

    return (
        (float(a[0]), float(a[1])),
        (float(b[0]), float(b[1])),
    )


def _points_touch(a, b) -> bool:
    return hypot(
        float(a[0]) - float(b[0]),
        float(a[1]) - float(b[1]),
    ) <= _ENDPOINT_TOL


def _point_touches_segments(point, segments) -> bool:
    px, py = point

    for a, b in segments:
        ax, ay = a
        bx, by = b

        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy

        if length_sq <= _ENDPOINT_TOL * _ENDPOINT_TOL:
            if hypot(px - ax, py - ay) <= _ENDPOINT_TOL:
                return True
            continue

        t = ((px - ax) * dx + (py - ay) * dy) / length_sq

        if t < 0.0:
            qx, qy = ax, ay
        elif t > 1.0:
            qx, qy = bx, by
        else:
            qx = ax + t * dx
            qy = ay + t * dy

        if hypot(px - qx, py - qy) <= _ENDPOINT_TOL:
            return True

    return False


def _primitive_endpoint_touches_selected_endpoints(
    primitive,
    selected_endpoints,
) -> bool:
    endpoints = _primitive_endpoints(primitive)

    if endpoints is None:
        return False

    a, b = endpoints

    for selected_endpoint in selected_endpoints:
        if _points_touch(a, selected_endpoint):
            return True

        if _points_touch(b, selected_endpoint):
            return True

    return False


def _selected_endpoints(document, primitive_indices):
    result = []

    for index in primitive_indices:
        if index < 0 or index >= len(document.primitives):
            continue

        endpoints = _primitive_endpoints(
            document.primitives[index]
        )

        if endpoints is None:
            continue

        result.extend(endpoints)

    return tuple(result)


def _drawing_units_per_10cm(document) -> float:
    # 10 cm = 100 mm.
    # DXF/DWG INSUNITS is read generically. Unitless fallback is millimeters,
    # consistent with the existing CAD workflow.
    insunits = 4

    parsed_path = getattr(document, "parsed_path", None)

    if parsed_path:
        try:
            dxf = ezdxf.readfile(str(parsed_path))
            insunits = int(dxf.header.get("$INSUNITS", 4) or 4)
        except Exception:
            insunits = 4

    mm_per_unit = {
        1: 25.4,                 # inches
        2: 304.8,                # feet
        3: 1609344.0,            # miles
        4: 1.0,                  # millimeters
        5: 10.0,                 # centimeters
        6: 1000.0,               # meters
        7: 1000000.0,            # kilometers
        8: 0.0000254,            # microinches
        9: 0.0254,               # mils
        10: 914.4,               # yards
        11: 0.0000001,           # angstroms
        12: 0.000001,            # nanometers
        13: 0.001,               # microns
        14: 100.0,               # decimeters
        15: 10000.0,             # decameters
        16: 100000.0,            # hectometers
        17: 1000000000000.0,     # gigameters
    }.get(insunits, 1.0)

    return 100.0 / mm_per_unit


def _segment_direction(segment):
    (ax, ay), (bx, by) = segment
    dx = bx - ax
    dy = by - ay
    length = hypot(dx, dy)

    if length <= _ENDPOINT_TOL:
        return None

    return dx / length, dy / length


def _segments_parallel(segment_a, segment_b) -> bool:
    da = _segment_direction(segment_a)
    db = _segment_direction(segment_b)

    if da is None or db is None:
        return False

    cross = abs(da[0] * db[1] - da[1] * db[0])
    return cross <= _PARALLEL_TOL


def _parallel_line_distance(segment_a, segment_b) -> float:
    (ax, ay), (bx, by) = segment_a
    (cx, cy), _ = segment_b

    dx = bx - ax
    dy = by - ay
    length = hypot(dx, dy)

    if length <= _ENDPOINT_TOL:
        return 0.0

    return abs(
        dy * (cx - ax) - dx * (cy - ay)
    ) / length


def _has_selected_parallel_at_least_distance(
    document,
    primitive_index,
    selected_indices,
    minimum_distance,
) -> bool:
    primitive = document.primitives[primitive_index]
    own_segments = primitive_segments(primitive)

    for other_index in selected_indices:
        if other_index == primitive_index:
            continue

        other = document.primitives[other_index]

        for segment_a in own_segments:
            for segment_b in primitive_segments(other):
                if not _segments_parallel(segment_a, segment_b):
                    continue

                if _parallel_line_distance(
                    segment_a,
                    segment_b,
                ) >= minimum_distance:
                    return True

    return False


def _touches_exactly_one_end_to_windows_and_selected_walls(
    document,
    primitive_index,
    selected_indices,
    door_segments,
    window_segments,
) -> bool:
    primitive = document.primitives[primitive_index]
    endpoints = _primitive_endpoints(primitive)

    if endpoints is None:
        return False

    other_selected = set(selected_indices)
    other_selected.discard(primitive_index)

    selected_wall_segments = primitive_indices_to_segments(
        document,
        other_selected,
    )

    target_segments = (
        tuple(door_segments)
        + tuple(window_segments)
        + tuple(selected_wall_segments)
    )

    a, b = endpoints

    a_touches = _point_touches_segments(a, target_segments)
    b_touches = _point_touches_segments(b, target_segments)

    return a_touches != b_touches


def _build_collinear_overlap_owner_map(document, claimed_indices):
    # Only simple 2-point straight primitives are considered.
    # If a same-layer line is fully contained in a longer collinear line,
    # the longer line becomes its wall-selection owner.
    records_by_layer = {}

    for index, primitive in enumerate(document.primitives):
        if index in claimed_indices:
            continue

        points = tuple(getattr(primitive, "points", ()) or ())
        if len(points) != 2:
            continue

        segments = primitive_segments(primitive)
        if len(segments) != 1:
            continue

        segment = segments[0]
        direction = _segment_direction(segment)
        if direction is None:
            continue

        ux, uy = direction
        if ux < -_ENDPOINT_TOL or (
            abs(ux) <= _ENDPOINT_TOL and uy < -_ENDPOINT_TOL
        ):
            ux = -ux
            uy = -uy

        (ax, ay), (bx, by) = segment
        nx, ny = -uy, ux
        offset = ax * nx + ay * ny

        # Quantization is only for grouping near-identical lines.
        key = (
            primitive_layer(primitive),
            round(ux, 6),
            round(uy, 6),
            round(offset, 6),
        )

        t0 = ax * ux + ay * uy
        t1 = bx * ux + by * uy
        lo, hi = sorted((t0, t1))

        records_by_layer.setdefault(key, []).append(
            (index, lo, hi, hi - lo)
        )

    owner = {}

    for records in records_by_layer.values():
        if len(records) < 2:
            continue

        # Longest first. A short line can only be owned by a longer one.
        records = sorted(records, key=lambda item: item[3], reverse=True)

        for pos, (short_index, short_lo, short_hi, short_len) in enumerate(records):
            best_index = None
            best_len = short_len

            for long_index, long_lo, long_hi, long_len in records[:pos]:
                if long_len <= short_len + _ENDPOINT_TOL:
                    continue

                if (
                    long_lo <= short_lo + _ENDPOINT_TOL
                    and long_hi >= short_hi - _ENDPOINT_TOL
                ):
                    if long_len > best_len:
                        best_index = long_index
                        best_len = long_len

            if best_index is not None:
                owner[short_index] = best_index

    return owner


def detect_walls(
    document: CadDocument,
    door_candidates=None,
    window_candidates=None,
    *args,
    **kwargs,
):
    # DUVAR KURAL 1 + KURAL 2 + KURAL 3 GENISLETILMIS
    #
    # KURAL 1:
    # - Kapi ve pencere olarak secilmis cizgiler baska secim icin kullanilamaz.
    # - Kapi cizgilerine dokunan her cizgi duvardir.
    # - Bu ilk duvar cizgilerinin layer/layerlari izinli duvar layerlaridir.
    # - Bundan sonra bu layerlarin disindaki hicbir cizgi duvar secilemez.
    #
    # KURAL 2:
    # - Yalnizca izinli duvar layerlarinda olmak sartiyla,
    #   pencere cizgilerine dokunan her cizgi de duvardir.
    #
    # KURAL 3:
    # - Mevcut secili duvar cizgilerine uctan uca temas eden,
    #   izinli layerdaki tum cizgiler duvar olarak secilir.
    # - Yeni secilen her cizgi de ayni kurala dahil edilir.
    # - Uctan uca yeni temas eden cizgi kalmayana kadar devam edilir.
    #
    # KURAL 3 GENISLETME:
    # - Secilen bir cizgi, pencerelere ve diger secili duvar cizgilerine
    #   yalnizca TEK bir ucundan temas ediyorsa secimden cikarilir.
    # - Secilen bir cizginin paralelinde, en az 10 cm uzakta baska bir
    #   secili cizgi yoksa secimden cikarilir.
    #
    # Baska hicbir duvar kurali uygulanmaz.

    door_indices = door_primitive_indices(door_candidates)
    window_indices = window_primitive_indices(window_candidates)

    claimed_indices = set(door_indices)
    claimed_indices.update(window_indices)

    overlap_owner = _build_collinear_overlap_owner_map(
        document,
        claimed_indices,
    )

    door_segments = primitive_indices_to_segments(
        document,
        door_indices,
    )

    window_segments = primitive_indices_to_segments(
        document,
        window_indices,
    )

    if not door_segments:
        return []

    selected_indices = set()
    allowed_layers = set()

    # KURAL 1
    for index, primitive in enumerate(document.primitives):
        if index in claimed_indices:
            continue

        if not primitive_segments(primitive):
            continue

        if primitive_touches_segments(
            primitive,
            door_segments,
        ):
            selected_index = overlap_owner.get(index, index)
            selected_indices.add(selected_index)
            allowed_layers.add(
                primitive_layer(document.primitives[selected_index])
            )

    if not allowed_layers:
        return [
            WallCandidate(
                primitive_index=index,
                layer=primitive_layer(document.primitives[index]),
            )
            for index in sorted(selected_indices)
        ]

    # KURAL 2
    if window_segments:
        for index, primitive in enumerate(document.primitives):
            if index in claimed_indices:
                continue

            if primitive_layer(primitive) not in allowed_layers:
                continue

            if not primitive_segments(primitive):
                continue

            if primitive_touches_segments(
                primitive,
                window_segments,
            ):
                selected_indices.add(
                    overlap_owner.get(index, index)
                )

    # KURAL 3 - uctan uca devamliilik
    while True:
        selected_endpoints = _selected_endpoints(
            document,
            selected_indices,
        )

        newly_selected = set()

        for index, primitive in enumerate(document.primitives):
            if index in claimed_indices:
                continue

            if index in selected_indices:
                continue

            if primitive_layer(primitive) not in allowed_layers:
                continue

            if not primitive_segments(primitive):
                continue

            if _primitive_endpoint_touches_selected_endpoints(
                primitive,
                selected_endpoints,
            ):
                newly_selected.add(
                    overlap_owner.get(index, index)
                )

        if not newly_selected:
            break

        selected_indices.update(newly_selected)

    # YENI KURAL:
    # Ayni anda kendi HER IKI UCUNDAN;
    # secilmis duvar cizgilerinin, kapi cizgilerinin veya pencere
    # cizgilerinin uclarina temas eden izinli-layer cizgileri duvardir.
    selected_endpoints = _selected_endpoints(
        document,
        selected_indices,
    )
    door_endpoints = _selected_endpoints(
        document,
        door_indices,
    )
    window_endpoints = _selected_endpoints(
        document,
        window_indices,
    )

    target_endpoints = (
        tuple(selected_endpoints)
        + tuple(door_endpoints)
        + tuple(window_endpoints)
    )

    both_endpoint_indices = set()

    for index, primitive in enumerate(document.primitives):
        if index in claimed_indices:
            continue

        if index in selected_indices:
            continue

        if primitive_layer(primitive) not in allowed_layers:
            continue

        endpoints = _primitive_endpoints(primitive)

        if endpoints is None:
            continue

        a, b = endpoints

        a_touches = any(
            _points_touch(a, target)
            for target in target_endpoints
        )

        b_touches = any(
            _points_touch(b, target)
            for target in target_endpoints
        )

        if a_touches and b_touches:
            both_endpoint_indices.add(
                overlap_owner.get(index, index)
            )

    selected_indices.update(both_endpoint_indices)

    # KURAL 3 GENISLETME - secimden ihrac
    minimum_parallel_distance = _drawing_units_per_10cm(
        document
    )

    excluded_indices = set()

    for index in selected_indices:
        if _touches_exactly_one_end_to_windows_and_selected_walls(
            document,
            index,
            selected_indices,
            door_segments,
            window_segments,
        ):
            excluded_indices.add(index)
            continue

        if not _has_selected_parallel_at_least_distance(
            document,
            index,
            selected_indices,
            minimum_parallel_distance,
        ):
            excluded_indices.add(index)

    selected_indices.difference_update(excluded_indices)

    return [
        WallCandidate(
            primitive_index=index,
            layer=primitive_layer(document.primitives[index]),
        )
        for index in sorted(selected_indices)
    ]
