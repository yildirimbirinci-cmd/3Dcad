from __future__ import annotations

from cad._cad_to_3d_max_facade.geometry_core import (
    direction2,
    directions_parallel,
    distance2,
    point_segment_distance,
)


ENGINE = "CAD3D_DETERMINISTIC_STRUCTURAL_RULES_V1"


def extract_structural_segments(
    geometry,
    *,
    structural_layer=None,
    layer_acceptor=None,
    point_parser=None,
    minimum_length=1.0,
):
    """
    Build normalized structural segments.

    Exact structural_layer always wins.
    Semantic layer_acceptor is only fallback.
    """

    segments = []

    exact_layer = str(
        structural_layer
        or ""
    ).strip()

    if point_parser is None:
        raise ValueError(
            "point_parser is required"
        )

    for item in geometry:
        if not isinstance(
            item,
            dict,
        ):
            continue

        layer = str(
            item.get(
                "layer",
                "",
            )
            or ""
        ).strip()

        if exact_layer:
            if layer != exact_layer:
                continue
        else:
            if layer_acceptor is not None:
                if not layer_acceptor(layer):
                    continue

        points = []

        for value in (
            item.get(
                "points",
                [],
            )
            or []
        ):
            point = point_parser(
                value
            )

            if point is not None:
                points.append(
                    point
                )

        if len(points) < 2:
            continue

        for a, b in zip(
            points,
            points[1:],
        ):
            length = distance2(
                a,
                b,
            )

            if length <= minimum_length:
                continue

            segments.append(
                {
                    "a": a,
                    "b": b,
                    "layer": layer,
                    "length": length,
                }
            )

        if (
            bool(
                item.get(
                    "closed",
                    False,
                )
            )
            and len(points) > 2
        ):
            a = points[-1]
            b = points[0]

            length = distance2(
                a,
                b,
            )

            if length > minimum_length:
                segments.append(
                    {
                        "a": a,
                        "b": b,
                        "layer": layer,
                        "length": length,
                    }
                )

    return segments


def segment_direction(
    segment,
    *,
    min_length=1.0e-9,
):
    if not segment:
        return None

    return direction2(
        segment["a"],
        segment["b"],
        min_length=min_length,
    )


def nearest_structural_segment(
    point,
    segments,
    *,
    required_direction=None,
    max_angle_deg=18.0,
    degenerate_epsilon=1.0e-12,
):
    best = None
    best_distance = float("inf")

    for segment in segments:

        if (
            required_direction
            is not None
        ):
            candidate_direction = (
                segment_direction(
                    segment
                )
            )

            if not directions_parallel(
                required_direction,
                candidate_direction,
                max_angle_deg=max_angle_deg,
            ):
                continue

        distance = (
            point_segment_distance(
                point,
                segment["a"],
                segment["b"],
                degenerate_epsilon=(
                    degenerate_epsilon
                ),
            )
        )

        if distance < best_distance:
            best_distance = distance
            best = segment

    return (
        best,
        best_distance,
    )


def nearest_wall_continuation(
    jamb,
    segments,
    opening_direction,
    required_sign,
    *,
    max_angle_deg=18.0,
    minimum_projection=1.0,
):
    """
    Resolve wall continuation AWAY from an opening jamb.

    required_sign:
        -1 -> continuation toward negative opening axis
        +1 -> continuation toward positive opening axis
    """

    best_segment = None
    best_endpoint_distance = (
        float("inf")
    )

    ux = float(
        opening_direction[0]
    )

    uy = float(
        opening_direction[1]
    )

    for segment in segments:

        candidate_direction = (
            segment_direction(
                segment
            )
        )

        if not directions_parallel(
            opening_direction,
            candidate_direction,
            max_angle_deg=max_angle_deg,
        ):
            continue

        a = segment["a"]
        b = segment["b"]

        candidates = (
            (a, b),
            (b, a),
        )

        for endpoint, other in candidates:

            endpoint_distance = (
                distance2(
                    jamb,
                    endpoint,
                )
            )

            vx = (
                other[0]
                - jamb[0]
            )

            vy = (
                other[1]
                - jamb[1]
            )

            projection = (
                vx * ux
                + vy * uy
            )

            if required_sign < 0:
                if projection >= (
                    -minimum_projection
                ):
                    continue
            else:
                if projection <= (
                    minimum_projection
                ):
                    continue

            if (
                endpoint_distance
                < best_endpoint_distance
            ):
                best_endpoint_distance = (
                    endpoint_distance
                )
                best_segment = segment

    return (
        best_segment,
        best_endpoint_distance,
    )
