from __future__ import annotations

import argparse
import math

from cad._cad_to_3d_max_facade.cad_intelligence import (
    extract_segments,
    infer_cad_profile,
    semantic_category,
)

ENGINE = "GENERIC_BATCH_DOOR_DETECTOR_V3"


# CAD3D_DOOR_COMMON_GEOMETRY_CORE_V2
from cad._cad_to_3d_max_facade.geometry_core import (
    distance2 as _core_distance2,
    point2 as _core_point2,
    point_segment_distance as _core_point_segment_distance,
    polyline_length as _core_polyline_length,
)

# CAD3D_DOOR_STRUCTURAL_RULES_V1
from cad._cad_to_3d_max_facade.structural_rules import (
    nearest_structural_segment as _core_nearest_structural_segment,
)

# CAD3D_DOOR_RECOGNITION_CONTRACT_IMPORT_V1
from cad._cad_to_3d_max_facade.recognition_contracts import (
    require_all as _recognition_require_all,
    rule as _recognition_rule,
)

# CAD3D_DOOR_ARCHITECTURAL_ENTITY_IMPORT_V1
from cad._cad_to_3d_max_facade.architectural_entities import (
    ENTITY_DOOR as _ENTITY_DOOR,
    create_entity as _create_architectural_entity,
)

def _point(value):
    return _core_point2(
        value,
        require_sequence=False,
        require_finite=False,
    )

def _distance(a, b):
    return _core_distance2(
        a,
        b,
    )

def _polyline_length(points):
    return _core_polyline_length(
        points,
        distance_fn=_distance,
    )

def _point_segment_distance(
    point,
    a,
    b,
):
    return _core_point_segment_distance(
        point,
        a,
        b,
        degenerate_epsilon=1.0e-18,
        distance_fn=_distance,
    )

def _circle_from_three_points(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c

    d = 2.0 * (
        ax * (by - cy)
        + bx * (cy - ay)
        + cx * (ay - by)
    )

    if abs(d) <= 1e-12:
        return None

    aa = ax * ax + ay * ay
    bb = bx * bx + by * by
    cc = cx * cx + cy * cy

    ux = (
        aa * (by - cy)
        + bb * (cy - ay)
        + cc * (ay - by)
    ) / d

    uy = (
        aa * (cx - bx)
        + bb * (ax - cx)
        + cc * (bx - ax)
    ) / d

    center = (ux, uy)
    radius = _distance(center, a)

    if not math.isfinite(radius) or radius <= 1e-9:
        return None

    return center, radius


def _mid_path_point(points):
    if len(points) < 3:
        return None

    lengths = [_distance(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)

    if total <= 1e-12:
        return points[len(points) // 2]

    half = total * 0.5
    walked = 0.0

    for index, length in enumerate(lengths):
        if walked + length >= half:
            if length <= 1e-12:
                return points[index]

            t = (half - walked) / length
            a = points[index]
            b = points[index + 1]

            return (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
            )

        walked += length

    return points[-1]


def _arc_candidate(item, profile):
    points = []

    for value in item.get("points") or []:
        p = _point(value)

        if p is None:
            continue

        if points and _distance(points[-1], p) <= 1e-9:
            continue

        points.append(p)

    if len(points) < 3 or bool(item.get("closed", False)):
        return None

    middle = _mid_path_point(points)

    if middle is None:
        return None

    circle = _circle_from_three_points(points[0], middle, points[-1])

    if circle is None:
        return None

    center, radius = circle
    diagonal = max(float(profile.get("drawing_diagonal", 1.0)), 1e-9)
    families = profile.get("gap_families") or []

    wall_gap = (
        float(families[0]["gap"])
        if families
        else max(
            float(profile.get("median_length", diagonal * 0.01)) * 0.20,
            diagonal * 0.001,
        )
    )

    min_radius = max(wall_gap * 1.80, diagonal * 0.0012)
    max_radius = max(wall_gap * 40.0, diagonal * 0.22)

    if not (min_radius <= radius <= max_radius):
        return None

    radial_errors = [abs(_distance(center, p) - radius) for p in points]
    radial_mean_error = sum(radial_errors) / max(1, len(radial_errors))
    radial_error_ratio = radial_mean_error / max(radius, 1e-9)

    if radial_error_ratio > 0.075:
        return None

    sweep_degrees = math.degrees(_polyline_length(points) / radius)

    if not (35.0 <= sweep_degrees <= 150.0):
        return None

    return {
        "center": center,
        "radius": radius,
        "start": points[0],
        "end": points[-1],
        "sweep_deg": sweep_degrees,
        "radial_error_ratio": radial_error_ratio,
        "layer": str(item.get("layer") or "").strip(),
        "wall_gap": wall_gap,
        "source_points": points,
    }



def _dedicated_door_arc_candidate(item, profile):
    points = []

    for value in item.get("points") or []:
        p = _point(value)

        if p is None:
            continue

        if points and _distance(points[-1], p) <= 1e-9:
            continue

        points.append(p)

    if len(points) < 3:
        return None

    middle = _mid_path_point(points)

    if middle is None:
        return None

    circle = _circle_from_three_points(
        points[0],
        middle,
        points[-1],
    )

    if circle is None:
        return None

    center, radius = circle

    diagonal = max(
        float(
            profile.get(
                "drawing_diagonal",
                1.0,
            )
        ),
        1e-9,
    )

    # Very broad architectural-opening bounds.
    # The exact source layer already provides the semantic evidence.
    min_radius = diagonal * 0.00035
    max_radius = diagonal * 0.25

    if not (
        min_radius
        <= radius
        <= max_radius
    ):
        return None

    radial_errors = [
        abs(
            _distance(
                center,
                p,
            )
            - radius
        )
        for p in points
    ]

    radial_mean_error = (
        sum(radial_errors)
        / max(
            1,
            len(radial_errors),
        )
    )

    radial_error_ratio = (
        radial_mean_error
        / max(
            radius,
            1e-9,
        )
    )

    if radial_error_ratio > 0.18:
        return None

    sweep_degrees = math.degrees(
        _polyline_length(points)
        / radius
    )

    if not (
        20.0
        <= sweep_degrees
        <= 180.0
    ):
        return None

    families = (
        profile.get(
            "gap_families"
        )
        or []
    )

    wall_gap = (
        float(
            families[0]["gap"]
        )
        if families
        else max(
            diagonal * 0.001,
            1.0,
        )
    )

    return {
        "center": center,
        "radius": radius,
        "start": points[0],
        "end": points[-1],
        "sweep_deg": sweep_degrees,
        "radial_error_ratio": radial_error_ratio,
        "layer": str(
            item.get(
                "layer"
            )
            or ""
        ).strip(),
        "wall_gap": wall_gap,
        "source_points": points,
        "dedicated_layer_fallback": True,
    }



# CAD3D_LOCAL_DOOR_AXIS_JAMBS_V3
# CAD3D_DOOR_JAMB_LINE_RESOLVER_V4
def _resolve_wall_gap_jambs(
    arc,
    wall_segments,
):
    # IMPORTANT:
    # Do NOT search for isolated wall ENDPOINTS.
    #
    # A real door opening in the structural wall drawing is bounded by
    # two short JAMB/CAP LINES. Those lines are approximately:
    # - perpendicular to the wall / closed-door axis,
    # - parallel to each other,
    # - separated by about one detected door radius,
    # - local to the detected door swing.
    #
    # The door arc is used only to establish:
    # - hinge location,
    # - two possible closed-door axes,
    # - approximate door width.
    #
    # Final jamb positions are the MIDPOINTS of the two detected
    # structural jamb lines. The full jamb lines are also retained.

    center = (
        float(arc["center"][0]),
        float(arc["center"][1]),
    )

    radius = float(
        arc["radius"]
    )

    if (
        radius <= 1e-9
        or not wall_segments
    ):
        return None

    axes = []

    for endpoint_name in (
        "start",
        "end",
    ):
        endpoint = arc.get(
            endpoint_name
        )

        if (
            endpoint is None
            or len(endpoint) < 2
        ):
            continue

        vx = (
            float(endpoint[0])
            - center[0]
        )

        vy = (
            float(endpoint[1])
            - center[1]
        )

        axis_length = math.hypot(
            vx,
            vy,
        )

        if axis_length <= 1e-9:
            continue

        axes.append(
            {
                "name": endpoint_name,
                "ux": vx / axis_length,
                "uy": vy / axis_length,
            }
        )

    if not axes:
        return None

    # Generic size limits relative to the detected door width.
    # Jamb/cap lines are short compared with the door opening.
    min_cap_length = radius * 0.015
    max_cap_length = radius * 0.48

    # Search only around this door.
    min_along = -radius * 0.30
    max_along = radius * 1.30
    max_cross = radius * 0.34

    # One line must be near the hinge and the other near one door width.
    hinge_along_tolerance = radius * 0.28
    far_along_tolerance = radius * 0.28

    # Pair geometry.
    min_width = radius * 0.68
    max_width = radius * 1.32

    best = None

    for axis in axes:
        ux = float(
            axis["ux"]
        )

        uy = float(
            axis["uy"]
        )

        nx = -uy
        ny = ux

        candidates = []

        for segment_index, segment in enumerate(
            wall_segments
        ):
            p0, p1 = _segment_points(
                segment
            )

            x0 = float(
                p0[0]
            )
            y0 = float(
                p0[1]
            )
            x1 = float(
                p1[0]
            )
            y1 = float(
                p1[1]
            )

            sx = x1 - x0
            sy = y1 - y0

            seg_length = math.hypot(
                sx,
                sy,
            )

            if not (
                min_cap_length
                <= seg_length
                <= max_cap_length
            ):
                continue

            sux = sx / seg_length
            suy = sy / seg_length

            # A jamb/cap line is approximately perpendicular to the
            # door opening / wall-run axis.
            perpendicularity = abs(
                sux * ux
                + suy * uy
            )

            if perpendicularity > 0.34:
                continue

            midpoint = (
                (x0 + x1) * 0.5,
                (y0 + y1) * 0.5,
            )

            dx = (
                midpoint[0]
                - center[0]
            )

            dy = (
                midpoint[1]
                - center[1]
            )

            along = (
                dx * ux
                + dy * uy
            )

            cross = (
                dx * nx
                + dy * ny
            )

            if not (
                min_along
                <= along
                <= max_along
            ):
                continue

            if abs(
                cross
            ) > max_cross:
                continue

            candidates.append(
                {
                    "segment_index":
                        int(segment_index),
                    "p0": (
                        x0,
                        y0,
                    ),
                    "p1": (
                        x1,
                        y1,
                    ),
                    "midpoint":
                        midpoint,
                    "length": float(
                        seg_length
                    ),
                    "dir": (
                        float(sux),
                        float(suy),
                    ),
                    "along": float(
                        along
                    ),
                    "cross": float(
                        cross
                    ),
                    "perpendicularity":
                        float(
                            perpendicularity
                        ),
                }
            )

        if len(
            candidates
        ) < 2:
            continue

        hinge_lines = [
            row
            for row in candidates
            if abs(
                row["along"]
            ) <= hinge_along_tolerance
        ]

        far_lines = [
            row
            for row in candidates
            if abs(
                row["along"]
                - radius
            ) <= far_along_tolerance
        ]

        if (
            not hinge_lines
            or not far_lines
        ):
            continue

        for line_a in hinge_lines:
            for line_b in far_lines:
                if (
                    line_a["segment_index"]
                    == line_b[
                        "segment_index"
                    ]
                ):
                    continue

                ax, ay = line_a[
                    "midpoint"
                ]

                bx, by = line_b[
                    "midpoint"
                ]

                pair_dx = bx - ax
                pair_dy = by - ay

                pair_width = math.hypot(
                    pair_dx,
                    pair_dy,
                )

                if not (
                    min_width
                    <= pair_width
                    <= max_width
                ):
                    continue

                # Both jamb lines must be parallel to each other.
                adx, ady = line_a[
                    "dir"
                ]

                bdx, bdy = line_b[
                    "dir"
                ]

                line_parallel = abs(
                    adx * bdx
                    + ady * bdy
                )

                if line_parallel < 0.94:
                    continue

                pair_along = (
                    pair_dx * ux
                    + pair_dy * uy
                )

                pair_cross = (
                    pair_dx * nx
                    + pair_dy * ny
                )

                if pair_along <= 0.0:
                    continue

                if abs(
                    pair_cross
                ) > radius * 0.24:
                    continue

                along_ratio = (
                    pair_along
                    / radius
                )

                if not (
                    0.68
                    <= along_ratio
                    <= 1.32
                ):
                    continue

                length_ratio = (
                    min(
                        line_a[
                            "length"
                        ],
                        line_b[
                            "length"
                        ],
                    )
                    / max(
                        line_a[
                            "length"
                        ],
                        line_b[
                            "length"
                        ],
                        1e-9,
                    )
                )

                if length_ratio < 0.40:
                    continue

                hinge_error = (
                    abs(
                        line_a[
                            "along"
                        ]
                    )
                    / radius
                )

                far_error = (
                    abs(
                        line_b[
                            "along"
                        ]
                        - radius
                    )
                    / radius
                )

                width_error = (
                    abs(
                        pair_width
                        - radius
                    )
                    / radius
                )

                cross_error = (
                    abs(
                        pair_cross
                    )
                    / radius
                )

                parallel_error = (
                    1.0
                    - line_parallel
                )

                length_error = (
                    1.0
                    - length_ratio
                )

                score = (
                    hinge_error * 1.45
                    + far_error * 1.45
                    + width_error * 1.20
                    + cross_error * 1.10
                    + parallel_error * 0.80
                    + length_error * 0.35
                    + line_a[
                        "perpendicularity"
                    ] * 0.65
                    + line_b[
                        "perpendicularity"
                    ] * 0.65
                )

                candidate = {
                    "score":
                        float(score),
                    "axis_name":
                        str(
                            axis["name"]
                        ),
                    "line_a":
                        line_a,
                    "line_b":
                        line_b,
                    "width":
                        float(
                            pair_width
                        ),
                    "pair_along":
                        float(
                            pair_along
                        ),
                    "pair_cross":
                        float(
                            pair_cross
                        ),
                    "line_parallel":
                        float(
                            line_parallel
                        ),
                }

                if (
                    best is None
                    or candidate[
                        "score"
                    ] < best[
                        "score"
                    ]
                ):
                    best = candidate

    if best is None:
        return None

    line_a = best[
        "line_a"
    ]

    line_b = best[
        "line_b"
    ]

    jamb_a = (
        float(
            line_a[
                "midpoint"
            ][0]
        ),
        float(
            line_a[
                "midpoint"
            ][1]
        ),
    )

    jamb_b = (
        float(
            line_b[
                "midpoint"
            ][0]
        ),
        float(
            line_b[
                "midpoint"
            ][1]
        ),
    )

    actual_width = _distance(
        jamb_a,
        jamb_b,
    )

    if actual_width <= 1e-9:
        return None

    dx = (
        jamb_b[0]
        - jamb_a[0]
    )

    dy = (
        jamb_b[1]
        - jamb_a[1]
    )

    return {
        "jamb_a":
            jamb_a,
        "jamb_b":
            jamb_b,
        "jamb_line_a": [
            [
                float(
                    line_a[
                        "p0"
                    ][0]
                ),
                float(
                    line_a[
                        "p0"
                    ][1]
                ),
            ],
            [
                float(
                    line_a[
                        "p1"
                    ][0]
                ),
                float(
                    line_a[
                        "p1"
                    ][1]
                ),
            ],
        ],
        "jamb_line_b": [
            [
                float(
                    line_b[
                        "p0"
                    ][0]
                ),
                float(
                    line_b[
                        "p0"
                    ][1]
                ),
            ],
            [
                float(
                    line_b[
                        "p1"
                    ][0]
                ),
                float(
                    line_b[
                        "p1"
                    ][1]
                ),
            ],
        ],
        "width":
            float(
                actual_width
            ),
        "wall_direction": (
            float(
                dx
                / actual_width
            ),
            float(
                dy
                / actual_width
            ),
        ),
        "hinge":
            jamb_a,
        "arc_radius":
            float(
                radius
            ),
        "actual_gap_width":
            float(
                actual_width
            ),
        "door_axis_source":
            str(
                best[
                    "axis_name"
                ]
            ),
        "bridge_jamb_source":
            "structural_wall_jamb_lines",
        "line_parallel":
            float(
                best[
                    "line_parallel"
                ]
            ),
        "pair_cross":
            float(
                best[
                    "pair_cross"
                ]
            ),
        "local_resolution_score":
            float(
                best[
                    "score"
                ]
            ),
    }


def _door_from_dedicated_layer_arc(
    arc,
    leaf,
    wall_segments,
):
    center = arc["center"]
    radius = arc["radius"]

    endpoint_rows = []

    for endpoint in (
        arc["start"],
        arc["end"],
    ):
        near = _nearest_wall_segment(
            endpoint,
            wall_segments,
        )

        if near is not None:
            endpoint_rows.append(
                (
                    float(near[0]),
                    endpoint,
                )
            )

    if endpoint_rows:
        endpoint_rows.sort(
            key=lambda row: row[0]
        )

        jamb_b = endpoint_rows[0][1]
        wall_relation = True
    else:
        jamb_b = arc["start"]
        wall_relation = False

    jamb_a = (
        float(center[0]),
        float(center[1]),
    )

    jamb_b = (
        float(jamb_b[0]),
        float(jamb_b[1]),
    )

    dx = jamb_b[0] - jamb_a[0]
    dy = jamb_b[1] - jamb_a[1]
    length = math.hypot(
        dx,
        dy,
    )

    if length <= 1e-9:
        return None

    return {
        "jamb_a": jamb_a,
        "jamb_b": jamb_b,
        "width": float(radius),
        "wall_direction": (
            float(dx / length),
            float(dy / length),
        ),
        "hinge": jamb_a,
        "confidence": 0.92,
        "source_layer": arc["layer"],
        "swing_degrees": float(
            arc["sweep_deg"]
        ),
        "source_arc_points": [
            [
                float(p[0]),
                float(p[1]),
            ]
            for p in arc.get(
                "source_points",
                [],
            )
        ],
        "bridge_ready": False,
        "detection_mode": (
            "dedicated_door_layer"
        ),
        "evidence": {
            "dedicated_door_layer": True,
            "arc": True,
            "leaf": bool(
                leaf is not None
            ),
            "wall_relation": bool(
                wall_relation
            ),
        },
    }


def _segment_points(segment):
    return (
        (float(segment["x1"]), float(segment["y1"])),
        (float(segment["x2"]), float(segment["y2"])),
    )


def _nearest_wall_segment(
    point,
    wall_segments,
):
    # CAD3D_DOOR_STRUCTURAL_SEGMENT_ADAPTER_V2
    #
    # Door detector keeps its EXISTING wall-segment schema.
    # Common structural core receives only normalized {a,b}
    # adapter records.
    #
    # The original door segment is returned unchanged.

    normalized_segments = []

    for original_segment in wall_segments:
        try:
            a, b = _segment_points(
                original_segment
            )
        except Exception:
            continue

        if a is None or b is None:
            continue

        normalized_segments.append(
            {
                "a": a,
                "b": b,
                "_door_original_segment": (
                    original_segment
                ),
            }
        )

    if not normalized_segments:
        return None

    normalized, distance = (
        _core_nearest_structural_segment(
            point,
            normalized_segments,
            required_direction=None,
            degenerate_epsilon=1.0e-18,
        )
    )

    if normalized is None:
        return None

    original_segment = normalized.get(
        "_door_original_segment"
    )

    if original_segment is None:
        return None

    # Preserve old door-detector contract EXACTLY:
    # (distance, original_segment)
    return (
        distance,
        original_segment,
    )

def _leaf_match(arc, all_segments):
    center = arc["center"]
    radius = arc["radius"]
    hinge_tol = max(arc["wall_gap"] * 0.45, radius * 0.10)
    candidates = []

    for segment in all_segments:
        a, b = _segment_points(segment)
        da = _distance(center, a)
        db = _distance(center, b)

        if min(da, db) > hinge_tol:
            continue

        length_ratio = float(segment["length"]) / max(radius, 1e-9)

        if not (0.62 <= length_ratio <= 1.38):
            continue

        free_end = b if da <= db else a

        endpoint_error = min(
            _distance(free_end, arc["start"]),
            _distance(free_end, arc["end"]),
        )

        score = abs(1.0 - length_ratio) + endpoint_error / max(radius, 1e-9)
        candidates.append((score, segment))

    if not candidates:
        return None

    candidates.sort(key=lambda value: value[0])

    return {
        "score": float(candidates[0][0]),
        "segment": candidates[0][1],
    }


# CAD3D_DOOR_HARD_RULE_LOGGER_V3
def _log_door_hard_rule_candidate(
    *,
    arc,
    center,
    radius,
    nearest_center_distance,
    along,
    leaf,
    leaf_score,
    semantic_score,
    arc_score,
    sweep_score,
    wall_score,
    confidence,
):
    """
    Diagnostic only.

    Does not accept/reject a door.
    Does not modify geometry.
    Does not modify Max metadata.
    """

    try:
        from pathlib import Path as _HardRulePath

        log_path = (
            _HardRulePath(__file__).resolve().parents[2]
            / "logs"
            / "door_hard_rule_runtime.txt"
        )

        log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        radius_value = max(
            abs(float(radius)),
            1.0e-9,
        )

        wall_gap_value = float(
            arc.get(
                "wall_gap",
                0.0,
            )
            or 0.0
        )

        radial_error = float(
            arc.get(
                "radial_error_ratio",
                0.0,
            )
            or 0.0
        )

        sweep = float(
            arc.get(
                "sweep_deg",
                0.0,
            )
            or 0.0
        )

        along_ratio = (
            abs(float(along))
            / radius_value
        )

        wall_distance_ratio = (
            float(nearest_center_distance)
            / radius_value
        )

        row = (
            "center="
            + repr(center)

            + " | radius="
            + repr(float(radius))

            + " | layer="
            + repr(
                arc.get(
                    "layer"
                )
            )

            + " | radial_error="
            + repr(radial_error)

            + " | sweep="
            + repr(sweep)

            + " | nearest_wall="
            + repr(
                float(
                    nearest_center_distance
                )
            )

            + " | wall_distance_ratio="
            + repr(
                float(
                    wall_distance_ratio
                )
            )

            + " | wall_gap="
            + repr(
                wall_gap_value
            )

            + " | along="
            + repr(
                float(along)
            )

            + " | along_ratio="
            + repr(
                float(
                    along_ratio
                )
            )

            + " | leaf="
            + repr(
                bool(
                    leaf is not None
                )
            )

            + " | leaf_score="
            + repr(
                float(
                    leaf_score
                )
            )

            + " | semantic="
            + repr(
                bool(
                    semantic_score > 0.0
                )
            )

            + " | arc_score="
            + repr(
                float(
                    arc_score
                )
            )

            + " | sweep_score="
            + repr(
                float(
                    sweep_score
                )
            )

            + " | wall_score="
            + repr(
                float(
                    wall_score
                )
            )

            + " | confidence="
            + repr(
                float(
                    confidence
                )
            )

            + " | LEGACY_ACCEPT="
            + repr(
                bool(
                    confidence >= 0.48
                )
            )

            + "\n"
        )

        with log_path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(row)

    except Exception:
        # Diagnostic must never affect door detection.
        pass


def _resolve_door(arc, leaf, wall_segments):
    center = arc["center"]
    radius = arc["radius"]
    near_center = _nearest_wall_segment(center, wall_segments)
    wall_segment = near_center[1] if near_center is not None else None

    endpoint_rows = []

    for endpoint in (arc["start"], arc["end"]):
        near = _nearest_wall_segment(endpoint, wall_segments)

        if near is not None:
            endpoint_rows.append((near[0], endpoint, near[1]))

    if endpoint_rows:
        endpoint_rows.sort(key=lambda value: value[0])

        if wall_segment is None or endpoint_rows[0][0] < near_center[0]:
            wall_segment = endpoint_rows[0][2]

    if wall_segment is None:
        return None

    a, b = _segment_points(wall_segment)
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)

    if length <= 1e-9:
        return None

    ux = dx / length
    uy = dy / length

    endpoint_scores = []

    for endpoint in (arc["start"], arc["end"]):
        vx = endpoint[0] - center[0]
        vy = endpoint[1] - center[1]
        along = vx * ux + vy * uy
        normal = abs(vx * (-uy) + vy * ux)
        endpoint_scores.append((normal, -abs(along), along))

    endpoint_scores.sort(key=lambda value: (value[0], value[1]))
    along = endpoint_scores[0][2]

    if abs(along) <= radius * 0.20:
        return None

    sign = 1.0 if along >= 0.0 else -1.0

    jamb_a = (float(center[0]), float(center[1]))
    jamb_b = (
        float(center[0] + ux * radius * sign),
        float(center[1] + uy * radius * sign),
    )

    nearest_center_distance = near_center[0] if near_center is not None else radius

    wall_score = max(
        0.0,
        1.0
        - nearest_center_distance
        / max(radius * 0.35, arc["wall_gap"], 1e-9),
    )

    arc_score = max(0.0, 1.0 - arc["radial_error_ratio"] / 0.075)
    sweep_score = max(0.0, 1.0 - abs(arc["sweep_deg"] - 90.0) / 70.0)

    leaf_score = 0.0

    if leaf is not None:
        leaf_score = max(0.0, 1.0 - leaf["score"] / 0.70)

    semantic_score = 1.0 if semantic_category(arc["layer"]) == "door" else 0.0

    confidence = (
        0.30 * arc_score
        + 0.20 * sweep_score
        + 0.22 * wall_score
        + 0.20 * leaf_score
        + 0.08 * semantic_score
    )

    # CAD3D_DOOR_HARD_RULE_DIAGNOSTIC_V3
    _log_door_hard_rule_candidate(
        arc=arc,
        center=center,
        radius=radius,
        nearest_center_distance=nearest_center_distance,
        along=along,
        leaf=leaf,
        leaf_score=leaf_score,
        semantic_score=semantic_score,
        arc_score=arc_score,
        sweep_score=sweep_score,
        wall_score=wall_score,
        confidence=confidence,
    )

    # CAD3D_DOOR_HARD_RULE_ACCEPTANCE_V1
    # Legacy confidence is diagnostic/ranking metadata only.
    _dedicated_arc = bool(
        arc.get(
            "dedicated_layer_fallback",
            False,
        )
    )

    _radial_limit = (
        0.18
        if _dedicated_arc
        else 0.075
    )

    _sweep_min = (
        20.0
        if _dedicated_arc
        else 35.0
    )

    _sweep_max = (
        180.0
        if _dedicated_arc
        else 150.0
    )

    _radial_error = float(
        arc.get(
            "radial_error_ratio",
            1.0,
        )
    )

    _sweep_value = float(
        arc.get(
            "sweep_deg",
            0.0,
        )
    )

    _radius_safe = max(
        abs(float(radius)),
        1.0e-9,
    )

    _wall_distance_ratio = (
        float(nearest_center_distance)
        / _radius_safe
    )

    _along_ratio = (
        abs(float(along))
        / _radius_safe
    )

    _symbol_support = (
        leaf is not None
        or semantic_score > 0.0
        or _dedicated_arc
    )

    _hard_rules = (
        _recognition_rule(
            "door.arc_geometry_valid",
            _radial_error <= _radial_limit,
            actual=_radial_error,
            expected=(
                "<= " + str(_radial_limit)
            ),
            reason="valid circular swing geometry",
        ),

        _recognition_rule(
            "door.swing_range_valid",
            (
                _sweep_min
                <= _sweep_value
                <= _sweep_max
            ),
            actual=_sweep_value,
            expected=(
                str(_sweep_min)
                + ".."
                + str(_sweep_max)
            ),
            reason="valid architectural swing range",
        ),

        _recognition_rule(
            "door.local_wall_proximity",
            _wall_distance_ratio <= 0.35,
            actual=_wall_distance_ratio,
            expected="<= 0.35 x radius",
            reason="door hinge must be locally supported by structural wall geometry",
        ),

        _recognition_rule(
            "door.opening_axis_valid",
            _along_ratio > 0.20,
            actual=_along_ratio,
            expected="> 0.20 x radius",
            reason="swing endpoint must define a usable wall-axis opening direction",
        ),

        _recognition_rule(
            "door.symbol_support",
            _symbol_support,
            actual={
                "leaf": bool(leaf is not None),
                "semantic": bool(semantic_score > 0.0),
                "dedicated_arc": _dedicated_arc,
            },
            expected="leaf OR semantic door hint OR dedicated door arc",
            reason="explicit door-symbol support required",
        ),
    )

    _hard_decision = (
        _recognition_require_all(
            "door_candidate",
            "swing_door",
            _hard_rules,
            accepted_reason=(
                "deterministic-door-rules-passed"
            ),
            rejected_reason=(
                "deterministic-door-rule-failed"
            ),
            metadata={
                "legacy_confidence": float(confidence),
                "wall_distance_ratio": float(_wall_distance_ratio),
                "along_ratio": float(_along_ratio),
            },
        )
    )

    if not _hard_decision.accepted:
        return None

    return {
        "jamb_a": jamb_a,
        "jamb_b": jamb_b,
        "width": float(radius),
        "wall_direction": (float(ux * sign), float(uy * sign)),
        "hinge": jamb_a,
        "confidence": float(confidence),
        "candidate_recognition_contract": _hard_decision.as_dict(),
        "source_layer": arc["layer"],
        "swing_degrees": float(arc["sweep_deg"]),
        "evidence": {
            "arc": True,
            "leaf": bool(leaf is not None),
            "wall_relation": True,
            "semantic_door_hint": bool(semantic_score > 0.0),
        },
    }


# CAD3D_NONE_SAFE_DOOR_DEDUPE_V2_HINGE_FIRST
def _dedupe_doors(
    doors,
    wall_gap,
):
    # Door identity is based primarily on the detected swing hinge,
    # not on the midpoint of the resolved jamb pair.
    #
    # This matters because a resolved door midpoint is naturally about
    # half a door width away from the hinge, while an unresolved copy
    # can only expose the hinge/arc location. Using midpoint first would
    # prevent the same physical door from deduping.

    if not doors:
        return []

    try:
        wall_gap_value = abs(
            float(wall_gap)
        )
    except (
        TypeError,
        ValueError,
    ):
        wall_gap_value = 0.0

    def _point2(value):
        if not isinstance(
            value,
            (list, tuple),
        ):
            return None

        if len(value) < 2:
            return None

        try:
            return (
                float(value[0]),
                float(value[1]),
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    def _anchor(door):
        # 1) Swing hinge is the stable identity anchor for BOTH
        # resolved and unresolved records.
        hinge = _point2(
            door.get(
                "hinge"
            )
        )

        if hinge is not None:
            return hinge

        # 2) Detector center/arc center are next best stable anchors.
        for key in (
            "center",
            "arc_center",
        ):
            point = _point2(
                door.get(
                    key
                )
            )

            if point is not None:
                return point

        # 3) If no swing anchor exists, use resolved jamb midpoint.
        jamb_a = _point2(
            door.get(
                "jamb_a"
            )
        )

        jamb_b = _point2(
            door.get(
                "jamb_b"
            )
        )

        if (
            jamb_a is not None
            and jamb_b is not None
        ):
            return (
                (
                    jamb_a[0]
                    + jamb_b[0]
                )
                * 0.5,
                (
                    jamb_a[1]
                    + jamb_b[1]
                )
                * 0.5,
            )

        # 4) Last fallback: centroid of source arc points.
        source_points = door.get(
            "source_arc_points",
            []
        )

        valid_points = [
            point
            for point in (
                _point2(value)
                for value in source_points
            )
            if point is not None
        ]

        if valid_points:
            return (
                sum(
                    point[0]
                    for point in valid_points
                )
                / len(valid_points),
                sum(
                    point[1]
                    for point in valid_points
                )
                / len(valid_points),
            )

        return None

    def _width(door):
        for key in (
            "arc_radius",
            "width",
            "actual_gap_width",
        ):
            value = door.get(
                key
            )

            try:
                number = abs(
                    float(value)
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if number > 1e-9:
                return number

        return 0.0

    def _preference(door):
        bridge_ready = (
            1
            if bool(
                door.get(
                    "bridge_ready",
                    False,
                )
            )
            else 0
        )

        try:
            confidence = float(
                door.get(
                    "confidence",
                    0.0,
                )
                or 0.0
            )
        except (
            TypeError,
            ValueError,
        ):
            confidence = 0.0

        return (
            bridge_ready,
            confidence,
        )

    rows = []

    for source_index, door in enumerate(
        doors
    ):
        if not isinstance(
            door,
            dict,
        ):
            continue

        rows.append(
            {
                "door": door,
                "anchor": _anchor(
                    door
                ),
                "width": _width(
                    door
                ),
                "source_index":
                    int(source_index),
            }
        )

    # Resolved records first, so a resolved/unresolved duplicate keeps
    # the record that contains the real structural jamb lines.
    rows.sort(
        key=lambda row: (
            -_preference(
                row["door"]
            )[0],
            -_preference(
                row["door"]
            )[1],
            row["source_index"],
        )
    )

    kept = []

    for row in rows:
        anchor = row[
            "anchor"
        ]

        width = float(
            row[
                "width"
            ]
        )

        duplicate_index = None

        if anchor is not None:
            for index, existing in enumerate(
                kept
            ):
                existing_anchor = existing[
                    "anchor"
                ]

                if existing_anchor is None:
                    continue

                distance = math.hypot(
                    anchor[0]
                    - existing_anchor[0],
                    anchor[1]
                    - existing_anchor[1],
                )

                existing_width = float(
                    existing[
                        "width"
                    ]
                )

                usable_widths = [
                    value
                    for value in (
                        width,
                        existing_width,
                    )
                    if value > 1e-9
                ]

                reference_width = (
                    min(
                        usable_widths
                    )
                    if usable_widths
                    else 0.0
                )

                # Hinge points from the same detected swing should be
                # very close. Keep this local and scale-aware.
                # CAD3D_DEDUPE_HINGE_TOLERANCE_FIX_V1
                # Door identity must be LOCAL to the swing hinge.
                # Global inferred wall_gap can be much larger than a door
                # and previously caused neighbouring real doors to collapse.
                distance_tolerance = max(
                    reference_width * 0.10,
                    1.0,
                )

                if distance > distance_tolerance:
                    continue

                if (
                    width > 1e-9
                    and existing_width > 1e-9
                ):
                    width_ratio = (
                        max(
                            width,
                            existing_width,
                        )
                        / min(
                            width,
                            existing_width,
                        )
                    )

                    if width_ratio > 1.25:
                        continue

                duplicate_index = index
                break

        if duplicate_index is None:
            kept.append(
                row
            )
            continue

        existing = kept[
            duplicate_index
        ]

        if (
            _preference(
                row["door"]
            )
            > _preference(
                existing["door"]
            )
        ):
            kept[
                duplicate_index
            ] = row

    kept.sort(
        key=lambda row: row[
            "source_index"
        ]
    )

    return [
        row["door"]
        for row in kept
    ]




# CAD3D_MULTI_DOOR_LAYER_REAL_V1
def _resolve_exact_door_layer(geometry, profile):
    import re

    grouped = {}

    for item in geometry:
        layer = str(
            item.get("layer")
            or ""
        ).strip()

        if not layer:
            continue

        tokens = set(
            re.findall(
                r"[A-Z]+",
                layer.upper(),
            )
        )

        if not (
            "DOOR" in tokens
            or "DOORS" in tokens
        ):
            continue

        grouped.setdefault(
            layer,
            [],
        ).append(item)

    if not grouped:
        return [], []

    scored = []

    for layer, items in grouped.items():
        arc_count = 0

        for item in items:
            candidate = _arc_candidate(
                item,
                profile,
            )

            if candidate is None:
                candidate = _dedicated_door_arc_candidate(
                    item,
                    profile,
                )

            if candidate is not None:
                arc_count += 1

        scored.append(
            (
                arc_count,
                len(items),
                layer,
                items,
            )
        )

    scored.sort(
        key=lambda row: (
            -row[0],
            -row[1],
            row[2].upper(),
        )
    )

    door_layers = [
        row[2]
        for row in scored
    ]

    door_items = []

    for row in scored:
        door_items.extend(
            row[3]
        )

    return door_layers, door_items


# CAD3D_DOUBLE_SWING_REAL_V1
def _double_door_point(value):
    if not isinstance(
        value,
        (list, tuple),
    ):
        return None

    if len(value) < 2:
        return None

    try:
        return (
            float(value[0]),
            float(value[1]),
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _double_door_join_arcs(points_a, points_b):
    a = [
        _double_door_point(p)
        for p in (points_a or [])
    ]

    b = [
        _double_door_point(p)
        for p in (points_b or [])
    ]

    a = [
        p
        for p in a
        if p is not None
    ]

    b = [
        p
        for p in b
        if p is not None
    ]

    if not a:
        return [
            [p[0], p[1]]
            for p in b
        ]

    if not b:
        return [
            [p[0], p[1]]
            for p in a
        ]

    variants = [
        (a, b),
        (list(reversed(a)), b),
        (a, list(reversed(b))),
        (
            list(reversed(a)),
            list(reversed(b)),
        ),
    ]

    best = None

    for va, vb in variants:
        gap = _distance(
            va[-1],
            vb[0],
        )

        if (
            best is None
            or gap < best[0]
        ):
            best = (
                gap,
                va,
                vb,
            )

    joined = (
        best[1]
        + best[2]
    )

    return [
        [
            float(p[0]),
            float(p[1]),
        ]
        for p in joined
    ]


def _double_door_outer_jamb(
    hinge,
    axis,
    leaf_width,
    wall_segments,
):
    hinge = _double_door_point(
        hinge
    )

    if hinge is None:
        return None

    try:
        ax = float(axis[0])
        ay = float(axis[1])
        width = abs(
            float(leaf_width)
        )
    except Exception:
        return None

    axis_length = math.hypot(
        ax,
        ay,
    )

    if (
        axis_length <= 1e-9
        or width <= 1e-9
    ):
        return None

    ax /= axis_length
    ay /= axis_length

    min_length = width * 0.025
    max_length = width * 0.50
    max_distance = width * 0.38

    best = None

    for segment in wall_segments:
        try:
            a, b = _segment_points(
                segment
            )

            x1 = float(a[0])
            y1 = float(a[1])
            x2 = float(b[0])
            y2 = float(b[1])
        except Exception:
            continue

        dx = x2 - x1
        dy = y2 - y1

        length = math.hypot(
            dx,
            dy,
        )

        if not (
            min_length
            <= length
            <= max_length
        ):
            continue

        mx = (
            x1
            + x2
        ) * 0.5

        my = (
            y1
            + y2
        ) * 0.5

        vx = (
            mx
            - hinge[0]
        )

        vy = (
            my
            - hinge[1]
        )

        distance = math.hypot(
            vx,
            vy,
        )

        if distance > max_distance:
            continue

        ux = dx / length
        uy = dy / length

        # Opening axis = wall direction.
        # Jamb/cap line must be close to perpendicular.
        parallel = abs(
            ux * ax
            + uy * ay
        )

        if parallel > 0.45:
            continue

        along = abs(
            vx * ax
            + vy * ay
        )

        score = (
            distance
            / width
            + parallel * 1.50
            + along
            / width
            * 0.75
        )

        candidate = {
            "score": float(score),
            "midpoint": (
                float(mx),
                float(my),
            ),
            "line": [
                [
                    float(x1),
                    float(y1),
                ],
                [
                    float(x2),
                    float(y2),
                ],
            ],
        }

        if (
            best is None
            or candidate["score"]
            < best["score"]
        ):
            best = candidate

    return best


def _merge_double_swing_doors(
    doors,
    wall_segments,
):
    doors = list(
        doors or []
    )

    pair_candidates = []

    for i in range(len(doors)):
        a = doors[i]

        # The double leaves we need to merge are normally the
        # individually detected but unresolved records.
        if bool(
            a.get(
                "bridge_ready",
                False,
            )
        ):
            continue

        hinge_a = _double_door_point(
            a.get("hinge")
        )

        try:
            width_a = abs(
                float(
                    a.get(
                        "arc_radius",
                        a.get(
                            "width",
                            0.0,
                        ),
                    )
                    or a.get(
                        "width",
                        0.0,
                    )
                    or 0.0
                )
            )
        except Exception:
            width_a = 0.0

        if (
            hinge_a is None
            or width_a <= 1e-9
        ):
            continue

        for j in range(
            i + 1,
            len(doors),
        ):
            b = doors[j]

            if bool(
                b.get(
                    "bridge_ready",
                    False,
                )
            ):
                continue

            hinge_b = _double_door_point(
                b.get("hinge")
            )

            try:
                width_b = abs(
                    float(
                        b.get(
                            "arc_radius",
                            b.get(
                                "width",
                                0.0,
                            ),
                        )
                        or b.get(
                            "width",
                            0.0,
                        )
                        or 0.0
                    )
                )
            except Exception:
                width_b = 0.0

            if (
                hinge_b is None
                or width_b <= 1e-9
            ):
                continue

            ratio = (
                max(
                    width_a,
                    width_b,
                )
                / max(
                    min(
                        width_a,
                        width_b,
                    ),
                    1e-9,
                )
            )

            if ratio > 1.40:
                continue

            hinge_distance = _distance(
                hinge_a,
                hinge_b,
            )

            expected_width = (
                width_a
                + width_b
            )

            if not (
                expected_width * 0.68
                <= hinge_distance
                <= expected_width * 1.32
            ):
                continue

            points_a = list(
                a.get(
                    "source_arc_points",
                    [],
                )
                or []
            )

            points_b = list(
                b.get(
                    "source_arc_points",
                    [],
                )
                or []
            )

            if (
                len(points_a) < 2
                or len(points_b) < 2
            ):
                continue

            ends_a = [
                _double_door_point(
                    points_a[0]
                ),
                _double_door_point(
                    points_a[-1]
                ),
            ]

            ends_b = [
                _double_door_point(
                    points_b[0]
                ),
                _double_door_point(
                    points_b[-1]
                ),
            ]

            endpoint_distances = []

            for pa in ends_a:
                if pa is None:
                    continue

                for pb in ends_b:
                    if pb is None:
                        continue

                    endpoint_distances.append(
                        _distance(
                            pa,
                            pb,
                        )
                    )

            if not endpoint_distances:
                continue

            meeting_error = min(
                endpoint_distances
            )

            meeting_tolerance = (
                min(
                    width_a,
                    width_b,
                )
                * 0.32
            )

            if (
                meeting_error
                > meeting_tolerance
            ):
                continue

            axis = (
                hinge_b[0]
                - hinge_a[0],
                hinge_b[1]
                - hinge_a[1],
            )

            axis_length = math.hypot(
                axis[0],
                axis[1],
            )

            if axis_length <= 1e-9:
                continue

            axis = (
                axis[0]
                / axis_length,
                axis[1]
                / axis_length,
            )

            jamb_a = _double_door_outer_jamb(
                hinge_a,
                axis,
                width_a,
                wall_segments,
            )

            jamb_b = _double_door_outer_jamb(
                hinge_b,
                axis,
                width_b,
                wall_segments,
            )

            # Pair identity can be established from the swings
            # even before jamb resolution. Jamb availability only
            # decides Bridge readiness.
            size_error = abs(
                hinge_distance
                - expected_width
            ) / max(
                expected_width,
                1e-9,
            )

            leaf_error = abs(
                width_a
                - width_b
            ) / max(
                max(
                    width_a,
                    width_b,
                ),
                1e-9,
            )

            pair_score = (
                meeting_error
                / max(
                    min(
                        width_a,
                        width_b,
                    ),
                    1e-9,
                )
                * 1.40
                + size_error * 1.10
                + leaf_error * 0.60
            )

            pair_candidates.append(
                (
                    float(pair_score),
                    i,
                    j,
                    hinge_a,
                    hinge_b,
                    width_a,
                    width_b,
                    axis,
                    jamb_a,
                    jamb_b,
                )
            )

    pair_candidates.sort(
        key=lambda row: row[0]
    )

    consumed = set()
    merged = []

    for row in pair_candidates:
        (
            pair_score,
            i,
            j,
            hinge_a,
            hinge_b,
            width_a,
            width_b,
            axis,
            outer_a,
            outer_b,
        ) = row

        if (
            i in consumed
            or j in consumed
        ):
            continue

        door_a = doors[i]
        door_b = doors[j]

        bridge_ready = (
            outer_a is not None
            and outer_b is not None
        )

        if bridge_ready:
            jamb_a = (
                outer_a[
                    "midpoint"
                ]
            )

            jamb_b = (
                outer_b[
                    "midpoint"
                ]
            )

            actual_width = _distance(
                jamb_a,
                jamb_b,
            )

            dx = (
                jamb_b[0]
                - jamb_a[0]
            )

            dy = (
                jamb_b[1]
                - jamb_a[1]
            )

            length = math.hypot(
                dx,
                dy,
            )

            if length > 1e-9:
                wall_direction = (
                    float(dx / length),
                    float(dy / length),
                )
            else:
                wall_direction = (
                    float(axis[0]),
                    float(axis[1]),
                )
        else:
            jamb_a = None
            jamb_b = None

            actual_width = _distance(
                hinge_a,
                hinge_b,
            )

            wall_direction = (
                float(axis[0]),
                float(axis[1]),
            )

        center = (
            (
                hinge_a[0]
                + hinge_b[0]
            )
            * 0.5,
            (
                hinge_a[1]
                + hinge_b[1]
            )
            * 0.5,
        )

        confidence_a = float(
            door_a.get(
                "confidence",
                0.0,
            )
            or 0.0
        )

        confidence_b = float(
            door_b.get(
                "confidence",
                0.0,
            )
            or 0.0
        )

        source_layer_a = str(
            door_a.get(
                "source_layer",
                "",
            )
            or ""
        ).strip()

        source_layer_b = str(
            door_b.get(
                "source_layer",
                "",
            )
            or ""
        ).strip()

        if (
            source_layer_a
            == source_layer_b
        ):
            source_layer = (
                source_layer_a
            )
        else:
            source_layer = (
                source_layer_a
                + " | "
                + source_layer_b
            ).strip(" |")

        merged_door = {
            "jamb_a": jamb_a,
            "jamb_b": jamb_b,

            "width": float(
                actual_width
            ),

            "wall_direction": (
                float(
                    wall_direction[0]
                ),
                float(
                    wall_direction[1]
                ),
            ),

            "hinge": (
                float(center[0]),
                float(center[1]),
            ),

            "arc_center": (
                float(center[0]),
                float(center[1]),
            ),

            "confidence": float(
                max(
                    min(
                        confidence_a,
                        confidence_b,
                    ),
                    0.92,
                )
            ),

            "source_layer": (
                source_layer
            ),

            "swing_degrees": float(
                (
                    float(
                        door_a.get(
                            "swing_degrees",
                            90.0,
                        )
                        or 90.0
                    )
                    + float(
                        door_b.get(
                            "swing_degrees",
                            90.0,
                        )
                        or 90.0
                    )
                )
                * 0.5
            ),

            "source_arc_points": (
                _double_door_join_arcs(
                    door_a.get(
                        "source_arc_points",
                        [],
                    ),
                    door_b.get(
                        "source_arc_points",
                        [],
                    ),
                )
            ),

            "arc": True,
            "wall_relation": True,
            "semantic_door_hint": True,

            "detection_mode": (
                "double_swing_pair"
            ),

            "door_type": (
                "double_swing"
            ),

            "double_swing": True,
            "leaf_count": 2,

            "leaf_width_a": float(
                width_a
            ),

            "leaf_width_b": float(
                width_b
            ),

            "leaf_widths": [
                float(width_a),
                float(width_b),
            ],

            "bridge_ready": bool(
                bridge_ready
            ),

            "bridge_jamb_source": (
                "double_outer_structural_jamb_lines"
                if bridge_ready
                else "unresolved_double"
            ),

            "jamb_line_a": (
                outer_a["line"]
                if bridge_ready
                else None
            ),

            "jamb_line_b": (
                outer_b["line"]
                if bridge_ready
                else None
            ),

            # _dedupe_doors checks arc_radius before width.
            # For a merged double door the relevant radius/width
            # identity is the complete opening width.
            "arc_radius": float(
                actual_width
            ),

            "actual_gap_width": float(
                actual_width
            ),

            "door_axis_source": (
                "double_swing_outer_hinges"
            ),

            "line_parallel": 0.0,
            "pair_cross": 0.0,

            "local_resolution_score": float(
                pair_score
            ),
        }

        merged.append(
            merged_door
        )

        consumed.add(i)
        consumed.add(j)

    output = [
        door
        for index, door in enumerate(
            doors
        )
        if index not in consumed
    ]

    output.extend(
        merged
    )

    return output


# CAD3D_DOOR_FINAL_CONTRACT_HELPER_V1
def _attach_final_door_contracts(
    door,
):
    """
    Attach deterministic, read-only contracts to a FINAL
    door record.

    Recognition and Bridge execution are intentionally
    separate decisions.

    This function NEVER changes whether a door exists and
    NEVER changes bridge_ready.
    """

    if not isinstance(
        door,
        dict,
    ):
        return door

    evidence = door.get(
        "evidence",
        {},
    )

    if not isinstance(
        evidence,
        dict,
    ):
        evidence = {}

    door_type = str(
        door.get(
            "door_type",
            "",
        )
        or ""
    ).strip().lower()

    detection_mode = str(
        door.get(
            "detection_mode",
            "",
        )
        or ""
    ).strip().lower()

    # --------------------------------------------------------
    # Stable identity anchor
    # --------------------------------------------------------

    identity_anchor = None

    for key in (
        "hinge",
        "arc_center",
        "center",
        "jamb_a",
    ):
        value = _point(
            door.get(
                key
            )
        )

        if value is not None:
            identity_anchor = value
            break

    # --------------------------------------------------------
    # Width
    # --------------------------------------------------------

    try:
        width = abs(
            float(
                door.get(
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

    # --------------------------------------------------------
    # Door-symbol evidence
    #
    # Existing detector has already accepted this record.
    # Contract only describes WHY the final record is valid.
    # --------------------------------------------------------

    arc_evidence = bool(
        evidence.get(
            "arc",
            False,
        )
    )

    source_arc_points = (
        door.get(
            "source_arc_points",
            [],
        )
        or []
    )

    has_symbol_evidence = (
        arc_evidence
        or len(source_arc_points) >= 2
        or door_type in {
            "double_swing",
            "double_door",
        }
        or detection_mode in {
            "dedicated_door_layer",
            "dedicated_layer_plus_wall",
        }
    )

    recognition_rules = (
        _recognition_rule(
            "door.identity_anchor",
            identity_anchor is not None,
            actual=identity_anchor,
            expected="valid 2D anchor",
            reason=(
                "door requires a stable geometric identity anchor"
            ),
        ),

        _recognition_rule(
            "door.symbol_evidence",
            has_symbol_evidence,
            actual={
                "arc": arc_evidence,
                "source_arc_point_count":
                    len(source_arc_points),
                "door_type": door_type,
                "detection_mode": detection_mode,
            },
            expected=(
                "arc, dedicated door symbol, or merged double-door evidence"
            ),
            reason=(
                "door requires explicit architectural door evidence"
            ),
        ),

        _recognition_rule(
            "door.width_positive",
            width > 1.0e-9,
            actual=width,
            expected="> 0",
            reason=(
                "door opening width must be positive"
            ),
        ),
    )

    recognition_decision = (
        _recognition_require_all(
            "door",
            "door",
            recognition_rules,
            accepted_reason=(
                "final-door-record-valid"
            ),
            rejected_reason=(
                "final-door-contract-failed"
            ),
            metadata={
                "width": width,
                "door_type": door_type,
                "detection_mode": detection_mode,

                # Legacy detector score is metadata only here.
                # It is NOT used by this final contract.
                "legacy_confidence": (
                    door.get(
                        "confidence"
                    )
                ),
            },
        )
    )

    door[
        "recognition_contract"
    ] = recognition_decision.as_dict()

    # ========================================================
    # BRIDGE EXECUTION CONTRACT
    #
    # Recognition of a door is NOT sufficient permission
    # to mutate 3ds Max topology.
    # ========================================================

    bridge_ready = bool(
        door.get(
            "bridge_ready",
            False,
        )
    )

    jamb_a = _point(
        door.get(
            "jamb_a"
        )
    )

    jamb_b = _point(
        door.get(
            "jamb_b"
        )
    )

    jamb_line_a = door.get(
        "jamb_line_a"
    )

    jamb_line_b = door.get(
        "jamb_line_b"
    )

    bridge_rules = (
        _recognition_rule(
            "door.bridge_ready_flag",
            bridge_ready,
            actual=bridge_ready,
            expected=True,
            reason=(
                "detector must explicitly mark opening Bridge-ready"
            ),
        ),

        _recognition_rule(
            "door.jamb_a_resolved",
            jamb_a is not None,
            actual=jamb_a,
            expected="resolved jamb A",
            reason=(
                "Bridge requires real structural jamb A"
            ),
        ),

        _recognition_rule(
            "door.jamb_b_resolved",
            jamb_b is not None,
            actual=jamb_b,
            expected="resolved jamb B",
            reason=(
                "Bridge requires real structural jamb B"
            ),
        ),

        _recognition_rule(
            "door.jamb_line_a_resolved",
            jamb_line_a is not None,
            actual=jamb_line_a,
            expected="structural jamb line A",
            reason=(
                "Bridge requires source structural jamb line A"
            ),
        ),

        _recognition_rule(
            "door.jamb_line_b_resolved",
            jamb_line_b is not None,
            actual=jamb_line_b,
            expected="structural jamb line B",
            reason=(
                "Bridge requires source structural jamb line B"
            ),
        ),

        _recognition_rule(
            "door.bridge_width_positive",
            width > 1.0e-9,
            actual=width,
            expected="> 0",
            reason=(
                "Bridge requires positive opening width"
            ),
        ),
    )

    bridge_decision = (
        _recognition_require_all(
            "door_bridge",
            "bridge_opening",
            bridge_rules,
            accepted_reason=(
                "door-bridge-preconditions-satisfied"
            ),
            rejected_reason=(
                "door-bridge-precondition-failed"
            ),
            metadata={
                "bridge_jamb_source":
                    door.get(
                        "bridge_jamb_source"
                    ),
                "width": width,
            },
        )
    )

    door[
        "bridge_execution_contract"
    ] = bridge_decision.as_dict()

    return door


# CAD3D_DOOR_ENTITY_ADAPTER_V1
def _door_to_architectural_entity(
    door,
):
    """
    Read-only adapter.

    Recognition and Bridge execution remain separate.

    Existing door record is NOT modified.
    Existing Max Bridge pipeline is NOT modified.
    """

    if not isinstance(
        door,
        dict,
    ):
        raise TypeError(
            "Door entity adapter requires dict input."
        )

    recognition_contract = door.get(
        "recognition_contract",
        {},
    )

    if not isinstance(
        recognition_contract,
        dict,
    ):
        recognition_contract = {}

    bridge_contract = door.get(
        "bridge_execution_contract",
        {},
    )

    if not isinstance(
        bridge_contract,
        dict,
    ):
        bridge_contract = {}

    recognized = bool(
        recognition_contract.get(
            "accepted",
            False,
        )
    )

    bridge_contract_accepted = bool(
        bridge_contract.get(
            "accepted",
            False,
        )
    )

    bridge_allowed = bool(
        recognized
        and bridge_contract_accepted
    )

    hinge = _point(
        door.get(
            "hinge"
        )
    )

    arc_center = _point(
        door.get(
            "arc_center"
        )
    )

    center = _point(
        door.get(
            "center"
        )
    )

    jamb_a = _point(
        door.get(
            "jamb_a"
        )
    )

    jamb_b = _point(
        door.get(
            "jamb_b"
        )
    )

    wall_direction = _point(
        door.get(
            "wall_direction"
        )
    )

    identity_anchor = None

    for value in (
        hinge,
        arc_center,
        center,
        jamb_a,
    ):
        if value is not None:
            identity_anchor = value
            break

    def _safe_float(
        value,
        default=None,
    ):
        try:
            return float(value)
        except (
            TypeError,
            ValueError,
        ):
            return default

    width = _safe_float(
        door.get(
            "width"
        ),
        0.0,
    )

    if width is None:
        width = 0.0

    width = abs(
        float(width)
    )

    actual_gap_width = _safe_float(
        door.get(
            "actual_gap_width"
        )
    )

    arc_radius = _safe_float(
        door.get(
            "arc_radius"
        )
    )

    swing_degrees = _safe_float(
        door.get(
            "swing_degrees"
        )
    )

    source_arc_points = []

    for value in (
        door.get(
            "source_arc_points",
            []
        )
        or []
    ):
        point = _point(
            value
        )

        if point is None:
            continue

        source_arc_points.append(
            (
                float(point[0]),
                float(point[1]),
            )
        )

    source_layer = str(
        door.get(
            "source_layer",
            "",
        )
        or ""
    ).strip()

    bridge_ready = bool(
        door.get(
            "bridge_ready",
            False,
        )
    )

    structural_relation = {
        "bridge_ready":
            bridge_ready,

        "bridge_jamb_source":
            door.get(
                "bridge_jamb_source"
            ),

        "jamb_line_a":
            door.get(
                "jamb_line_a"
            ),

        "jamb_line_b":
            door.get(
                "jamb_line_b"
            ),

        "door_axis_source":
            door.get(
                "door_axis_source"
            ),

        "actual_gap_width":
            actual_gap_width,

        # Existing deterministic execution contract.
        "bridge_execution_contract":
            dict(
                bridge_contract
            ),
    }

    source_geometry = {
        "arc_points":
            list(
                source_arc_points
            ),

        "jamb_line_a":
            door.get(
                "jamb_line_a"
            ),

        "jamb_line_b":
            door.get(
                "jamb_line_b"
            ),
    }

    entity = (
        _create_architectural_entity(
            _ENTITY_DOOR,

            entity_id=str(
                door.get(
                    "door_id",
                    "",
                )
                or ""
            ),

            geometry={
                "identity_anchor":
                    identity_anchor,

                "hinge":
                    hinge,

                "arc_center":
                    arc_center,

                "center":
                    center,

                "jamb_a":
                    jamb_a,

                "jamb_b":
                    jamb_b,

                "width":
                    float(width),

                "actual_gap_width":
                    actual_gap_width,

                "arc_radius":
                    arc_radius,

                "wall_direction":
                    wall_direction,

                "swing_degrees":
                    swing_degrees,
            },

            structural_relation=(
                structural_relation
            ),

            # Final door-recognition contract is reused directly.
            recognition_contract=(
                dict(
                    recognition_contract
                )
            ),

            source_geometry=(
                source_geometry
            ),

            source_layer=(
                source_layer
            ),

            # Recognition alone never grants Bridge permission.
            execution_permissions={
                "bridge":
                    bridge_allowed,
            },

            metadata={
                "door_type":
                    door.get(
                        "door_type"
                    ),

                "detection_mode":
                    door.get(
                        "detection_mode"
                    ),

                "double_swing":
                    bool(
                        door.get(
                            "double_swing",
                            False,
                        )
                    ),

                "leaf_count":
                    door.get(
                        "leaf_count",
                        1,
                    ),

                "bridge_pair_index":
                    door.get(
                        "bridge_pair_index"
                    ),

                "legacy_confidence":
                    door.get(
                        "confidence"
                    ),
            },
        )
    )

    return entity


def detect_doors(geometry):
    geometry = list(geometry or [])
    profile = infer_cad_profile(geometry)

    structural_layers = list(profile.get("structural_layers") or [])
    primary = profile.get("primary_structural_layer")

    if not structural_layers and primary:
        structural_layers = [primary]

    wall_segments = extract_segments(
        geometry,
        structural_layers if structural_layers else None,
    )

    door_layers, door_layer_items = _resolve_exact_door_layer(
        geometry,
        profile,
    )

    # CAD3D_RUNTIME_ARC_PROBE_V1
    # Diagnostic only: record every geometrically plausible swing arc,
    # regardless of source layer. This does NOT change door detection.
    try:
        from pathlib import Path as _ProbePath

        _probe_rows = []

        _probe_rows.append(
            "=== DOOR ARC RUNTIME PROBE ==="
        )

        _probe_rows.append(
            "EXPLICIT DOOR LAYERS: "
            + repr(
                list(door_layers or [])
            )
        )

        _probe_rows.append(
            "GEOMETRY COUNT: "
            + str(len(geometry))
        )

        _probe_rows.append("")

        _probe_index = 0

        for _probe_item in geometry:
            _probe_candidate = _arc_candidate(
                _probe_item,
                profile,
            )

            _probe_mode = "STRICT"

            if _probe_candidate is None:
                _probe_candidate = _dedicated_door_arc_candidate(
                    _probe_item,
                    profile,
                )
                _probe_mode = "BROAD"

            if _probe_candidate is None:
                continue

            _probe_index += 1

            _probe_layer = str(
                _probe_item.get("layer")
                or ""
            ).strip()

            _probe_points = (
                _probe_item.get("points")
                or []
            )

            _probe_center = (
                _probe_candidate.get("center")
            )

            _probe_radius = float(
                _probe_candidate.get(
                    "radius",
                    0.0,
                )
            )

            _probe_sweep = float(
                _probe_candidate.get(
                    "sweep_deg",
                    0.0,
                )
            )

            _probe_explicit = (
                _probe_layer
                in set(
                    door_layers
                    or []
                )
            )

            _probe_rows.append(
                (
                    "#{:03d}"
                    " | layer={!r}"
                    " | explicit={}"
                    " | mode={}"
                    " | pts={}"
                    " | closed={}"
                    " | center=({:.3f},{:.3f})"
                    " | radius={:.3f}"
                    " | sweep={:.2f}"
                ).format(
                    _probe_index,
                    _probe_layer,
                    _probe_explicit,
                    _probe_mode,
                    len(_probe_points),
                    bool(
                        _probe_item.get(
                            "closed",
                            False,
                        )
                    ),
                    float(_probe_center[0]),
                    float(_probe_center[1]),
                    _probe_radius,
                    _probe_sweep,
                )
            )

        (
# CAD3D_PHASE_C13_PORTABLE_PROJECT_PATHS
# Diagnostic log paths are resolved from this source file's project root.
            _ProbePath(__file__).resolve().parents[2]
            / "logs"
            / "door_arc_runtime_probe.txt"
        ).write_text(
            "\n".join(_probe_rows),
            encoding="utf-8",
        )

    except Exception as _probe_error:
        try:
            (
                _ProbePath(__file__).resolve().parents[2]
                / "logs"
                / "door_arc_runtime_probe_ERROR.txt"
            ).write_text(
                repr(_probe_error),
                encoding="utf-8",
            )
        except Exception:
            pass


    # Compatibility value retained for existing result/UI fields.
    door_layer = (
        door_layers[0]
        if door_layers
        else None
    )

    # Leaf matching must see segments from EVERY explicit
    # architectural door layer, not only the first layer.
    door_layer_segments = (
        extract_segments(
            geometry,
            door_layers,
        )
        if door_layers
        else []
    )

    arcs = []

    for item in door_layer_items:
        candidate = _arc_candidate(
            item,
            profile,
        )

        if candidate is None:
            candidate = _dedicated_door_arc_candidate(
                item,
                profile,
            )

        if candidate is not None:
            arcs.append(candidate)

    doors = []

    for arc in arcs:
        leaf = _leaf_match(
            arc,
            door_layer_segments,
        )

        door = _resolve_door(
            arc,
            leaf,
            wall_segments,
        )

        if door is not None:
            door["detection_mode"] = (
                "dedicated_layer_plus_wall"
            )
            door["source_arc_points"] = [
                [
                    float(p[0]),
                    float(p[1]),
                ]
                for p in arc.get(
                    "source_points",
                    [],
                )
            ]
        else:
            # Dedicated DOOR layer keeps a geometrically valid door
            # visible even if secondary confidence is insufficient.
            door = _door_from_dedicated_layer_arc(
                arc,
                leaf,
                wall_segments,
            )

        if door is not None:
            # FINAL MAX-BRIDGE JAMBS:
            # derive both coordinates from ACTUAL structural-wall
            # segment endpoints around the opening.
            gap_jambs = _resolve_wall_gap_jambs(
                arc,
                wall_segments,
            )

            if gap_jambs is not None:
                door["jamb_a"] = (
                    gap_jambs["jamb_a"]
                )
                door["jamb_b"] = (
                    gap_jambs["jamb_b"]
                )
                door["width"] = float(
                    gap_jambs["width"]
                )
                door["wall_direction"] = (
                    gap_jambs[
                        "wall_direction"
                    ]
                )
                door["hinge"] = (
                    gap_jambs["hinge"]
                )
                door["bridge_ready"] = True
                door["bridge_jamb_source"] = (
                    "structural_wall_jamb_lines"
                )
                # CAD3D_DOOR_LINE_METADATA_V4
                door["jamb_line_a"] = gap_jambs.get(
                    "jamb_line_a"
                )
                door["jamb_line_b"] = gap_jambs.get(
                    "jamb_line_b"
                )
                door["arc_radius"] = float(
                    gap_jambs.get(
                        "arc_radius",
                        door.get(
                            "width",
                            0.0,
                        ),
                    )
                )
                door["actual_gap_width"] = float(
                    gap_jambs.get(
                        "actual_gap_width",
                        door.get(
                            "width",
                            0.0,
                        ),
                    )
                )
                door["door_axis_source"] = gap_jambs.get(
                    "door_axis_source"
                )
                door["line_parallel"] = float(
                    gap_jambs.get(
                        "line_parallel",
                        0.0,
                    )
                )
                door["pair_cross"] = float(
                    gap_jambs.get(
                        "pair_cross",
                        0.0,
                    )
                )
                door["local_resolution_score"] = float(
                    gap_jambs.get(
                        "local_resolution_score",
                        0.0,
                    )
                )
            else:
                door["bridge_ready"] = False
                door["bridge_jamb_source"] = (
                    "unresolved"
                )
                door["jamb_a"] = None
                door["jamb_b"] = None
                door["jamb_line_a"] = None
                door["jamb_line_b"] = None

            doors.append(door)

    # CAD3D_DOUBLE_SWING_MERGE_CALL_V1
    # Individual double-door leaves have already been detected above.
    # Merge matching unresolved opposing leaves into one full opening
    # before dedupe / stable door numbering.
    doors = _merge_double_swing_doors(
        doors,
        wall_segments,
    )

    families = profile.get("gap_families") or []

    wall_gap = (
        float(families[0]["gap"])
        if families
        else max(float(profile.get("median_length", 1.0)) * 0.20, 1.0)
    )

    # CAD3D_DOOR_PIPELINE_AUDIT_V2
    _pre_dedupe_doors = list(doors)

    doors = _dedupe_doors(
        doors,
        wall_gap,
    )

    try:
        from pathlib import Path as _AuditPath

        _audit_rows = []

        _audit_rows.append("=== DOOR PIPELINE AUDIT V2 ===")
        _audit_rows.append("ARC COUNT: " + str(len(arcs)))
        _audit_rows.append(
            "AFTER DOUBLE MERGE / BEFORE DEDUPE: "
            + str(len(_pre_dedupe_doors))
        )
        _audit_rows.append(
            "AFTER DEDUPE: "
            + str(len(doors))
        )
        _audit_rows.append("")

        _audit_rows.append("=== ARC STATUS ===")

        for _ai, _arc in enumerate(arcs, start=1):
            try:
                _c = _arc.get("center")
                _r = float(_arc.get("radius", 0.0) or 0.0)

                _leaf = _leaf_match(
                    _arc,
                    door_layer_segments,
                )

                _resolved = _resolve_door(
                    _arc,
                    _leaf,
                    wall_segments,
                )

                _gap = _resolve_wall_gap_jambs(
                    _arc,
                    wall_segments,
                )

                _audit_rows.append(
                    (
                        "ARC #{:02d}"
                        " | center=({:.3f},{:.3f})"
                        " | r={:.3f}"
                        " | layer={!r}"
                        " | leaf={}"
                        " | resolve={}"
                        " | gap_jambs={}"
                    ).format(
                        _ai,
                        float(_c[0]),
                        float(_c[1]),
                        _r,
                        str(_arc.get("layer") or ""),
                        _leaf is not None,
                        _resolved is not None,
                        _gap is not None,
                    )
                )

            except Exception as _e:
                _audit_rows.append(
                    "ARC #{:02d} ERROR: {!r}".format(
                        _ai,
                        _e,
                    )
                )

        def _audit_door_rows(title, values):
            _audit_rows.append("")
            _audit_rows.append(title)

            for _di, _door in enumerate(values, start=1):
                _audit_rows.append(
                    (
                        "DOOR #{:02d}"
                        " | hinge={}"
                        " | jamb_a={}"
                        " | jamb_b={}"
                        " | width={}"
                        " | bridge={}"
                        " | source={!r}"
                        " | mode={!r}"
                        " | type={!r}"
                        " | leaves={}"
                        " | confidence={}"
                    ).format(
                        _di,
                        repr(_door.get("hinge")),
                        repr(_door.get("jamb_a")),
                        repr(_door.get("jamb_b")),
                        repr(_door.get("width")),
                        bool(
                            _door.get(
                                "bridge_ready",
                                False,
                            )
                        ),
                        _door.get(
                            "bridge_jamb_source"
                        ),
                        _door.get(
                            "detection_mode"
                        ),
                        _door.get(
                            "door_type"
                        ),
                        _door.get(
                            "leaf_count",
                            1,
                        ),
                        _door.get(
                            "confidence"
                        ),
                    )
                )

        _audit_door_rows(
            "=== BEFORE DEDUPE ===",
            _pre_dedupe_doors,
        )

        _audit_door_rows(
            "=== FINAL AFTER DEDUPE ===",
            doors,
        )

        (
            _AuditPath(__file__).resolve().parents[2]
            / "logs"
            / "door_pipeline_audit.txt"
        ).write_text(
            "\n".join(_audit_rows),
            encoding="utf-8",
        )

    except Exception as _audit_error:
        try:
            from pathlib import Path as _AuditPathError

            (
                _AuditPathError(__file__).resolve().parents[2]
                / "logs"
                / "door_pipeline_audit_ERROR.txt"
            ).write_text(
                repr(_audit_error),
                encoding="utf-8",
            )
        except Exception:
            pass
    # CAD3D_DOOR_FINAL_CONTRACT_ATTACH_V1
    # Metadata-only. Door list and ordering are unchanged.
    for door in doors:
        _attach_final_door_contracts(
            door
        )

    # CAD3D_NONE_SAFE_FINAL_DOOR_SORT_V1
    def _door_sort_key(door):
        def _point2(value):
            if not isinstance(
                value,
                (list, tuple),
            ):
                return None

            if len(value) < 2:
                return None

            try:
                return (
                    float(value[0]),
                    float(value[1]),
                )
            except (
                TypeError,
                ValueError,
            ):
                return None

        # Stable order anchor:
        # hinge first, then detector center, then resolved jamb,
        # finally source arc centroid. Unresolved jambs are valid.
        for key in (
            "hinge",
            "center",
            "arc_center",
            "jamb_a",
        ):
            point = _point2(
                door.get(
                    key
                )
            )

            if point is not None:
                return (
                    round(
                        point[1],
                        6,
                    ),
                    round(
                        point[0],
                        6,
                    ),
                    0
                    if bool(
                        door.get(
                            "bridge_ready",
                            False,
                        )
                    )
                    else 1,
                )

        source_points = door.get(
            "source_arc_points",
            []
        )

        valid_points = [
            point
            for point in (
                _point2(value)
                for value in source_points
            )
            if point is not None
        ]

        if valid_points:
            x = sum(
                point[0]
                for point in valid_points
            ) / len(
                valid_points
            )

            y = sum(
                point[1]
                for point in valid_points
            ) / len(
                valid_points
            )

            return (
                round(
                    y,
                    6,
                ),
                round(
                    x,
                    6,
                ),
                1,
            )

        return (
            1.0e30,
            1.0e30,
            1,
        )

    doors.sort(
        key=_door_sort_key
    )

    for index, door in enumerate(doors, start=1):
        door["door_id"] = "D" + str(index).zfill(3)
        door["bridge_pair_index"] = index - 1

    # CAD3D_DOOR_ENTITY_OUTPUT_V1
    # Parallel output only. Existing doors list is unchanged.
    entities = []

    for door in doors:
        entity = _door_to_architectural_entity(
            door
        )
        entities.append(
            entity.as_dict()
        )

    # CAD3D_DOOR_ENTITY_RUNTIME_AUDIT_V1
    try:
        from pathlib import Path as _DoorEntityAuditPath
        _audit_path = (
            _DoorEntityAuditPath(__file__).resolve().parents[2]
            / "logs"
            / "door_entity_audit.txt"
        )
        _audit_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        _audit_lines = []
        _audit_lines.append("=== DOOR ENTITY AUDIT V1 ===")
        _audit_lines.append("DOOR COUNT: " + str(len(doors)))
        _audit_lines.append("ENTITY COUNT: " + str(len(entities)))
        _audit_lines.append(
            "BRIDGE READY COUNT: "
            + str(
                sum(
                    1
                    for _door in doors
                    if bool(
                        _door.get("bridge_ready", False)
                    )
                )
            )
        )
        _audit_lines.append("")
        for _entity in entities:
            _rc = _entity.get("recognition_contract", {}) or {}
            _sr = _entity.get("structural_relation", {}) or {}
            _xp = _entity.get("execution_permissions", {}) or {}
            _md = _entity.get("metadata", {}) or {}
            _bc = _sr.get("bridge_execution_contract", {}) or {}
            _audit_lines.append(
                "ENTITY " + str(_entity.get("entity_id"))
                + " | type=" + repr(_entity.get("entity_type"))
                + " | recognized=" + repr(bool(_rc.get("accepted", False)))
                + " | bridge_ready=" + repr(bool(_sr.get("bridge_ready", False)))
                + " | bridge_contract=" + repr(bool(_bc.get("accepted", False)))
                + " | bridge_allowed=" + repr(bool(_xp.get("bridge", False)))
                + " | jamb_source=" + repr(_sr.get("bridge_jamb_source"))
                + " | door_type=" + repr(_md.get("door_type"))
                + " | mode=" + repr(_md.get("detection_mode"))
                + " | leaves=" + repr(_md.get("leaf_count"))
            )
        _audit_path.write_text(
            "\n".join(_audit_lines) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "engine": ENGINE,
        "door_layer": door_layer,
        "door_arc_count": len(arcs),
        "door_count": len(doors),
        "bridge_ready_count": sum(
            1
            for door in doors
            if bool(
                door.get(
                    "bridge_ready",
                    False,
                )
            )
        ),
        "doors": doors,
        "entity_count": len(entities),
        "entities": entities,
        "profile": {
            "primary_structural_layer": primary,
            "structural_layers": structural_layers,
            "confidence": float(profile.get("confidence", 0.0)),
            "wall_gap": float(wall_gap),
        },
        "batch_bridge_rule": (
            "all doors detected first; "
            "future Max stage clears polygon selection per door, "
            "selects exactly two opposing upper polygons, "
            "bridges that pair, commits, then continues to next door"
        ),
    }


def _arc_points(center, radius, start_deg, end_deg, count=13):
    output = []

    for index in range(count):
        t = index / max(1, count - 1)
        angle = math.radians(start_deg + (end_deg - start_deg) * t)

        output.append(
            (
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
            )
        )

    return output


def self_test():
    geometry = []

    for y in (0.0, 180.0):
        geometry.append(
            {
                "layer": "X_STRUCT",
                "points": [(-2000.0, y), (0.0, y)],
            }
        )

        geometry.append(
            {
                "layer": "X_STRUCT",
                "points": [(900.0, y), (3000.0, y)],
            }
        )

    geometry.append(
        {
            "layer": "TEST_DOOR",
            "points": _arc_points((0.0, 0.0), 900.0, 0.0, 90.0),
        }
    )

    geometry.append(
        {
            "layer": "TEST_DOOR",
            "points": [(0.0, 0.0), (0.0, 900.0)],
        }
    )

    result = detect_doors(geometry)

    assert result["door_count"] == 1, result

    door = result["doors"][0]

    assert abs(door["width"] - 900.0) < 20.0, door
    assert door["bridge_pair_index"] == 0

    print("GENERIC BATCH DOOR DETECTOR V2 SELF-TEST: OK")
    print("DOORS:", result["door_count"])
    print("WIDTH:", round(door["width"], 3))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
