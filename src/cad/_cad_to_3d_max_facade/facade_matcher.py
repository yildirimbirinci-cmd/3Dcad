from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median


ENGINE = "CAD3D_AUTO_DWG_FACADE_FRONT_REAR_V8"


# ============================================================
# BASIC GEOMETRY
# ============================================================

def _point(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except Exception:
            return None

    return None


def _item_bbox(item):
    points = []

    for value in item.get("points", []) or []:
        point = _point(value)

        if point is not None:
            points.append(point)

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return (
        min(xs),
        min(ys),
        max(xs),
        max(ys),
    )


def _union_bbox(boxes):
    if not boxes:
        return None

    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def geometry_bounds(geometry):
    return _union_bbox(
        [
            box
            for item in geometry or []
            for box in [_item_bbox(item)]
            if box is not None
        ]
    )


def _bbox_center(box):
    return (
        (box[0] + box[2]) * 0.5,
        (box[1] + box[3]) * 0.5,
    )


# ============================================================
# SEMANTIC HINTS
# ============================================================

def _layer_kind(layer):
    layer = str(layer or "").strip()

    try:
        from cad._cad_to_3d_max_facade.cad_intelligence import semantic_category

        value = str(
            semantic_category(layer)
            or ""
        ).strip().lower()

        if value in {
            "door",
            "window",
            "furniture",
        }:
            return value

    except Exception:
        pass

    upper = layer.upper()

    if "DOOR" in upper or "KAPI" in upper:
        return "door"

    if "WINDOW" in upper or "PENCERE" in upper:
        return "window"

    if (
        "FURNITURE" in upper
        or "WARDROBE" in upper
        or "KITCHEN" in upper
    ):
        return "furniture"

    return ""


def _is_hatch(layer):
    return "HATCH" in str(layer or "").upper()


def _is_detail_layer(layer):
    upper = str(layer or "").upper()

    return any(
        token in upper
        for token in (
            "HATCH",
            "DIMENSION",
            "FURNITURE",
            "WARDROBE",
            "KITCHEN",
            "STAIR",
            "TEXT",
            "ANNOT",
        )
    )


# ============================================================
# FULL DWG REGION SEGMENTATION
# ============================================================

def detect_drawing_regions(geometry):
    geometry = list(geometry or [])

    full_bounds = geometry_bounds(
        geometry
    )

    if full_bounds is None:
        return []

    width = max(
        full_bounds[2] - full_bounds[0],
        1.0,
    )

    height = max(
        full_bounds[3] - full_bounds[1],
        1.0,
    )

    # Probe showed ~1000 drawing units separates the real drawings.
    # Derive it from drawing size, not project identity.
    cell_size = max(
        500.0,
        min(width, height) * 0.025,
    )

    records = []

    for index, item in enumerate(
        geometry
    ):
        if not isinstance(item, dict):
            continue

        box = _item_bbox(
            item
        )

        if box is None:
            continue

        cx, cy = _bbox_center(
            box
        )

        records.append(
            {
                "index": index,
                "item": item,
                "bbox": box,
                "center": (cx, cy),
            }
        )

    cells = defaultdict(list)

    for record_index, record in enumerate(
        records
    ):
        cx, cy = record["center"]

        gx = int(
            math.floor(
                (
                    cx
                    - full_bounds[0]
                )
                / cell_size
            )
        )

        gy = int(
            math.floor(
                (
                    cy
                    - full_bounds[1]
                )
                / cell_size
            )
        )

        cells[
            (gx, gy)
        ].append(
            record_index
        )

    active = {
        cell
        for cell, values in cells.items()
        if len(values) >= 3
    }

    visited = set()
    components = []

    for start in active:
        if start in visited:
            continue

        stack = [start]
        visited.add(start)
        component_cells = []

        while stack:
            current = stack.pop()
            component_cells.append(
                current
            )

            gx, gy = current

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue

                    neighbor = (
                        gx + dx,
                        gy + dy,
                    )

                    if (
                        neighbor in active
                        and neighbor
                        not in visited
                    ):
                        visited.add(
                            neighbor
                        )

                        stack.append(
                            neighbor
                        )

        indices = []

        for cell in component_cells:
            indices.extend(
                cells[cell]
            )

        components.append(
            sorted(
                set(indices)
            )
        )

    min_items = max(
        80,
        int(
            len(records)
            * 0.007
        ),
    )

    regions = []

    for component in components:
        if len(component) < min_items:
            continue

        component_records = [
            records[i]
            for i in component
        ]

        boxes = [
            record["bbox"]
            for record in component_records
        ]

        box = _union_bbox(
            boxes
        )

        region_geometry = [
            record["item"]
            for record in component_records
        ]

        semantic_count = 0
        furniture_count = 0
        hatch_count = 0
        generic_count = 0

        for item in region_geometry:
            layer = str(
                item.get(
                    "layer",
                    ""
                )
                or ""
            )

            kind = _layer_kind(
                layer
            )

            if kind in {
                "door",
                "window",
            }:
                semantic_count += 1

            if kind == "furniture":
                furniture_count += 1

            if _is_hatch(layer):
                hatch_count += 1

            if (
                not _is_detail_layer(
                    layer
                )
                and kind not in {
                    "door",
                    "window",
                    "furniture",
                }
            ):
                generic_count += 1

        cx, cy = _bbox_center(
            box
        )

        regions.append(
            {
                "bbox": box,
                "center": (cx, cy),
                "geometry": region_geometry,
                "item_count": len(region_geometry),
                "semantic_count": semantic_count,
                "furniture_count": furniture_count,
                "hatch_count": hatch_count,
                "generic_count": generic_count,
            }
        )

    # CAD Y increases upward.
    regions.sort(
        key=lambda region: (
            -region["center"][1],
            region["center"][0],
        )
    )

    for index, region in enumerate(
        regions,
        start=1,
    ):
        region["region_id"] = (
            "R"
            + str(index).zfill(2)
        )

    return regions


# ============================================================
# MAIN PLAN SELECTION
# ============================================================

def choose_main_plan_region(regions):
    candidates = []

    for region in regions:
        total = max(
            region["item_count"],
            1,
        )

        semantic = region[
            "semantic_count"
        ]

        furniture = region[
            "furniture_count"
        ]

        if (
            semantic < 6
            and furniture < 25
        ):
            continue

        score = (
            semantic * 4.0
            + furniture * 0.40
            + total * 0.20
        )

        candidates.append(
            (
                score,
                region,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda row:
            row[0],
        reverse=True,
    )

    return candidates[0][1]


# ============================================================
# ELEVATION REGION SELECTION
# ============================================================

def choose_elevation_regions(
    regions,
    main_plan,
):
    result = []

    for region in regions:
        if region is main_plan:
            continue

        total = max(
            region[
                "item_count"
            ],
            1,
        )

        furniture_ratio = (
            region[
                "furniture_count"
            ]
            / total
        )

        semantic_ratio = (
            region[
                "semantic_count"
            ]
            / total
        )

        generic_ratio = (
            region[
                "generic_count"
            ]
            / total
        )

        box = region[
            "bbox"
        ]

        width = max(
            box[2] - box[0],
            1.0,
        )

        height = max(
            box[3] - box[1],
            1.0,
        )

        aspect = (
            width / height
        )

        # Elevations in this DWG:
        # - very little furniture,
        # - no plan door/window symbols,
        # - large amount of structural generic linework.
        if furniture_ratio > 0.08:
            continue

        if semantic_ratio > 0.02:
            continue

        if generic_ratio < 0.30:
            continue

        if total < 300:
            continue

        if aspect < 1.15:
            continue

        result.append(
            region
        )

    result.sort(
        key=lambda region: (
            -region["center"][1],
            region["center"][0],
        )
    )

    for index, region in enumerate(
        result,
        start=1,
    ):
        region[
            "facade_number"
        ] = index

    return result


# ============================================================
# PLAN OPENING EXTRACTION
# ============================================================

def _bbox_gap(a, b):
    dx = max(
        0.0,
        max(a[0], b[0])
        - min(a[2], b[2]),
    )

    dy = max(
        0.0,
        max(a[1], b[1])
        - min(a[3], b[3]),
    )

    return dx, dy


def _cluster_semantic_openings(
    geometry,
):
    records = []

    for item in geometry or []:
        kind = _layer_kind(
            item.get(
                "layer",
                ""
            )
        )

        if kind not in {
            "door",
            "window",
        }:
            continue

        box = _item_bbox(
            item
        )

        if box is None:
            continue

        records.append(
            {
                "kind": kind,
                "bbox": box,
            }
        )

    if not records:
        return []

    sizes = [
        max(
            record["bbox"][2]
            - record["bbox"][0],

            record["bbox"][3]
            - record["bbox"][1],

            1.0,
        )
        for record in records
    ]

    reference = median(
        sizes
    )

    join_gap = max(
        20.0,
        reference * 0.12,
    )

    parent = list(
        range(
            len(records)
        )
    )

    def find(index):
        while parent[index] != index:
            parent[index] = (
                parent[
                    parent[index]
                ]
            )

            index = parent[index]

        return index

    def union(a, b):
        ra = find(a)
        rb = find(b)

        if ra != rb:
            parent[rb] = ra

    for i in range(
        len(records)
    ):
        for j in range(
            i + 1,
            len(records),
        ):
            if (
                records[i]["kind"]
                != records[j]["kind"]
            ):
                continue

            dx, dy = _bbox_gap(
                records[i]["bbox"],
                records[j]["bbox"],
            )

            if (
                dx <= join_gap
                and dy <= join_gap
            ):
                union(i, j)

    groups = defaultdict(list)

    for index, record in enumerate(
        records
    ):
        groups[
            find(index)
        ].append(
            record
        )

    openings = []

    for group in groups.values():
        box = _union_bbox(
            [
                item["bbox"]
                for item in group
            ]
        )

        cx, cy = _bbox_center(
            box
        )

        openings.append(
            {
                "kind":
                    group[0]["kind"],

                "bbox":
                    box,

                "center":
                    (cx, cy),
            }
        )

    return openings


# CAD3D_PHYSICAL_FACADE_MATCH_V5

def _canonical_axis(value):
    point = _point(value)

    if point is None:
        return None

    length = math.hypot(
        point[0],
        point[1],
    )

    if length <= 1.0e-9:
        return None

    ux = point[0] / length
    uy = point[1] / length

    if (
        ux < 0.0
        or (
            abs(ux) <= 1.0e-9
            and uy < 0.0
        )
    ):
        ux = -ux
        uy = -uy

    return (
        ux,
        uy,
    )


def _detector_opening_record(
    record,
    kind,
):
    if not isinstance(
        record,
        dict,
    ):
        return None

    jamb_a = _point(
        record.get(
            "jamb_a"
        )
    )

    jamb_b = _point(
        record.get(
            "jamb_b"
        )
    )

    center = None

    if (
        jamb_a is not None
        and jamb_b is not None
    ):
        center = (
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

    if center is None:
        for key in (
            "center",
            "hinge",
            "arc_center",
        ):
            center = _point(
                record.get(key)
            )

            if center is not None:
                break

    if center is None:
        return None

    direction = None

    for key in (
        "direction",
        "wall_direction",
    ):
        direction = (
            _canonical_axis(
                record.get(key)
            )
        )

        if direction is not None:
            break

    if (
        direction is None
        and jamb_a is not None
        and jamb_b is not None
    ):
        direction = (
            _canonical_axis(
                (
                    jamb_b[0]
                    - jamb_a[0],

                    jamb_b[1]
                    - jamb_a[1],
                )
            )
        )

    if direction is None:
        return None

    try:
        width = abs(
            float(
                record.get(
                    "width",
                    0.0,
                )
                or 0.0
            )
        )
    except Exception:
        width = 0.0

    if (
        width <= 1.0e-9
        and jamb_a is not None
        and jamb_b is not None
    ):
        width = math.hypot(
            jamb_b[0]
            - jamb_a[0],

            jamb_b[1]
            - jamb_a[1],
        )

    if width <= 1.0e-9:
        return None

    normal = (
        -direction[1],
        direction[0],
    )

    try:
        thickness = abs(
            float(
                record.get(
                    "plan_thickness",
                    0.0,
                )
                or 0.0
            )
        )
    except Exception:
        thickness = 0.0

    return {
        "kind": kind,

        "center": center,

        "direction":
            direction,

        "normal":
            normal,

        "offset":
            (
                center[0]
                * normal[0]
                + center[1]
                * normal[1]
            ),

        "width":
            width,

        "plan_thickness":
            thickness,
    }


def _dedupe_physical_records(
    records,
):
    result = []

    for record in sorted(
        records,
        key=lambda row: (
            row["center"][0],
            row["center"][1],
            row["kind"],
        ),
    ):
        duplicate = False

        for kept in result:
            if (
                kept["kind"]
                != record["kind"]
            ):
                continue

            distance = math.hypot(
                kept["center"][0]
                - record["center"][0],

                kept["center"][1]
                - record["center"][1],
            )

            tolerance = max(
                40.0,
                min(
                    kept["width"],
                    record["width"],
                )
                * 0.12,
            )

            if distance <= tolerance:
                duplicate = True
                break

        if not duplicate:
            result.append(
                record
            )

    return result


def _merge_collinear_segments(
    horizontal,
    vertical,
    rw,
    rh,
):
    def merge_rows(
        rows,
        axis_key,
        start_key,
        end_key,
        axis_tol,
        gap_tol,
    ):
        groups = []

        for row in sorted(
            rows,
            key=lambda item:
                item[axis_key],
        ):
            target = None

            for group in groups:
                if abs(
                    row[axis_key]
                    - group["axis"]
                ) <= axis_tol:
                    target = group
                    break

            if target is None:
                groups.append(
                    {
                        "axis":
                            row[axis_key],

                        "rows":
                            [row],
                    }
                )
            else:
                target["rows"].append(
                    row
                )

                target["axis"] = (
                    sum(
                        item[axis_key]
                        for item
                        in target["rows"]
                    )
                    / len(
                        target["rows"]
                    )
                )

        merged = []

        for group in groups:
            intervals = sorted(
                (
                    row[start_key],
                    row[end_key],
                )
                for row in group[
                    "rows"
                ]
            )

            current_start = None
            current_end = None

            for start, end in intervals:
                if current_start is None:
                    current_start = start
                    current_end = end
                    continue

                if (
                    start
                    <= current_end
                    + gap_tol
                ):
                    current_end = max(
                        current_end,
                        end,
                    )
                else:
                    merged.append(
                        (
                            group["axis"],
                            current_start,
                            current_end,
                        )
                    )

                    current_start = start
                    current_end = end

            if current_start is not None:
                merged.append(
                    (
                        group["axis"],
                        current_start,
                        current_end,
                    )
                )

        return merged

    merged_v = merge_rows(
        vertical,
        "x",
        "y0",
        "y1",
        max(
            10.0,
            rw * 0.0018,
        ),
        max(
            20.0,
            rh * 0.012,
        ),
    )

    merged_h = merge_rows(
        horizontal,
        "y",
        "x0",
        "x1",
        max(
            10.0,
            rh * 0.0018,
        ),
        max(
            20.0,
            rw * 0.008,
        ),
    )

    vertical_result = [
        {
            "x": axis,
            "y0": start,
            "y1": end,
            "length":
                end - start,
        }
        for axis, start, end
        in merged_v
    ]

    horizontal_result = [
        {
            "y": axis,
            "x0": start,
            "x1": end,
            "length":
                end - start,
        }
        for axis, start, end
        in merged_h
    ]

    return (
        horizontal_result,
        vertical_result,
    )

# CAD3D_PLAN_FACADE_RESOLVER_V6

def _plan_window_line_candidates(
    geometry,
):
    rows = []

    for item in geometry or []:
        if not isinstance(
            item,
            dict,
        ):
            continue

        if (
            _layer_kind(
                item.get(
                    "layer",
                    "",
                )
            )
            != "window"
        ):
            continue

        box = _item_bbox(
            item
        )

        if box is None:
            continue

        width = max(
            box[2] - box[0],
            0.0,
        )

        height = max(
            box[3] - box[1],
            0.0,
        )

        cx, cy = _bbox_center(
            box
        )

        if (
            width >= height * 1.60
            and width >= 80.0
        ):
            rows.append(
                {
                    "orientation":
                        "horizontal",

                    "center":
                        (cx, cy),

                    "t":
                        cx,

                    "offset":
                        cy,

                    "span":
                        width,
                }
            )

        elif (
            height >= width * 1.60
            and height >= 80.0
        ):
            rows.append(
                {
                    "orientation":
                        "vertical",

                    "center":
                        (cx, cy),

                    "t":
                        cy,

                    "offset":
                        cx,

                    "span":
                        height,
                }
            )

    return rows


def _collapse_plan_window_rows(
    rows,
):
    rows = list(
        rows
        or []
    )

    if not rows:
        return []

    spans = [
        row["span"]
        for row in rows
        if row["span"] > 0.0
    ]

    reference_span = (
        median(spans)
        if spans
        else 600.0
    )

    tangent_tol = max(
        70.0,
        reference_span * 0.18,
    )

    offset_tol = max(
        380.0,
        reference_span * 0.70,
    )

    parent = list(
        range(
            len(rows)
        )
    )

    def find(index):
        while parent[index] != index:
            parent[index] = (
                parent[
                    parent[index]
                ]
            )

            index = parent[index]

        return index

    def union(a, b):
        ra = find(a)
        rb = find(b)

        if ra != rb:
            parent[rb] = ra

    for i in range(
        len(rows)
    ):
        for j in range(
            i + 1,
            len(rows),
        ):
            if (
                rows[i][
                    "orientation"
                ]
                !=
                rows[j][
                    "orientation"
                ]
            ):
                continue

            if (
                abs(
                    rows[i]["t"]
                    - rows[j]["t"]
                )
                > tangent_tol
            ):
                continue

            if (
                abs(
                    rows[i]["offset"]
                    - rows[j]["offset"]
                )
                > offset_tol
            ):
                continue

            union(
                i,
                j,
            )

    groups = defaultdict(
        list
    )

    for index, row in enumerate(
        rows
    ):
        groups[
            find(index)
        ].append(
            row
        )

    result = []

    for group in groups.values():
        orientation = group[
            0
        ][
            "orientation"
        ]

        centers_x = [
            row[
                "center"
            ][0]
            for row in group
        ]

        centers_y = [
            row[
                "center"
            ][1]
            for row in group
        ]

        spans = [
            row["span"]
            for row in group
        ]

        center = (
            median(
                centers_x
            ),
            median(
                centers_y
            ),
        )

        result.append(
            {
                "orientation":
                    orientation,

                "center":
                    center,

                "span":
                    median(
                        spans
                    ),

                "source_count":
                    len(group),
            }
        )

    return result

def build_plan_facades(
    plan_region,
):
    from cad._cad_to_3d_max_facade.cad_intelligence import (
        infer_cad_profile,
    )

    from cad._cad_to_3d_max_facade.door_detector import (
        detect_doors,
    )

    from cad._cad_to_3d_max_facade.window_detector import (
        detect_windows,
    )

    geometry = list(
        plan_region.get(
            "geometry",
            [],
        )
        or []
    )

    if not geometry:
        return []

    box = plan_region[
        "bbox"
    ]

    x0, y0, x1, y1 = box

    plan_center = (
        (x0 + x1) * 0.5,
        (y0 + y1) * 0.5,
    )

    # --------------------------------------------------------
    # WINDOW SOURCE 1:
    # CAD semantic graphics.
    #
    # Layer name is only a hint; this is not the final
    # architectural acceptance gate. The graphics are resolved
    # geometrically into physical window positions.
    # --------------------------------------------------------

    raw_rows = (
        _plan_window_line_candidates(
            geometry
        )
    )

    physical_rows = (
        _collapse_plan_window_rows(
            raw_rows
        )
    )

    side_windows = {
        "bottom": [],
        "right": [],
        "top": [],
        "left": [],
    }

    cx, cy = plan_center

    for row in physical_rows:
        px, py = row[
            "center"
        ]

        if (
            row[
                "orientation"
            ]
            == "horizontal"
        ):
            side = (
                "bottom"
                if py < cy
                else "top"
            )

            direction = (
                1.0,
                0.0,
            )

        else:
            side = (
                "left"
                if px < cx
                else "right"
            )

            direction = (
                0.0,
                1.0,
            )

        side_windows[
            side
        ].append(
            {
                "kind":
                    "window",

                "center":
                    (px, py),

                "direction":
                    direction,

                "width":
                    row[
                        "span"
                    ],

                "source":
                    "semantic_geometry",

                "source_count":
                    row[
                        "source_count"
                    ],
            }
        )

    # --------------------------------------------------------
    # WINDOW SOURCE 2:
    # existing proven detector is retained as fallback.
    # --------------------------------------------------------

    profile = infer_cad_profile(
        geometry
    )

    structural_layer = (
        profile.get(
            "primary_structural_layer"
        )
    )

    window_result = detect_windows(
        geometry,
        structural_layer=
            structural_layer,
    )

    detected_windows = list(
        window_result.get(
            "windows",
            [],
        )
        or []
    )

    if not detected_windows:
        fallback = detect_windows(
            geometry,
            structural_layer=None,
        )

        detected_windows = list(
            fallback.get(
                "windows",
                [],
            )
            or []
        )

    detector_window_records = [
        row
        for row in (
            _detector_opening_record(
                item,
                "window",
            )
            for item in
            detected_windows
        )
        if row is not None
    ]

    for row in detector_window_records:
        dx, dy = row[
            "direction"
        ]

        px, py = row[
            "center"
        ]

        if abs(dx) >= abs(dy):
            side = (
                "bottom"
                if py < cy
                else "top"
            )
        else:
            side = (
                "left"
                if px < cx
                else "right"
            )

        # Only fill a side if semantic geometry did not
        # already establish that facade.
        if not side_windows[
            side
        ]:
            side_windows[
                side
            ].append(
                {
                    "kind":
                        "window",

                    "center":
                        row[
                            "center"
                        ],

                    "direction":
                        row[
                            "direction"
                        ],

                    "width":
                        row[
                            "width"
                        ],

                    "source":
                        "window_detector",
                }
            )

    # --------------------------------------------------------
    # DOORS:
    # keep actual door detector entities and attach them to
    # the corresponding facade hemisphere.
    # --------------------------------------------------------

    door_result = detect_doors(
        geometry
    )

    door_records = [
        row
        for row in (
            _detector_opening_record(
                item,
                "door",
            )
            for item in
            door_result.get(
                "doors",
                [],
            )
            or []
        )
        if row is not None
    ]

    door_records = (
        _dedupe_physical_records(
            door_records
        )
    )

    result = []

    side_specs = {
        "bottom": {
            "direction":
                (1.0, 0.0),

            "outward":
                (0.0, -1.0),

            "expected_width":
                x1 - x0,
        },

        "top": {
            "direction":
                (1.0, 0.0),

            "outward":
                (0.0, 1.0),

            "expected_width":
                x1 - x0,
        },

        "left": {
            "direction":
                (0.0, 1.0),

            "outward":
                (-1.0, 0.0),

            "expected_width":
                y1 - y0,
        },

        "right": {
            "direction":
                (0.0, 1.0),

            "outward":
                (1.0, 0.0),

            "expected_width":
                y1 - y0,
        },
    }

    for side in (
        "bottom",
        "right",
        "top",
        "left",
    ):
        windows = list(
            side_windows[
                side
            ]
        )

        if not windows:
            continue

        spec = side_specs[
            side
        ]

        direction = spec[
            "direction"
        ]

        if side in {
            "bottom",
            "top",
        }:
            window_offsets = [
                item[
                    "center"
                ][1]
                for item in windows
            ]
        else:
            window_offsets = [
                item[
                    "center"
                ][0]
                for item in windows
            ]

        window_widths = [
            max(
                float(
                    item.get(
                        "width",
                        0.0,
                    )
                    or 0.0
                ),
                1.0,
            )
            for item in windows
        ]

        reference_width = max(
            median(
                window_widths
            ),
            1.0,
        )

        offset_min = min(
            window_offsets
        )

        offset_max = max(
            window_offsets
        )

        door_offset_margin = max(
            500.0,
            reference_width * 0.85,
        )

        openings = list(
            windows
        )

        for door in door_records:
            ddx, ddy = door[
                "direction"
            ]

            dot = abs(
                ddx
                * direction[0]
                +
                ddy
                * direction[1]
            )

            if (
                dot
                < math.cos(
                    math.radians(
                        12.0
                    )
                )
            ):
                continue

            px, py = door[
                "center"
            ]

            if side == "bottom":
                if py >= cy:
                    continue
                offset = py

            elif side == "top":
                if py <= cy:
                    continue
                offset = py

            elif side == "left":
                if px >= cx:
                    continue
                offset = px

            else:
                if px <= cx:
                    continue
                offset = px

            if not (
                offset_min
                - door_offset_margin
                <= offset
                <= offset_max
                + door_offset_margin
            ):
                continue

            openings.append(
                {
                    "kind":
                        "door",

                    "center":
                        door[
                            "center"
                        ],

                    "direction":
                        door[
                            "direction"
                        ],

                    "width":
                        door[
                            "width"
                        ],

                    "source":
                        "door_detector",
                }
            )

        # Physical dedupe across the completed facade.
        cleaned = []

        for opening in sorted(
            openings,
            key=lambda item: (
                item["center"][0]
                if side in {
                    "bottom",
                    "top",
                }
                else item[
                    "center"
                ][1]
            ),
        ):
            duplicate = False

            for kept in cleaned:
                if (
                    kept["kind"]
                    != opening["kind"]
                ):
                    continue

                distance = math.hypot(
                    kept[
                        "center"
                    ][0]
                    -
                    opening[
                        "center"
                    ][0],

                    kept[
                        "center"
                    ][1]
                    -
                    opening[
                        "center"
                    ][1],
                )

                tolerance = max(
                    70.0,
                    min(
                        float(
                            kept.get(
                                "width",
                                reference_width,
                            )
                        ),
                        float(
                            opening.get(
                                "width",
                                reference_width,
                            )
                        ),
                    )
                    * 0.16,
                )

                if distance <= tolerance:
                    duplicate = True
                    break

            if not duplicate:
                cleaned.append(
                    opening
                )

        openings = cleaned

        if not openings:
            continue

        for opening in openings:
            px, py = opening[
                "center"
            ]

            opening["t"] = (
                px * direction[0]
                + py * direction[1]
            )

        openings.sort(
            key=lambda item:
                item["t"]
        )

        facade_window_widths = [
            item["width"]
            for item in openings
            if item["kind"]
            == "window"
        ]

        standard_window = (
            median(
                facade_window_widths
            )
            if facade_window_widths
            else reference_width
        )

        for item in openings:
            if (
                item["kind"]
                == "window"
                and item["width"]
                > standard_window * 1.60
            ):
                item[
                    "signature_kind"
                ] = "wide_window"
            else:
                item[
                    "signature_kind"
                ] = item["kind"]

        extent_min = min(
            item["t"]
            - item["width"]
            * 0.5
            for item in openings
        )

        extent_max = max(
            item["t"]
            + item["width"]
            * 0.5
            for item in openings
        )

        span = max(
            extent_max
            - extent_min,
            1.0,
        )

        for item in openings:
            item[
                "relative_center"
            ] = (
                item["t"]
                - extent_min
            ) / span

            item[
                "relative_width"
            ] = (
                item["width"]
                / span
            )

        if side in {
            "bottom",
            "top",
        }:
            anchor_x = median(
                [
                    item[
                        "center"
                    ][0]
                    for item in openings
                ]
            )

            if side == "bottom":
                anchor_y = (
                    min(
                        item[
                            "center"
                        ][1]
                        for item in openings
                    )
                    - 650.0
                )
            else:
                anchor_y = (
                    max(
                        item[
                            "center"
                        ][1]
                        for item in openings
                    )
                    + 650.0
                )

        else:
            anchor_y = median(
                [
                    item[
                        "center"
                    ][1]
                    for item in openings
                ]
            )

            if side == "left":
                anchor_x = (
                    min(
                        item[
                            "center"
                        ][0]
                        for item in openings
                    )
                    - 650.0
                )
            else:
                anchor_x = (
                    max(
                        item[
                            "center"
                        ][0]
                        for item in openings
                    )
                    + 650.0
                )

        result.append(
            {
                "side":
                    side,

                "anchor":
                    (
                        anchor_x,
                        anchor_y,
                    ),

                "expected_width":
                    float(
                        spec[
                            "expected_width"
                        ]
                    ),

                "openings":
                    openings,

                "signature": [
                    item[
                        "signature_kind"
                    ]
                    for item in openings
                ],

                "resolved_window_count":
                    sum(
                        1
                        for item in openings
                        if item["kind"]
                        == "window"
                    ),

                "resolved_door_count":
                    sum(
                        1
                        for item in openings
                        if item["kind"]
                        == "door"
                    ),
            }
        )

    return result

def _extract_axis_segments(
    geometry,
):
    horizontal = []
    vertical = []

    for item in geometry or []:
        layer = str(
            item.get(
                "layer",
                ""
            )
            or ""
        )

        if _is_detail_layer(
            layer
        ):
            continue

        points = [
            point
            for point in (
                _point(value)
                for value in item.get(
                    "points",
                    [],
                )
            )
            if point is not None
        ]

        if len(points) < 2:
            continue

        for a, b in zip(
            points,
            points[1:],
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

            if length <= 1.0e-6:
                continue

            if abs(dy) <= length * 0.025:
                horizontal.append(
                    {
                        "y":
                            (
                                a[1]
                                + b[1]
                            )
                            * 0.5,

                        "x0":
                            min(
                                a[0],
                                b[0],
                            ),

                        "x1":
                            max(
                                a[0],
                                b[0],
                            ),

                        "length":
                            length,
                    }
                )

            elif abs(dx) <= length * 0.025:
                vertical.append(
                    {
                        "x":
                            (
                                a[0]
                                + b[0]
                            )
                            * 0.5,

                        "y0":
                            min(
                                a[1],
                                b[1],
                            ),

                        "y1":
                            max(
                                a[1],
                                b[1],
                            ),

                        "length":
                            length,
                    }
                )

    return horizontal, vertical


# CAD3D_ELEVATION_ENTITY_BINDING_V7
def detect_elevation_openings(
    region,
):
    from cad._cad_to_3d_max_facade.elevation_opening_detector import (
        detect_elevation_openings
        as detect_physical_elevation_openings,
    )

    detection = (
        detect_physical_elevation_openings(
            region.get(
                "geometry",
                [],
            ),

            region.get(
                "bbox"
            ),
        )
    )

    region[
        "elevation_opening_detection"
    ] = detection

    return list(
        detection.get(
            "entities",
            [],
        )
        or []
    )

def _type_cost(
    a,
    b,
):
    if a == b:
        return 0.0

    if {
        a,
        b,
    } <= {
        "window",
        "wide_window",
    }:
        return 0.25

    return 8.0

def _alignment_cost(
    plan,
    facade,
    reverse=False,
):
    plan_openings = list(
        plan.get(
            "openings",
            [],
        )
        or []
    )

    raw_elevation = list(
        facade.get(
            "openings",
            [],
        )
        or []
    )

    if not plan_openings:
        return (
            1000000.0,
            [],
        )

    if len(
        raw_elevation
    ) < len(
        plan_openings
    ):
        return (
            1000000.0
            + (
                len(plan_openings)
                - len(raw_elevation)
            )
            * 1000.0,

            [],
        )

    elevation = []

    if reverse:
        for original_index in reversed(
            range(
                len(
                    raw_elevation
                )
            )
        ):
            item = dict(
                raw_elevation[
                    original_index
                ]
            )

            item[
                "_original_index"
            ] = original_index

            item[
                "_match_position"
            ] = (
                1.0
                - float(
                    item.get(
                        "relative_center",
                        0.0,
                    )
                )
            )

            elevation.append(
                item
            )

    else:
        for original_index, source in enumerate(
            raw_elevation
        ):
            item = dict(
                source
            )

            item[
                "_original_index"
            ] = original_index

            item[
                "_match_position"
            ] = float(
                item.get(
                    "relative_center",
                    0.0,
                )
            )

            elevation.append(
                item
            )

    n = len(
        plan_openings
    )

    m = len(
        elevation
    )

    inf = float(
        "inf"
    )

    dp = [
        [
            inf
            for _ in range(
                m + 1
            )
        ]
        for _ in range(
            n + 1
        )
    ]

    paths = [
        [
            None
            for _ in range(
                m + 1
            )
        ]
        for _ in range(
            n + 1
        )
    ]

    dp[0][0] = 0.0
    paths[0][0] = []

    skip_penalty = 0.12

    for i in range(
        n + 1
    ):
        for j in range(
            m
        ):
            current = dp[
                i
            ][j]

            if not math.isfinite(
                current
            ):
                continue

            # Skip a drawing-frame hypothesis.
            skip_cost = (
                current
                + skip_penalty
            )

            if (
                skip_cost
                < dp[i][
                    j + 1
                ]
            ):
                dp[i][
                    j + 1
                ] = skip_cost

                paths[i][
                    j + 1
                ] = list(
                    paths[i][j]
                    or []
                )

            if i >= n:
                continue

            plan_item = (
                plan_openings[
                    i
                ]
            )

            elevation_item = (
                elevation[
                    j
                ]
            )

            local_cost = (
                _type_cost(
                    plan_item.get(
                        "signature_kind",
                        plan_item.get(
                            "kind",
                            "",
                        ),
                    ),

                    elevation_item.get(
                        "signature_kind",
                        elevation_item.get(
                            "kind",
                            "",
                        ),
                    ),
                )
            )

            local_cost += (
                abs(
                    float(
                        plan_item.get(
                            "relative_center",
                            0.0,
                        )
                    )
                    -
                    float(
                        elevation_item[
                            "_match_position"
                        ]
                    )
                )
                * 12.0
            )

            plan_width = float(
                plan_item.get(
                    "relative_width",
                    0.0,
                )
                or 0.0
            )

            elevation_width = float(
                elevation_item.get(
                    "relative_width",
                    0.0,
                )
                or 0.0
            )

            if (
                plan_width > 0.0
                and elevation_width > 0.0
            ):
                local_cost += (
                    abs(
                        plan_width
                        - elevation_width
                    )
                    * 1.5
                )

            match_cost = (
                current
                + local_cost
            )

            if (
                match_cost
                < dp[
                    i + 1
                ][
                    j + 1
                ]
            ):
                dp[
                    i + 1
                ][
                    j + 1
                ] = (
                    match_cost
                )

                path = list(
                    paths[i][j]
                    or []
                )

                path.append(
                    (
                        i,
                        elevation_item[
                            "_original_index"
                        ],
                    )
                )

                paths[
                    i + 1
                ][
                    j + 1
                ] = path

    return (
        dp[n][m],
        paths[n][m]
        or [],
    )


def _match_cost(
    plan,
    facade,
    reverse=False,
):
    cost, _ = (
        _alignment_cost(
            plan,
            facade,
            reverse=reverse,
        )
    )

    return cost


# CAD3D_FRONT_REAR_DISCRIMINATOR_V8
def _entrance_evidence(openings):
    score = 0.0

    for item in openings or []:
        if item.get("kind") != "door":
            continue

        try:
            relative_width = float(
                item.get(
                    "relative_width",
                    0.0,
                )
                or 0.0
            )
        except Exception:
            relative_width = 0.0

        if (
            relative_width <= 0.0
            or relative_width <= 0.22
        ):
            score += 1.0
        else:
            score += 0.45

    return score


def _front_rear_swap_if_better(
    assignment,
    plan_facades,
    elevation_facades,
):
    assignment = list(
        assignment or []
    )

    if len(assignment) < 2:
        return assignment

    plan_rank = sorted(
        range(len(plan_facades)),
        key=lambda i: float(
            plan_facades[i].get(
                "expected_width",
                0.0,
            )
            or 0.0
        ),
        reverse=True,
    )

    elevation_rank = sorted(
        range(len(elevation_facades)),
        key=lambda i: (
            float(
                elevation_facades[i]
                .get(
                    "bbox",
                    (0.0, 0.0, 0.0, 0.0),
                )[2]
            )
            -
            float(
                elevation_facades[i]
                .get(
                    "bbox",
                    (0.0, 0.0, 0.0, 0.0),
                )[0]
            )
        ),
        reverse=True,
    )

    if (
        len(plan_rank) < 2
        or len(elevation_rank) < 2
    ):
        return assignment

    long_plans = set(
        plan_rank[:2]
    )

    long_elevations = set(
        elevation_rank[:2]
    )

    pairs = [
        (pos, pi, fi)
        for pos, (pi, fi)
        in enumerate(assignment)
        if (
            pi in long_plans
            and fi in long_elevations
        )
    ]

    if len(pairs) != 2:
        return assignment

    pos_a, plan_a, facade_a = pairs[0]
    pos_b, plan_b, facade_b = pairs[1]

    pa = _entrance_evidence(
        plan_facades[plan_a].get(
            "openings",
            [],
        )
    )

    pb = _entrance_evidence(
        plan_facades[plan_b].get(
            "openings",
            [],
        )
    )

    fa = _entrance_evidence(
        elevation_facades[facade_a].get(
            "openings",
            [],
        )
    )

    fb = _entrance_evidence(
        elevation_facades[facade_b].get(
            "openings",
            [],
        )
    )

    current_error = (
        abs(pa - fa)
        + abs(pb - fb)
    )

    swapped_error = (
        abs(pa - fb)
        + abs(pb - fa)
    )

    if (
        swapped_error + 0.25
        < current_error
    ):
        assignment[pos_a] = (
            plan_a,
            facade_b,
        )

        assignment[pos_b] = (
            plan_b,
            facade_a,
        )

    return assignment


def match_facades(
    plan_facades,
    elevation_facades,
):
    from itertools import (
        permutations,
    )

    plan_facades = list(
        plan_facades
        or []
    )

    elevation_facades = list(
        elevation_facades
        or []
    )

    if (
        not plan_facades
        or not elevation_facades
    ):
        return []

    plan_width_scale = max(
        [
            float(
                plan.get(
                    "expected_width",
                    1.0,
                )
                or 1.0
            )
            for plan in plan_facades
        ]
        or [1.0]
    )

    elevation_width_scale = max(
        [
            max(
                float(
                    facade.get(
                        "bbox",
                        (0.0, 0.0, 1.0, 1.0),
                    )[2]
                )
                -
                float(
                    facade.get(
                        "bbox",
                        (0.0, 0.0, 1.0, 1.0),
                    )[0]
                ),
                1.0,
            )
            for facade in elevation_facades
        ]
        or [1.0]
    )

    pair_results = {}

    for pi, plan in enumerate(
        plan_facades
    ):
        for fi, facade in enumerate(
            elevation_facades
        ):
            normal_cost, normal_path = (
                _alignment_cost(
                    plan,
                    facade,
                    reverse=False,
                )
            )

            reverse_cost, reverse_path = (
                _alignment_cost(
                    plan,
                    facade,
                    reverse=True,
                )
            )

            plan_width_norm = (
                float(
                    plan.get(
                        "expected_width",
                        1.0,
                    )
                    or 1.0
                )
                / max(
                    plan_width_scale,
                    1.0,
                )
            )

            facade_box = facade.get(
                "bbox",
                (0.0, 0.0, 1.0, 1.0),
            )

            facade_width_norm = (
                max(
                    float(
                        facade_box[2]
                    )
                    -
                    float(
                        facade_box[0]
                    ),
                    1.0,
                )
                / max(
                    elevation_width_scale,
                    1.0,
                )
            )

            width_family_cost = (
                abs(
                    plan_width_norm
                    -
                    facade_width_norm
                )
                * 90.0
            )

            normal_cost += (
                width_family_cost
            )

            reverse_cost += (
                width_family_cost
            )

            if reverse_cost < normal_cost:
                pair_results[
                    (pi, fi)
                ] = {
                    "cost":
                        reverse_cost,

                    "reversed":
                        True,

                    "path":
                        reverse_path,
                }
            else:
                pair_results[
                    (pi, fi)
                ] = {
                    "cost":
                        normal_cost,

                    "reversed":
                        False,

                    "path":
                        normal_path,
                }

    assignment = []

    plan_count = len(
        plan_facades
    )

    facade_count = len(
        elevation_facades
    )

    if (
        plan_count
        <= facade_count
        and plan_count <= 7
    ):
        best_total = None
        best_perm = None

        for perm in permutations(
            range(
                facade_count
            ),
            plan_count,
        ):
            total = 0.0

            for pi, fi in enumerate(
                perm
            ):
                total += pair_results[
                    (pi, fi)
                ][
                    "cost"
                ]

            if (
                best_total is None
                or total < best_total
            ):
                best_total = total
                best_perm = perm

        if best_perm is not None:
            assignment = [
                (
                    pi,
                    fi,
                )
                for pi, fi
                in enumerate(
                    best_perm
                )
            ]

    if not assignment:
        candidates = []

        for (
            pi,
            fi,
        ), result in pair_results.items():
            candidates.append(
                (
                    result[
                        "cost"
                    ],
                    pi,
                    fi,
                )
            )

        candidates.sort()

        used_plan = set()
        used_facade = set()

        for _, pi, fi in candidates:
            if pi in used_plan:
                continue

            if fi in used_facade:
                continue

            used_plan.add(pi)
            used_facade.add(fi)

            assignment.append(
                (
                    pi,
                    fi,
                )
            )

    assignment = _front_rear_swap_if_better(
        assignment,
        plan_facades,
        elevation_facades,
    )

    matches = []

    for pi, fi in assignment:
        plan = plan_facades[
            pi
        ]

        facade = elevation_facades[
            fi
        ]

        pair = pair_results[
            (pi, fi)
        ]

        opening_pairs = []

        for (
            plan_index,
            elevation_index,
        ) in pair["path"]:
            if not (
                0
                <= plan_index
                < len(
                    plan[
                        "openings"
                    ]
                )
            ):
                continue

            if not (
                0
                <= elevation_index
                < len(
                    facade[
                        "openings"
                    ]
                )
            ):
                continue

            plan_opening = (
                plan[
                    "openings"
                ][
                    plan_index
                ]
            )

            elevation_opening = (
                facade[
                    "openings"
                ][
                    elevation_index
                ]
            )

            opening_pairs.append(
                {
                    "plan_index":
                        plan_index,

                    "elevation_index":
                        elevation_index,

                    "kind":
                        plan_opening.get(
                            "kind"
                        ),

                    "plan_center":
                        plan_opening.get(
                            "center"
                        ),

                    "plan_width":
                        plan_opening.get(
                            "width"
                        ),

                    "elevation_bbox":
                        elevation_opening.get(
                            "bbox"
                        ),

                    "elevation_bottom_y":
                        elevation_opening.get(
                            "bottom_y"
                        ),

                    "elevation_top_y":
                        elevation_opening.get(
                            "top_y"
                        ),

                    "elevation_height":
                        elevation_opening.get(
                            "height"
                        ),
                }
            )

        matches.append(
            {
                "facade_number":
                    facade[
                        "facade_number"
                    ],

                "plan_side":
                    plan[
                        "side"
                    ],

                "plan_anchor":
                    plan[
                        "anchor"
                    ],

                "facade_anchor":
                    facade[
                        "anchor"
                    ],

                "plan_signature":
                    plan[
                        "signature"
                    ],

                "facade_hypothesis_count":
                    len(
                        facade[
                            "openings"
                        ]
                    ),

                "matched_opening_count":
                    len(
                        opening_pairs
                    ),

                "reversed":
                    pair[
                        "reversed"
                    ],

                "cost":
                    pair[
                        "cost"
                    ],

                "opening_pairs":
                    opening_pairs,
            }
        )

    matches.sort(
        key=lambda row:
            row[
                "facade_number"
            ]
    )

    return matches

def auto_analyse_dwg_facades(
    full_geometry,
):
    full_geometry = list(
        full_geometry
        or []
    )

    full_bounds = geometry_bounds(
        full_geometry
    )

    regions = detect_drawing_regions(
        full_geometry
    )

    main_plan = (
        choose_main_plan_region(
            regions
        )
    )

    if main_plan is None:
        return {
            "engine": ENGINE,
            "full_bounds": full_bounds,
            "regions": [],
            "main_plan": None,
            "plan_facades": [],
            "elevation_facades": [],
            "matches": [],
        }

    elevation_regions = (
        choose_elevation_regions(
            regions,
            main_plan,
        )
    )

    plan_facades = (
        build_plan_facades(
            main_plan
        )
    )

    elevation_facades = []

    for region in elevation_regions:
        openings = (
            detect_elevation_openings(
                region
            )
        )

        box = region[
            "bbox"
        ]

        width = (
            box[2]
            - box[0]
        )

        height = (
            box[3]
            - box[1]
        )

        facade = {
            "facade_number":
                region[
                    "facade_number"
                ],

            "region_id":
                region[
                    "region_id"
                ],

            "bbox":
                box,

            "anchor": (
                (
                    box[0]
                    + box[2]
                )
                * 0.5,

                box[1]
                - max(
                    height * 0.08,
                    450.0,
                ),
            ),

            "openings":
                openings,

            "signature": [
                opening[
                    "signature_kind"
                ]
                for opening in openings
            ],
        }

        elevation_facades.append(
            facade
        )

    matches = match_facades(
        plan_facades,
        elevation_facades,
    )

    region_diagnostics = []

    for region in regions:
        region_diagnostics.append(
            {
                "region_id":
                    region[
                        "region_id"
                    ],

                "bbox":
                    region[
                        "bbox"
                    ],

                "item_count":
                    region[
                        "item_count"
                    ],

                "semantic_count":
                    region[
                        "semantic_count"
                    ],

                "furniture_count":
                    region[
                        "furniture_count"
                    ],

                "hatch_count":
                    region[
                        "hatch_count"
                    ],

                "generic_count":
                    region[
                        "generic_count"
                    ],
            }
        )

    # CAD3D_MULTI_STOREY_FACADE_BINDING_V9
    _cad3d_facade_result = {
        "engine": ENGINE,
        "full_bounds": full_bounds,

        "regions":
            region_diagnostics,

        "main_plan": {
            "region_id":
                main_plan[
                    "region_id"
                ],

            "bbox":
                main_plan[
                    "bbox"
                ],

            "item_count":
                main_plan[
                    "item_count"
                ],

            "semantic_count":
                main_plan[
                    "semantic_count"
                ],

            "furniture_count":
                main_plan[
                    "furniture_count"
                ],
        },

        "plan_facades":
            plan_facades,

        "elevation_facades":
            elevation_facades,

        "matches":
            matches,
    }
    from cad._cad_to_3d_max_facade.multi_storey_facade_matcher import attach_multi_storey_plan_matches
    return attach_multi_storey_plan_matches(
        _cad3d_facade_result,
        regions,
    )


def self_test():
    plan = {
        "openings": [
            {
                "signature_kind": "window",
                "relative_center": 0.0,
            },
            {
                "signature_kind": "door",
                "relative_center": 0.5,
            },
            {
                "signature_kind": "window",
                "relative_center": 1.0,
            },
        ]
    }

    facade = {
        "openings": [
            {
                "signature_kind": "window",
                "relative_center": 0.0,
            },
            {
                "signature_kind": "door",
                "relative_center": 0.5,
            },
            {
                "signature_kind": "window",
                "relative_center": 1.0,
            },
        ]
    }

    assert (
        _match_cost(
            plan,
            facade,
            False,
        )
        < 0.001
    )

    print(
        "AUTO DWG FACADE REGION V4 SELF-TEST: OK"
    )


if __name__ == "__main__":
    self_test()
