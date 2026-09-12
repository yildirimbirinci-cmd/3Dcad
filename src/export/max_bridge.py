from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_to_mm(document) -> float:
    try:
        import ezdxf

        doc = ezdxf.readfile(document.parsed_path)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        insunits = 0

    table = {
        1: 25.4,
        2: 304.8,
        4: 1.0,
        5: 10.0,
        6: 1000.0,
    }

    return float(table.get(insunits, 1.0))


def _safe_line_text(value) -> str:
    return (
        str(value or "")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _safe_node_name(floor_name: str) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(floor_name or ""),
    )

    text = (
        text.encode("ascii", "ignore")
        .decode("ascii")
    )

    text = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        text,
    ).strip("_")

    if not text:
        text = "Floor"

    return "3Dcad_" + text + "_Walls"


# CAD3D_CANONICAL_WALL_CONTOUR_EXPORT_V1
def _cad3d_wall_point_xy(value):
    if (
        hasattr(value, "x")
        and hasattr(value, "y")
    ):
        return (
            float(value.x),
            float(value.y),
        )

    return (
        float(value[0]),
        float(value[1]),
    )


def _cad3d_wall_distance(
    a,
    b,
):
    import math

    return math.hypot(
        float(b[0]) - float(a[0]),
        float(b[1]) - float(a[1]),
    )


def _cad3d_wall_ring_area(
    points,
):
    if len(points) < 3:
        return 0.0

    total = 0.0

    for index, point_a in enumerate(
        points
    ):
        point_b = points[
            (index + 1)
            % len(points)
        ]

        total += (
            float(point_a[0])
            * float(point_b[1])
            - float(point_b[0])
            * float(point_a[1])
        )

    return abs(
        total * 0.5
    )


def _cad3d_remove_redundant_ring_vertices(
    raw_points,
    tolerance,
):
    import math

    points = []

    for value in raw_points or ():
        try:
            point = (
                float(value[0]),
                float(value[1]),
            )
        except (
            TypeError,
            ValueError,
            IndexError,
        ):
            continue

        if (
            points
            and _cad3d_wall_distance(
                points[-1],
                point,
            )
            <= tolerance
        ):
            continue

        points.append(
            point
        )

    if (
        len(points) >= 2
        and _cad3d_wall_distance(
            points[0],
            points[-1],
        )
        <= tolerance
    ):
        points.pop()

    if len(points) < 3:
        return ()

    changed = True

    while (
        changed
        and len(points) > 3
    ):
        changed = False
        result = []
        count = len(points)

        for index in range(count):
            a = points[
                (index - 1)
                % count
            ]
            b = points[index]
            c = points[
                (index + 1)
                % count
            ]

            acx = (
                float(c[0])
                - float(a[0])
            )

            acy = (
                float(c[1])
                - float(a[1])
            )

            ac_length = math.hypot(
                acx,
                acy,
            )

            if ac_length <= tolerance:
                result.append(
                    b
                )
                continue

            abx = (
                float(b[0])
                - float(a[0])
            )

            aby = (
                float(b[1])
                - float(a[1])
            )

            cross = abs(
                acx * aby
                - acy * abx
            )

            perpendicular = (
                cross
                / ac_length
            )

            bcx = (
                float(c[0])
                - float(b[0])
            )

            bcy = (
                float(c[1])
                - float(b[1])
            )

            same_direction = (
                abx * bcx
                + aby * bcy
            ) >= -(
                tolerance
                * tolerance
            )

            if (
                perpendicular <= tolerance
                and same_direction
            ):
                changed = True
                continue

            result.append(
                b
            )

        if len(result) < 3:
            break

        points = result

    return tuple(
        points
    )


def _cad3d_ring_identity(
    points,
    tolerance,
):
    scale = max(
        float(tolerance),
        1.0e-9,
    )

    values = tuple(
        (
            int(
                round(
                    float(point[0])
                    / scale
                )
            ),
            int(
                round(
                    float(point[1])
                    / scale
                )
            ),
        )
        for point in points
    )

    if not values:
        return ()

    rotations = []

    count = len(values)

    for sequence in (
        values,
        tuple(reversed(values)),
    ):
        for index in range(count):
            rotations.append(
                sequence[index:]
                + sequence[:index]
            )

    return min(
        rotations
    )


def _cad3d_build_closed_wall_contours(
    document,
    selected_primitives,
    source_to_mm,
):
    from export._cad_to_3d_max_cleanup.generic_cad_cleanup import (
        build_clean_visible_polylines,
    )

    drawings = []

    raw_vertex_count = 0

    for source_index, primitive in enumerate(
        selected_primitives
    ):
        points = []

        for raw_point in (
            getattr(
                primitive,
                "points",
                (),
            )
            or ()
        ):
            try:
                points.append(
                    _cad3d_wall_point_xy(
                        raw_point
                    )
                )
            except (
                TypeError,
                ValueError,
                IndexError,
                AttributeError,
            ):
                continue

        if len(points) < 2:
            continue

        raw_vertex_count += len(
            points
        )

        layer = str(
            getattr(
                primitive,
                "layer",
                "",
            )
            or ""
        ).strip()

        linetype = str(
            getattr(
                primitive,
                "linetype",
                "",
            )
            or getattr(
                primitive,
                "linetype_name",
                "",
            )
            or "CONTINUOUS"
        ).strip()

        source_type = str(
            getattr(
                primitive,
                "source_type",
                "",
            )
            or ""
        ).strip()

        drawings.append(
            {
                "points":
                    [
                        [
                            float(point[0]),
                            float(point[1]),
                        ]
                        for point in points
                    ],

                "closed":
                    bool(
                        getattr(
                            primitive,
                            "closed",
                            False,
                        )
                    ),

                "layer":
                    layer,

                "linetype":
                    linetype,

                "type":
                    (
                        source_type
                        or (
                            "LWPOLYLINE"
                            if len(points) > 2
                            else "LINE"
                        )
                    ),

                "source_index":
                    int(source_index),
            }
        )

    if not drawings:
        raise RuntimeError(
            "Duvar topology kaynagi bos."
        )

    cad_meta = {
        "source_unit_code":
            0,

        "source_unit_token":
            "source",

        "source_unit_name":
            "CAD source units",

        "source_to_mm":
            float(source_to_mm),

        "source_unit_confidence":
            "3Dcad_document",
    }

    cleaned_paths, cleanup_report = (
        build_clean_visible_polylines(
            drawings,
            cad_meta=cad_meta,
        )
    )

    tolerance_source = max(
        1.0e-9,
        0.1
        / max(
            float(source_to_mm),
            1.0e-12,
        ),
    )

    closed_paths = []
    seen = set()

    for closed, raw_points in (
        cleaned_paths
        or ()
    ):
        if not bool(closed):
            continue

        points = (
            _cad3d_remove_redundant_ring_vertices(
                raw_points,
                tolerance_source,
            )
        )

        if len(points) < 3:
            continue

        if (
            _cad3d_wall_ring_area(
                points
            )
            <= (
                tolerance_source
                * tolerance_source
            )
        ):
            continue

        identity = (
            _cad3d_ring_identity(
                points,
                tolerance_source,
            )
        )

        if identity in seen:
            continue

        seen.add(
            identity
        )

        closed_paths.append(
            points
        )

    if not closed_paths:
        status = ""

        if isinstance(
            cleanup_report,
            dict,
        ):
            status = str(
                cleanup_report.get(
                    "wall_contour_contract_status",
                    "",
                )
                or ""
            )

        raise RuntimeError(
            "Max aktarimi durduruldu: "
            "kapali duvar konturu uretilemedi"
            + (
                " | "
                + status
                if status
                else ""
            )
        )

    report_keys = (
        "raw_segments",
        "exact_duplicates_removed",
        "initial_weld_groups",
        "initial_welded_endpoints",
        "collinear_overlap_removed",
        "reference_dashed_removed",
        "intersection_splits",
        "post_split_duplicates_removed",
        "internal_chords_removed",
        "shared_interior_edges_removed",
        "short_spurs_removed",
        "final_weld_groups",
        "final_welded_endpoints",
        "final_duplicates_removed",
        "redundant_path_vertices_removed",
        "open_paths_before_wall_contract",
        "nonwall_open_paths_removed",
        "wall_contour_contract_status",
        "closed_count",
        "open_count",
    )

    compact_cleanup = {}

    if isinstance(
        cleanup_report,
        dict,
    ):
        for key in report_keys:
            if key in cleanup_report:
                compact_cleanup[key] = (
                    cleanup_report[
                        key
                    ]
                )

    topology_report = {
        "engine":
            "CAD3D_CANONICAL_WALL_CONTOUR_EXPORT_V1",

        "input_wall_primitives":
            len(
                selected_primitives
            ),

        "input_vertices":
            raw_vertex_count,

        "cleaned_path_count":
            len(
                cleaned_paths
                or ()
            ),

        "output_closed_contours":
            len(
                closed_paths
            ),

        "output_open_contours":
            0,

        "output_vertices":
            sum(
                len(points)
                for points in closed_paths
            ),

        "serializer_tolerance_mm":
            0.1,

        "cleanup":
            compact_cleanup,
    }

    return (
        tuple(
            closed_paths
        ),
        topology_report,
    )


def _cad3d_write_wall_topology_log(
    *,
    request_id,
    floor_name,
    node_name,
    report,
):
    import json

    target = (
        _project_root()
        / "logs"
        / "wall_export_topology.json"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = dict(
        report
        if isinstance(
            report,
            dict,
        )
        else {}
    )

    payload[
        "request_id"
    ] = str(
        request_id
    )

    payload[
        "floor_name"
    ] = (
        str(floor_name)
        if floor_name is not None
        else None
    )

    payload[
        "node_name"
    ] = str(
        node_name
    )

    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return target


def send_wall_lines_to_max(
    document,
    wall_candidates,
    *,
    floor_name=None,
    floor_index=None,
    base_z_cm=0.0,
    wall_height_cm=0.0,
    interfloor_cm=0.0,
    pivot_source=None,
    connect_levels_cm=None,
):
    if document is None:
        raise RuntimeError(
            "?nce plan alan? se?ilmelidir."
        )

    candidates = tuple(
        wall_candidates
        or ()
    )

    if not candidates:
        raise RuntimeError(
            "Max'e g?nderilecek se?ilmi? duvar yok."
        )

    indices = []

    for candidate in candidates:
        index = getattr(
            candidate,
            "primitive_index",
            None,
        )

        if index is None:
            continue

        try:
            index = int(index)
        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            index < 0
            or index >= len(
                document.primitives
            )
            or index in indices
        ):
            continue

        indices.append(
            index
        )

    if not indices:
        raise RuntimeError(
            "Ge?erli duvar primitive'i bulunamad?."
        )

    selected_primitives = [
        document.primitives[
            index
        ]
        for index in indices
    ]

    xs = []
    ys = []

    for primitive in selected_primitives:
        for raw_point in (
            getattr(
                primitive,
                "points",
                (),
            )
            or ()
        ):
            try:
                x, y = (
                    _cad3d_wall_point_xy(
                        raw_point
                    )
                )
            except Exception:
                continue

            xs.append(
                float(x)
            )

            ys.append(
                float(y)
            )

    if not xs:
        raise RuntimeError(
            "Duvar geometrisi bo?."
        )

    source_to_mm = (
        _source_to_mm(
            document
        )
    )

    (
        closed_wall_paths,
        topology_report,
    ) = (
        _cad3d_build_closed_wall_contours(
            document,
            selected_primitives,
            source_to_mm,
        )
    )

    if pivot_source is None:
        pivot_x_source = (
            min(xs)
            + max(xs)
        ) * 0.5

        pivot_y_source = (
            min(ys)
            + max(ys)
        ) * 0.5

    else:
        if (
            not isinstance(
                pivot_source,
                (tuple, list),
            )
            or len(pivot_source) != 2
        ):
            raise RuntimeError(
                "Kat pivotu ge?ersiz."
            )

        pivot_x_source = float(
            pivot_source[0]
        )

        pivot_y_source = float(
            pivot_source[1]
        )

    pivot_x_mm = (
        pivot_x_source
        * source_to_mm
    )

    pivot_y_mm = (
        pivot_y_source
        * source_to_mm
    )

    request_id = str(
        time.time_ns()
    )

    is_floor_request = (
        floor_name is not None
    )

    if is_floor_request:
        if floor_index is None:
            raise RuntimeError(
                "Kat index bilgisi eksik."
            )

        floor_name = (
            _safe_line_text(
                floor_name
            )
        )

        node_name = (
            _safe_node_name(
                floor_name
            )
        )

        lines = [
            "3DCAD_WALL_REQUEST_V2",
            "REQUEST_ID="
            + request_id,
            "FLOOR_NAME="
            + floor_name,
            "FLOOR_INDEX="
            + str(
                int(
                    floor_index
                )
            ),
            "BASE_Z_CM="
            + repr(
                float(
                    base_z_cm
                )
            ),
            "HEIGHT_CM="
            + repr(
                float(
                    wall_height_cm
                )
            ),
            "INTERFLOOR_CM="
            + repr(
                float(
                    interfloor_cm
                )
            ),
            "NODE_NAME="
            + node_name,
            "PIVOT_X_MM="
            + repr(
                float(
                    pivot_x_mm
                )
            ),
            "PIVOT_Y_MM="
            + repr(
                float(
                    pivot_y_mm
                )
            ),
            "SOURCE_TO_MM="
            + repr(
                float(
                    source_to_mm
                )
            ),
        ]

    else:
        node_name = (
            "3Dcad_Walls"
        )

        lines = [
            "3DCAD_WALL_REQUEST_V1",
            "REQUEST_ID="
            + request_id,
            "PIVOT_X_MM="
            + repr(
                float(
                    pivot_x_mm
                )
            ),
            "PIVOT_Y_MM="
            + repr(
                float(
                    pivot_y_mm
                )
            ),
            "SOURCE_TO_MM="
            + repr(
                float(
                    source_to_mm
                )
            ),
        ]

    # CAD3D_CONNECT_REQUEST_PIPELINE_V1
    normalized_connect_levels = []
    seen_connect_levels = set()

    if is_floor_request:
        for raw_level in (
            connect_levels_cm
            or ()
        ):
            try:
                level = float(
                    raw_level
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if (
                level != level
                or abs(
                    level
                )
                == float(
                    "inf"
                )
            ):
                continue

            if not (
                0.0
                < level
                < float(
                    wall_height_cm
                )
            ):
                continue

            key = round(
                level,
                6,
            )

            if key in seen_connect_levels:
                continue

            seen_connect_levels.add(
                key
            )

            normalized_connect_levels.append(
                float(
                    key
                )
            )

        normalized_connect_levels.sort()

        lines.append(
            "CONNECT_LEVEL_COUNT="
            + str(
                len(
                    normalized_connect_levels
                )
            )
        )

        for level in normalized_connect_levels:
            lines.append(
                "CONNECT_LEVEL_CM="
                + repr(
                    float(
                        level
                    )
                )
            )

    sent_count = 0

    for points in closed_wall_paths:
        if len(points) < 3:
            continue

        point_text = ";".join(
            (
                f"{float(point[0]) * source_to_mm:.9f},"
                f"{float(point[1]) * source_to_mm:.9f}"
            )
            for point in points
        )

        # FINAL CONTRACT:
        # Max'e artik yalniz CLOSED spline gider.
        lines.append(
            "S|1|"
            + point_text
        )

        sent_count += 1

    if sent_count <= 0:
        raise RuntimeError(
            "Aktar?labilir kapal? duvar konturu bulunamad?."
        )

    target = (
        _project_root()
        / "data"
        / "cache"
        / "max_bridge"
        / "visible_cad_request.txt"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        target.with_suffix(
            ".tmp"
        )
    )

    temporary.write_text(
        "\n".join(
            lines
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        target
    )

    topology_log = (
        _cad3d_write_wall_topology_log(
            request_id=
                request_id,
            floor_name=
                floor_name
                if is_floor_request
                else None,
            node_name=
                node_name,
            report=
                topology_report,
        )
    )

    print("")
    print(
        "=== 3DCAD WALL CONTOUR EXPORT ==="
    )
    print(
        "RAW WALL PRIMITIVES:",
        topology_report[
            "input_wall_primitives"
        ],
    )
    print(
        "RAW VERTICES:",
        topology_report[
            "input_vertices"
        ],
    )
    print(
        "CLOSED CONTOURS:",
        topology_report[
            "output_closed_contours"
        ],
    )
    print(
        "OPEN CONTOURS:",
        0,
    )
    print(
        "FINAL VERTICES:",
        topology_report[
            "output_vertices"
        ],
    )
    print(
        "TOPOLOGY LOG:",
        topology_log,
    )
    print(
        "=== END WALL CONTOUR EXPORT ==="
    )
    print("")

    return {
        "request_id":
            request_id,

        "wall_count":
            sent_count,

        "pivot_x_mm":
            pivot_x_mm,

        "pivot_y_mm":
            pivot_y_mm,

        "source_to_mm":
            source_to_mm,

        "floor_name":
            (
                floor_name
                if is_floor_request
                else None
            ),

        "floor_index":
            (
                int(
                    floor_index
                )
                if is_floor_request
                else None
            ),

        "base_z_cm":
            (
                float(
                    base_z_cm
                )
                if is_floor_request
                else 0.0
            ),

        "wall_height_cm":
            (
                float(
                    wall_height_cm
                )
                if is_floor_request
                else 0.0
            ),

        "interfloor_cm":
            (
                float(
                    interfloor_cm
                )
                if is_floor_request
                else 0.0
            ),

        "node_name":
            node_name,

        "request_file":
            target,

        "topology_log":
            topology_log,
    }
