from __future__ import annotations

import math

from statistics import median


ENGINE_VERSION = "GENERIC_CAD_CLEANUP_V5_3_VERTEX_SIMPLIFY"


# ============================================================
# BASIC GEOMETRY
# ============================================================

def _dist(
    a,
    b,
):
    return math.hypot(
        a[0] - b[0],
        a[1] - b[1],
    )


def _length(
    seg,
):
    return _dist(
        seg["a"],
        seg["b"],
    )


def _cross(
    a,
    b,
):
    return (
        a[0] * b[1]
        - a[1] * b[0]
    )


def _dot(
    a,
    b,
):
    return (
        a[0] * b[0]
        + a[1] * b[1]
    )


def _unit_vector(
    a,
    b,
):
    dx = (
        b[0] - a[0]
    )

    dy = (
        b[1] - a[1]
    )

    length = math.hypot(
        dx,
        dy,
    )

    if length <= 1e-12:
        return None

    ux = (
        dx / length
    )

    uy = (
        dy / length
    )

    # Canonical orientation:
    # opposite-direction segments use the same direction.
    if (
        ux < -1e-12
        or (
            abs(
                ux
            ) <= 1e-12
            and uy < 0.0
        )
    ):
        ux = -ux
        uy = -uy

    return (
        ux,
        uy,
    )


def _angle(
    seg,
):
    u = _unit_vector(
        seg["a"],
        seg["b"],
    )

    if u is None:
        return 0.0

    return math.atan2(
        u[1],
        u[0],
    )


def _angle_difference(
    a,
    b,
):
    diff = abs(
        a - b
    )

    while (
        diff
        >= math.pi
    ):
        diff -= math.pi

    return min(
        diff,
        math.pi - diff,
    )


def _percentile(
    values,
    ratio,
):
    if not values:
        return 0.0

    ordered = sorted(
        values
    )

    position = int(
        round(
            (
                len(
                    ordered
                )
                - 1
            )
            * ratio
        )
    )

    position = max(
        0,
        min(
            len(
                ordered
            )
            - 1,
            position,
        ),
    )

    return float(
        ordered[
            position
        ]
    )


# ============================================================
# SOURCE -> SEGMENTS
# ============================================================

def explode_drawings_to_segments(
    drawings,
):
    segments = []

    for source_index, item in enumerate(
        drawings
    ):
        points = item.get(
            "points",
            [],
        )

        if len(
            points
        ) < 2:
            continue

        clean = []

        for point in points:
            try:
                p = (
                    float(
                        point[0]
                    ),
                    float(
                        point[1]
                    ),
                )

            except Exception:
                continue

            if (
                clean
                and _dist(
                    clean[-1],
                    p,
                )
                <= 1e-12
            ):
                continue

            clean.append(
                p
            )

        if len(
            clean
        ) < 2:
            continue

        closed = bool(
            item.get(
                "closed",
                False,
            )
        )

        if (
            len(
                clean
            )
            >= 3
            and _dist(
                clean[0],
                clean[-1],
            )
            <= 1e-9
        ):
            closed = True
            clean = clean[
                :-1
            ]

        metadata = {
            "layer":
                str(
                    item.get(
                        "layer",
                        "",
                    )
                ).strip(),

            "linetype":
                str(
                    item.get(
                        "linetype",
                        "",
                    )
                ).strip(),

            "effective_linetype":
                str(
                    item.get(
                        "effective_linetype",
                        item.get(
                            "linetype",
                            "",
                        ),
                    )
                ).strip(),

            "entity_type":
                str(
                    item.get(
                        "entity_type",
                        "",
                    )
                ).strip(),

            "handle":
                str(
                    item.get(
                        "handle",
                        "",
                    )
                ).strip(),

            "source_index":
                source_index,

            "source_closed":
                bool(
                    closed
                ),
        }

        for index in range(
            len(
                clean
            )
            - 1
        ):
            seg = dict(
                metadata
            )

            seg[
                "a"
            ] = clean[
                index
            ]

            seg[
                "b"
            ] = clean[
                index + 1
            ]

            if (
                _length(
                    seg
                )
                > 1e-12
            ):
                segments.append(
                    seg
                )

        if (
            closed
            and len(
                clean
            )
            >= 3
        ):
            seg = dict(
                metadata
            )

            seg[
                "a"
            ] = clean[
                -1
            ]

            seg[
                "b"
            ] = clean[
                0
            ]

            if (
                _length(
                    seg
                )
                > 1e-12
            ):
                segments.append(
                    seg
                )

    return segments


# ============================================================
# DYNAMIC DRAWING PROFILE
# ============================================================

def infer_geometry_profile(
    segments,
):
    points = []

    lengths = []

    for seg in segments:
        points.append(
            seg["a"]
        )

        points.append(
            seg["b"]
        )

        value = _length(
            seg
        )

        if value > 1e-12:
            lengths.append(
                value
            )

    if not points:
        return {
            "drawing_diagonal": 1.0,
            "median_length": 1.0,
            "p10_length": 1.0,
            "snap_tolerance": 1e-5,
            "line_tolerance": 1e-5,
            "angle_tolerance_deg": 1.5,
            "short_spur_limit": 1e-4,
        }

    xs = [
        point[0]
        for point in points
    ]

    ys = [
        point[1]
        for point in points
    ]

    width = max(
        xs
    ) - min(
        xs
    )

    height = max(
        ys
    ) - min(
        ys
    )

    diagonal = max(
        math.hypot(
            width,
            height,
        ),
        1e-9,
    )

    if lengths:
        med = median(
            lengths
        )

        p10 = _percentile(
            lengths,
            0.10,
        )

    else:
        med = (
            diagonal
            * 0.01
        )

        p10 = med

    # --------------------------------------------------------
    # Scale-relative tolerances.
    #
    # Example:
    # 20,000-unit plan -> ~1 unit snap
    # 20-meter plan    -> ~0.001 unit snap
    #
    # Same physical/geometrical behavior regardless of CAD unit.
    # --------------------------------------------------------

    snap = (
        diagonal
        * 0.00005
    )

    snap = min(
        snap,
        max(
            med
            * 0.03,
            diagonal
            * 1e-8,
        ),
    )

    snap = max(
        snap,
        diagonal
        * 1e-8,
        1e-12,
    )

    line_tol = (
        snap
        * 1.25
    )

    spur_limit = max(
        snap
        * 8.0,
        min(
            med
            * 0.25,
            diagonal
            * 0.002,
        ),
    )

    return {
        "drawing_diagonal":
            float(
                diagonal
            ),

        "median_length":
            float(
                med
            ),

        "p10_length":
            float(
                p10
            ),

        "snap_tolerance":
            float(
                snap
            ),

        "line_tolerance":
            float(
                line_tol
            ),

        "angle_tolerance_deg":
            1.5,

        "short_spur_limit":
            float(
                spur_limit
            ),
    }


# ============================================================
# KEYS / GRAPH
# ============================================================

def _node_key(
    point,
    tolerance,
):
    unit = max(
        tolerance
        * 0.25,
        1e-12,
    )

    return (
        round(
            point[0]
            / unit
        ),
        round(
            point[1]
            / unit
        ),
    )


def _segment_key(
    seg,
    tolerance,
):
    a = _node_key(
        seg["a"],
        tolerance,
    )

    b = _node_key(
        seg["b"],
        tolerance,
    )

    return tuple(
        sorted(
            (
                a,
                b,
            )
        )
    )


def remove_exact_duplicates(
    segments,
    tolerance,
):
    output = []

    seen = set()

    removed = 0

    for seg in segments:
        key = _segment_key(
            seg,
            tolerance,
        )

        if key in seen:
            removed += 1
            continue

        seen.add(
            key
        )

        output.append(
            seg
        )

    return (
        output,
        removed,
    )


# ============================================================
# ENDPOINT SNAP / WELD
# ============================================================

def snap_endpoints(
    segments,
    profile,
):
    tolerance = profile[
        "snap_tolerance"
    ]

    endpoints = []

    for seg_index, seg in enumerate(
        segments
    ):
        endpoints.append(
            (
                seg_index,
                "a",
                seg["a"],
            )
        )

        endpoints.append(
            (
                seg_index,
                "b",
                seg["b"],
            )
        )

    count = len(
        endpoints
    )

    parent = list(
        range(
            count
        )
    )

    def find(
        value,
    ):
        while (
            parent[value]
            != value
        ):
            parent[value] = parent[
                parent[value]
            ]

            value = parent[
                value
            ]

        return value

    def union(
        a,
        b,
    ):
        ra = find(
            a
        )

        rb = find(
            b
        )

        if ra != rb:
            parent[
                rb
            ] = ra

    if count <= 0:
        return (
            list(
                segments
            ),
            0,
            0,
        )

    cell_size = max(
        tolerance,
        1e-12,
    )

    cells = {}

    for index, (
        seg_index,
        side,
        point,
    ) in enumerate(
        endpoints
    ):
        cx = math.floor(
            point[0]
            / cell_size
        )

        cy = math.floor(
            point[1]
            / cell_size
        )

        for ox in (
            -1,
            0,
            1,
        ):
            for oy in (
                -1,
                0,
                1,
            ):
                for other_index in cells.get(
                    (
                        cx + ox,
                        cy + oy,
                    ),
                    [],
                ):
                    if (
                        _dist(
                            point,
                            endpoints[
                                other_index
                            ][2],
                        )
                        <= tolerance
                    ):
                        union(
                            index,
                            other_index,
                        )

        cells.setdefault(
            (
                cx,
                cy,
            ),
            [],
        ).append(
            index
        )

    clusters = {}

    for index in range(
        count
    ):
        root = find(
            index
        )

        clusters.setdefault(
            root,
            [],
        ).append(
            index
        )

    positions = {}

    welded_groups = 0
    welded_endpoints = 0

    for root, members in (
        clusters.items()
    ):
        x = sum(
            endpoints[
                index
            ][2][0]
            for index in members
        ) / len(
            members
        )

        y = sum(
            endpoints[
                index
            ][2][1]
            for index in members
        ) / len(
            members
        )

        positions[
            root
        ] = (
            x,
            y,
        )

        if len(
            members
        ) > 1:
            welded_groups += 1
            welded_endpoints += len(
                members
            )

    result = [
        dict(
            seg
        )
        for seg in segments
    ]

    for endpoint_index, (
        seg_index,
        side,
        point,
    ) in enumerate(
        endpoints
    ):
        result[
            seg_index
        ][
            side
        ] = positions[
            find(
                endpoint_index
            )
        ]

    result = [
        seg
        for seg in result
        if (
            _length(
                seg
            )
            > tolerance
            * 0.10
        )
    ]

    return (
        result,
        welded_groups,
        welded_endpoints,
    )


# ============================================================
# COLLINEAR OVERLAP NORMALIZATION
#
# Removes duplicate/overlapping line portions regardless of
# angle. No H/V assumption.
# ============================================================

def normalize_collinear_overlaps(
    segments,
    profile,
):
    if not segments:
        return (
            [],
            0,
        )

    angle_tol = math.radians(
        0.75
    )

    offset_tol = max(
        profile[
            "line_tolerance"
        ]
        * 0.5,
        1e-12,
    )

    groups = {}

    for index, seg in enumerate(
        segments
    ):
        u = _unit_vector(
            seg["a"],
            seg["b"],
        )

        if u is None:
            continue

        angle = math.atan2(
            u[1],
            u[0],
        )

        midpoint = (
            (
                seg["a"][0]
                + seg["b"][0]
            )
            * 0.5,
            (
                seg["a"][1]
                + seg["b"][1]
            )
            * 0.5,
        )

        normal = (
            -u[1],
            u[0],
        )

        offset = _dot(
            normal,
            midpoint,
        )

        key = (
            round(
                angle
                / angle_tol
            ),
            round(
                offset
                / offset_tol
            ),
        )

        groups.setdefault(
            key,
            [],
        ).append(
            (
                index,
                seg,
            )
        )

    output = []

    overlap_removed = 0

    handled = set()

    for group in groups.values():
        if not group:
            continue

        first_seg = group[
            0
        ][1]

        u = _unit_vector(
            first_seg[
                "a"
            ],
            first_seg[
                "b"
            ],
        )

        if u is None:
            continue

        origin = first_seg[
            "a"
        ]

        intervals = []

        for index, seg in group:
            handled.add(
                index
            )

            t0 = _dot(
                (
                    seg["a"][0]
                    - origin[0],
                    seg["a"][1]
                    - origin[1],
                ),
                u,
            )

            t1 = _dot(
                (
                    seg["b"][0]
                    - origin[0],
                    seg["b"][1]
                    - origin[1],
                ),
                u,
            )

            start = min(
                t0,
                t1,
            )

            end = max(
                t0,
                t1,
            )

            intervals.append(
                (
                    start,
                    end,
                    seg,
                )
            )

        if len(
            intervals
        ) == 1:
            output.append(
                intervals[
                    0
                ][2]
            )

            continue

        cuts = sorted(
            {
                value
                for start, end, seg
                in intervals
                for value in (
                    start,
                    end,
                )
            }
        )

        emitted = 0

        for cut_index in range(
            len(
                cuts
            )
            - 1
        ):
            start = cuts[
                cut_index
            ]

            end = cuts[
                cut_index + 1
            ]

            if (
                end - start
                <= profile[
                    "snap_tolerance"
                ]
                * 0.10
            ):
                continue

            middle = (
                start
                + end
            ) * 0.5

            covers = [
                item
                for item in intervals
                if (
                    item[0]
                    - profile[
                        "snap_tolerance"
                    ]
                    * 0.10
                    <= middle
                    <= item[1]
                    + profile[
                        "snap_tolerance"
                    ]
                    * 0.10
                )
            ]

            if not covers:
                continue

            template = dict(
                covers[
                    0
                ][2]
            )

            template[
                "source_closed"
            ] = any(
                bool(
                    item[2].get(
                        "source_closed",
                        False,
                    )
                )
                for item in covers
            )

            template[
                "a"
            ] = (
                origin[0]
                + u[0] * start,
                origin[1]
                + u[1] * start,
            )

            template[
                "b"
            ] = (
                origin[0]
                + u[0] * end,
                origin[1]
                + u[1] * end,
            )

            output.append(
                template
            )

            emitted += 1

        overlap_removed += max(
            0,
            len(
                intervals
            )
            - emitted,
        )

    for index, seg in enumerate(
        segments
    ):
        if index not in handled:
            output.append(
                seg
            )

    return (
        output,
        overlap_removed,
    )


# ============================================================
# ARBITRARY ANGLE INTERSECTION SPLIT
# ============================================================

def split_intersections(
    segments,
    profile,
):
    """
    GENERIC ARBITRARY-ANGLE INTERSECTION SPLITTER V2

    IMPORTANT:
    Geometric tolerance is in CAD coordinate units.

    Intersection parameters t/u are dimensionless values in
    the range 0..1.

    Therefore a coordinate tolerance MUST be converted to a
    per-segment parametric tolerance:

        t_tol = coordinate_tolerance / segment_length

    The previous implementation compared CAD units directly
    against t/u and could reject intersections near the first
    or last ~10 percent of long segments.

    This version correctly handles:
    - X intersections
    - T junctions
    - endpoint -> middle junctions
    - arbitrary rotations
    - any CAD source unit
    """

    tolerance = max(
        float(
            profile[
                "snap_tolerance"
            ]
        ),
        1e-12,
    )

    split_parameters = {
        index: {
            0.0,
            1.0,
        }
        for index in range(
            len(
                segments
            )
        )
    }

    split_count = 0

    for i in range(
        len(
            segments
        )
    ):
        seg_a = segments[
            i
        ]

        p = seg_a[
            "a"
        ]

        r = (
            seg_a["b"][0]
            - seg_a["a"][0],
            seg_a["b"][1]
            - seg_a["a"][1],
        )

        r_length = math.hypot(
            r[0],
            r[1],
        )

        if (
            r_length
            <= 1e-12
        ):
            continue

        # Coordinate distance -> dimensionless t tolerance.
        t_tolerance = min(
            0.25,
            max(
                tolerance
                / r_length,
                1e-12,
            ),
        )

        ax0 = min(
            seg_a["a"][0],
            seg_a["b"][0],
        ) - tolerance

        ax1 = max(
            seg_a["a"][0],
            seg_a["b"][0],
        ) + tolerance

        ay0 = min(
            seg_a["a"][1],
            seg_a["b"][1],
        ) - tolerance

        ay1 = max(
            seg_a["a"][1],
            seg_a["b"][1],
        ) + tolerance

        for j in range(
            i + 1,
            len(
                segments
            )
        ):
            seg_b = segments[
                j
            ]

            q = seg_b[
                "a"
            ]

            s = (
                seg_b["b"][0]
                - seg_b["a"][0],
                seg_b["b"][1]
                - seg_b["a"][1],
            )

            s_length = math.hypot(
                s[0],
                s[1],
            )

            if (
                s_length
                <= 1e-12
            ):
                continue

            u_tolerance = min(
                0.25,
                max(
                    tolerance
                    / s_length,
                    1e-12,
                ),
            )

            bx0 = min(
                seg_b["a"][0],
                seg_b["b"][0],
            ) - tolerance

            bx1 = max(
                seg_b["a"][0],
                seg_b["b"][0],
            ) + tolerance

            by0 = min(
                seg_b["a"][1],
                seg_b["b"][1],
            ) - tolerance

            by1 = max(
                seg_b["a"][1],
                seg_b["b"][1],
            ) + tolerance

            # Cheap bounding-box reject.
            if (
                ax1 < bx0
                or bx1 < ax0
                or ay1 < by0
                or by1 < ay0
            ):
                continue

            denominator = _cross(
                r,
                s,
            )

            denominator_scale = max(
                r_length
                * s_length,
                1e-12,
            )

            # Parallel / collinear.
            #
            # Overlapping collinear geometry is handled by
            # normalize_collinear_overlaps(), so it must not
            # create fake crossing intersections here.
            if (
                abs(
                    denominator
                )
                <= denominator_scale
                * 1e-10
            ):
                continue

            qp = (
                q[0] - p[0],
                q[1] - p[1],
            )

            t = (
                _cross(
                    qp,
                    s,
                )
                / denominator
            )

            u = (
                _cross(
                    qp,
                    r,
                )
                / denominator
            )

            # Accept intersections that are within one geometric
            # tolerance of the segment endpoint.
            if not (
                -t_tolerance
                <= t
                <= 1.0
                + t_tolerance
            ):
                continue

            if not (
                -u_tolerance
                <= u
                <= 1.0
                + u_tolerance
            ):
                continue

            t_clamped = max(
                0.0,
                min(
                    1.0,
                    t,
                ),
            )

            u_clamped = max(
                0.0,
                min(
                    1.0,
                    u,
                ),
            )

            # ------------------------------------------------
            # Split A if the intersection is genuinely inside A.
            #
            # If B merely ENDS on the middle of A, this still
            # creates the required T-junction vertex in A.
            # ------------------------------------------------

            if (
                t_tolerance
                < t_clamped
                < 1.0
                - t_tolerance
            ):
                before = len(
                    split_parameters[
                        i
                    ]
                )

                split_parameters[
                    i
                ].add(
                    t_clamped
                )

                if (
                    len(
                        split_parameters[
                            i
                        ]
                    )
                    > before
                ):
                    split_count += 1

            # ------------------------------------------------
            # Split B independently.
            #
            # This is deliberately independent of whether A was
            # split, which is required for endpoint-to-middle
            # T-junctions.
            # ------------------------------------------------

            if (
                u_tolerance
                < u_clamped
                < 1.0
                - u_tolerance
            ):
                before = len(
                    split_parameters[
                        j
                    ]
                )

                split_parameters[
                    j
                ].add(
                    u_clamped
                )

                if (
                    len(
                        split_parameters[
                            j
                        ]
                    )
                    > before
                ):
                    split_count += 1

    result = []

    for index, seg in enumerate(
        segments
    ):
        parameters = sorted(
            split_parameters[
                index
            ]
        )

        dx = (
            seg["b"][0]
            - seg["a"][0]
        )

        dy = (
            seg["b"][1]
            - seg["a"][1]
        )

        for part_index in range(
            len(
                parameters
            )
            - 1
        ):
            t0 = parameters[
                part_index
            ]

            t1 = parameters[
                part_index + 1
            ]

            if (
                t1 - t0
                <= 1e-12
            ):
                continue

            child = dict(
                seg
            )

            child[
                "a"
            ] = (
                seg["a"][0]
                + dx * t0,
                seg["a"][1]
                + dy * t0,
            )

            child[
                "b"
            ] = (
                seg["a"][0]
                + dx * t1,
                seg["a"][1]
                + dy * t1,
            )

            if (
                _length(
                    child
                )
                > tolerance
                * 0.10
            ):
                result.append(
                    child
                )

    return (
        result,
        split_count,
    )


def _build_graph(
    segments,
    profile,
):
    tolerance = profile[
        "snap_tolerance"
    ]

    adjacency = {}

    node_points = {}

    edge_nodes = []

    for index, seg in enumerate(
        segments
    ):
        a = _node_key(
            seg["a"],
            tolerance,
        )

        b = _node_key(
            seg["b"],
            tolerance,
        )

        edge_nodes.append(
            (
                a,
                b,
            )
        )

        node_points[
            a
        ] = seg[
            "a"
        ]

        node_points[
            b
        ] = seg[
            "b"
        ]

        adjacency.setdefault(
            a,
            [],
        ).append(
            index
        )

        adjacency.setdefault(
            b,
            [],
        ).append(
            index
        )

    return (
        adjacency,
        edge_nodes,
        node_points,
    )


def _find_bridge_edges(
    segments,
    profile,
):
    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    discovery = {}

    low = {}

    time_counter = [
        0
    ]

    bridges = set()

    def other(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        return a

    def dfs(
        node,
        parent_edge=None,
    ):
        time_counter[
            0
        ] += 1

        discovery[
            node
        ] = time_counter[
            0
        ]

        low[
            node
        ] = time_counter[
            0
        ]

        for edge_index in adjacency.get(
            node,
            [],
        ):
            if (
                edge_index
                == parent_edge
            ):
                continue

            next_node = other(
                edge_index,
                node,
            )

            if (
                next_node
                not in discovery
            ):
                dfs(
                    next_node,
                    edge_index,
                )

                low[
                    node
                ] = min(
                    low[
                        node
                    ],
                    low[
                        next_node
                    ],
                )

                if (
                    low[
                        next_node
                    ]
                    > discovery[
                        node
                    ]
                ):
                    bridges.add(
                        edge_index
                    )

            else:
                low[
                    node
                ] = min(
                    low[
                        node
                    ],
                    discovery[
                        next_node
                    ],
                )

    for node in adjacency:
        if node not in discovery:
            dfs(
                node
            )

    return bridges


def cycle_protected_edges(
    segments,
    profile,
):
    bridges = _find_bridge_edges(
        segments,
        profile,
    )

    protected = set()

    for index, seg in enumerate(
        segments
    ):
        if bool(
            seg.get(
                "source_closed",
                False,
            )
        ):
            protected.add(
                index
            )

        elif index not in bridges:
            # Any non-bridge edge belongs to at least one cycle.
            protected.add(
                index
            )

    return protected


# ============================================================
# PARALLEL GEOMETRY + AUTOMATIC WALL-SPACING FAMILIES
# ============================================================

def _parallel_metrics(
    a,
    b,
):
    ua = _unit_vector(
        a["a"],
        a["b"],
    )

    ub = _unit_vector(
        b["a"],
        b["b"],
    )

    if (
        ua is None
        or ub is None
    ):
        return None

    angle_diff = _angle_difference(
        math.atan2(
            ua[1],
            ua[0],
        ),
        math.atan2(
            ub[1],
            ub[0],
        ),
    )

    normal = (
        -ua[1],
        ua[0],
    )

    midpoint_b = (
        (
            b["a"][0]
            + b["b"][0]
        )
        * 0.5,
        (
            b["a"][1]
            + b["b"][1]
        )
        * 0.5,
    )

    gap = abs(
        _dot(
            normal,
            (
                midpoint_b[0]
                - a["a"][0],
                midpoint_b[1]
                - a["a"][1],
            ),
        )
    )

    a0 = 0.0

    a1 = _length(
        a
    )

    b0 = _dot(
        (
            b["a"][0]
            - a["a"][0],
            b["a"][1]
            - a["a"][1],
        ),
        ua,
    )

    b1 = _dot(
        (
            b["b"][0]
            - a["a"][0],
            b["b"][1]
            - a["a"][1],
        ),
        ua,
    )

    overlap = max(
        0.0,
        min(
            a1,
            max(
                b0,
                b1,
            ),
        )
        - max(
            a0,
            min(
                b0,
                b1,
            ),
        ),
    )

    shorter = min(
        _length(
            a
        ),
        _length(
            b
        ),
    )

    ratio = (
        overlap
        / shorter
        if shorter > 1e-12
        else 0.0
    )

    return {
        "angle_difference":
            angle_diff,

        "gap":
            gap,

        "overlap":
            overlap,

        "overlap_ratio":
            ratio,
    }


def infer_parallel_gap_families(
    segments,
    profile,
):
    """
    Learn structural parallel-face spacing directly from CAD.

    Generic evidence rule:

        overlap >= gap * MIN_STRUCTURAL_ASPECT

    This rejects room-to-room spacing and short dashed pieces
    while preserving genuine long parallel architectural faces.

    No physical unit or wall-thickness assumptions.
    """

    angle_tol = math.radians(
        profile[
            "angle_tolerance_deg"
        ]
    )

    min_gap = (
        profile[
            "snap_tolerance"
        ]
        * 3.0
    )

    max_gap = (
        profile[
            "drawing_diagonal"
        ]
        * 0.08
    )

    MIN_STRUCTURAL_ASPECT = 1.50

    gaps = []

    for i in range(
        len(
            segments
        )
    ):
        a = segments[
            i
        ]

        for j in range(
            i + 1,
            len(
                segments
            )
        ):
            b = segments[
                j
            ]

            metrics = _parallel_metrics(
                a,
                b,
            )

            if metrics is None:
                continue

            if (
                metrics[
                    "angle_difference"
                ]
                > angle_tol
            ):
                continue

            if (
                metrics[
                    "overlap_ratio"
                ]
                < 0.60
            ):
                continue

            gap = metrics[
                "gap"
            ]

            overlap = metrics[
                "overlap"
            ]

            if not (
                min_gap
                <= gap
                <= max_gap
            ):
                continue

            # ------------------------------------------------
            # CRITICAL GENERIC TEST
            #
            # Long parallel faces separated by a comparatively
            # small distance are architectural-band evidence.
            #
            # Short dashes separated from another line by a
            # similar/larger amount cannot teach a wall family.
            # ------------------------------------------------

            if (
                overlap
                < gap
                * MIN_STRUCTURAL_ASPECT
            ):
                continue

            gaps.append(
                gap
            )

    if not gaps:
        return []

    gaps.sort()

    clusters = []

    for gap in gaps:

        if not clusters:
            clusters.append(
                [
                    gap
                ]
            )

            continue

        current = clusters[
            -1
        ]

        center = median(
            current
        )

        tolerance = max(
            profile[
                "snap_tolerance"
            ]
            * 3.0,
            center
            * 0.08,
        )

        if (
            abs(
                gap
                - center
            )
            <= tolerance
        ):
            current.append(
                gap
            )

        else:
            clusters.append(
                [
                    gap
                ]
            )

    families = []

    for cluster in clusters:

        if len(
            cluster
        ) < 3:
            continue

        center = median(
            cluster
        )

        families.append(
            {
                "gap":
                    float(
                        center
                    ),

                "count":
                    len(
                        cluster
                    ),

                "tolerance":
                    float(
                        max(
                            profile[
                                "snap_tolerance"
                            ]
                            * 3.0,
                            center
                            * 0.10,
                        )
                    ),
            }
        )

    families.sort(
        key=lambda item:
            (
                -item[
                    "count"
                ],
                item[
                    "gap"
                ],
            )
    )

    return families


def _has_parallel_family_support(
    index,
    segments,
    profile,
    families,
):
    if not families:
        return False

    a = segments[
        index
    ]

    angle_tol = math.radians(
        profile[
            "angle_tolerance_deg"
        ]
    )

    MIN_STRUCTURAL_ASPECT = 1.50

    for j, b in enumerate(
        segments
    ):
        if j == index:
            continue

        metrics = _parallel_metrics(
            a,
            b,
        )

        if metrics is None:
            continue

        if (
            metrics[
                "angle_difference"
            ]
            > angle_tol
        ):
            continue

        if (
            metrics[
                "overlap_ratio"
            ]
            < 0.45
        ):
            continue

        gap = metrics[
            "gap"
        ]

        overlap = metrics[
            "overlap"
        ]

        # Do not allow a short dash to masquerade as a wall face
        # just because its offset equals a learned wall spacing.
        if (
            overlap
            < gap
            * MIN_STRUCTURAL_ASPECT
        ):
            continue

        for family in families:

            if (
                abs(
                    gap
                    - family[
                        "gap"
                    ]
                )
                <= family[
                    "tolerance"
                ]
            ):
                return True

    return False


# ============================================================
# DASH / REFERENCE LINE DETECTION
#
# No wall thickness values.
# No porch-specific rules.
# No physical mm thresholds.
# ============================================================

def remove_reference_dashed_runs(
    segments,
    profile,
    gap_families,
):
    """
    GENERIC REFERENCE / DASH FILTER V2

    No wall thickness constants.
    No physical size constants.
    No H/V assumption.
    No project/layer/porch-specific rule.

    Protection:
        - source CAD closed components
        - graph cycles

    Removal:
        - explicit reference/dashed CAD linetypes
        - regular collinear dash-gap rhythms

    Important:
    wall-gap families are NOT used as a veto here.
    A dashed centre/reference line may legitimately run
    parallel to real wall faces.
    """

    protected = cycle_protected_edges(
        segments,
        profile,
    )

    remove = set()

    # ========================================================
    # SOURCE PROVENANCE PROTECTION
    #
    # A CAD polyline/entity can be split into several segments.
    # If one part proves that the original entity participates
    # in a structural parallel-face family, do not allow another
    # part of the SAME source entity to be deleted merely because
    # it happens to lie next to a repeated dash sequence.
    #
    # This is generic provenance propagation, not a drawing rule.
    # ========================================================

    structural_support_flags = {}

    structural_source_indexes = set()

    for structural_index, structural_seg in enumerate(
        segments
    ):
        supported = (
            _has_parallel_family_support(
                structural_index,
                segments,
                profile,
                gap_families,
            )
        )

        structural_support_flags[
            structural_index
        ] = bool(
            supported
        )

        if supported:

            source_index = int(
                structural_seg.get(
                    "source_index",
                    -1,
                )
            )

            if source_index >= 0:
                structural_source_indexes.add(
                    source_index
                )

    reference_tokens = (
        "DASH",
        "HIDDEN",
        "CENTER",
        "CENTRE",
        "PHANTOM",
        "DOT",
        "BORDER",
    )

    # ========================================================
    # 1. EXPLICIT CAD LINETYPE
    # ========================================================

    for index, seg in enumerate(
        segments
    ):
        if index in protected:
            continue

        linetype = (
            str(
                seg.get(
                    "effective_linetype",
                    "",
                )
            )
            + " "
            + str(
                seg.get(
                    "linetype",
                    "",
                )
            )
        ).upper()

        if any(
            token in linetype
            for token in reference_tokens
        ):
            remove.add(
                index
            )

    # ========================================================
    # 2. GEOMETRIC DASH CANDIDATES
    #
    # Arbitrary rotation.
    # ========================================================

    candidate_items = []

    for index, seg in enumerate(
        segments
    ):
        source_index = int(
            seg.get(
                "source_index",
                -1,
            )
        )

        if (
            index in protected
            or index in remove
            or structural_support_flags.get(
                index,
                False,
            )
            or (
                source_index >= 0
                and source_index
                in structural_source_indexes
            )
        ):
            continue

        u = _unit_vector(
            seg["a"],
            seg["b"],
        )

        if u is None:
            continue

        angle = math.atan2(
            u[1],
            u[0],
        )

        candidate_items.append(
            {
                "index":
                    index,

                "seg":
                    seg,

                "u":
                    u,

                "angle":
                    angle,

                "length":
                    _length(
                        seg
                    ),
            }
        )

    if len(
        candidate_items
    ) < 4:
        result = [
            seg
            for index, seg
            in enumerate(
                segments
            )
            if index not in remove
        ]

        return (
            result,
            len(
                remove
            ),
        )

    # ========================================================
    # 3. COLLINEAR CLUSTERING
    #
    # Do not use a fragile exact Y/X bucket.
    # Union segments when they have:
    # - same direction
    # - same infinite supporting line
    # ========================================================

    angle_tolerance = math.radians(
        max(
            1.5,
            profile[
                "angle_tolerance_deg"
            ]
            * 1.5,
        )
    )

    line_tolerance = max(
        profile[
            "line_tolerance"
        ]
        * 4.0,
        profile[
            "median_length"
        ]
        * 0.02,
        profile[
            "snap_tolerance"
        ]
        * 3.0,
    )

    count = len(
        candidate_items
    )

    parent = list(
        range(
            count
        )
    )

    def find(
        value,
    ):
        while (
            parent[value]
            != value
        ):
            parent[value] = parent[
                parent[value]
            ]

            value = parent[
                value
            ]

        return value

    def union(
        a,
        b,
    ):
        ra = find(
            a
        )

        rb = find(
            b
        )

        if ra != rb:
            parent[
                rb
            ] = ra

    def point_line_distance(
        point,
        origin,
        direction,
    ):
        relative = (
            point[0]
            - origin[0],
            point[1]
            - origin[1],
        )

        return abs(
            _cross(
                direction,
                relative,
            )
        )

    for i in range(
        count
    ):
        item_a = candidate_items[
            i
        ]

        for j in range(
            i + 1,
            count
        ):
            item_b = candidate_items[
                j
            ]

            if (
                _angle_difference(
                    item_a[
                        "angle"
                    ],
                    item_b[
                        "angle"
                    ],
                )
                > angle_tolerance
            ):
                continue

            origin = item_a[
                "seg"
            ][
                "a"
            ]

            direction = item_a[
                "u"
            ]

            distance_a = (
                point_line_distance(
                    item_b[
                        "seg"
                    ][
                        "a"
                    ],
                    origin,
                    direction,
                )
            )

            distance_b = (
                point_line_distance(
                    item_b[
                        "seg"
                    ][
                        "b"
                    ],
                    origin,
                    direction,
                )
            )

            if (
                distance_a
                <= line_tolerance
                and distance_b
                <= line_tolerance
            ):
                union(
                    i,
                    j,
                )

    groups = {}

    for index in range(
        count
    ):
        root = find(
            index
        )

        groups.setdefault(
            root,
            [],
        ).append(
            candidate_items[
                index
            ]
        )

    # ========================================================
    # 4. RHYTHM ANALYSIS
    # ========================================================

    def evaluate_sequence(
        sequence,
    ):
        if len(
            sequence
        ) < 4:
            return

        lengths = [
            item[
                "length"
            ]
            for item in sequence
        ]

        med_length = median(
            lengths
        )

        if med_length <= 1e-12:
            return

        similar_lengths = sum(
            1
            for value in lengths
            if (
                med_length * 0.40
                <= value
                <= med_length * 2.50
            )
        )

        if (
            similar_lengths
            / len(
                lengths
            )
            < 0.70
        ):
            return

        gaps = []

        for index in range(
            len(
                sequence
            )
            - 1
        ):
            gap = (
                sequence[
                    index + 1
                ][
                    "start"
                ]
                - sequence[
                    index
                ][
                    "end"
                ]
            )

            if (
                gap
                > profile[
                    "snap_tolerance"
                ]
                * 2.0
            ):
                gaps.append(
                    gap
                )

        # At least:
        #
        # dash gap dash gap dash gap dash
        #
        if len(
            gaps
        ) < 3:
            return

        med_gap = median(
            gaps
        )

        if med_gap <= 0.0:
            return

        similar_gaps = sum(
            1
            for gap in gaps
            if (
                med_gap * 0.35
                <= gap
                <= med_gap * 2.85
            )
        )

        if (
            similar_gaps
            / len(
                gaps
            )
            < 0.65
        ):
            return

        run_start = sequence[
            0
        ][
            "start"
        ]

        run_end = sequence[
            -1
        ][
            "end"
        ]

        run_span = (
            run_end
            - run_start
        )

        if run_span <= 1e-12:
            return

        drawn_length = sum(
            lengths
        )

        fill_ratio = (
            drawn_length
            / run_span
        )

        # A real continuous wall broken only at occasional
        # junctions normally has high fill ratio.
        # Repeated reference dashes do not.
        if (
            fill_ratio
            >= 0.84
        ):
            return

        if (
            run_span
            < med_length
            * 4.0
        ):
            return

        # ====================================================
        # STRUCTURAL VETO
        #
        # A continuous architectural face can be fragmented by
        # CAD intersections and superficially resemble a dash
        # rhythm.
        #
        # Protect it only when a majority of its fragments have
        # strong, long-overlap support from an automatically
        # learned parallel-face family.
        # ====================================================

        structural_support = sum(
            1
            for item in sequence
            if _has_parallel_family_support(
                item[
                    "index"
                ],
                segments,
                profile,
                gap_families,
            )
        )

        if (
            structural_support
            / len(
                sequence
            )
            >= 0.50
        ):
            return

        # ====================================================
        # MEMBER-LEVEL DASH CLASSIFICATION
        #
        # Do not delete long continuous boundary fragments just
        # because they share the same supporting line with a
        # repeated dash rhythm.
        #
        # Only members belonging to the statistically identified
        # dash-length population are removed.
        # ====================================================

        dash_members = [
            item
            for item in sequence
            if (
                med_length
                * 0.40
                <= item[
                    "length"
                ]
                <= med_length
                * 2.50
            )
        ]

        if len(
            dash_members
        ) < 4:
            return

        # The dash population itself still needs to dominate the
        # sequence. Long structural end pieces are treated as
        # outliers and preserved.
        if (
            len(
                dash_members
            )
            / len(
                sequence
            )
            < 0.65
        ):
            return

        for item in dash_members:

            item_index = item[
                "index"
            ]

            item_source_index = int(
                segments[
                    item_index
                ].get(
                    "source_index",
                    -1,
                )
            )

            if structural_support_flags.get(
                item_index,
                False,
            ):
                continue

            if (
                item_source_index >= 0
                and item_source_index
                in structural_source_indexes
            ):
                continue

            remove.add(
                item_index
            )

    for group in groups.values():

        if len(
            group
        ) < 4:
            continue

        reference = max(
            group,
            key=lambda item:
                item[
                    "length"
                ],
        )

        direction = reference[
            "u"
        ]

        origin = reference[
            "seg"
        ][
            "a"
        ]

        intervals = []

        for item in group:

            seg = item[
                "seg"
            ]

            t0 = _dot(
                (
                    seg["a"][0]
                    - origin[0],
                    seg["a"][1]
                    - origin[1],
                ),
                direction,
            )

            t1 = _dot(
                (
                    seg["b"][0]
                    - origin[0],
                    seg["b"][1]
                    - origin[1],
                ),
                direction,
            )

            value = dict(
                item
            )

            value[
                "start"
            ] = min(
                t0,
                t1,
            )

            value[
                "end"
            ] = max(
                t0,
                t1,
            )

            intervals.append(
                value
            )

        intervals.sort(
            key=lambda item:
                item[
                    "start"
                ]
        )

        group_lengths = [
            item[
                "length"
            ]
            for item in intervals
        ]

        med_length = median(
            group_lengths
        )

        positive_gaps = []

        for index in range(
            len(
                intervals
            )
            - 1
        ):
            gap = (
                intervals[
                    index + 1
                ][
                    "start"
                ]
                - intervals[
                    index
                ][
                    "end"
                ]
            )

            if (
                gap
                > profile[
                    "snap_tolerance"
                ]
                * 2.0
            ):
                positive_gaps.append(
                    gap
                )

        if positive_gaps:
            med_positive_gap = median(
                positive_gaps
            )

        else:
            med_positive_gap = 0.0

        # Split unrelated remote geometry lying on the same
        # infinite CAD line.
        sequence_break_gap = max(
            med_length
            * 5.0,
            med_positive_gap
            * 3.5,
            profile[
                "median_length"
            ]
            * 2.0,
        )

        current = [
            intervals[
                0
            ]
        ]

        for item in intervals[
            1:
        ]:

            previous = current[
                -1
            ]

            gap = (
                item[
                    "start"
                ]
                - previous[
                    "end"
                ]
            )

            if (
                gap
                <= sequence_break_gap
            ):
                current.append(
                    item
                )

            else:
                evaluate_sequence(
                    current
                )

                current = [
                    item
                ]

        evaluate_sequence(
            current
        )

    result = [
        seg
        for index, seg
        in enumerate(
            segments
        )
        if index not in remove
    ]

    return (
        result,
        len(
            remove
        ),
    )


def remove_small_acyclic_noise(
    segments,
    profile,
    gap_families,
):
    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    protected = cycle_protected_edges(
        segments,
        profile,
    )

    visited_nodes = set()

    remove_edges = set()

    def other(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        return a

    for start_node in adjacency:
        if start_node in visited_nodes:
            continue

        stack = [
            start_node
        ]

        component_nodes = set()

        component_edges = set()

        while stack:
            node = stack.pop()

            if node in component_nodes:
                continue

            component_nodes.add(
                node
            )

            visited_nodes.add(
                node
            )

            for edge_index in adjacency.get(
                node,
                [],
            ):
                component_edges.add(
                    edge_index
                )

                next_node = other(
                    edge_index,
                    node,
                )

                if (
                    next_node
                    not in component_nodes
                ):
                    stack.append(
                        next_node
                    )

        if not component_edges:
            continue

        if any(
            edge_index in protected
            for edge_index in component_edges
        ):
            continue

        # Conservative:
        # only tiny acyclic components.
        if len(
            component_edges
        ) > 2:
            continue

        total_length = sum(
            _length(
                segments[
                    edge_index
                ]
            )
            for edge_index
            in component_edges
        )

        max_total = max(
            profile[
                "median_length"
            ]
            * 4.0,
            profile[
                "drawing_diagonal"
            ]
            * 0.03,
        )

        if total_length > max_total:
            continue

        if any(
            _has_parallel_family_support(
                edge_index,
                segments,
                profile,
                gap_families,
            )
            for edge_index
            in component_edges
        ):
            continue

        remove_edges.update(
            component_edges
        )

    result = [
        seg
        for index, seg in enumerate(
            segments
        )
        if index not in remove_edges
    ]

    return (
        result,
        len(
            remove_edges
        ),
    )


# ============================================================
# INTERNAL CHORD
#
# Rotation independent.
# Scale independent.
# ============================================================

def remove_terminal_annotation_branches(
    segments,
    profile,
    gap_families,
):
    """
    GENERIC TERMINAL BREAK / ANNOTATION CLASSIFIER V2

    A removable branch must:

    - start at a graph junction
    - terminate at a free endpoint
    - consist entirely of graph bridges
    - have no structural parallel-face support
    - have no source-closed geometry
    - contain several significant turns
    - alternate turn direction
    - leave and return to approximately the same baseline
      direction

    This identifies break/annotation symbols independently of:
    - CAD units
    - rotation
    - layer names
    - coordinates
    - wall thickness
    """

    if not segments:
        return (
            segments,
            0,
        )

    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    bridges = _find_bridge_edges(
        segments,
        profile,
    )

    remove_edges = set()

    def other_node(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        if b == node:
            return a

        return None

    def unit_vector_between(
        node_a,
        node_b,
    ):
        p0 = node_points[
            node_a
        ]

        p1 = node_points[
            node_b
        ]

        dx = (
            p1[0]
            - p0[0]
        )

        dy = (
            p1[1]
            - p0[1]
        )

        length = math.hypot(
            dx,
            dy,
        )

        if length <= 1e-12:
            return None

        return (
            dx / length,
            dy / length,
        )

    junction_nodes = [
        node
        for node, edges
        in adjacency.items()
        if len(
            edges
        ) >= 3
    ]

    for root in junction_nodes:

        for first_edge in adjacency.get(
            root,
            [],
        ):

            if first_edge not in bridges:
                continue

            if first_edge in remove_edges:
                continue

            chain_edges = []

            chain_nodes = [
                root
            ]

            current_node = (
                root
            )

            current_edge = (
                first_edge
            )

            valid = True
            terminal = False

            while True:

                if current_edge in chain_edges:
                    valid = False
                    break

                if current_edge not in bridges:
                    valid = False
                    break

                chain_edges.append(
                    current_edge
                )

                if len(
                    chain_edges
                ) > 16:
                    valid = False
                    break

                next_node = other_node(
                    current_edge,
                    current_node,
                )

                if next_node is None:
                    valid = False
                    break

                chain_nodes.append(
                    next_node
                )

                degree = len(
                    adjacency.get(
                        next_node,
                        [],
                    )
                )

                if degree == 1:
                    terminal = True
                    break

                if degree != 2:
                    valid = False
                    break

                options = [
                    edge_index
                    for edge_index
                    in adjacency.get(
                        next_node,
                        [],
                    )
                    if edge_index
                    != current_edge
                ]

                if len(
                    options
                ) != 1:
                    valid = False
                    break

                current_node = (
                    next_node
                )

                current_edge = (
                    options[
                        0
                    ]
                )

            if (
                not valid
                or not terminal
            ):
                continue

            if len(
                chain_edges
            ) < 4:
                continue

            # Never remove source-closed geometry.
            if any(
                bool(
                    segments[
                        edge_index
                    ].get(
                        "source_closed",
                        False,
                    )
                )
                for edge_index
                in chain_edges
            ):
                continue

            # Real architectural parallel-face evidence veto.
            if any(
                _has_parallel_family_support(
                    edge_index,
                    segments,
                    profile,
                    gap_families,
                )
                for edge_index
                in chain_edges
            ):
                continue

            vectors = []

            for index in range(
                len(
                    chain_nodes
                )
                - 1
            ):
                vector = unit_vector_between(
                    chain_nodes[
                        index
                    ],
                    chain_nodes[
                        index + 1
                    ],
                )

                if vector is None:
                    valid = False
                    break

                vectors.append(
                    vector
                )

            if not valid:
                continue

            if len(
                vectors
            ) < 4:
                continue

            positive = 0
            negative = 0

            turn_signs = []

            significant_turns = 0

            for index in range(
                len(
                    vectors
                )
                - 1
            ):
                v0 = vectors[
                    index
                ]

                v1 = vectors[
                    index + 1
                ]

                dot_value = max(
                    -1.0,
                    min(
                        1.0,
                        _dot(
                            v0,
                            v1,
                        ),
                    ),
                )

                angle = math.degrees(
                    math.acos(
                        dot_value
                    )
                )

                if angle < 20.0:
                    continue

                significant_turns += 1

                signed = _cross(
                    v0,
                    v1,
                )

                if signed > 1e-8:
                    positive += 1
                    turn_signs.append(
                        1
                    )

                elif signed < -1e-8:
                    negative += 1
                    turn_signs.append(
                        -1
                    )

            if significant_turns < 3:
                continue

            if (
                positive == 0
                or negative == 0
            ):
                continue

            sign_changes = sum(
                1
                for index in range(
                    len(
                        turn_signs
                    )
                    - 1
                )
                if (
                    turn_signs[
                        index
                    ]
                    != turn_signs[
                        index + 1
                    ]
                )
            )

            if sign_changes < 2:
                continue

            # Break symbols normally enter and exit on nearly
            # the same baseline direction, with the oscillation
            # occurring in the middle.
            first_angle = math.atan2(
                vectors[
                    0
                ][1],
                vectors[
                    0
                ][0],
            )

            last_angle = math.atan2(
                vectors[
                    -1
                ][1],
                vectors[
                    -1
                ][0],
            )

            if (
                _angle_difference(
                    first_angle,
                    last_angle,
                )
                > math.radians(
                    15.0
                )
            ):
                continue

            # Relative locality check only.
            total_length = sum(
                _length(
                    segments[
                        edge_index
                    ]
                )
                for edge_index
                in chain_edges
            )

            if (
                total_length
                > profile[
                    "drawing_diagonal"
                ]
                * 0.15
            ):
                continue

            remove_edges.update(
                chain_edges
            )

    if not remove_edges:
        return (
            segments,
            0,
        )

    result = [
        seg
        for index, seg
        in enumerate(
            segments
        )
        if index not in remove_edges
    ]

    return (
        result,
        len(
            remove_edges
        ),
    )


def remove_compact_open_symbol_components(
    segments,
    profile,
    gap_families,
):
    """
    GENERIC COMPACT OPEN COMPONENT CLEANUP V2

    Fundamental rule:

        NEVER delete a cycle core merely because open branches
        are attached to it.

    For a compact component containing both:
        - cyclic geometry
        - acyclic terminal bridge geometry

    preserve the cycle and remove only bridge subgraphs that
    terminate at open endpoints.

    This is generic graph topology:
        no coordinates
        no layer names
        no CAD units
        no wall thickness
        no project-specific dimensions
    """

    if not segments:
        return (
            segments,
            0,
        )

    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    bridges = _find_bridge_edges(
        segments,
        profile,
    )

    visited_nodes = set()

    remove_edges = set()

    def other_node(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        if b == node:
            return a

        return None

    # Relative limit only.
    compact_limit = max(
        profile[
            "snap_tolerance"
        ]
        * 20.0,
        min(
            profile[
                "median_length"
            ]
            * 3.0,
            profile[
                "drawing_diagonal"
            ]
            * 0.025,
        ),
    )

    # ========================================================
    # CONNECTED COMPONENTS
    # ========================================================

    for seed in adjacency:

        if seed in visited_nodes:
            continue

        stack = [
            seed
        ]

        component_nodes = set()

        component_edges = set()

        while stack:

            node = stack.pop()

            if node in component_nodes:
                continue

            component_nodes.add(
                node
            )

            visited_nodes.add(
                node
            )

            for edge_index in adjacency.get(
                node,
                [],
            ):

                component_edges.add(
                    edge_index
                )

                next_node = other_node(
                    edge_index,
                    node,
                )

                if (
                    next_node is not None
                    and next_node
                    not in component_nodes
                ):
                    stack.append(
                        next_node
                    )

        if not component_edges:
            continue

        # Conservative cap.
        if len(
            component_edges
        ) > 16:
            continue

        degrees = {
            node:
                len(
                    [
                        edge_index
                        for edge_index
                        in adjacency.get(
                            node,
                            [],
                        )
                        if edge_index
                        in component_edges
                    ]
                )
            for node
            in component_nodes
        }

        endpoint_nodes = {
            node
            for node, degree
            in degrees.items()
            if degree == 1
        }

        branch_nodes = {
            node
            for node, degree
            in degrees.items()
            if degree >= 3
        }

        # Pure closed component:
        # preserve completely.
        if not endpoint_nodes:
            continue

        # Simple open U/L contour:
        # preserve completely.
        if not branch_nodes:
            continue

        component_bridge_edges = {
            edge_index
            for edge_index
            in component_edges
            if edge_index in bridges
        }

        component_cycle_edges = (
            component_edges
            - component_bridge_edges
        )

        # No cycle core -> this function is not responsible.
        if not component_cycle_edges:
            continue

        # ====================================================
        # HARD CYCLE-CORE PROTECTION
        #
        # These edges participate in at least one graph cycle.
        # They are NEVER added to remove_edges here.
        # ====================================================

        if any(
            bool(
                segments[
                    edge_index
                ].get(
                    "source_closed",
                    False,
                )
            )
            for edge_index
            in component_cycle_edges
        ):
            # Even stronger preservation evidence.
            pass

        # If the component has genuine structural wall evidence,
        # leave the whole component untouched.
        if any(
            _has_parallel_family_support(
                edge_index,
                segments,
                profile,
                gap_families,
            )
            for edge_index
            in component_edges
        ):
            continue

        # ====================================================
        # COMPACTNESS
        # ====================================================

        xs = []
        ys = []

        for node in component_nodes:

            point = node_points[
                node
            ]

            xs.append(
                float(
                    point[0]
                )
            )

            ys.append(
                float(
                    point[1]
                )
            )

        width = (
            max(
                xs
            )
            - min(
                xs
            )
        )

        height = (
            max(
                ys
            )
            - min(
                ys
            )
        )

        bbox_diagonal = math.hypot(
            width,
            height,
        )

        if (
            bbox_diagonal
            > compact_limit
        ):
            continue

        # ====================================================
        # BRIDGE SUBGRAPH ANALYSIS
        #
        # Remove ONLY bridge-connected subgraphs that contain
        # at least one true endpoint.
        #
        # A bridge between two cycle cores with no terminal
        # endpoint is preserved.
        # ====================================================

        bridge_adjacency = {}

        for edge_index in component_bridge_edges:

            a, b = edge_nodes[
                edge_index
            ]

            bridge_adjacency.setdefault(
                a,
                [],
            ).append(
                edge_index
            )

            bridge_adjacency.setdefault(
                b,
                [],
            ).append(
                edge_index
            )

        visited_bridge_edges = set()

        for seed_edge in component_bridge_edges:

            if seed_edge in visited_bridge_edges:
                continue

            bridge_stack = [
                seed_edge
            ]

            bridge_component_edges = set()

            bridge_component_nodes = set()

            while bridge_stack:

                edge_index = bridge_stack.pop()

                if edge_index in bridge_component_edges:
                    continue

                bridge_component_edges.add(
                    edge_index
                )

                visited_bridge_edges.add(
                    edge_index
                )

                a, b = edge_nodes[
                    edge_index
                ]

                bridge_component_nodes.add(
                    a
                )

                bridge_component_nodes.add(
                    b
                )

                for node in (
                    a,
                    b,
                ):

                    for next_edge in bridge_adjacency.get(
                        node,
                        [],
                    ):

                        if (
                            next_edge
                            not in bridge_component_edges
                        ):
                            bridge_stack.append(
                                next_edge
                            )

            # ------------------------------------------------
            # Critical condition:
            #
            # Only acyclic bridge structures reaching a FREE
            # ENDPOINT are removable.
            # ------------------------------------------------

            reaches_open_endpoint = any(
                node in endpoint_nodes
                for node
                in bridge_component_nodes
            )

            if not reaches_open_endpoint:
                continue

            # ------------------------------------------------
            # Must actually attach to a protected cycle core.
            # ------------------------------------------------

            touches_cycle_core = False

            for node in bridge_component_nodes:

                for edge_index in adjacency.get(
                    node,
                    [],
                ):

                    if (
                        edge_index
                        in component_cycle_edges
                    ):
                        touches_cycle_core = True
                        break

                if touches_cycle_core:
                    break

            if not touches_cycle_core:
                continue

            # Delete the tail/tree only.
            # NEVER the cycle core.
            remove_edges.update(
                bridge_component_edges
            )

    if not remove_edges:
        return (
            segments,
            0,
        )

    result = [
        seg
        for index, seg
        in enumerate(
            segments
        )
        if index not in remove_edges
    ]

    return (
        result,
        len(
            remove_edges
        ),
    )


def remove_shared_interior_edges(
    segments,
    profile,
):
    """
    Generic shared interior edge removal.

    An edge is removable only when, after excluding it,
    its endpoint nodes still have TWO edge-disjoint
    alternative routes.

    This identifies a common internal boundary between
    two graph cycles/faces.

    No project coordinates, layer names, physical dimensions,
    wall thickness constants or axis assumptions.
    """

    if not segments:
        return (
            segments,
            0,
        )

    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    def other_node(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        if b == node:
            return a

        return None

    def find_path(
        start,
        target,
        excluded_edges,
    ):
        stack = [
            (
                start,
                [],
            )
        ]

        visited = {
            start
        }

        while stack:

            node, path_edges = (
                stack.pop()
            )

            if node == target:
                return path_edges

            for edge_index in adjacency.get(
                node,
                [],
            ):

                if edge_index in excluded_edges:
                    continue

                next_node = other_node(
                    edge_index,
                    node,
                )

                if next_node is None:
                    continue

                if next_node in visited:
                    continue

                visited.add(
                    next_node
                )

                stack.append(
                    (
                        next_node,
                        path_edges
                        + [
                            edge_index
                        ],
                    )
                )

        return None

    def has_two_alternate_routes(
        candidate_edge,
        start,
        target,
    ):
        path_1 = find_path(
            start,
            target,
            {
                candidate_edge
            },
        )

        if not path_1:
            return False

        excluded = {
            candidate_edge
        }

        excluded.update(
            path_1
        )

        path_2 = find_path(
            start,
            target,
            excluded,
        )

        return bool(
            path_2
        )

    remove_edges = set()

    for edge_index, seg in enumerate(
        segments
    ):

        start, end = edge_nodes[
            edge_index
        ]

        if (
            len(
                adjacency.get(
                    start,
                    [],
                )
            )
            < 3
        ):
            continue

        if (
            len(
                adjacency.get(
                    end,
                    [],
                )
            )
            < 3
        ):
            continue

        if has_two_alternate_routes(
            edge_index,
            start,
            end,
        ):
            remove_edges.add(
                edge_index
            )

    if not remove_edges:
        return (
            segments,
            0,
        )

    result = [
        seg
        for index, seg
        in enumerate(
            segments
        )
        if index not in remove_edges
    ]

    return (
        result,
        len(
            remove_edges
        ),
    )


def remove_internal_chords(
    segments,
    profile,
):
    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    angle_tol = math.radians(
        profile[
            "angle_tolerance_deg"
        ]
    )

    max_candidate_length = max(
        profile[
            "median_length"
        ]
        * 8.0,
        profile[
            "drawing_diagonal"
        ]
        * 0.05,
    )

    side_tolerance = (
        profile[
            "snap_tolerance"
        ]
        * 2.0
    )

    def other(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        return a

    def is_parallel(
        a,
        b,
    ):
        if (
            a is None
            or b is None
        ):
            return False

        angle_a = math.atan2(
            a[1],
            a[0],
        )

        angle_b = math.atan2(
            b[1],
            b[0],
        )

        return (
            _angle_difference(
                angle_a,
                angle_b,
            )
            <= angle_tol
        )

    def straight_continuation(
        node,
        chord_direction,
        required_sign,
        excluded_edge,
    ):
        origin = node_points[
            node
        ]

        for edge_index in adjacency.get(
            node,
            [],
        ):
            if (
                edge_index
                == excluded_edge
            ):
                continue

            next_node = other(
                edge_index,
                node,
            )

            direction = _unit_vector(
                origin,
                node_points[
                    next_node
                ],
            )

            if not is_parallel(
                chord_direction,
                direction,
            ):
                continue

            value = _dot(
                chord_direction,
                direction,
            )

            if (
                required_sign < 0
                and value < -0.95
            ):
                return True

            if (
                required_sign > 0
                and value > 0.95
            ):
                return True

        return False

    def alternate_path(
        chord_edge,
        start,
        target,
        chord_direction,
        chord_length,
    ):
        max_edges = 8

        max_length = (
            chord_length
            * 8.0
        )

        stack = []

        for edge_index in adjacency.get(
            start,
            [],
        ):
            if edge_index == chord_edge:
                continue

            next_node = other(
                edge_index,
                start,
            )

            direction = _unit_vector(
                node_points[
                    start
                ],
                node_points[
                    next_node
                ],
            )

            # Alternate perimeter must leave sideways.
            if is_parallel(
                chord_direction,
                direction,
            ):
                continue

            stack.append(
                (
                    next_node,
                    [
                        edge_index
                    ],
                    {
                        start,
                        next_node,
                    },
                    _length(
                        segments[
                            edge_index
                        ]
                    ),
                    [
                        start,
                        next_node,
                    ],
                )
            )

        while stack:
            (
                node,
                used_edges,
                visited,
                total_length,
                path_nodes,
            ) = stack.pop()

            if (
                len(
                    used_edges
                )
                > max_edges
                or total_length
                > max_length
            ):
                continue

            if node == target:
                if len(
                    path_nodes
                ) < 3:
                    continue

                start_point = node_points[
                    start
                ]

                positive = False
                negative = False

                for path_node in path_nodes[
                    1:-1
                ]:
                    point = node_points[
                        path_node
                    ]

                    relative = (
                        point[0]
                        - start_point[0],
                        point[1]
                        - start_point[1],
                    )

                    signed = _cross(
                        chord_direction,
                        relative,
                    )

                    if (
                        signed
                        > side_tolerance
                    ):
                        positive = True

                    elif (
                        signed
                        < -side_tolerance
                    ):
                        negative = True

                if (
                    positive
                    and negative
                ):
                    continue

                if (
                    positive
                    or negative
                ):
                    return True

                continue

            for edge_index in adjacency.get(
                node,
                [],
            ):
                if (
                    edge_index
                    == chord_edge
                    or edge_index
                    in used_edges
                ):
                    continue

                next_node = other(
                    edge_index,
                    node,
                )

                if next_node in visited:
                    continue

                new_length = (
                    total_length
                    + _length(
                        segments[
                            edge_index
                        ]
                    )
                )

                if new_length > max_length:
                    continue

                stack.append(
                    (
                        next_node,
                        used_edges
                        + [
                            edge_index
                        ],
                        visited
                        | {
                            next_node
                        },
                        new_length,
                        path_nodes
                        + [
                            next_node
                        ],
                    )
                )

        return False

    remove = set()

    for edge_index, seg in enumerate(
        segments
    ):
        length = _length(
            seg
        )

        if (
            length
            > max_candidate_length
        ):
            continue

        start, end = edge_nodes[
            edge_index
        ]

        if (
            len(
                adjacency.get(
                    start,
                    [],
                )
            )
            < 3
            or len(
                adjacency.get(
                    end,
                    [],
                )
            )
            < 3
        ):
            continue

        direction = _unit_vector(
            node_points[
                start
            ],
            node_points[
                end
            ],
        )

        if direction is None:
            continue

        # ====================================================
        # ORIENTATION-INDEPENDENT CONTINUATION
        #
        # The geometric edge may be stored A->B or B->A.
        # Both orientations describe the same internal chord.
        # ====================================================

        orientation_a = (
            straight_continuation(
                start,
                direction,
                -1,
                edge_index,
            )
            and straight_continuation(
                end,
                direction,
                +1,
                edge_index,
            )
        )

        orientation_b = (
            straight_continuation(
                start,
                direction,
                +1,
                edge_index,
            )
            and straight_continuation(
                end,
                direction,
                -1,
                edge_index,
            )
        )

        if not (
            orientation_a
            or orientation_b
        ):
            continue

        if not alternate_path(
            edge_index,
            start,
            end,
            direction,
            length,
        ):
            continue

        remove.add(
            edge_index
        )

    result = [
        seg
        for index, seg in enumerate(
            segments
        )
        if index not in remove
    ]

    return (
        result,
        len(
            remove
        ),
    )


# ============================================================
# SHORT DANGLING SPURS
# ============================================================

def remove_short_spurs(
    segments,
    profile,
):
    current = list(
        segments
    )

    removed = 0

    limit = profile[
        "short_spur_limit"
    ]

    for iteration in range(
        4
    ):
        adjacency, edge_nodes, node_points = (
            _build_graph(
                current,
                profile,
            )
        )

        remove = set()

        for edge_index, seg in enumerate(
            current
        ):
            a, b = edge_nodes[
                edge_index
            ]

            if (
                _length(
                    seg
                )
                > limit
            ):
                continue

            if (
                len(
                    adjacency.get(
                        a,
                        [],
                    )
                )
                == 1
                or len(
                    adjacency.get(
                        b,
                        [],
                    )
                )
                == 1
            ):
                if not bool(
                    seg.get(
                        "source_closed",
                        False,
                    )
                ):
                    remove.add(
                        edge_index
                    )

        if not remove:
            break

        current = [
            seg
            for index, seg in enumerate(
                current
            )
            if index not in remove
        ]

        removed += len(
            remove
        )

    return (
        current,
        removed,
    )


# ============================================================
# RESTORE ONLY ORIGINAL CAD EDGES
#
# No invented physical size thresholds.
# ============================================================

def restore_original_three_side_loops(
    segments,
    original_segments,
    profile,
):
    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    tolerance = (
        profile[
            "snap_tolerance"
        ]
        * 3.0
    )

    angle_tol = math.radians(
        6.0
    )

    def other(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        return a

    def find_original(
        p0,
        p1,
    ):
        for original in original_segments:
            if (
                _dist(
                    original[
                        "a"
                    ],
                    p0,
                )
                <= tolerance
                and _dist(
                    original[
                        "b"
                    ],
                    p1,
                )
                <= tolerance
            ):
                return dict(
                    original
                )

            if (
                _dist(
                    original[
                        "a"
                    ],
                    p1,
                )
                <= tolerance
                and _dist(
                    original[
                        "b"
                    ],
                    p0,
                )
                <= tolerance
            ):
                return dict(
                    original
                )

        return None

    open_nodes = [
        node
        for node, edges
        in adjacency.items()
        if len(
            edges
        ) == 1
    ]

    def three_edge_path(
        start,
        target,
    ):
        stack = [
            (
                start,
                [],
                [
                    start
                ],
            )
        ]

        while stack:
            node, used, nodes = (
                stack.pop()
            )

            if node == target:
                if len(
                    used
                ) == 3:
                    return (
                        used,
                        nodes,
                    )

                continue

            if len(
                used
            ) >= 3:
                continue

            for edge_index in adjacency.get(
                node,
                [],
            ):
                if edge_index in used:
                    continue

                next_node = other(
                    edge_index,
                    node,
                )

                if (
                    next_node in nodes
                    and next_node
                    != target
                ):
                    continue

                stack.append(
                    (
                        next_node,
                        used
                        + [
                            edge_index
                        ],
                        nodes
                        + [
                            next_node
                        ],
                    )
                )

        return None

    additions = []

    consumed = set()

    for i, start in enumerate(
        open_nodes
    ):
        if start in consumed:
            continue

        for end in open_nodes[
            i + 1:
        ]:
            if end in consumed:
                continue

            p0 = node_points[
                start
            ]

            p1 = node_points[
                end
            ]

            original = find_original(
                p0,
                p1,
            )

            if original is None:
                continue

            path = three_edge_path(
                start,
                end,
            )

            if path is None:
                continue

            used_edges, nodes = path

            edge_segments = [
                segments[
                    edge_index
                ]
                for edge_index
                in used_edges
            ]

            directions = [
                _unit_vector(
                    edge[
                        "a"
                    ],
                    edge[
                        "b"
                    ],
                )
                for edge
                in edge_segments
            ]

            if any(
                direction is None
                for direction in directions
            ):
                continue

            # First and third sides should be parallel.
            if (
                _angle_difference(
                    math.atan2(
                        directions[
                            0
                        ][1],
                        directions[
                            0
                        ][0],
                    ),
                    math.atan2(
                        directions[
                            2
                        ][1],
                        directions[
                            2
                        ][0],
                    ),
                )
                > angle_tol
            ):
                continue

            missing_direction = _unit_vector(
                p0,
                p1,
            )

            middle_direction = directions[
                1
            ]

            if (
                missing_direction is None
                or _angle_difference(
                    math.atan2(
                        missing_direction[
                            1
                        ],
                        missing_direction[
                            0
                        ],
                    ),
                    math.atan2(
                        middle_direction[
                            1
                        ],
                        middle_direction[
                            0
                        ],
                    ),
                )
                > angle_tol
            ):
                continue

            missing_length = _dist(
                p0,
                p1,
            )

            middle_length = _length(
                edge_segments[
                    1
                ]
            )

            shorter = min(
                missing_length,
                middle_length,
            )

            longer = max(
                missing_length,
                middle_length,
            )

            if (
                shorter <= 1e-12
                or longer
                / shorter
                > 1.25
            ):
                continue

            original[
                "a"
            ] = p0

            original[
                "b"
            ] = p1

            additions.append(
                original
            )

            consumed.add(
                start
            )

            consumed.add(
                end
            )

            break

    if not additions:
        return (
            segments,
            0,
        )

    result = list(
        segments
    )

    result.extend(
        additions
    )

    result, duplicates = (
        remove_exact_duplicates(
            result,
            profile[
                "snap_tolerance"
            ],
        )
    )

    return (
        result,
        len(
            additions
        ),
    )


# ============================================================
# CHAIN BUILDING
# ============================================================

def build_endpoint_chains(
    segments,
    profile,
):
    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    visited = set()

    paths = []

    def other(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        return a

    def oriented_points(
        edge_index,
        node,
    ):
        seg = segments[
            edge_index
        ]

        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return (
                seg[
                    "a"
                ],
                seg[
                    "b"
                ],
                b,
            )

        return (
            seg[
                "b"
            ],
            seg[
                "a"
            ],
            a,
        )

    def walk(
        start_node,
        first_edge,
    ):
        points = []

        current_node = start_node

        edge_index = first_edge

        closed = False

        while True:
            if edge_index in visited:
                break

            p0, p1, next_node = (
                oriented_points(
                    edge_index,
                    current_node,
                )
            )

            if not points:
                points.append(
                    p0
                )

            points.append(
                p1
            )

            visited.add(
                edge_index
            )

            if next_node == start_node:
                closed = True
                break

            node_edges = adjacency.get(
                next_node,
                [],
            )

            remaining = [
                value
                for value in node_edges
                if value not in visited
            ]

            # At branches, do not invent connectivity.
            if (
                len(
                    node_edges
                )
                != 2
                or len(
                    remaining
                )
                != 1
            ):
                break

            current_node = next_node
            edge_index = remaining[
                0
            ]

        return (
            closed,
            points,
        )

    # Open/branch starts.
    for node, edges in adjacency.items():
        if len(
            edges
        ) == 2:
            continue

        for edge_index in edges:
            if edge_index in visited:
                continue

            closed, points = walk(
                node,
                edge_index,
            )

            if len(
                points
            ) >= 2:
                paths.append(
                    (
                        closed,
                        points,
                    )
                )

    # Remaining cycles.
    for edge_index, seg in enumerate(
        segments
    ):
        if edge_index in visited:
            continue

        start = edge_nodes[
            edge_index
        ][0]

        closed, points = walk(
            start,
            edge_index,
        )

        if len(
            points
        ) >= 2:
            paths.append(
                (
                    closed,
                    points,
                )
            )

    return paths


def normalize_paths(
    paths,
    profile,
):
    tolerance = profile[
        "snap_tolerance"
    ]

    output = []

    for closed, points in paths:
        clean = []

        for point in points:
            if (
                not clean
                or _dist(
                    clean[-1],
                    point,
                )
                > tolerance
                * 0.10
            ):
                clean.append(
                    (
                        float(
                            point[0]
                        ),
                        float(
                            point[1]
                        ),
                    )
                )

        if len(
            clean
        ) < 2:
            continue

        if (
            not closed
            and len(
                clean
            )
            >= 3
            and _dist(
                clean[0],
                clean[-1],
            )
            <= tolerance
        ):
            closed = True

        if closed:
            if (
                len(
                    clean
                )
                >= 3
                and _dist(
                    clean[0],
                    clean[-1],
                )
                <= tolerance
            ):
                clean = clean[
                    :-1
                ]

            if len(
                clean
            ) < 3:
                closed = False

        output.append(
            (
                bool(
                    closed
                ),
                clean,
            )
        )

    return output


# ============================================================
# UNIT METADATA
# ============================================================

def _source_unit_report(
    cad_meta,
):
    cad_meta = (
        cad_meta
        if isinstance(
            cad_meta,
            dict,
        )
        else {}
    )

    return {
        "source_unit_code":
            int(
                cad_meta.get(
                    "source_unit_code",
                    0,
                )
                or 0
            ),

        "source_unit_token":
            str(
                cad_meta.get(
                    "source_unit_token",
                    "mm",
                )
            ),

        "source_unit_name":
            str(
                cad_meta.get(
                    "source_unit_name",
                    "Millimeters",
                )
            ),

        "source_to_mm":
            float(
                cad_meta.get(
                    "source_to_mm",
                    1.0,
                )
                or 1.0
            ),

        "source_unit_confidence":
            str(
                cad_meta.get(
                    "source_unit_confidence",
                    "unknown",
                )
            ),
    }


# ============================================================
# GENERIC DECISION / PROVENANCE DIAGNOSTICS
#
# IMPORTANT:
# These functions DO NOT modify geometry.
# They only explain what the generic engine did.
# ============================================================

def _debug_segment_record(
    seg,
    profile,
    structural_support=None,
):
    record = {
        "a": [
            float(
                seg["a"][0]
            ),
            float(
                seg["a"][1]
            ),
        ],

        "b": [
            float(
                seg["b"][0]
            ),
            float(
                seg["b"][1]
            ),
        ],

        "length":
            float(
                _length(
                    seg
                )
            ),

        "angle_deg":
            float(
                math.degrees(
                    _angle(
                        seg
                    )
                )
            ),

        "layer":
            str(
                seg.get(
                    "layer",
                    "",
                )
            ),

        "linetype":
            str(
                seg.get(
                    "linetype",
                    "",
                )
            ),

        "effective_linetype":
            str(
                seg.get(
                    "effective_linetype",
                    "",
                )
            ),

        "entity_type":
            str(
                seg.get(
                    "entity_type",
                    "",
                )
            ),

        "handle":
            str(
                seg.get(
                    "handle",
                    "",
                )
            ),

        "source_index":
            int(
                seg.get(
                    "source_index",
                    -1,
                )
            ),

        "source_closed":
            bool(
                seg.get(
                    "source_closed",
                    False,
                )
            ),
    }

    if structural_support is not None:
        record[
            "structural_parallel_support"
        ] = bool(
            structural_support
        )

    return record


def _diagnose_removed_segments(
    before,
    after,
    profile,
    gap_families,
):
    """
    Return exact segment provenance for geometry removed by
    one cleanup stage.

    Diagnostic only. Does not affect cleanup decisions.
    """

    after_keys = {
        _segment_key(
            seg,
            profile[
                "snap_tolerance"
            ]
            * 0.10,
        )
        for seg
        in after
    }

    records = []

    for index, seg in enumerate(
        before
    ):
        key = _segment_key(
            seg,
            profile[
                "snap_tolerance"
            ]
            * 0.10,
        )

        if key in after_keys:
            continue

        structural_support = (
            _has_parallel_family_support(
                index,
                before,
                profile,
                gap_families,
            )
        )

        records.append(
            _debug_segment_record(
                seg,
                profile,
                structural_support=(
                    structural_support
                ),
            )
        )

    return records


def _diagnose_terminal_branches(
    segments,
    profile,
    gap_families,
):
    """
    Inspect branches that start at a graph junction and terminate
    at an open endpoint.

    Diagnostic only.

    This specifically allows the generic engine to understand
    annotation/break/leader structures that are embedded inside
    a much larger architectural component.
    """

    if not segments:
        return []

    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    bridges = _find_bridge_edges(
        segments,
        profile,
    )

    def other_node(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        if b == node:
            return a

        return None

    def directed_vector(
        p0,
        p1,
    ):
        dx = (
            p1[0]
            - p0[0]
        )

        dy = (
            p1[1]
            - p0[1]
        )

        length = math.hypot(
            dx,
            dy,
        )

        if length <= 1e-12:
            return None

        return (
            dx / length,
            dy / length,
        )

    results = []

    seen_edge_sets = set()

    junction_nodes = [
        node
        for node, edges
        in adjacency.items()
        if len(
            edges
        ) >= 3
    ]

    for root in junction_nodes:

        for first_edge in adjacency.get(
            root,
            [],
        ):

            chain_edges = []

            chain_nodes = [
                root
            ]

            previous_edge = None

            current_edge = (
                first_edge
            )

            current_node = (
                root
            )

            terminal = False

            valid = True

            for step in range(
                24
            ):
                if (
                    current_edge
                    in chain_edges
                ):
                    valid = False
                    break

                chain_edges.append(
                    current_edge
                )

                next_node = other_node(
                    current_edge,
                    current_node,
                )

                if next_node is None:
                    valid = False
                    break

                chain_nodes.append(
                    next_node
                )

                next_degree = len(
                    adjacency.get(
                        next_node,
                        [],
                    )
                )

                if next_degree == 1:
                    terminal = True
                    break

                if next_degree != 2:
                    valid = False
                    break

                options = [
                    edge_index
                    for edge_index
                    in adjacency.get(
                        next_node,
                        [],
                    )
                    if edge_index
                    != current_edge
                ]

                if len(
                    options
                ) != 1:
                    valid = False
                    break

                previous_edge = (
                    current_edge
                )

                current_edge = (
                    options[
                        0
                    ]
                )

                current_node = (
                    next_node
                )

            if (
                not valid
                or not terminal
            ):
                continue

            edge_key = tuple(
                sorted(
                    chain_edges
                )
            )

            if edge_key in seen_edge_sets:
                continue

            seen_edge_sets.add(
                edge_key
            )

            structural_edges = [
                edge_index
                for edge_index
                in chain_edges
                if _has_parallel_family_support(
                    edge_index,
                    segments,
                    profile,
                    gap_families,
                )
            ]

            vectors = []

            for index in range(
                len(
                    chain_nodes
                )
                - 1
            ):
                vectors.append(
                    directed_vector(
                        node_points[
                            chain_nodes[
                                index
                            ]
                        ],
                        node_points[
                            chain_nodes[
                                index + 1
                            ]
                        ],
                    )
                )

            turns = []

            positive = 0
            negative = 0

            for index in range(
                len(
                    vectors
                )
                - 1
            ):

                v0 = vectors[
                    index
                ]

                v1 = vectors[
                    index + 1
                ]

                if (
                    v0 is None
                    or v1 is None
                ):
                    continue

                dot_value = max(
                    -1.0,
                    min(
                        1.0,
                        _dot(
                            v0,
                            v1,
                        ),
                    ),
                )

                angle = math.degrees(
                    math.acos(
                        dot_value
                    )
                )

                signed = _cross(
                    v0,
                    v1,
                )

                if signed > 1e-8:
                    sign = 1

                    if angle >= 10.0:
                        positive += 1

                elif signed < -1e-8:
                    sign = -1

                    if angle >= 10.0:
                        negative += 1

                else:
                    sign = 0

                turns.append(
                    {
                        "angle_deg":
                            float(
                                angle
                            ),

                        "sign":
                            sign,
                    }
                )

            xs = [
                float(
                    node_points[
                        node
                    ][0]
                )
                for node
                in chain_nodes
            ]

            ys = [
                float(
                    node_points[
                        node
                    ][1]
                )
                for node
                in chain_nodes
            ]

            results.append(
                {
                    "root_degree":
                        len(
                            adjacency.get(
                                root,
                                [],
                            )
                        ),

                    "edge_count":
                        len(
                            chain_edges
                        ),

                    "all_edges_are_bridges":
                        all(
                            edge_index
                            in bridges
                            for edge_index
                            in chain_edges
                        ),

                    "structural_support_edge_count":
                        len(
                            structural_edges
                        ),

                    "positive_turn_count":
                        positive,

                    "negative_turn_count":
                        negative,

                    "total_length":
                        float(
                            sum(
                                _length(
                                    segments[
                                        edge_index
                                    ]
                                )
                                for edge_index
                                in chain_edges
                            )
                        ),

                    "bbox": [
                        min(
                            xs
                        ),
                        min(
                            ys
                        ),
                        max(
                            xs
                        ),
                        max(
                            ys
                        ),
                    ],

                    "turns":
                        turns,

                    "edges": [
                        _debug_segment_record(
                            segments[
                                edge_index
                            ],
                            profile,
                            structural_support=(
                                edge_index
                                in structural_edges
                            ),
                        )
                        for edge_index
                        in chain_edges
                    ],
                }
            )

    results.sort(
        key=lambda item:
            (
                item[
                    "edge_count"
                ],
                item[
                    "bbox"
                ][0],
                item[
                    "bbox"
                ][1],
            )
    )

    return results


def _diagnose_open_components(
    segments,
    profile,
    gap_families,
):
    """
    Explain remaining graph components.

    This allows us to distinguish:
    - real open architectural contours
    - break/annotation symbols
    - isolated fragments
    - branch structures

    without adding project-specific rules.
    """

    if not segments:
        return []

    adjacency, edge_nodes, node_points = (
        _build_graph(
            segments,
            profile,
        )
    )

    bridge_edges = _find_bridge_edges(
        segments,
        profile,
    )

    visited_nodes = set()

    output = []

    def other_node(
        edge_index,
        node,
    ):
        a, b = edge_nodes[
            edge_index
        ]

        if a == node:
            return b

        if b == node:
            return a

        return None

    def directed_vector(
        p0,
        p1,
    ):
        dx = (
            p1[0]
            - p0[0]
        )

        dy = (
            p1[1]
            - p0[1]
        )

        length = math.hypot(
            dx,
            dy,
        )

        if length <= 1e-12:
            return None

        return (
            dx / length,
            dy / length,
        )

    for seed in adjacency:

        if seed in visited_nodes:
            continue

        stack = [
            seed
        ]

        component_nodes = set()

        component_edges = set()

        while stack:

            node = stack.pop()

            if node in component_nodes:
                continue

            component_nodes.add(
                node
            )

            visited_nodes.add(
                node
            )

            for edge_index in adjacency.get(
                node,
                [],
            ):
                component_edges.add(
                    edge_index
                )

                next_node = other_node(
                    edge_index,
                    node,
                )

                if (
                    next_node is not None
                    and next_node
                    not in component_nodes
                ):
                    stack.append(
                        next_node
                    )

        if not component_edges:
            continue

        degrees = {
            node:
                len(
                    [
                        edge_index
                        for edge_index
                        in adjacency.get(
                            node,
                            [],
                        )
                        if edge_index
                        in component_edges
                    ]
                )
            for node
            in component_nodes
        }

        endpoint_nodes = [
            node
            for node, degree
            in degrees.items()
            if degree == 1
        ]

        branch_nodes = [
            node
            for node, degree
            in degrees.items()
            if degree >= 3
        ]

        # We mainly care about remaining OPEN structures.
        if len(
            endpoint_nodes
        ) == 0:
            continue

        structural_edges = [
            edge_index
            for edge_index
            in component_edges
            if _has_parallel_family_support(
                edge_index,
                segments,
                profile,
                gap_families,
            )
        ]

        source_closed_edges = [
            edge_index
            for edge_index
            in component_edges
            if bool(
                segments[
                    edge_index
                ].get(
                    "source_closed",
                    False,
                )
            )
        ]

        xs = []

        ys = []

        for node in component_nodes:
            point = node_points[
                node
            ]

            xs.append(
                float(
                    point[0]
                )
            )

            ys.append(
                float(
                    point[1]
                )
            )

        total_length = sum(
            _length(
                segments[
                    edge_index
                ]
            )
            for edge_index
            in component_edges
        )

        record = {
            "edge_count":
                len(
                    component_edges
                ),

            "node_count":
                len(
                    component_nodes
                ),

            "endpoint_count":
                len(
                    endpoint_nodes
                ),

            "branch_node_count":
                len(
                    branch_nodes
                ),

            "all_edges_are_bridges":
                all(
                    edge_index
                    in bridge_edges
                    for edge_index
                    in component_edges
                ),

            "structural_support_edge_count":
                len(
                    structural_edges
                ),

            "source_closed_edge_count":
                len(
                    source_closed_edges
                ),

            "total_length":
                float(
                    total_length
                ),

            "bbox": [
                float(
                    min(
                        xs
                    )
                ),
                float(
                    min(
                        ys
                    )
                ),
                float(
                    max(
                        xs
                    )
                ),
                float(
                    max(
                        ys
                    )
                ),
            ],
        }

        # ----------------------------------------------------
        # Additional turn analysis for SIMPLE OPEN CHAINS.
        # ----------------------------------------------------

        if (
            len(
                endpoint_nodes
            )
            == 2
            and not branch_nodes
        ):
            start = endpoint_nodes[
                0
            ]

            target = endpoint_nodes[
                1
            ]

            ordered_nodes = [
                start
            ]

            ordered_edges = []

            current_node = start

            previous_edge = None

            valid = True

            while (
                current_node
                != target
            ):

                options = [
                    edge_index
                    for edge_index
                    in adjacency.get(
                        current_node,
                        [],
                    )
                    if (
                        edge_index
                        in component_edges
                        and edge_index
                        != previous_edge
                    )
                ]

                if len(
                    options
                ) != 1:
                    valid = False
                    break

                edge_index = options[
                    0
                ]

                next_node = other_node(
                    edge_index,
                    current_node,
                )

                if next_node is None:
                    valid = False
                    break

                ordered_edges.append(
                    edge_index
                )

                ordered_nodes.append(
                    next_node
                )

                previous_edge = edge_index

                current_node = next_node

                if (
                    len(
                        ordered_edges
                    )
                    > len(
                        component_edges
                    )
                ):
                    valid = False
                    break

            if valid:

                vectors = []

                for index in range(
                    len(
                        ordered_nodes
                    )
                    - 1
                ):
                    vector = directed_vector(
                        node_points[
                            ordered_nodes[
                                index
                            ]
                        ],
                        node_points[
                            ordered_nodes[
                                index + 1
                            ]
                        ],
                    )

                    vectors.append(
                        vector
                    )

                turns = []

                positive_turns = 0
                negative_turns = 0

                for index in range(
                    len(
                        vectors
                    )
                    - 1
                ):
                    v0 = vectors[
                        index
                    ]

                    v1 = vectors[
                        index + 1
                    ]

                    if (
                        v0 is None
                        or v1 is None
                    ):
                        continue

                    dot_value = max(
                        -1.0,
                        min(
                            1.0,
                            _dot(
                                v0,
                                v1,
                            ),
                        ),
                    )

                    angle = math.degrees(
                        math.acos(
                            dot_value
                        )
                    )

                    signed = _cross(
                        v0,
                        v1,
                    )

                    if signed > 1e-8:
                        sign = 1

                        if angle >= 10.0:
                            positive_turns += 1

                    elif signed < -1e-8:
                        sign = -1

                        if angle >= 10.0:
                            negative_turns += 1

                    else:
                        sign = 0

                    turns.append(
                        {
                            "angle_deg":
                                float(
                                    angle
                                ),

                            "sign":
                                sign,
                        }
                    )

                record[
                    "simple_open_chain"
                ] = True

                record[
                    "turns"
                ] = turns

                record[
                    "positive_turn_count"
                ] = positive_turns

                record[
                    "negative_turn_count"
                ] = negative_turns

        # Keep individual edges for small enough components.
        if len(
            component_edges
        ) <= 30:

            record[
                "edges"
            ] = [
                _debug_segment_record(
                    segments[
                        edge_index
                    ],
                    profile,
                    structural_support=(
                        edge_index
                        in structural_edges
                    ),
                )
                for edge_index
                in sorted(
                    component_edges
                )
            ]

        output.append(
            record
        )

    output.sort(
        key=lambda item:
            (
                item[
                    "edge_count"
                ],
                item[
                    "bbox"
                ][0],
                item[
                    "bbox"
                ][1],
            )
    )

    return output


# ============================================================
# PUBLIC PIPELINE
# ============================================================

def simplify_redundant_path_vertices(
    paths,
    profile,
):
    """
    GENERIC FINAL SPLINE VERTEX SIMPLIFICATION

    Removes only geometrically redundant intermediate vertices:

        A ---- B ---- C

    when B lies on the same straight continuation A -> C.

    Preserves:
    - corners
    - actual kinks
    - path endpoints
    - closed/open state
    - minimum polygon topology

    Runs after architectural topology cleanup.

    No:
    - project coordinates
    - layer names
    - wall thickness
    - axis assumptions
    - CAD unit assumptions
    """

    if not paths:
        return (
            paths,
            0,
        )

    snap_tolerance = abs(
        float(
            profile.get(
                "snap_tolerance",
                0.0,
            )
            or 0.0
        )
    )

    drawing_diagonal = abs(
        float(
            profile.get(
                "drawing_diagonal",
                0.0,
            )
            or 0.0
        )
    )

    # Very conservative geometric tolerance.
    # This is only for essentially identical straight lines.
    straight_tolerance = max(
        snap_tolerance
        * 0.02,
        drawing_diagonal
        * 1e-10,
        1e-8,
    )

    duplicate_tolerance = max(
        straight_tolerance
        * 0.10,
        1e-10,
    )

    removed_total = 0

    output = []

    def point_distance(
        a,
        b,
    ):
        return math.hypot(
            b[0] - a[0],
            b[1] - a[1],
        )

    def redundant_middle(
        a,
        b,
        c,
    ):
        abx = (
            b[0]
            - a[0]
        )

        aby = (
            b[1]
            - a[1]
        )

        bcx = (
            c[0]
            - b[0]
        )

        bcy = (
            c[1]
            - b[1]
        )

        acx = (
            c[0]
            - a[0]
        )

        acy = (
            c[1]
            - a[1]
        )

        len_ab = math.hypot(
            abx,
            aby,
        )

        len_bc = math.hypot(
            bcx,
            bcy,
        )

        len_ac = math.hypot(
            acx,
            acy,
        )

        if (
            len_ab
            <= duplicate_tolerance
            or len_bc
            <= duplicate_tolerance
        ):
            return True

        if (
            len_ac
            <= duplicate_tolerance
        ):
            return False

        # Do not collapse a reversal / fold-back.
        forward_dot = (
            abx
            * bcx
            + aby
            * bcy
        )

        if (
            forward_dot
            <= 0.0
        ):
            return False

        # Perpendicular distance of B from line A-C.
        cross = abs(
            acx
            * (
                b[1]
                - a[1]
            )
            - acy
            * (
                b[0]
                - a[0]
            )
        )

        deviation = (
            cross
            / len_ac
        )

        if (
            deviation
            > straight_tolerance
        ):
            return False

        # B must lie between A and C.
        ac_squared = (
            acx
            * acx
            + acy
            * acy
        )

        projection = (
            (
                b[0]
                - a[0]
            )
            * acx
            + (
                b[1]
                - a[1]
            )
            * acy
        )

        t = (
            projection
            / ac_squared
        )

        param_tolerance = (
            straight_tolerance
            / len_ac
        )

        if not (
            -param_tolerance
            <= t
            <= 1.0
            + param_tolerance
        ):
            return False

        return True

    for closed, points in paths:

        clean = []

        # --------------------------------------------
        # Consecutive duplicate cleanup.
        # --------------------------------------------

        for point in points:

            current = (
                float(
                    point[0]
                ),
                float(
                    point[1]
                ),
            )

            if (
                clean
                and point_distance(
                    clean[-1],
                    current,
                )
                <= duplicate_tolerance
            ):
                removed_total += 1
                continue

            clean.append(
                current
            )

        # A closed chain does not need an explicit duplicated
        # final point because the Max spline itself is closed.
        if (
            closed
            and len(
                clean
            )
            >= 2
            and point_distance(
                clean[0],
                clean[-1],
            )
            <= duplicate_tolerance
        ):
            clean.pop()

            removed_total += 1

        # --------------------------------------------
        # CLOSED PATH
        # --------------------------------------------

        if closed:

            changed = True

            while (
                changed
                and len(
                    clean
                )
                > 3
            ):
                changed = False

                count = len(
                    clean
                )

                for index in range(
                    count
                ):

                    previous_point = clean[
                        (
                            index - 1
                        )
                        % count
                    ]

                    current_point = clean[
                        index
                    ]

                    next_point = clean[
                        (
                            index + 1
                        )
                        % count
                    ]

                    if redundant_middle(
                        previous_point,
                        current_point,
                        next_point,
                    ):
                        del clean[
                            index
                        ]

                        removed_total += 1

                        changed = True

                        break

        # --------------------------------------------
        # OPEN PATH
        #
        # First and last points are protected.
        # --------------------------------------------

        else:

            changed = True

            while (
                changed
                and len(
                    clean
                )
                > 2
            ):
                changed = False

                for index in range(
                    1,
                    len(
                        clean
                    )
                    - 1
                ):

                    if redundant_middle(
                        clean[
                            index - 1
                        ],
                        clean[
                            index
                        ],
                        clean[
                            index + 1
                        ],
                    ):
                        del clean[
                            index
                        ]

                        removed_total += 1

                        changed = True

                        break

        if (
            closed
            and len(
                clean
            )
            < 3
        ):
            raise RuntimeError(
                "Vertex simplifier closed path topology bozdu."
            )

        if (
            not closed
            and len(
                clean
            )
            < 2
        ):
            raise RuntimeError(
                "Vertex simplifier open path topology bozdu."
            )

        output.append(
            (
                bool(
                    closed
                ),
                clean,
            )
        )

    return (
        output,
        removed_total,
    )


def build_clean_visible_polylines(
    drawings,
    cad_meta=None,
):
    report = {
        "engine":
            ENGINE_VERSION,
    }

    segments = (
        explode_drawings_to_segments(
            drawings
        )
    )

    report[
        "raw_segments"
    ] = len(
        segments
    )

    if not segments:
        report.update(
            _source_unit_report(
                cad_meta
            )
        )

        return (
            [],
            report,
        )

    profile = infer_geometry_profile(
        segments
    )

    report[
        "profile"
    ] = dict(
        profile
    )

    segments, removed = (
        remove_exact_duplicates(
            segments,
            profile[
                "snap_tolerance"
            ]
            * 0.10,
        )
    )

    report[
        "exact_duplicates_removed"
    ] = removed

    original_segments = [
        dict(
            seg
        )
        for seg in segments
    ]

    segments, weld_groups, welded_endpoints = (
        snap_endpoints(
            segments,
            profile,
        )
    )

    report[
        "initial_weld_groups"
    ] = weld_groups

    report[
        "initial_welded_endpoints"
    ] = welded_endpoints

    segments, overlap_removed = (
        normalize_collinear_overlaps(
            segments,
            profile,
        )
    )

    report[
        "collinear_overlap_removed"
    ] = overlap_removed

    # ========================================================
    # IMPORTANT GENERIC ORDER
    #
    # Reference/dashed geometry must be classified BEFORE
    # intersection splitting.
    #
    # Otherwise a dashed construction/reference line crossing
    # a wall becomes connected to the architectural graph and
    # can incorrectly gain cycle protection.
    #
    # This is topology-based and contains NO drawing-specific
    # dimensions.
    # ========================================================

    dash_gap_families = (
        infer_parallel_gap_families(
            segments,
            profile,
        )
    )

    report[
        "pre_split_parallel_gap_families"
    ] = dash_gap_families

    # Diagnostic snapshot only.
    segments_before_reference_diagnostic = [
        dict(
            seg
        )
        for seg in segments
    ]

    segments, dashed_removed = (
        remove_reference_dashed_runs(
            segments,
            profile,
            dash_gap_families,
        )
    )

    report[
        "reference_dashed_removed"
    ] = dashed_removed

    reference_removed_diagnostics = (
        _diagnose_removed_segments(
            segments_before_reference_diagnostic,
            segments,
            profile,
            dash_gap_families,
        )
    )

    # Only architectural geometry that survived reference
    # cleanup is allowed to create graph intersections.
    segments, split_count = (
        split_intersections(
            segments,
            profile,
        )
    )

    report[
        "intersection_splits"
    ] = split_count

    segments, removed = (
        remove_exact_duplicates(
            segments,
            profile[
                "snap_tolerance"
            ],
        )
    )

    report[
        "post_split_duplicates_removed"
    ] = removed

    # Re-learn the parallel families after reference removal
    # and intersection splitting. These are used by later
    # topology cleanup stages.
    gap_families = (
        infer_parallel_gap_families(
            segments,
            profile,
        )
    )

    report[
        "parallel_gap_families"
    ] = gap_families

    segments, isolated_removed = (
        remove_small_acyclic_noise(
            segments,
            profile,
            gap_families,
        )
    )

    report[
        "isolated_noise_removed"
    ] = isolated_removed

    # ========================================================
    # Generic detached/open zigzag annotations.
    # Does NOT require physical connection to a wall.
    # ========================================================

    # V5: legacy open-zigzag classifier retired.
    # Terminal branch classifier handles this class now.
    report[
        "open_zigzag_removed"
    ] = 0


    # ========================================================
    # Remove terminal annotation/reference branches.
    # Example: open zig-zag / break / leader symbols attached
    # to an otherwise structural graph.
    # ========================================================

    segments, terminal_annotation_removed = (
        remove_terminal_annotation_branches(
            segments,
            profile,
            gap_families,
        )
    )

    report[
        "terminal_annotation_removed"
    ] = terminal_annotation_removed

    # ========================================================
    # Remove compact open CAD symbols with branching/cycle
    # topology but no structural evidence.
    # ========================================================

    segments, compact_open_symbol_removed = (
        remove_compact_open_symbol_components(
            segments,
            profile,
            gap_families,
        )
    )

    report[
        "compact_open_symbol_removed"
    ] = compact_open_symbol_removed

    # ========================================================
    # Remove interior shared/chord edges.
    #
    # Example:
    #
    # wall + small rectangular projection:
    #
    #      +---+
    #      |   |
    # -----|   |-----
    #      ^ shared internal edge is removed
    #
    # The outer rectangle/projection remains.
    # ========================================================

    segments, chord_removed = (
        remove_internal_chords(
            segments,
            profile,
        )
    )

    report[
        "internal_chords_removed"
    ] = chord_removed

    # ========================================================
    # Remove common internal boundaries between two cycles.
    #
    # This is the generic solution for the tiny internal edge
    # visible where an attached square/rectangular projection
    # meets a larger wall contour.
    # ========================================================

    segments, shared_interior_edges_removed = (
        remove_shared_interior_edges(
            segments,
            profile,
        )
    )

    report[
        "shared_interior_edges_removed"
    ] = shared_interior_edges_removed

    segments, spur_removed = (
        remove_short_spurs(
            segments,
            profile,
        )
    )

    report[
        "short_spurs_removed"
    ] = spur_removed

    segments, restored = (
        restore_original_three_side_loops(
            segments,
            original_segments,
            profile,
        )
    )

    report[
        "original_edges_restored"
    ] = restored

    segments, final_weld_groups, final_welded_endpoints = (
        snap_endpoints(
            segments,
            profile,
        )
    )

    report[
        "final_weld_groups"
    ] = final_weld_groups

    report[
        "final_welded_endpoints"
    ] = final_welded_endpoints

    segments, final_duplicates = (
        remove_exact_duplicates(
            segments,
            profile[
                "snap_tolerance"
            ],
        )
    )

    report[
        "final_duplicates_removed"
    ] = final_duplicates

    report[
        "clean_segments"
    ] = len(
        segments
    )

    # ========================================================
    # DECISION DIAGNOSTICS
    #
    # Does NOT affect exported geometry.
    # ========================================================

    report[
        "diagnostics"
    ] = {
        "reference_removed_segments":
            reference_removed_diagnostics,

        "remaining_open_components":
            _diagnose_open_components(
                segments,
                profile,
                gap_families,
            ),

        "terminal_branch_candidates":
            _diagnose_terminal_branches(
                segments,
                profile,
                gap_families,
            ),

        "note":
            (
                "Diagnostic data only. "
                "No cleanup decision is changed by this block."
            ),
    }

    paths = build_endpoint_chains(
        segments,
        profile,
    )

    paths = normalize_paths(
        paths,
        profile,
    )

    # ========================================================
    # FINAL VERTEX DETAIL CLEANUP
    #
    # All topology decisions are complete.
    # Only redundant collinear spline knots are removed.
    # ========================================================

    path_vertices_before_simplify = sum(
        len(
            points
        )
        for closed, points
        in paths
    )

    paths, redundant_path_vertices_removed = (
        simplify_redundant_path_vertices(
            paths,
            profile,
        )
    )

    path_vertices_after_simplify = sum(
        len(
            points
        )
        for closed, points
        in paths
    )

    report[
        "path_vertices_before_simplify"
    ] = path_vertices_before_simplify

    report[
        "redundant_path_vertices_removed"
    ] = redundant_path_vertices_removed

    report[
        "path_vertices_after_simplify"
    ] = path_vertices_after_simplify


    closed_count = sum(
        1
        for closed, points
        in paths
        if closed
    )

    open_count = (
        len(
            paths
        )
        - closed_count
    )


    # ========================================================
    # CAD3D_FINAL_CLOSED_WALL_CONTOUR_CONTRACT_V2
    #
    # FINAL GENERIC SOLID-WALL PRODUCT CONTRACT
    #
    # The final product sent to 3ds Max is a SOLID wall
    # footprint. Therefore it can contain only CLOSED contours.
    #
    # Residual OPEN paths are separated from wall output only
    # when at least one valid closed wall contour exists.
    #
    # This uses NO:
    #   drawing coordinate
    #   floor position
    #   layer name
    #   roof name
    #   line length
    #   horizontal/vertical assumption
    #
    # If there are NO valid closed contours, nothing is removed.
    # ========================================================

    _cad3d_paths_before_contract = list(
        paths
    )

    _cad3d_closed_paths = []
    _cad3d_open_paths = []

    for _cad3d_path_index, _cad3d_path in enumerate(
        _cad3d_paths_before_contract
    ):
        try:
            (
                _cad3d_is_closed,
                _cad3d_points,
            ) = _cad3d_path
        except Exception:
            raise RuntimeError(
                "Unexpected final path structure."
            )

        _cad3d_points = list(
            _cad3d_points or []
        )

        if (
            bool(
                _cad3d_is_closed
            )
            and len(
                _cad3d_points
            ) >= 3
        ):
            _cad3d_closed_paths.append(
                (
                    True,
                    _cad3d_points,
                )
            )

        elif len(
            _cad3d_points
        ) >= 2:
            _cad3d_open_paths.append(
                (
                    _cad3d_path_index,
                    _cad3d_points,
                )
            )


    _cad3d_wall_contract_status = (
        "preserved_no_closed_contours"
    )

    _cad3d_removed_open_count = 0


    if _cad3d_closed_paths:

        _cad3d_removed_open_count = len(
            _cad3d_open_paths
        )

        paths = list(
            _cad3d_closed_paths
        )

        _cad3d_wall_contract_status = (
            "closed_wall_product"
        )

    report[
        "path_count"
    ] = len(
        paths
    )

    report[
        "closed_count"
    ] = closed_count

    report[
        "open_count"
    ] = open_count


    # Final counts MUST describe the actual product returned
    # to the preview / 3ds Max bridge.

    report[
        "path_count"
    ] = len(
        paths
    )

    report[
        "closed_count"
    ] = sum(
        1
        for _cad3d_closed, _cad3d_points
        in paths
        if bool(
            _cad3d_closed
        )
    )

    report[
        "open_count"
    ] = sum(
        1
        for _cad3d_closed, _cad3d_points
        in paths
        if not bool(
            _cad3d_closed
        )
    )

    report[
        "wall_contour_contract_status"
    ] = (
        _cad3d_wall_contract_status
    )

    report[
        "open_paths_before_wall_contract"
    ] = len(
        _cad3d_open_paths
    )

    report[
        "nonwall_open_paths_removed"
    ] = int(
        _cad3d_removed_open_count
    )


    report[
        "removed_total"
    ] = (
        report[
            "exact_duplicates_removed"
        ]
        + report[
            "collinear_overlap_removed"
        ]
        + report[
            "post_split_duplicates_removed"
        ]
        + report[
            "reference_dashed_removed"
        ]
        + report[
            "isolated_noise_removed"
        ]
        + report[
            "open_zigzag_removed"
        ]
        + report[
            "terminal_annotation_removed"
        ]
        + report[
            "compact_open_symbol_removed"
        ]
        + report[
            "internal_chords_removed"
        ]
        + report[
            "shared_interior_edges_removed"
        ]
        + report[
            "short_spurs_removed"
        ]
        + report[
            "final_duplicates_removed"
        ]
    )

    raw = max(
        report[
            "raw_segments"
        ],
        1,
    )

    removal_ratio = (
        report[
            "removed_total"
        ]
        / raw
    )

    report[
        "removal_ratio"
    ] = removal_ratio

    if removal_ratio <= 0.20:
        confidence = "high"

    elif removal_ratio <= 0.35:
        confidence = "medium"

    else:
        confidence = "low"

    report[
        "cleanup_confidence"
    ] = confidence

    report.update(
        _source_unit_report(
            cad_meta
        )
    )

    return (
        paths,
        report,
    )
