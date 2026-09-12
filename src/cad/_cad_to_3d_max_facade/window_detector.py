from __future__ import annotations

import argparse
import math
from statistics import median


# CAD3D_COMMON_RULE_CORE_IMPORTS_V1
from cad._cad_to_3d_max_facade.geometry_core import (
    adaptive_tolerance as _core_adaptive_tolerance,
    distance2 as _core_distance2,
    directions_parallel as _core_directions_parallel,
    point2 as _core_point2,
    point_segment_distance as _core_point_segment_distance,
    polyline_length as _core_polyline_length,
)
from cad._cad_to_3d_max_facade.structural_rules import (
    extract_structural_segments as _core_extract_structural_segments,
    nearest_structural_segment as _core_nearest_structural_segment,
    nearest_wall_continuation as _core_nearest_wall_continuation,
    segment_direction as _core_segment_direction,
)

ENGINE = "CAD3D_PLAN_WINDOW_DETECTOR_V1"

KNOWN_WINDOW_LAYERS = {
    "3WINDOWS_P",
    "PDF2_0 windows",
}


# CAD3D_WINDOW_RECOGNITION_CONTRACT_V1
from cad._cad_to_3d_max_facade.recognition_contracts import (
    alternate as _recognition_alternate,
    require_all as _recognition_require_all,
    rule as _recognition_rule,
)

# CAD3D_WINDOW_ARCHITECTURAL_ENTITY_IMPORT_V1
from cad._cad_to_3d_max_facade.architectural_entities import (
    ENTITY_WINDOW as _ENTITY_WINDOW,
    create_entity as _create_architectural_entity,
)

def _point(value):
    return _core_point2(
        value,
        require_sequence=True,
        require_finite=True,
    )

def _distance(a, b):
    return _core_distance2(
        a,
        b,
    )

def _is_window_layer(layer):
    name = str(layer or "").strip()

    if name in KNOWN_WINDOW_LAYERS:
        return True

    upper = name.upper()

    return (
        "WINDOW" in upper
        or "PENCERE" in upper
        or "GLAZ" in upper
    )



# CAD3D_WINDOW_FACADE_WALL_SUPPORT_V3
def _is_wall_layer(layer):
    name = str(layer or "").strip()
    upper = name.upper()

    if _is_window_layer(name):
        return False

    if (
        "DOOR" in upper
        or "KAPI" in upper
    ):
        return False

    return (
        "WALL" in upper
        or "PARTITION" in upper
        or "DUVAR" in upper
    )



def _polyline_length(points):
    return _core_polyline_length(
        points,
        distance_fn=_distance,
    )

def _farthest_pair(points):
    if len(points) < 2:
        return None

    best = None
    best_distance = -1.0

    for i, a in enumerate(points):
        for b in points[i + 1:]:
            d = _distance(a, b)

            if d > best_distance:
                best_distance = d
                best = (a, b)

    return best


def _record(index, item):
    layer = str(
        item.get(
            "layer",
            "",
        )
        or ""
    ).strip()

    if not _is_window_layer(layer):
        return None

    points = []

    for value in item.get("points", []) or []:
        p = _point(value)

        if p is not None:
            points.append(p)

    if len(points) < 2:
        return None

    pair = _farthest_pair(points)

    if pair is None:
        return None

    a, b = pair

    major_length = _distance(a, b)

    if major_length <= 0.001:
        return None

    ux = (
        b[0] - a[0]
    ) / major_length

    uy = (
        b[1] - a[1]
    ) / major_length

    if (
        ux < 0.0
        or (
            abs(ux) <= 1.0e-9
            and uy < 0.0
        )
    ):
        ux = -ux
        uy = -uy

    cx = sum(
        p[0]
        for p in points
    ) / len(points)

    cy = sum(
        p[1]
        for p in points
    ) / len(points)

    return {
        "index": index,
        "item": item,
        "layer": layer,
        "points": points,
        "major_length": major_length,
        "polyline_length": _polyline_length(
            points
        ),
        "ux": ux,
        "uy": uy,
        "center": (cx, cy),
    }


def _projection_interval(record, ux, uy):
    values = [
        p[0] * ux
        + p[1] * uy
        for p in record["points"]
    ]

    return min(values), max(values)


def _parallel_overlap(a, b, band_gap):
    dot = abs(
        a["ux"] * b["ux"]
        + a["uy"] * b["uy"]
    )

    if dot < math.cos(
        math.radians(10.0)
    ):
        return False

    if (
        a["major_length"]
        >= b["major_length"]
    ):
        ux = a["ux"]
        uy = a["uy"]
    else:
        ux = b["ux"]
        uy = b["uy"]

    a0, a1 = _projection_interval(
        a,
        ux,
        uy,
    )

    b0, b1 = _projection_interval(
        b,
        ux,
        uy,
    )

    overlap = max(
        0.0,
        min(a1, b1)
        - max(a0, b0),
    )

    minimum_span = min(
        a1 - a0,
        b1 - b0,
    )

    if minimum_span <= 0.001:
        return False

    overlap_ratio = (
        overlap
        / minimum_span
    )

    if overlap_ratio < 0.45:
        return False

    nx = -uy
    ny = ux

    a_axis = (
        a["center"][0] * nx
        + a["center"][1] * ny
    )

    b_axis = (
        b["center"][0] * nx
        + b["center"][1] * ny
    )

    perpendicular_gap = abs(
        a_axis - b_axis
    )

    return (
        perpendicular_gap
        <= band_gap
    )


def _point_segment_distance(p, a, b):
    return _core_point_segment_distance(
        p,
        a,
        b,
        degenerate_epsilon=1.0e-12,
        distance_fn=_distance,
    )

def _wall_segments_from_geometry(
    geometry,
    structural_layer=None,
):
    return _core_extract_structural_segments(
        geometry,
        structural_layer=structural_layer,
        layer_acceptor=_is_wall_layer,
        point_parser=_point,
        minimum_length=1.0,
    )

def _nearest_wall_segment(
    point,
    wall_segments,
    required_direction=None,
    max_angle_deg=18.0,
):
    return _core_nearest_structural_segment(
        point,
        wall_segments,
        required_direction=required_direction,
        max_angle_deg=max_angle_deg,
        degenerate_epsilon=1.0e-12,
    )

def _segment_direction(segment):
    return _core_segment_direction(
        segment,
        min_length=1.0e-9,
    )

def _direction_parallel(
    a,
    b,
    max_angle_deg=15.0,
):
    return _core_directions_parallel(
        a,
        b,
        max_angle_deg=max_angle_deg,
    )

def _nearest_wall_continuation(
    jamb,
    wall_segments,
    window_direction,
    required_sign,
):
    return _core_nearest_wall_continuation(
        jamb,
        wall_segments,
        window_direction,
        required_sign,
        max_angle_deg=18.0,
        minimum_projection=1.0,
    )

def _classify_window_support(
    window,
    wall_segments,
):
    jamb_a = window.get(
        "jamb_a"
    )

    jamb_b = window.get(
        "jamb_b"
    )

    direction = window.get(
        "direction"
    )

    if (
        jamb_a is None
        or jamb_b is None
        or direction is None
    ):
        return {
            "classification": "unknown",
            "supported": False,
            "reason": "missing-window-axis",
        }

    if not wall_segments:
        return {
            "classification": "facade_window",
            "supported": True,
            "reason": "no-wall-geometry-fallback",
            "jamb_a_distance": None,
            "jamb_b_distance": None,
            "jamb_a_parallel": None,
            "jamb_b_parallel": None,
            "tolerance": None,
        }

    width = max(
        1.0,
        float(
            window.get(
                "width",
                0.0,
            )
            or 0.0
        ),
    )

    plan_thickness = max(
        0.0,
        float(
            window.get(
                "plan_thickness",
                0.0,
            )
            or 0.0
        ),
    )

    # A real wall window must have structural wall continuation
    # at BOTH ends of the opening.
    #
    # A = wall continues away in negative window-axis direction.
    # B = wall continues away in positive window-axis direction.
    wall_a, distance_a = (
        _nearest_wall_continuation(
            jamb_a,
            wall_segments,
            direction,
            -1,
        )
    )

    wall_b, distance_b = (
        _nearest_wall_continuation(
            jamb_b,
            wall_segments,
            direction,
            1,
        )
    )

    # Window graphics are normally centred inside the wall band,
    # so a small offset from the actual structural wall endpoint
    # is expected.
    # CAD3D_DETERMINISTIC_LOCAL_TOLERANCE_V1
    tolerance = _core_adaptive_tolerance(
        width=width,
        thickness=plan_thickness,
        minimum=180.0,
        maximum=450.0,
        width_ratio=0.08,
        thickness_ratio=1.25,
    )

    continuation_a = (
        wall_a is not None
        and distance_a <= tolerance
    )

    continuation_b = (
        wall_b is not None
        and distance_b <= tolerance
    )

    # CAD3D_WINDOW_DETERMINISTIC_DECISION_V1
    #
    # Recognition does not modify CAD geometry.
    # It receives already-computed evidence and produces
    # an explicit deterministic decision.

    support_rules = (
        _recognition_rule(
            "window.wall_continuation_a",
            continuation_a,
            actual=distance_a,
            expected=(
                "<= " + str(tolerance)
            ),
            reason=(
                "structural wall must continue "
                "from jamb A"
            ),
        ),
        _recognition_rule(
            "window.wall_continuation_b",
            continuation_b,
            actual=distance_b,
            expected=(
                "<= " + str(tolerance)
            ),
            reason=(
                "structural wall must continue "
                "from jamb B"
            ),
        ),
    )

    base_decision = (
        _recognition_require_all(
            "window",
            "facade_window",
            support_rules,
            accepted_reason=(
                "structural-wall-continuation-both-sides"
            ),
            rejected_reason=(
                "no-structural-wall-continuation"
            ),
            metadata={
                "jamb_a_distance": distance_a,
                "jamb_b_distance": distance_b,
                "tolerance": tolerance,
            },
        )
    )

    if base_decision.accepted:
        decision = base_decision
    else:
        decision = _recognition_alternate(
            "window",
            "rooflight",
            reason=(
                "no-structural-wall-continuation"
            ),
            rules=support_rules,
            metadata={
                "jamb_a_distance": distance_a,
                "jamb_b_distance": distance_b,
                "tolerance": tolerance,
            },
        )

    supported = decision.accepted
    classification = decision.classification
    reason = decision.reason

    return {
        "classification": classification,
        "supported": supported,
        "reason": reason,

        # Keep existing diagnostic field names so the current
        # runtime logger immediately shows continuation distances.
        "jamb_a_distance": distance_a,
        "jamb_b_distance": distance_b,

        "jamb_a_parallel": continuation_a,
        "jamb_b_parallel": continuation_b,

        "tolerance": tolerance,

        "wall_a_layer": (
            wall_a.get("layer")
            if wall_a
            else None
        ),

        "wall_b_layer": (
            wall_b.get("layer")
            if wall_b
            else None
        ),

        # Read-only recognition evidence.
        # Existing detector consumers may ignore this field.
        "recognition_contract": (
            decision.as_dict()
        ),
    }

def _geometry_distance(a, b):
    best = float("inf")

    for p in a["points"]:
        for q0, q1 in zip(
            b["points"],
            b["points"][1:],
        ):
            best = min(
                best,
                _point_segment_distance(
                    p,
                    q0,
                    q1,
                ),
            )

    for p in b["points"]:
        for q0, q1 in zip(
            a["points"],
            a["points"][1:],
        ):
            best = min(
                best,
                _point_segment_distance(
                    p,
                    q0,
                    q1,
                ),
            )

    return best


def _connected(a, b, band_gap, attach_gap):
    if _parallel_overlap(
        a,
        b,
        band_gap,
    ):
        return True

    gap = _geometry_distance(
        a,
        b,
    )

    if gap > attach_gap:
        return False

    center_distance = _distance(
        a["center"],
        b["center"],
    )

    scale = max(
        a["major_length"],
        b["major_length"],
    )

    return (
        center_distance
        <= (
            scale * 1.35
            + band_gap
        )
    )


def _components(records):
    if not records:
        return []

    lengths = [
        record["major_length"]
        for record in records
        if record["major_length"] > 0.0
    ]

    typical = (
        median(lengths)
        if lengths
        else 500.0
    )

    band_gap = min(
        450.0,
        max(
            80.0,
            typical * 0.45,
        ),
    )

    attach_gap = min(
        100.0,
        max(
            20.0,
            typical * 0.10,
        ),
    )

    adjacency = [
        set()
        for _ in records
    ]

    for i, a in enumerate(records):
        for j in range(
            i + 1,
            len(records),
        ):
            b = records[j]

            if _connected(
                a,
                b,
                band_gap,
                attach_gap,
            ):
                adjacency[i].add(j)
                adjacency[j].add(i)

    seen = set()
    output = []

    for start in range(len(records)):
        if start in seen:
            continue

        stack = [start]
        seen.add(start)

        component = []

        while stack:
            current = stack.pop()

            component.append(
                records[current]
            )

            for other in adjacency[current]:
                if other in seen:
                    continue

                seen.add(other)
                stack.append(other)

        output.append(component)

    return output


def _principal_window(component):
    points = []

    for record in component:
        points.extend(
            record["points"]
        )

    if len(points) < 2:
        return None

    cx = sum(
        p[0]
        for p in points
    ) / len(points)

    cy = sum(
        p[1]
        for p in points
    ) / len(points)

    xx = 0.0
    xy = 0.0
    yy = 0.0

    for x, y in points:
        dx = x - cx
        dy = y - cy

        xx += dx * dx
        xy += dx * dy
        yy += dy * dy

    theta = 0.5 * math.atan2(
        2.0 * xy,
        xx - yy,
    )

    ux = math.cos(theta)
    uy = math.sin(theta)

    if (
        ux < 0.0
        or (
            abs(ux) <= 1.0e-9
            and uy < 0.0
        )
    ):
        ux = -ux
        uy = -uy

    nx = -uy
    ny = ux

    along = [
        x * ux + y * uy
        for x, y in points
    ]

    across = [
        x * nx + y * ny
        for x, y in points
    ]

    t0 = min(along)
    t1 = max(along)

    s0 = min(across)
    s1 = max(across)

    width = t1 - t0
    thickness = s1 - s0

    if width < 120.0:
        return None

    s_center = (
        s0 + s1
    ) * 0.5

    jamb_a = (
        ux * t0
        + nx * s_center,
        uy * t0
        + ny * s_center,
    )

    jamb_b = (
        ux * t1
        + nx * s_center,
        uy * t1
        + ny * s_center,
    )

    center = (
        (
            jamb_a[0]
            + jamb_b[0]
        ) * 0.5,
        (
            jamb_a[1]
            + jamb_b[1]
        ) * 0.5,
    )

    layers = sorted(
        {
            record["layer"]
            for record in component
        }
    )

    indices = sorted(
        record["index"]
        for record in component
    )

    confidence = 0.99

    if len(component) == 1:
        confidence = 0.85

    return {
        "center": center,
        "jamb_a": jamb_a,
        "jamb_b": jamb_b,
        "width": width,
        "plan_thickness": thickness,
        "direction": (ux, uy),
        "source_layers": layers,
        "source_indices": indices,
        "source_count": len(component),
        "confidence": confidence,
    }


# CAD3D_WINDOW_ENTITY_ADAPTER_V1
def _window_to_architectural_entity(
    window,
    *,
    entity_id,
    geometry,
):
    """
    Read-only adapter.

    Existing window detector output is NOT modified.

    A rooflight is still recognized as an architectural
    window entity, but it receives no wall-opening permission.
    """

    if not isinstance(
        window,
        dict,
    ):
        raise TypeError(
            "Window entity adapter requires dict input."
        )

    classification = str(
        window.get(
            "classification",
            "unknown",
        )
        or "unknown"
    ).strip()

    center = _point(
        window.get(
            "center"
        )
    )

    jamb_a = _point(
        window.get(
            "jamb_a"
        )
    )

    jamb_b = _point(
        window.get(
            "jamb_b"
        )
    )

    direction = _point(
        window.get(
            "direction"
        )
    )

    try:
        width = abs(
            float(
                window.get(
                    "width",
                    0.0,
                )
                or 0.0
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        width = 0.0

    try:
        plan_thickness = abs(
            float(
                window.get(
                    "plan_thickness",
                    0.0,
                )
                or 0.0
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        plan_thickness = 0.0

    source_indices = []

    for value in (
        window.get(
            "source_indices",
            []
        )
        or []
    ):
        try:
            index = int(value)
        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            index >= 0
            and index < len(geometry)
        ):
            source_indices.append(
                index
            )

    source_items = [
        geometry[index]
        for index in source_indices
    ]

    source_layers = [
        str(value).strip()
        for value in (
            window.get(
                "source_layers",
                []
            )
            or []
        )
        if str(value).strip()
    ]

    source_layer = " | ".join(
        source_layers
    )

    # --------------------------------------------------------
    # ENTITY recognition:
    #
    # This answers:
    # "Did we recognize a valid window-like architectural
    #  entity"
    #
    # It is deliberately separate from:
    # "May this object cut a structural wall"
    # --------------------------------------------------------

    entity_rules = (
        _recognition_rule(
            "window_entity.center_valid",
            center is not None,
            actual=center,
            expected="valid 2D center",
            reason=(
                "window entity requires a valid center"
            ),
        ),

        _recognition_rule(
            "window_entity.axis_valid",
            (
                jamb_a is not None
                and jamb_b is not None
                and direction is not None
            ),
            actual={
                "jamb_a": jamb_a,
                "jamb_b": jamb_b,
                "direction": direction,
            },
            expected=(
                "jamb A, jamb B and direction"
            ),
            reason=(
                "window entity requires a complete plan axis"
            ),
        ),

        _recognition_rule(
            "window_entity.width_positive",
            width > 1.0e-9,
            actual=width,
            expected="> 0",
            reason=(
                "window entity width must be positive"
            ),
        ),

        _recognition_rule(
            "window_entity.source_geometry_present",
            bool(source_items),
            actual=len(source_items),
            expected=">= 1 source item",
            reason=(
                "window entity requires source CAD geometry"
            ),
        ),
    )

    entity_decision = (
        _recognition_require_all(
            "window",
            classification,
            entity_rules,
            accepted_reason=(
                "window-entity-geometry-valid"
            ),
            rejected_reason=(
                "window-entity-geometry-invalid"
            ),
            metadata={
                "classification":
                    classification,
                "source_count":
                    len(source_items),
            },
        )
    )

    wall_support = bool(
        window.get(
            "wall_support",
            False,
        )
    )

    support_contract = window.get(
        "recognition_contract",
        {}
    )

    if not isinstance(
        support_contract,
        dict,
    ):
        support_contract = {}

    structural_relation = {
        "classification":
            classification,

        "wall_supported":
            wall_support,

        "reason":
            window.get(
                "support_reason"
            ),

        "jamb_a_distance":
            window.get(
                "wall_support_jamb_a_distance"
            ),

        "jamb_b_distance":
            window.get(
                "wall_support_jamb_b_distance"
            ),

        "jamb_a_parallel":
            window.get(
                "wall_support_jamb_a_parallel"
            ),

        "jamb_b_parallel":
            window.get(
                "wall_support_jamb_b_parallel"
            ),

        "tolerance":
            window.get(
                "wall_support_tolerance"
            ),

        # Existing facade-vs-rooflight recognition contract.
        "support_contract":
            dict(
                support_contract
            ),
    }

    # --------------------------------------------------------
    # Execution permission is separate from recognition.
    #
    # Rooflight:
    #   recognized = True
    #   cut_wall_opening = False
    #
    # Facade window:
    #   recognized = True
    #   cut_wall_opening = True
    #   only when structural support is confirmed.
    # --------------------------------------------------------

    can_cut_wall = bool(
        entity_decision.accepted
        and classification
        == "facade_window"
        and wall_support
    )

    entity = (
        _create_architectural_entity(
            _ENTITY_WINDOW,

            entity_id=str(
                entity_id
            ),

            geometry={
                "center":
                    center,

                "jamb_a":
                    jamb_a,

                "jamb_b":
                    jamb_b,

                "width":
                    float(width),

                "plan_thickness":
                    float(
                        plan_thickness
                    ),

                "direction":
                    direction,
            },

            structural_relation=(
                structural_relation
            ),

            recognition_contract=(
                entity_decision.as_dict()
            ),

            source_geometry=(
                source_items
            ),

            source_layer=(
                source_layer
            ),

            execution_permissions={
                "cut_wall_opening":
                    can_cut_wall,
            },

            metadata={
                "classification":
                    classification,

                "source_layers":
                    source_layers,

                "source_indices":
                    source_indices,

                "source_count":
                    len(
                        source_items
                    ),

                # Existing detector confidence is metadata only.
                "legacy_confidence":
                    window.get(
                        "confidence"
                    ),
            },
        )
    )

    return entity


def detect_windows(
    geometry,
    structural_layer=None,
):
    geometry = list(
        geometry
        or []
    )

    records = []

    for index, item in enumerate(
        geometry
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        record = _record(
            index,
            item,
        )

        if record is not None:
            records.append(record)

    components = _components(
        records
    )

    wall_segments = (
        _wall_segments_from_geometry(
            geometry,
            structural_layer=structural_layer,
        )
    )

    windows = []
    rooflights = []

    for component in components:
        window = _principal_window(
            component
        )

        if window is None:
            continue

        support = (
            _classify_window_support(
                window,
                wall_segments,
            )
        )

        window["classification"] = (
            support.get(
                "classification",
                "unknown",
            )
        )

        window["support_reason"] = (
            support.get(
                "reason"
            )
        )

        window["wall_support"] = bool(
            support.get(
                "supported",
                False,
            )
        )

        window[
            "wall_support_jamb_a_distance"
        ] = support.get(
            "jamb_a_distance"
        )

        window[
            "wall_support_jamb_b_distance"
        ] = support.get(
            "jamb_b_distance"
        )

        window[
            "wall_support_tolerance"
        ] = support.get(
            "tolerance"
        )

        window[
            "wall_support_jamb_a_parallel"
        ] = support.get(
            "jamb_a_parallel"
        )

        window[
            "wall_support_jamb_b_parallel"
        ] = support.get(
            "jamb_b_parallel"
        )

        if (
            window["classification"]
            == "facade_window"
        ):
            windows.append(
                window
            )
        else:
            rooflights.append(
                window
            )

    windows.sort(
        key=lambda w: (
            round(
                w["center"][1],
                6,
            ),
            round(
                w["center"][0],
                6,
            ),
        )
    )

    rooflights.sort(
        key=lambda w: (
            round(
                w["center"][1],
                6,
            ),
            round(
                w["center"][0],
                6,
            ),
        )
    )

    source_indices = set()

    for index, window in enumerate(
        windows,
        start=1,
    ):
        window["window_id"] = (
            "W"
            + str(index).zfill(3)
        )

        source_indices.update(
            window[
                "source_indices"
            ]
        )

    for index, rooflight in enumerate(
        rooflights,
        start=1,
    ):
        rooflight["rooflight_id"] = (
            "R"
            + str(index).zfill(3)
        )

    source_geometry = [
        geometry[index]
        for index in sorted(
            source_indices
        )
        if (
            index >= 0
            and index < len(
                geometry
            )
        )
    ]

    # CAD3D_WINDOW_ENTITY_OUTPUT_V1
    # Parallel output only. Existing detector lists are unchanged.
    entities = []

    for index, window in enumerate(
        windows,
        start=1,
    ):
        entity = _window_to_architectural_entity(
            window,
            entity_id="W" + str(index).zfill(3),
            geometry=geometry,
        )
        entities.append(
            entity.as_dict()
        )

    for index, window in enumerate(
        rooflights,
        start=1,
    ):
        entity = _window_to_architectural_entity(
            window,
            entity_id="RL" + str(index).zfill(3),
            geometry=geometry,
        )
        entities.append(
            entity.as_dict()
        )

    # CAD3D_WINDOW_ENTITY_RUNTIME_AUDIT_V1
    try:
        from pathlib import Path as _EntityAuditPath
        _audit_path = (
            _EntityAuditPath(__file__).resolve().parents[2]
            / "logs"
            / "window_entity_audit.txt"
        )
        _audit_path.parent.mkdir(parents=True, exist_ok=True)
        _audit_lines = []
        _audit_lines.append("=== WINDOW ENTITY AUDIT V1 ===")
        _audit_lines.append("WINDOW COUNT: " + str(len(windows)))
        _audit_lines.append("ROOFLIGHT COUNT: " + str(len(rooflights)))
        _audit_lines.append("ENTITY COUNT: " + str(len(entities)))
        _audit_lines.append("")
        for _entity in entities:
            _rc = _entity.get("recognition_contract", {}) or {}
            _sr = _entity.get("structural_relation", {}) or {}
            _xp = _entity.get("execution_permissions", {}) or {}
            _md = _entity.get("metadata", {}) or {}
            _audit_lines.append(
                "ENTITY " + str(_entity.get("entity_id"))
                + " | type=" + repr(_entity.get("entity_type"))
                + " | classification=" + repr(_md.get("classification"))
                + " | recognized=" + repr(bool(_rc.get("accepted", False)))
                + " | wall_supported=" + repr(bool(_sr.get("wall_supported", False)))
                + " | cut_wall_opening=" + repr(bool(_xp.get("cut_wall_opening", False)))
                + " | reason=" + repr(_sr.get("reason"))
            )
        _audit_path.write_text(
            "\n".join(_audit_lines) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "engine": ENGINE,
        "window_count": len(
            windows
        ),
        "rooflight_count": len(
            rooflights
        ),
        "source_item_count": len(
            records
        ),
        "structural_layer": (
            str(
                structural_layer
                or ""
            ).strip()
        ),
        "wall_segment_count": len(
            wall_segments
        ),
        "windows": windows,
        "rooflights": rooflights,
        "source_geometry": source_geometry,
        "entity_count": len(entities),
        "entities": entities,
    }

def self_test():
    geometry = []

    for y in (
        0.0,
        40.0,
        80.0,
    ):
        geometry.append(
            {
                "layer": "3WINDOWS_P",
                "points": [
                    (0.0, y),
                    (1200.0, y),
                ],
            }
        )

    for y in (
        0.0,
        40.0,
        80.0,
    ):
        geometry.append(
            {
                "layer": "3WINDOWS_P",
                "points": [
                    (3000.0, y),
                    (4200.0, y),
                ],
            }
        )

    result = detect_windows(
        geometry
    )

    assert (
        result["window_count"]
        == 2
    ), result

    print(
        "WINDOW DETECTOR SELF-TEST: OK"
    )
    print(
        "WINDOWS:",
        result["window_count"],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
