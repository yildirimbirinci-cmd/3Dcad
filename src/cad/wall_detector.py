from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from cad.model import CadDocument, CadPolyline
from cad.wall_rulebook import (
    TOL,
    door_primitive_indices,
    point_segment_distance,
    primitive_indices_to_segments,
    primitive_layer,
    primitive_segments,
    window_primitive_indices,
)


@dataclass(frozen=True, slots=True)
class WallCandidate:
    primitive_index: int
    layer: str


def available_wall_primitive_indices(
    document: CadDocument,
    door_candidates=None,
    window_candidates=None,
):
    door_indices = set(
        door_primitive_indices(door_candidates)
    )

    window_indices = set(
        window_primitive_indices(window_candidates)
    )

    claimed_indices = door_indices | window_indices

    return tuple(
        index
        for index in range(len(document.primitives))
        if index not in claimed_indices
    )


def _primitive_endpoints(primitive):
    endpoints = []

    for a, b in primitive_segments(primitive):
        endpoints.append(
            (float(a[0]), float(a[1]))
        )
        endpoints.append(
            (float(b[0]), float(b[1]))
        )

    return tuple(endpoints)


def _points_touch(a, b) -> bool:
    return hypot(
        float(a[0]) - float(b[0]),
        float(a[1]) - float(b[1]),
    ) <= TOL


def _endpoint_touches_segments(
    endpoint,
    segments,
) -> bool:
    for a, b in segments:
        if point_segment_distance(
            endpoint,
            a,
            b,
        ) <= TOL:
            return True

    return False


def _primitive_source_touching_endpoints(
    primitive,
    source_segments,
):
    result = []

    for endpoint in _primitive_endpoints(primitive):
        if _endpoint_touches_segments(
            endpoint,
            source_segments,
        ):
            result.append(endpoint)

    return tuple(result)


def _endpoint_touches_other_wall_endpoint(
    document,
    primitive_index,
    endpoint,
    wall_indices,
) -> bool:
    for other_index in wall_indices:
        if other_index == primitive_index:
            continue

        other_primitive = document.primitives[other_index]

        for other_endpoint in _primitive_endpoints(
            other_primitive
        ):
            if _points_touch(
                endpoint,
                other_endpoint,
            ):
                return True

    return False


def _has_source_and_wall_continuity(
    document,
    primitive_index,
    source_segments,
    wall_indices,
) -> bool:
    primitive = document.primitives[primitive_index]
    endpoints = _primitive_endpoints(primitive)

    for source_endpoint in endpoints:
        if not _endpoint_touches_segments(
            source_endpoint,
            source_segments,
        ):
            continue

        for other_endpoint in endpoints:
            if other_endpoint == source_endpoint:
                continue

            if _endpoint_touches_other_wall_endpoint(
                document,
                primitive_index,
                other_endpoint,
                wall_indices,
            ):
                return True

    return False


def _primitive_touches_selected_wall_endpoint(
    document,
    primitive_index,
    selected_indices,
) -> bool:
    primitive = document.primitives[primitive_index]

    for endpoint in _primitive_endpoints(primitive):
        if _endpoint_touches_other_wall_endpoint(
            document,
            primitive_index,
            endpoint,
            selected_indices,
        ):
            return True

    return False


def _segment_length(a, b) -> float:
    return hypot(
        float(b[0]) - float(a[0]),
        float(b[1]) - float(a[1]),
    )


def _unit_direction(a, b):
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = hypot(dx, dy)

    if length <= TOL:
        return None

    return (
        dx / length,
        dy / length,
    )


def _directions_parallel(direction_a, direction_b) -> bool:
    if direction_a is None or direction_b is None:
        return False

    cross = (
        direction_a[0] * direction_b[1]
        - direction_a[1] * direction_b[0]
    )

    return abs(cross) <= TOL


def _connector_is_perpendicular(
    endpoint_a,
    endpoint_b,
    wall_direction,
) -> bool:
    connector_direction = _unit_direction(
        endpoint_a,
        endpoint_b,
    )

    if connector_direction is None:
        return False

    dot = abs(
        connector_direction[0] * wall_direction[0]
        + connector_direction[1] * wall_direction[1]
    )

    return dot <= TOL


def _selected_wall_segments(
    document,
    selected_indices,
):
    segments = []

    for primitive_index in selected_indices:
        primitive = document.primitives[primitive_index]

        for segment_index, (a, b) in enumerate(
            primitive_segments(primitive)
        ):
            if _segment_length(a, b) <= TOL:
                continue

            segments.append(
                (
                    primitive_index,
                    segment_index,
                    (
                        (float(a[0]), float(a[1])),
                        (float(b[0]), float(b[1])),
                    ),
                )
            )

    return tuple(segments)


def _endpoint_degree(
    point,
    wall_segments,
) -> int:
    degree = 0

    for _, _, (a, b) in wall_segments:
        if _points_touch(point, a):
            degree += 1

        if _points_touch(point, b):
            degree += 1

    return degree


def _open_wall_endpoints(
    wall_segments,
):
    """
    Secilmis duvar aginda yalnizca tek bir duvar segmentine
    ait olan gercek acik uclari dondurur.
    """

    result = []

    for record_index, (
        primitive_index,
        segment_index,
        (a, b),
    ) in enumerate(wall_segments):

        direction_ab = _unit_direction(a, b)

        if direction_ab is None:
            continue

        if _endpoint_degree(a, wall_segments) == 1:
            result.append(
                (
                    record_index,
                    primitive_index,
                    segment_index,
                    a,
                    direction_ab,
                )
            )

        if _endpoint_degree(b, wall_segments) == 1:
            result.append(
                (
                    record_index,
                    primitive_index,
                    segment_index,
                    b,
                    (-direction_ab[0], -direction_ab[1]),
                )
            )

    return tuple(result)


def _existing_line_connects_points(
    document,
    point_a,
    point_b,
) -> bool:
    """
    Iki acik ucu zaten dogrudan birlestiren CAD segmenti
    varsa yeni connector olusturulmaz.
    """

    for primitive in document.primitives:
        for a, b in primitive_segments(primitive):
            if (
                _points_touch(point_a, a)
                and _points_touch(point_b, b)
            ):
                return True

            if (
                _points_touch(point_a, b)
                and _points_touch(point_b, a)
            ):
                return True

    return False


def _existing_wall_cap_lengths(
    document,
    selected_indices,
):
    """
    Cizimde zaten gercekten mevcut olan duvar kapatma
    segmentlerinin uzunluklarini bulur.

    Bir segmentin iki ucunda da, kendisine dik ve birbirine
    paralel secilmis duvar segmentleri bulunuyorsa bu segment
    gercek bir duvar kapatma cizgisi olarak kabul edilir.
    """

    wall_segments = _selected_wall_segments(
        document,
        selected_indices,
    )

    result = []

    for (
        cap_primitive,
        cap_segment,
        (cap_a, cap_b),
    ) in wall_segments:

        cap_direction = _unit_direction(
            cap_a,
            cap_b,
        )

        if cap_direction is None:
            continue

        touching_a = []
        touching_b = []

        for (
            wall_primitive,
            wall_segment,
            (wall_a, wall_b),
        ) in wall_segments:

            if (
                wall_primitive == cap_primitive
                and wall_segment == cap_segment
            ):
                continue

            wall_direction = _unit_direction(
                wall_a,
                wall_b,
            )

            if wall_direction is None:
                continue

            if (
                _points_touch(cap_a, wall_a)
                or _points_touch(cap_a, wall_b)
            ):
                touching_a.append(
                    wall_direction
                )

            if (
                _points_touch(cap_b, wall_a)
                or _points_touch(cap_b, wall_b)
            ):
                touching_b.append(
                    wall_direction
                )

        found = False

        for direction_a in touching_a:
            for direction_b in touching_b:

                if not _directions_parallel(
                    direction_a,
                    direction_b,
                ):
                    continue

                dot_a = abs(
                    cap_direction[0] * direction_a[0]
                    + cap_direction[1] * direction_a[1]
                )

                dot_b = abs(
                    cap_direction[0] * direction_b[0]
                    + cap_direction[1] * direction_b[1]
                )

                if dot_a > TOL:
                    continue

                if dot_b > TOL:
                    continue

                result.append(
                    _segment_length(
                        cap_a,
                        cap_b,
                    )
                )

                found = True
                break

            if found:
                break

    return tuple(result)


def _remove_old_synthetic_wall_connectors(
    document,
):
    """
    Ayni CadDocument tekrar hesaplanirsa onceki yapay
    connector'lar yeni hesaba dahil edilmez.
    """

    document.primitives[:] = [
        primitive
        for primitive in document.primitives
        if getattr(
            primitive,
            "source_type",
            "",
        ) != "SYNTHETIC_WALL_CONNECTOR"
    ]


def _build_missing_parallel_wall_connectors(
    document,
    selected_indices,
):
    """
    ACIK UC KAPATMA KURALI

    Program yalnizca cizimde gercek duvar kalinligi olarak
    gozlemlenmis mesafeler icindeki eksik kapatma cizgisini
    olusturabilir.

    Uzak paralel duvarlar veya farkli bina/oda kisimlari
    birbirine baglanamaz.
    """

    wall_segments = _selected_wall_segments(
        document,
        selected_indices,
    )

    open_endpoints = _open_wall_endpoints(
        wall_segments,
    )

    if len(open_endpoints) < 2:
        return ()

    real_cap_lengths = _existing_wall_cap_lengths(
        document,
        selected_indices,
    )

    if not real_cap_lengths:
        return ()

    max_real_wall_width = max(
        real_cap_lengths
    )

    compatible = {}

    for i in range(len(open_endpoints)):

        (
            record_a,
            primitive_a,
            segment_a,
            point_a,
            direction_a,
        ) = open_endpoints[i]

        compatible[i] = []

        for j in range(len(open_endpoints)):

            if i == j:
                continue

            (
                record_b,
                primitive_b,
                segment_b,
                point_b,
                direction_b,
            ) = open_endpoints[j]

            if record_a == record_b:
                continue

            if _points_touch(
                point_a,
                point_b,
            ):
                continue

            if not _directions_parallel(
                direction_a,
                direction_b,
            ):
                continue

            facing_dot = (
                direction_a[0] * direction_b[0]
                + direction_a[1] * direction_b[1]
            )

            if facing_dot <= 0.0:
                continue

            if not _connector_is_perpendicular(
                point_a,
                point_b,
                direction_a,
            ):
                continue

            if _existing_line_connects_points(
                document,
                point_a,
                point_b,
            ):
                continue

            distance = _segment_length(
                point_a,
                point_b,
            )

            # KRITIK KURAL:
            # Eksik kapatma mesafesi cizimde gozlemlenmis
            # gercek duvar kalinligindan buyuk olamaz.
            if distance > max_real_wall_width:
                continue

            compatible[i].append(
                (
                    distance,
                    j,
                )
            )

    nearest = {}

    for endpoint_index, candidates in compatible.items():

        if not candidates:
            continue

        candidates.sort(
            key=lambda item: item[0]
        )

        nearest[endpoint_index] = (
            candidates[0][1]
        )

    used_endpoints = set()
    connectors = []

    for endpoint_index_a in sorted(nearest):

        if endpoint_index_a in used_endpoints:
            continue

        endpoint_index_b = nearest[
            endpoint_index_a
        ]

        if nearest.get(
            endpoint_index_b
        ) != endpoint_index_a:
            continue

        if endpoint_index_b in used_endpoints:
            continue

        (
            record_a,
            primitive_a,
            segment_a,
            point_a,
            direction_a,
        ) = open_endpoints[
            endpoint_index_a
        ]

        (
            record_b,
            primitive_b,
            segment_b,
            point_b,
            direction_b,
        ) = open_endpoints[
            endpoint_index_b
        ]

        layer_a = primitive_layer(
            document.primitives[
                primitive_a
            ]
        )

        connector = CadPolyline(
            points=(
                point_a,
                point_b,
            ),
            layer=layer_a,
            color=(215, 215, 215),
            closed=False,
            source_type="SYNTHETIC_WALL_CONNECTOR",
        )

        document.primitives.append(
            connector
        )

        connector_index = (
            len(document.primitives) - 1
        )

        connectors.append(
            connector_index
        )

        used_endpoints.add(
            endpoint_index_a
        )

        used_endpoints.add(
            endpoint_index_b
        )

    return tuple(connectors)

def detect_walls(
    document: CadDocument,
    door_candidates=None,
    window_candidates=None,
    *args,
    **kwargs,
):
    """
    WALL RULES

    1. Kapi cizgilerine kendi ucundan temas eden cizgiler
       ilk duvar adaylarini olusturur.

    2. Bu ilk secimin layer/layerlari izinli duvar
       layerlaridir. Diger layerlar elenir.

    3. Pencere cizgilerine kendi ucundan temas eden,
       izinli layerdaki cizgiler de duvar adayi olabilir.

    4. Kapi veya pencereye temas eden aday cizginin diger
       ucu baska bir duvar cizgisinin ucuna temas etmiyorsa
       duvar olarak tanimlanamaz.

    5. Secilmis duvara uctan uca temas eden izinli-layer
       cizgileri, uctan uca temas sonlanana kadar secilir.

    6. Secilmis paralel iki duvarin ayni taraftaki acik
       uclari arasinda kapatma cizgisi yoksa program
       eksik duvar cizgisini olusturur.
    """

    available_indices = available_wall_primitive_indices(
        document,
        door_candidates,
        window_candidates,
    )

    door_indices = set(
        door_primitive_indices(door_candidates)
    )

    window_indices = set(
        window_primitive_indices(window_candidates)
    )

    door_segments = primitive_indices_to_segments(
        document,
        door_indices,
    )

    window_segments = primitive_indices_to_segments(
        document,
        window_indices,
    )

    # ---------------------------------------------------------
    # 1. KAPI TEMASLI ILK ADAYLAR
    # ---------------------------------------------------------

    initial_door_indices = set()

    for index in available_indices:
        primitive = document.primitives[index]

        if _primitive_source_touching_endpoints(
            primitive,
            door_segments,
        ):
            initial_door_indices.add(index)

    # ---------------------------------------------------------
    # 2. IZINLI WALL LAYERLARI
    # ---------------------------------------------------------

    allowed_wall_layers = {
        primitive_layer(document.primitives[index])
        for index in initial_door_indices
    }

    if not allowed_wall_layers:
        return []

    # ---------------------------------------------------------
    # 3. KAPI + PENCERE TEMASLI ADAYLAR
    # ---------------------------------------------------------

    source_candidate_indices = set()

    for index in available_indices:
        primitive = document.primitives[index]

        if primitive_layer(
            primitive
        ) not in allowed_wall_layers:
            continue

        touches_door = bool(
            _primitive_source_touching_endpoints(
                primitive,
                door_segments,
            )
        )

        touches_window = bool(
            _primitive_source_touching_endpoints(
                primitive,
                window_segments,
            )
        )

        if touches_door or touches_window:
            source_candidate_indices.add(index)

    # ---------------------------------------------------------
    # 4. DIGER UC BASKA DUVAR UCUNA TEMAS ETMELI
    # ---------------------------------------------------------

    selected_indices = {
        index
        for index in source_candidate_indices
        if _has_source_and_wall_continuity(
            document,
            index,
            door_segments + window_segments,
            source_candidate_indices,
        )
    }

    # ---------------------------------------------------------
    # 5. UCTAN UCA DUVAR DEVAMLILIGI
    # ---------------------------------------------------------

    while True:
        newly_selected = set()

        for index in available_indices:
            if index in selected_indices:
                continue

            primitive = document.primitives[index]

            if primitive_layer(
                primitive
            ) not in allowed_wall_layers:
                continue

            if _primitive_touches_selected_wall_endpoint(
                document,
                index,
                selected_indices,
            ):
                newly_selected.add(index)

        if not newly_selected:
            break

        selected_indices.update(
            newly_selected
        )

    # ---------------------------------------------------------
    # 6. EKSIK PARALEL DUVAR KAPATMA CIZGILERI
    # ---------------------------------------------------------

    connector_indices = (
        _build_missing_parallel_wall_connectors(
            document,
            selected_indices,
        )
    )

    selected_indices.update(
        connector_indices
    )

    # ---------------------------------------------------------
    return [
        WallCandidate(
            primitive_index=index,
            layer=primitive_layer(
                document.primitives[index]
            ),
        )
        for index in sorted(selected_indices)
    ]