from __future__ import annotations

import math
from collections import defaultdict
from statistics import median


ENGINE = "CAD3D_ELEVATION_OPENING_DETECTOR_V1"

# FINAL VERTICAL MEASUREMENT CONTRACT:
# Z=0 is ALWAYS the bottom line of the MAIN ENTRANCE DOOR.
# Drawing ground lines / level lines / provisional ground detection
# are never authoritative for final window vertical measurements.
GROUND_REFERENCE_RULE = "MAIN_ENTRANCE_DOOR_BOTTOM_V1"


# ============================================================
# BASIC GEOMETRY
# ============================================================

def _point(value):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
    ):
        try:
            return (
                float(value[0]),
                float(value[1]),
            )
        except Exception:
            return None

    return None


def _is_ignored_layer(layer):
    upper = str(
        layer or ""
    ).upper()

    return any(
        token in upper
        for token in (
            "HATCH",
            "DIM",
            "TEXT",
            "ANNOT",
            "TITLE",
        )
    )


def _extract_axis_segments(
    geometry,
):
    horizontal = []
    vertical = []

    for item in geometry or []:
        if not isinstance(
            item,
            dict,
        ):
            continue

        if _is_ignored_layer(
            item.get(
                "layer",
                "",
            )
        ):
            continue

        points = [
            p
            for p in (
                _point(value)
                for value in item.get(
                    "points",
                    [],
                )
                or []
            )
            if p is not None
        ]

        if len(points) < 2:
            continue

        for a, b in zip(
            points,
            points[1:],
        ):
            dx = b[0] - a[0]
            dy = b[1] - a[1]

            length = math.hypot(
                dx,
                dy,
            )

            if length <= 1.0e-6:
                continue

            # Almost-horizontal.
            if (
                abs(dy)
                <= length * 0.015
            ):
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
                    }
                )

            # Almost-vertical.
            elif (
                abs(dx)
                <= length * 0.015
            ):
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
                    }
                )

    return (
        horizontal,
        vertical,
    )


# ============================================================
# MERGE COLLINEAR CAD SEGMENTS
# ============================================================

def _merge_horizontal(
    lines,
    y_tolerance,
    gap_tolerance,
):
    groups = []

    for line in sorted(
        lines,
        key=lambda row:
            row["y"],
    ):
        target = None

        for group in groups:
            if (
                abs(
                    group["y"]
                    - line["y"]
                )
                <= y_tolerance
            ):
                target = group
                break

        if target is None:
            groups.append(
                {
                    "y":
                        line["y"],

                    "lines":
                        [line],
                }
            )
        else:
            target[
                "lines"
            ].append(
                line
            )

            target["y"] = (
                sum(
                    row["y"]
                    for row in target[
                        "lines"
                    ]
                )
                / len(
                    target[
                        "lines"
                    ]
                )
            )

    result = []

    for group in groups:
        intervals = sorted(
            (
                row["x0"],
                row["x1"],
            )
            for row in group[
                "lines"
            ]
        )

        start = None
        end = None

        for x0, x1 in intervals:
            if start is None:
                start = x0
                end = x1
                continue

            if (
                x0
                <= end
                + gap_tolerance
            ):
                end = max(
                    end,
                    x1,
                )

            else:
                result.append(
                    {
                        "y":
                            group["y"],

                        "x0":
                            start,

                        "x1":
                            end,
                    }
                )

                start = x0
                end = x1

        if start is not None:
            result.append(
                {
                    "y":
                        group["y"],

                    "x0":
                        start,

                    "x1":
                        end,
                }
            )

    return result


def _merge_vertical(
    lines,
    x_tolerance,
    gap_tolerance,
):
    groups = []

    for line in sorted(
        lines,
        key=lambda row:
            row["x"],
    ):
        target = None

        for group in groups:
            if (
                abs(
                    group["x"]
                    - line["x"]
                )
                <= x_tolerance
            ):
                target = group
                break

        if target is None:
            groups.append(
                {
                    "x":
                        line["x"],

                    "lines":
                        [line],
                }
            )
        else:
            target[
                "lines"
            ].append(
                line
            )

            target["x"] = (
                sum(
                    row["x"]
                    for row in target[
                        "lines"
                    ]
                )
                / len(
                    target[
                        "lines"
                    ]
                )
            )

    result = []

    for group in groups:
        intervals = sorted(
            (
                row["y0"],
                row["y1"],
            )
            for row in group[
                "lines"
            ]
        )

        start = None
        end = None

        for y0, y1 in intervals:
            if start is None:
                start = y0
                end = y1
                continue

            if (
                y0
                <= end
                + gap_tolerance
            ):
                end = max(
                    end,
                    y1,
                )

            else:
                result.append(
                    {
                        "x":
                            group["x"],

                        "y0":
                            start,

                        "y1":
                            end,
                    }
                )

                start = y0
                end = y1

        if start is not None:
            result.append(
                {
                    "x":
                        group["x"],

                    "y0":
                        start,

                    "y1":
                        end,
                }
            )

    return result


# ============================================================
# GROUND / FLOOR BASELINE
# ============================================================

def _detect_ground_line(
    horizontal,
    bounds,
):
    x0, y0, x1, y1 = bounds

    width = max(
        x1 - x0,
        1.0,
    )

    height = max(
        y1 - y0,
        1.0,
    )

    candidates = [
        line
        for line in horizontal
        if (
            line["x1"]
            - line["x0"]
        )
        >= width * 0.22
        and
        line["y"]
        <= y0
        + height * 0.27
    ]

    if not candidates:
        return y0

    # Prefer strong long lines close to bottom of the building,
    # but not simply the sheet's absolute lowest line.
    best = None
    best_score = None

    for line in candidates:
        coverage = (
            line["x1"]
            - line["x0"]
        ) / width

        relative_y = (
            line["y"]
            - y0
        ) / height

        score = (
            coverage * 3.0
            - relative_y * 0.35
        )

        if (
            best_score is None
            or score > best_score
        ):
            best_score = score
            best = line

    return float(
        best["y"]
    )


# ============================================================
# FRAME SUPPORT
# ============================================================

def _horizontal_coverage(
    horizontal,
    target_y,
    left_x,
    right_x,
    y_tolerance,
):
    width = max(
        right_x - left_x,
        1.0,
    )

    intervals = []

    for line in horizontal:
        if (
            abs(
                line["y"]
                - target_y
            )
            > y_tolerance
        ):
            continue

        start = max(
            left_x,
            line["x0"],
        )

        end = min(
            right_x,
            line["x1"],
        )

        if end > start:
            intervals.append(
                (
                    start,
                    end,
                )
            )

    if not intervals:
        return 0.0

    intervals.sort()

    merged = []

    for start, end in intervals:
        if (
            not merged
            or start
            > merged[-1][1]
        ):
            merged.append(
                [
                    start,
                    end,
                ]
            )
        else:
            merged[-1][1] = max(
                merged[-1][1],
                end,
            )

    covered = sum(
        end - start
        for start, end
        in merged
    )

    return min(
        1.0,
        covered / width,
    )


def _internal_structure_score(
    vertical,
    horizontal,
    bbox,
):
    x0, y0, x1, y1 = bbox

    inside_v = sum(
        1
        for line in vertical
        if (
            x0 < line["x"] < x1
            and
            line["y1"] >= y0
            and
            line["y0"] <= y1
        )
    )

    inside_h = sum(
        1
        for line in horizontal
        if (
            y0 < line["y"] < y1
            and
            line["x1"] >= x0
            and
            line["x0"] <= x1
        )
    )

    return min(
        4.0,
        math.log1p(
            inside_v
            + inside_h
        ),
    )


# ============================================================
# CANDIDATE FRAMES
# ============================================================

def _build_frame_candidates(
    horizontal,
    vertical,
    bounds,
    ground_y,
    all_storeys=False,
):
    rx0, ry0, rx1, ry1 = bounds

    width = max(
        rx1 - rx0,
        1.0,
    )

    height = max(
        ry1 - ry0,
        1.0,
    )

    y_tolerance = max(
        14.0,
        height * 0.006,
    )

    min_width = max(
        120.0,
        width * 0.012,
    )

    max_width = width * 0.285

    min_height = height * 0.055
    # Ground-floor doors are commonly taller than windows.
    # Do not reject them before door/window classification.
    max_height = height * 0.46

    ground_band_top = (
        ground_y
        + height * 0.40
    )

    # CAD3D_ELEVATION_ALL_STOREYS_V1
    #
    # Existing/default behavior remains ground-floor oriented.
    # The facade-window inspection mode may explicitly request
    # all storeys without changing any existing caller.
    usable_vertical = [
        line
        for line in vertical
        if (
            (
                line["y1"]
                - line["y0"]
            )
            >= min_height * 0.70
            and
            (
                bool(all_storeys)
                or line["y0"]
                <= ground_band_top
            )
        )
    ]

    usable_vertical.sort(
        key=lambda row:
            row["x"]
    )

    candidates = []

    for i, left in enumerate(
        usable_vertical
    ):
        for right in usable_vertical[
            i + 1:
        ]:
            frame_width = (
                right["x"]
                - left["x"]
            )

            if frame_width < min_width:
                continue

            if frame_width > max_width:
                break

            bottom_difference = abs(
                left["y0"]
                - right["y0"]
            )

            top_difference = abs(
                left["y1"]
                - right["y1"]
            )

            if (
                bottom_difference
                > y_tolerance * 2.0
                or
                top_difference
                > y_tolerance * 2.0
            ):
                continue

            bottom = (
                left["y0"]
                + right["y0"]
            ) * 0.5

            top = (
                left["y1"]
                + right["y1"]
            ) * 0.5

            frame_height = (
                top - bottom
            )

            if not (
                min_height
                <= frame_height
                <= max_height
            ):
                continue

            # Default detector behavior:
            # only ground-floor facade openings.
            #
            # Explicit facade-inspection mode:
            # allow upper-storey openings as well.
            if (
                not bool(all_storeys)
                and
                bottom
                > ground_y
                + height * 0.25
            ):
                continue

            bottom_support = (
                _horizontal_coverage(
                    horizontal,
                    bottom,
                    left["x"],
                    right["x"],
                    y_tolerance,
                )
            )

            top_support = (
                _horizontal_coverage(
                    horizontal,
                    top,
                    left["x"],
                    right["x"],
                    y_tolerance,
                )
            )

            if (
                bottom_support < 0.45
                or
                top_support < 0.45
            ):
                continue

            aspect = (
                frame_width
                / max(
                    frame_height,
                    1.0,
                )
            )

            if not (
                0.12
                <= aspect
                <= 4.5
            ):
                continue

            bbox = (
                left["x"],
                bottom,
                right["x"],
                top,
            )

            internal_score = (
                _internal_structure_score(
                    vertical,
                    horizontal,
                    bbox,
                )
            )

            score = (
                bottom_support * 2.0
                + top_support * 2.0
                + internal_score * 0.55
            )

            # Mild preference for a complete outer frame rather
            # than tiny pane rectangles.
            width_fraction = (
                frame_width
                / width
            )

            if (
                0.025
                <= width_fraction
                <= 0.16
            ):
                score += 0.75

            candidates.append(
                {
                    "bbox":
                        bbox,

                    "center": (
                        (
                            left["x"]
                            + right["x"]
                        )
                        * 0.5,

                        (
                            bottom
                            + top
                        )
                        * 0.5,
                    ),

                    "width":
                        frame_width,

                    "height":
                        frame_height,

                    "bottom_y":
                        bottom,

                    "top_y":
                        top,

                    "score":
                        score,

                    "bottom_support":
                        bottom_support,

                    "top_support":
                        top_support,
                }
            )

    return candidates


# ============================================================
# DEDUPE NESTED FRAME CANDIDATES
# ============================================================

def _same_opening_family(
    a,
    b,
    region_width,
    region_height,
):
    ax, ay = a["center"]
    bx, by = b["center"]

    center_tol_x = max(
        region_width * 0.018,
        min(
            a["width"],
            b["width"],
        )
        * 0.40,
    )

    center_tol_y = max(
        region_height * 0.018,
        min(
            a["height"],
            b["height"],
        )
        * 0.18,
    )

    return (
        abs(ax - bx)
        <= center_tol_x
        and
        abs(ay - by)
        <= center_tol_y
    )


def _resolve_nested_frames(
    candidates,
    bounds,
):
    rx0, ry0, rx1, ry1 = bounds

    region_width = max(
        rx1 - rx0,
        1.0,
    )

    region_height = max(
        ry1 - ry0,
        1.0,
    )

    ordered = sorted(
        candidates,
        key=lambda row: (
            -row["score"],
            -row["width"],
        ),
    )

    families = []

    for candidate in ordered:
        target = None

        for family in families:
            if any(
                _same_opening_family(
                    candidate,
                    member,
                    region_width,
                    region_height,
                )
                for member in family
            ):
                target = family
                break

        if target is None:
            families.append(
                [candidate]
            )
        else:
            target.append(
                candidate
            )

    resolved = []

    for family in families:
        # Prefer the strongest outer structural frame.
        best = max(
            family,
            key=lambda row: (
                row["score"]
                + min(
                    row["width"]
                    / region_width,
                    0.15,
                )
                * 4.0,
                row["width"],
            ),
        )

        resolved.append(
            dict(best)
        )

    return resolved


# ============================================================
# REMOVE OVERLAPPING FALSE COMBINATIONS
# ============================================================

def _interval_overlap(
    a,
    b,
):
    left = max(
        a["bbox"][0],
        b["bbox"][0],
    )

    right = min(
        a["bbox"][2],
        b["bbox"][2],
    )

    if right <= left:
        return 0.0

    overlap = (
        right - left
    )

    smaller = min(
        a["width"],
        b["width"],
    )

    return (
        overlap
        / max(
            smaller,
            1.0,
        )
    )


def _select_non_overlapping(
    candidates,
):
    selected = []

    for candidate in sorted(
        candidates,
        key=lambda row: (
            -row["score"],
            -row["width"],
        ),
    ):
        conflict = False

        for kept in selected:
            if (
                _interval_overlap(
                    candidate,
                    kept,
                )
                > 0.42
            ):
                conflict = True
                break

        if not conflict:
            selected.append(
                candidate
            )

    selected.sort(
        key=lambda row:
            row["center"][0]
    )

    return selected


# ============================================================
# ENTITY CLASSIFICATION
# ============================================================

def _classify_entities(
    openings,
    bounds,
    ground_y,
):
    rx0, ry0, rx1, ry1 = bounds

    region_height = max(
        ry1 - ry0,
        1.0,
    )

    if not openings:
        return []

    heights = [
        row["height"]
        for row in openings
    ]

    median_height = max(
        median(heights),
        1.0,
    )

    entities = []

    for index, row in enumerate(
        openings,
        start=1,
    ):
        distance_from_ground = (
            row["bottom_y"]
            - ground_y
        )

        near_ground = (
            distance_from_ground
            <= region_height * 0.045
        )

        tall = (
            row["height"]
            >= max(
                median_height * 1.22,
                region_height * 0.17,
            )
        )

        kind = (
            "door"
            if (
                near_ground
                and tall
            )
            else "window"
        )

        entity = dict(
            row
        )

        entity[
            "entity_id"
        ] = (
            (
                "D"
                if kind == "door"
                else "W"
            )
            + str(index).zfill(2)
        )

        entity["kind"] = kind

        entity[
            "left_jamb_x"
        ] = row["bbox"][0]

        entity[
            "right_jamb_x"
        ] = row["bbox"][2]

        # Preserve raw elevation coordinates.
        # Final Z values are deliberately unresolved here.
        # They may ONLY be resolved from the main entrance
        # door bottom line.
        entity[
            "drawing_bottom_y"
        ] = float(
            row["bottom_y"]
        )

        entity[
            "drawing_top_y"
        ] = float(
            row["top_y"]
        )

        entity[
            "window_height"
        ] = (
            float(
                row["top_y"]
            )
            -
            float(
                row["bottom_y"]
            )
        )

        entity[
            "window_bottom_z"
        ] = None

        entity[
            "window_top_z"
        ] = None

        entity[
            "ground_reference_y"
        ] = None

        entity[
            "ground_reference_rule"
        ] = GROUND_REFERENCE_RULE

        entities.append(
            entity
        )

    # Re-number after classification.
    door_index = 0
    window_index = 0

    for entity in entities:
        if entity["kind"] == "door":
            door_index += 1

            entity[
                "entity_id"
            ] = (
                "D"
                + str(
                    door_index
                ).zfill(2)
            )

        else:
            window_index += 1

            entity[
                "entity_id"
            ] = (
                "W"
                + str(
                    window_index
                ).zfill(2)
            )

    return entities


# ============================================================
# AUTHORITATIVE VERTICAL MEASUREMENT RULE
# ============================================================

def apply_main_entrance_ground_reference(
    entities,
    main_entrance_bottom_y,
):
    """
    Resolve final elevation Z values.

    HARD RULE:
        Z=0 = bottom line of main entrance door.

    No detected ground line, level line or facade baseline
    is permitted as a substitute.
    """

    if main_entrance_bottom_y is None:
        raise ValueError(
            "MAIN_ENTRANCE_DOOR_BOTTOM_REQUIRED"
        )

    reference_y = float(
        main_entrance_bottom_y
    )

    resolved = []

    for source in entities or []:
        entity = dict(
            source
        )

        bottom_y = entity.get(
            "drawing_bottom_y",
            entity.get(
                "bottom_y"
            ),
        )

        top_y = entity.get(
            "drawing_top_y",
            entity.get(
                "top_y"
            ),
        )

        if (
            bottom_y is None
            or top_y is None
        ):
            raise ValueError(
                "ELEVATION_ENTITY_VERTICAL_BOUNDS_REQUIRED"
            )

        bottom_y = float(
            bottom_y
        )

        top_y = float(
            top_y
        )

        entity[
            "ground_reference_y"
        ] = reference_y

        entity[
            "ground_reference_rule"
        ] = GROUND_REFERENCE_RULE

        entity[
            "window_bottom_z"
        ] = (
            bottom_y
            - reference_y
        )

        entity[
            "window_top_z"
        ] = (
            top_y
            - reference_y
        )

        entity[
            "window_height"
        ] = (
            top_y
            - bottom_y
        )

        resolved.append(
            entity
        )

    return resolved



# ============================================================
# NORMALIZED SEQUENCE DATA
# ============================================================


# ============================================================
# CAD3D_WINDOW_FRAME_VALIDATION_V1
#
# GENERAL RULE:
#
# A projecting sill is NOT part of the window frame bbox.
#
# Every detected window is checked independently.
#
# The algorithm searches only relative to that window's own
# width and height. No project-specific architectural size is
# used.
# ============================================================

def _validate_window_frame_bottoms(
    entities,
    horizontal,
    bounds,
):
    if not entities:
        return []

    result = []

    for source in entities:

        entity = dict(
            source
        )

        if (
            str(
                entity.get(
                    "kind",
                    "",
                )
                or ""
            ).strip().lower()
            != "window"
        ):
            result.append(
                entity
            )

            continue

        bbox = entity.get(
            "bbox"
        )

        if (
            not isinstance(
                bbox,
                (list, tuple),
            )
            or len(bbox) != 4
        ):
            entity[
                "frame_validation"
            ] = "INVALID_BBOX"

            result.append(
                entity
            )

            continue

        try:
            (
                x0,
                bottom,
                x1,
                top,
            ) = (
                float(value)
                for value in bbox
            )

        except Exception:
            entity[
                "frame_validation"
            ] = "INVALID_BBOX"

            result.append(
                entity
            )

            continue

        width = max(
            x1 - x0,
            1.0e-9,
        )

        height = max(
            top - bottom,
            1.0e-9,
        )

        raw_bottom = float(
            bottom
        )

        # ----------------------------------------------------
        # Search band around the current lower window boundary.
        #
        # This allows both cases:
        #
        # A) bbox is already correct:
        #
        #       FRAME BOTTOM
        #       ----------
        #      ------------
        #         SILL
        #
        # B) bbox incorrectly reaches into the sill:
        #
        #       REAL FRAME BOTTOM
        #       ----------
        #
        #      ------------
        #      CURRENT BBOX BOTTOM
        # ----------------------------------------------------

        band_low = (
            bottom
            - height * 0.20
        )

        band_high = (
            bottom
            + height * 0.20
        )

        projecting_lines = []

        for line in horizontal or []:

            try:
                line_y = float(
                    line["y"]
                )

                line_x0 = float(
                    line["x0"]
                )

                line_x1 = float(
                    line["x1"]
                )

            except Exception:
                continue

            if not (
                band_low
                <= line_y
                <= band_high
            ):
                continue

            line_length = max(
                line_x1 - line_x0,
                0.0,
            )

            overlap = max(
                0.0,
                min(
                    x1,
                    line_x1,
                )
                - max(
                    x0,
                    line_x0,
                ),
            )

            overlap_ratio = (
                overlap / width
            )

            if overlap_ratio < 0.72:
                continue

            length_ratio = (
                line_length
                / width
            )

            # Very long facade/cladding lines are NOT sills.
            if not (
                1.025
                <= length_ratio
                <= 1.85
            ):
                continue

            left_projection = max(
                0.0,
                x0 - line_x0,
            ) / width

            right_projection = max(
                0.0,
                line_x1 - x1,
            ) / width

            # A true projecting sill normally leaves the frame
            # on both sides.
            if (
                left_projection < 0.007
                or
                right_projection < 0.007
            ):
                continue

            projecting_lines.append(
                {
                    "y":
                        line_y,

                    "x0":
                        line_x0,

                    "x1":
                        line_x1,

                    "length_ratio":
                        length_ratio,

                    "left_projection":
                        left_projection,

                    "right_projection":
                        right_projection,
                }
            )


        # ----------------------------------------------------
        # No projecting sill evidence:
        # preserve detector result exactly.
        # ----------------------------------------------------

        if not projecting_lines:

            entity[
                "raw_frame_bottom_y"
            ] = raw_bottom

            entity[
                "frame_bottom_y"
            ] = raw_bottom

            entity[
                "sill_top_y"
            ] = None

            entity[
                "sill_bottom_y"
            ] = None

            entity[
                "frame_refined"
            ] = False

            entity[
                "frame_validation"
            ] = (
                "FRAME_ACCEPTED_NO_PROJECTING_SILL"
            )

            result.append(
                entity
            )

            continue


        sill_top_y = max(
            row["y"]
            for row in projecting_lines
        )

        sill_bottom_y = min(
            row["y"]
            for row in projecting_lines
        )


        # ----------------------------------------------------
        # Find the first frame-like horizontal immediately
        # ABOVE the projecting sill.
        #
        # We deliberately choose the nearest valid structural
        # line, rather than the highest line. This prevents
        # inner sash / glazing bars from becoming the new
        # window bottom.
        # ----------------------------------------------------

        min_step = (
            height * 0.006
        )

        max_step = (
            height * 0.20
        )

        frame_candidates = []

        for line in horizontal or []:

            try:
                line_y = float(
                    line["y"]
                )

                line_x0 = float(
                    line["x0"]
                )

                line_x1 = float(
                    line["x1"]
                )

            except Exception:
                continue

            if line_y <= (
                sill_top_y
                + min_step
            ):
                continue

            if line_y > (
                sill_top_y
                + max_step
            ):
                continue

            line_length = max(
                line_x1 - line_x0,
                0.0,
            )

            overlap = max(
                0.0,
                min(
                    x1,
                    line_x1,
                )
                - max(
                    x0,
                    line_x0,
                ),
            )

            overlap_ratio = (
                overlap / width
            )

            if overlap_ratio < 0.72:
                continue

            length_ratio = (
                line_length
                / width
            )

            # Frame-bottom lines should approximately belong
            # to the window itself, not the facade.
            if not (
                0.68
                <= length_ratio
                <= 1.25
            ):
                continue

            left_projection = max(
                0.0,
                x0 - line_x0,
            ) / width

            right_projection = max(
                0.0,
                line_x1 - x1,
            ) / width

            # Reject another projecting sill/ledge.
            if (
                left_projection >= 0.007
                and
                right_projection >= 0.007
                and
                length_ratio > 1.025
            ):
                continue

            edge_error = (
                abs(
                    line_x0 - x0
                )
                +
                abs(
                    line_x1 - x1
                )
            ) / width

            frame_candidates.append(
                {
                    "y":
                        line_y,

                    "edge_error":
                        edge_error,

                    "overlap_ratio":
                        overlap_ratio,
                }
            )


        frame_candidates.sort(
            key=lambda row: (
                row["y"],
                row["edge_error"],
                -row[
                    "overlap_ratio"
                ],
            )
        )


        # ----------------------------------------------------
        # Decide whether current bbox actually needs trimming.
        # ----------------------------------------------------

        sill_zone_tolerance = (
            height * 0.015
        )

        current_bottom_inside_sill = (
            raw_bottom
            <= (
                sill_top_y
                + sill_zone_tolerance
            )
        )

        new_bottom = (
            raw_bottom
        )

        refined = False

        if (
            current_bottom_inside_sill
            and frame_candidates
        ):
            candidate_bottom = float(
                frame_candidates[0][
                    "y"
                ]
            )

            if (
                candidate_bottom
                > raw_bottom
                + height * 0.006
                and
                candidate_bottom
                < top
            ):
                new_bottom = (
                    candidate_bottom
                )

                refined = True


        # ----------------------------------------------------
        # Update complete entity consistently.
        # ----------------------------------------------------

        entity[
            "raw_frame_bottom_y"
        ] = raw_bottom

        entity[
            "frame_bottom_y"
        ] = float(
            new_bottom
        )

        entity[
            "sill_top_y"
        ] = float(
            sill_top_y
        )

        entity[
            "sill_bottom_y"
        ] = float(
            sill_bottom_y
        )

        entity[
            "frame_refined"
        ] = bool(
            refined
        )

        if refined:

            entity[
                "frame_validation"
            ] = (
                "FRAME_BOTTOM_REFINED_FROM_PROJECTING_SILL"
            )

            entity["bbox"] = (
                x0,
                new_bottom,
                x1,
                top,
            )

            entity[
                "bottom_y"
            ] = float(
                new_bottom
            )

            entity[
                "drawing_bottom_y"
            ] = float(
                new_bottom
            )

            entity[
                "height"
            ] = float(
                top - new_bottom
            )

            entity[
                "window_height"
            ] = float(
                top - new_bottom
            )

            old_center = entity.get(
                "center"
            )

            if (
                isinstance(
                    old_center,
                    (list, tuple),
                )
                and len(
                    old_center
                ) >= 2
            ):
                entity[
                    "center"
                ] = (
                    float(
                        old_center[0]
                    ),
                    (
                        new_bottom
                        + top
                    )
                    * 0.5,
                )

        else:

            entity[
                "frame_validation"
            ] = (
                "FRAME_ACCEPTED_SILL_BELOW"
            )


        result.append(
            entity
        )

    return result


def _normalize_entities(
    entities,
):
    if not entities:
        return []

    min_x = min(
        row["bbox"][0]
        for row in entities
    )

    max_x = max(
        row["bbox"][2]
        for row in entities
    )

    span = max(
        max_x - min_x,
        1.0,
    )

    window_widths = [
        row["width"]
        for row in entities
        if row["kind"]
        == "window"
    ]

    typical_window = (
        median(
            window_widths
        )
        if window_widths
        else 0.0
    )

    for entity in entities:
        entity[
            "relative_center"
        ] = (
            entity["center"][0]
            - min_x
        ) / span

        entity[
            "relative_width"
        ] = (
            entity["width"]
            / span
        )

        if (
            entity["kind"]
            == "window"
            and typical_window > 0.0
            and entity["width"]
            > typical_window * 1.65
        ):
            entity[
                "signature_kind"
            ] = "wide_window"

        else:
            entity[
                "signature_kind"
            ] = entity[
                "kind"
            ]

    return entities


# ============================================================
# PUBLIC DETECTOR
# ============================================================


# ============================================================
# CAD3D_STRUCTURAL_ELEVATION_WINDOW_RESOLVER_V1
#
# GENERAL ARCHITECTURAL RULE
#
# Same philosophy as the proven door resolver:
#
# candidate
#   -> left/right structural jamb verification
#   -> top/bottom cap verification
#   -> internal sash/mullion/transom evidence
#   -> projecting sill rejection
#   -> nested-frame resolution
#   -> physical-opening de-duplication
#
# No facade number, no absolute window size and no coordinates
# from a particular project are used here.
# ============================================================


def _structural_window_cap_evidence(
    horizontal,
    x0,
    x1,
    target_y,
    width,
    height,
):
    y_tolerance = max(
        height * 0.020,
        1.0e-9,
    )

    rows = []

    for line in horizontal or []:

        try:
            y = float(
                line["y"]
            )

            lx0 = float(
                line["x0"]
            )

            lx1 = float(
                line["x1"]
            )

        except Exception:
            continue

        if abs(
            y - target_y
        ) > y_tolerance:
            continue

        length = max(
            lx1 - lx0,
            0.0,
        )

        if length <= 1.0e-9:
            continue

        overlap = max(
            0.0,
            min(
                x1,
                lx1,
            )
            - max(
                x0,
                lx0,
            ),
        )

        overlap_ratio = (
            overlap
            / max(
                width,
                1.0e-9,
            )
        )

        if overlap_ratio < 0.68:
            continue

        length_ratio = (
            length
            / max(
                width,
                1.0e-9,
            )
        )

        left_error = abs(
            lx0 - x0
        ) / width

        right_error = abs(
            lx1 - x1
        ) / width

        endpoint_error = (
            left_error
            + right_error
        )

        left_projection = max(
            0.0,
            x0 - lx0,
        ) / width

        right_projection = max(
            0.0,
            lx1 - x1,
        ) / width

        projecting = (
            length_ratio > 1.045
            and
            left_projection > 0.012
            and
            right_projection > 0.012
        )

        aligned = (
            endpoint_error <= 0.32
            and
            0.68
            <= length_ratio
            <= 1.38
        )

        rows.append(
            {
                "y":
                    y,

                "x0":
                    lx0,

                "x1":
                    lx1,

                "overlap_ratio":
                    overlap_ratio,

                "length_ratio":
                    length_ratio,

                "endpoint_error":
                    endpoint_error,

                "projecting":
                    bool(
                        projecting
                    ),

                "aligned":
                    bool(
                        aligned
                    ),
            }
        )

    if not rows:
        return None

    rows.sort(
        key=lambda row: (
            not row["aligned"],
            row["projecting"],
            row["endpoint_error"],
            -row["overlap_ratio"],
        )
    )

    return rows[0]


def _structural_window_jamb_evidence(
    vertical,
    target_x,
    y0,
    y1,
    width,
    height,
):
    x_tolerance = max(
        width * 0.025,
        1.0e-9,
    )

    best = 0.0

    for line in vertical or []:

        try:
            x = float(
                line["x"]
            )

            ly0 = float(
                line["y0"]
            )

            ly1 = float(
                line["y1"]
            )

        except Exception:
            continue

        if abs(
            x - target_x
        ) > x_tolerance:
            continue

        overlap = max(
            0.0,
            min(
                y1,
                ly1,
            )
            - max(
                y0,
                ly0,
            ),
        )

        ratio = (
            overlap
            / max(
                height,
                1.0e-9,
            )
        )

        best = max(
            best,
            ratio,
        )

    return min(
        1.0,
        best,
    )


def _structural_window_internal_evidence(
    horizontal,
    vertical,
    bbox,
):
    x0, y0, x1, y1 = (
        float(value)
        for value in bbox
    )

    width = max(
        x1 - x0,
        1.0e-9,
    )

    height = max(
        y1 - y0,
        1.0e-9,
    )

    inner_vertical = []

    for line in vertical or []:

        try:
            x = float(
                line["x"]
            )

            ly0 = float(
                line["y0"]
            )

            ly1 = float(
                line["y1"]
            )

        except Exception:
            continue

        if not (
            x0 + width * 0.07
            < x
            < x1 - width * 0.07
        ):
            continue

        overlap = max(
            0.0,
            min(
                y1,
                ly1,
            )
            - max(
                y0,
                ly0,
            ),
        )

        overlap_ratio = (
            overlap / height
        )

        source_length = max(
            ly1 - ly0,
            1.0e-9,
        )

        # A mullion/sash member should belong mostly to this
        # opening instead of running through the entire facade.
        if (
            overlap_ratio >= 0.28
            and
            source_length <= height * 1.30
        ):
            inner_vertical.append(
                {
                    "x":
                        x,

                    "coverage":
                        overlap_ratio,
                }
            )


    inner_horizontal = []

    for line in horizontal or []:

        try:
            y = float(
                line["y"]
            )

            lx0 = float(
                line["x0"]
            )

            lx1 = float(
                line["x1"]
            )

        except Exception:
            continue

        if not (
            y0 + height * 0.08
            < y
            < y1 - height * 0.08
        ):
            continue

        length = max(
            lx1 - lx0,
            1.0e-9,
        )

        overlap = max(
            0.0,
            min(
                x1,
                lx1,
            )
            - max(
                x0,
                lx0,
            ),
        )

        overlap_ratio = (
            overlap / width
        )

        # Siding/cladding lines are normally much longer than
        # the window. Reject them as transom evidence.
        if (
            overlap_ratio >= 0.42
            and
            length <= width * 1.28
        ):
            inner_horizontal.append(
                {
                    "y":
                        y,

                    "coverage":
                        overlap_ratio,
                }
            )

    return {
        "vertical_count":
            len(
                inner_vertical
            ),

        "horizontal_count":
            len(
                inner_horizontal
            ),

        "vertical":
            inner_vertical,

        "horizontal":
            inner_horizontal,
    }


def _structural_window_nested_count(
    candidate,
    candidates,
):
    x0, y0, x1, y1 = (
        float(value)
        for value in candidate[
            "bbox"
        ]
    )

    width = max(
        x1 - x0,
        1.0e-9,
    )

    height = max(
        y1 - y0,
        1.0e-9,
    )

    area = (
        width * height
    )

    count = 0

    for other in candidates or []:

        if other is candidate:
            continue

        try:
            ox0, oy0, ox1, oy1 = (
                float(value)
                for value in other[
                    "bbox"
                ]
            )

        except Exception:
            continue

        other_width = max(
            ox1 - ox0,
            0.0,
        )

        other_height = max(
            oy1 - oy0,
            0.0,
        )

        other_area = (
            other_width
            * other_height
        )

        if (
            other_area <= 0.0
            or area <= 0.0
        ):
            continue

        area_ratio = (
            other_area / area
        )

        if not (
            0.055
            <= area_ratio
            <= 0.88
        ):
            continue

        margin_x = (
            width * 0.008
        )

        margin_y = (
            height * 0.008
        )

        contained = (
            ox0
            >= x0 + margin_x
            and
            ox1
            <= x1 - margin_x
            and
            oy0
            >= y0 + margin_y
            and
            oy1
            <= y1 - margin_y
        )

        if contained:
            count += 1

    return count


def _structural_window_signature(
    candidate,
    candidates,
    horizontal,
    vertical,
):
    x0, y0, x1, y1 = (
        float(value)
        for value in candidate[
            "bbox"
        ]
    )

    width = max(
        x1 - x0,
        1.0e-9,
    )

    height = max(
        y1 - y0,
        1.0e-9,
    )


    left_jamb = (
        _structural_window_jamb_evidence(
            vertical,
            x0,
            y0,
            y1,
            width,
            height,
        )
    )

    right_jamb = (
        _structural_window_jamb_evidence(
            vertical,
            x1,
            y0,
            y1,
            width,
            height,
        )
    )


    bottom_cap = (
        _structural_window_cap_evidence(
            horizontal,
            x0,
            x1,
            y0,
            width,
            height,
        )
    )

    top_cap = (
        _structural_window_cap_evidence(
            horizontal,
            x0,
            x1,
            y1,
            width,
            height,
        )
    )


    internal = (
        _structural_window_internal_evidence(
            horizontal,
            vertical,
            (
                x0,
                y0,
                x1,
                y1,
            ),
        )
    )


    nested_count = (
        _structural_window_nested_count(
            candidate,
            candidates,
        )
    )


    score = 0.0

    score += (
        left_jamb * 1.65
    )

    score += (
        right_jamb * 1.65
    )


    if (
        bottom_cap is not None
        and bottom_cap["aligned"]
    ):
        score += 1.80

        score += (
            min(
                1.0,
                bottom_cap[
                    "overlap_ratio"
                ],
            )
            * 0.40
        )


    if (
        top_cap is not None
        and top_cap["aligned"]
    ):
        score += 1.80

        score += (
            min(
                1.0,
                top_cap[
                    "overlap_ratio"
                ],
            )
            * 0.40
        )


    # Window-specific internal structure.
    score += (
        min(
            3,
            internal[
                "vertical_count"
            ],
        )
        * 0.55
    )

    score += (
        min(
            3,
            internal[
                "horizontal_count"
            ],
        )
        * 0.45
    )


    # Outer window frames generally contain an inner sash /
    # glazing frame. This is strong but capped evidence.
    score += (
        min(
            4,
            nested_count,
        )
        * 0.55
    )


    # The line below a window may be a projecting sill.
    # A sill must not win as the physical frame bottom.
    projecting_sill = bool(
        bottom_cap is not None
        and bottom_cap[
            "projecting"
        ]
    )

    if projecting_sill:
        score -= 3.25


    # Existing geometric score remains only weak supporting
    # evidence, never the primary decision.
    try:
        legacy_score = float(
            candidate.get(
                "score",
                0.0,
            )
            or 0.0
        )

    except Exception:
        legacy_score = 0.0

    score += min(
        1.0,
        max(
            0.0,
            legacy_score
            * 0.08,
        ),
    )


    hard_frame = (
        left_jamb >= 0.58
        and
        right_jamb >= 0.58
        and
        bottom_cap is not None
        and
        top_cap is not None
        and
        bottom_cap[
            "aligned"
        ]
        and
        top_cap[
            "aligned"
        ]
        and
        not projecting_sill
    )


    internal_strength = (
        internal[
            "vertical_count"
        ]
        +
        internal[
            "horizontal_count"
        ]
        +
        min(
            nested_count,
            3,
        )
    )


    accepted = (
        hard_frame
        and
        internal_strength >= 1
        and
        score >= 6.20
    )


    result = dict(
        candidate
    )

    result[
        "structural_window_score"
    ] = float(
        score
    )

    result[
        "structural_window_accepted"
    ] = bool(
        accepted
    )

    result[
        "structural_left_jamb_coverage"
    ] = float(
        left_jamb
    )

    result[
        "structural_right_jamb_coverage"
    ] = float(
        right_jamb
    )

    result[
        "structural_bottom_cap"
    ] = bottom_cap

    result[
        "structural_top_cap"
    ] = top_cap

    result[
        "structural_internal_vertical_count"
    ] = int(
        internal[
            "vertical_count"
        ]
    )

    result[
        "structural_internal_horizontal_count"
    ] = int(
        internal[
            "horizontal_count"
        ]
    )

    result[
        "structural_nested_frame_count"
    ] = int(
        nested_count
    )

    result[
        "structural_projecting_sill"
    ] = bool(
        projecting_sill
    )

    return result


def _structural_bbox_relation(
    a,
    b,
):
    ax0, ay0, ax1, ay1 = (
        float(value)
        for value in a[
            "bbox"
        ]
    )

    bx0, by0, bx1, by1 = (
        float(value)
        for value in b[
            "bbox"
        ]
    )

    aw = max(
        ax1 - ax0,
        0.0,
    )

    ah = max(
        ay1 - ay0,
        0.0,
    )

    bw = max(
        bx1 - bx0,
        0.0,
    )

    bh = max(
        by1 - by0,
        0.0,
    )

    area_a = (
        aw * ah
    )

    area_b = (
        bw * bh
    )

    ix0 = max(
        ax0,
        bx0,
    )

    iy0 = max(
        ay0,
        by0,
    )

    ix1 = min(
        ax1,
        bx1,
    )

    iy1 = min(
        ay1,
        by1,
    )

    intersection = (
        max(
            0.0,
            ix1 - ix0,
        )
        *
        max(
            0.0,
            iy1 - iy0,
        )
    )

    union = (
        area_a
        + area_b
        - intersection
    )

    iou = (
        intersection / union
        if union > 1.0e-9
        else 0.0
    )

    smaller = min(
        area_a,
        area_b,
    )

    containment = (
        intersection / smaller
        if smaller > 1.0e-9
        else 0.0
    )

    acx = (
        ax0 + ax1
    ) * 0.5

    acy = (
        ay0 + ay1
    ) * 0.5

    bcx = (
        bx0 + bx1
    ) * 0.5

    bcy = (
        by0 + by1
    ) * 0.5

    center_dx = abs(
        acx - bcx
    ) / max(
        min(
            aw,
            bw,
        ),
        1.0e-9,
    )

    center_dy = abs(
        acy - bcy
    ) / max(
        min(
            ah,
            bh,
        ),
        1.0e-9,
    )

    return {
        "iou":
            iou,

        "containment":
            containment,

        "center_dx":
            center_dx,

        "center_dy":
            center_dy,
    }


def _same_structural_window(
    a,
    b,
):
    relation = (
        _structural_bbox_relation(
            a,
            b,
        )
    )

    if relation[
        "iou"
    ] >= 0.34:
        return True

    if (
        relation[
            "containment"
        ] >= 0.74
        and
        relation[
            "center_dx"
        ] <= 0.48
        and
        relation[
            "center_dy"
        ] <= 0.42
    ):
        return True

    return False


def _resolve_structural_windows(
    candidates,
    horizontal,
    vertical,
):
    """
    CAD3D_COMMON_OUTER_WINDOW_FRAME_V3

    GENERAL ARCHITECTURAL RULE:

    1. Detect strong window cores.
    2. Collapse nested duplicate cores.
    3. Search ALL frame candidates for a common structural
       outer frame containing one or more cores.
    4. The outer candidate must independently have:
       - left jamb
       - right jamb
       - top cap
       - bottom cap
       - no projecting sill as its bottom
    5. Multiple side-by-side window leaves sharing the same
       outer frame become ONE physical window.
    6. The outer frame must remain close to the union of its
       child cores, preventing walls / porches / facade panels
       from becoming windows.

    No absolute dimensions or project coordinates are used.
    """

    evaluated = [
        _structural_window_signature(
            candidate,
            candidates,
            horizontal,
            vertical,
        )
        for candidate in candidates or []
    ]


    # ========================================================
    # BASIC GEOMETRY
    # ========================================================

    def box(
        row,
    ):
        x0, y0, x1, y1 = (
            float(v)
            for v in row["bbox"]
        )

        width = max(
            x1 - x0,
            1.0e-9,
        )

        height = max(
            y1 - y0,
            1.0e-9,
        )

        return {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "w": width,
            "h": height,
            "area": width * height,
            "cx": (x0 + x1) * 0.5,
            "cy": (y0 + y1) * 0.5,
        }


    def intersection_area(
        a,
        b,
    ):
        return (
            max(
                0.0,
                min(
                    a["x1"],
                    b["x1"],
                )
                - max(
                    a["x0"],
                    b["x0"],
                ),
            )
            *
            max(
                0.0,
                min(
                    a["y1"],
                    b["y1"],
                )
                - max(
                    a["y0"],
                    b["y0"],
                ),
            )
        )


    def contains_core(
        outer,
        core,
    ):
        o = box(
            outer
        )

        c = box(
            core
        )

        intersection = (
            intersection_area(
                o,
                c,
            )
        )

        containment = (
            intersection
            / c["area"]
        )

        return (
            containment >= 0.90
            and
            o["cx"]
            - o["w"] * 0.51
            <= c["cx"]
            <= o["cx"]
            + o["w"] * 0.51
            and
            o["cy"]
            - o["h"] * 0.51
            <= c["cy"]
            <= o["cy"]
            + o["h"] * 0.51
        )


    # ========================================================
    # STRUCTURAL FRAME BOUNDARY
    # ========================================================

    def complete_frame(
        row,
    ):
        left = float(
            row.get(
                "structural_left_jamb_coverage",
                0.0,
            )
            or 0.0
        )

        right = float(
            row.get(
                "structural_right_jamb_coverage",
                0.0,
            )
            or 0.0
        )

        top_cap = row.get(
            "structural_top_cap"
        )

        bottom_cap = row.get(
            "structural_bottom_cap"
        )

        if (
            left < 0.50
            or right < 0.50
        ):
            return False

        if not isinstance(
            top_cap,
            dict,
        ):
            return False

        if not isinstance(
            bottom_cap,
            dict,
        ):
            return False

        if not bool(
            top_cap.get(
                "aligned",
                False,
            )
        ):
            return False

        if not bool(
            bottom_cap.get(
                "aligned",
                False,
            )
        ):
            return False

        if bool(
            bottom_cap.get(
                "projecting",
                False,
            )
        ):
            return False

        return True


    # ========================================================
    # STRONG WINDOW CORES
    # ========================================================

    strong = [
        row
        for row in evaluated
        if bool(
            row.get(
                "structural_window_accepted",
                False,
            )
        )
    ]


    strong.sort(
        key=lambda row: (
            -float(
                row.get(
                    "structural_window_score",
                    0.0,
                )
                or 0.0
            ),
            -box(
                row
            )["area"],
        )
    )


    # ========================================================
    # FIRST DEDUPE:
    # nested representations of the SAME leaf/core disappear.
    #
    # Side-by-side cores deliberately remain separate here.
    # ========================================================

    cores = []

    for candidate in strong:

        duplicate = False

        for kept in cores:

            relation = (
                _structural_bbox_relation(
                    candidate,
                    kept,
                )
            )

            if (
                relation[
                    "iou"
                ] >= 0.42
            ):
                duplicate = True
                break

            if (
                relation[
                    "containment"
                ] >= 0.82
                and
                relation[
                    "center_dx"
                ] <= 0.35
                and
                relation[
                    "center_dy"
                ] <= 0.35
            ):
                duplicate = True
                break

        if not duplicate:
            cores.append(
                candidate
            )


    # ========================================================
    # BUILD COMMON OUTER-FRAME FAMILIES
    # ========================================================

    families = []

    for outer in evaluated:

        if not complete_frame(
            outer
        ):
            continue

        o = box(
            outer
        )

        children = [
            core
            for core in cores
            if contains_core(
                outer,
                core,
            )
        ]

        if not children:
            continue


        # ----------------------------------------------------
        # Bounding rectangle of all child cores.
        #
        # THIS is the important difference from V2.
        #
        # A four-leaf window may be 4x wider than ONE child,
        # but only slightly larger than the UNION of all leaves.
        # ----------------------------------------------------

        child_boxes = [
            box(
                child
            )
            for child in children
        ]

        ux0 = min(
            item["x0"]
            for item in child_boxes
        )

        uy0 = min(
            item["y0"]
            for item in child_boxes
        )

        ux1 = max(
            item["x1"]
            for item in child_boxes
        )

        uy1 = max(
            item["y1"]
            for item in child_boxes
        )

        union_width = max(
            ux1 - ux0,
            1.0e-9,
        )

        union_height = max(
            uy1 - uy0,
            1.0e-9,
        )

        union_area = (
            union_width
            * union_height
        )


        width_ratio = (
            o["w"]
            / union_width
        )

        height_ratio = (
            o["h"]
            / union_height
        )

        area_ratio = (
            o["area"]
            / union_area
        )


        # ----------------------------------------------------
        # Outer frame must closely surround its window content.
        #
        # This rejects:
        # - whole facade panels
        # - wall rectangles
        # - porch openings
        # - groups of unrelated distant windows
        #
        # But it allows:
        # - single windows
        # - double windows
        # - triple windows
        # - four-leaf / multi-light windows
        # ----------------------------------------------------

        if not (
            0.98
            <= width_ratio
            <= 1.38
        ):
            continue

        if not (
            0.98
            <= height_ratio
            <= 1.38
        ):
            continue

        if area_ratio > 1.72:
            continue


        # ----------------------------------------------------
        # Outer frame should surround the child union
        # approximately symmetrically.
        # ----------------------------------------------------

        left_margin = (
            ux0 - o["x0"]
        )

        right_margin = (
            o["x1"] - ux1
        )

        bottom_margin = (
            uy0 - o["y0"]
        )

        top_margin = (
            o["y1"] - uy1
        )


        horizontal_total = max(
            left_margin
            + right_margin,
            union_width * 0.01,
        )

        vertical_total = max(
            bottom_margin
            + top_margin,
            union_height * 0.01,
        )


        horizontal_asymmetry = (
            abs(
                left_margin
                - right_margin
            )
            / horizontal_total
        )

        vertical_asymmetry = (
            abs(
                bottom_margin
                - top_margin
            )
            / vertical_total
        )


        if horizontal_asymmetry > 0.82:
            continue

        if vertical_asymmetry > 0.88:
            continue


        # ----------------------------------------------------
        # Make sure child cores occupy meaningful space inside
        # the frame. A large architectural rectangle containing
        # one tiny window must not win.
        # ----------------------------------------------------

        child_area_sum = sum(
            item["area"]
            for item in child_boxes
        )

        content_ratio = (
            child_area_sum
            / o["area"]
        )


        if (
            len(
                children
            )
            == 1
        ):
            if content_ratio < 0.42:
                continue

        else:
            if content_ratio < 0.30:
                continue


        families.append(
            {
                "outer":
                    outer,

                "children":
                    children,

                "child_count":
                    len(
                        children
                    ),

                "outer_area":
                    o["area"],

                "content_ratio":
                    content_ratio,

                "area_ratio":
                    area_ratio,
            }
        )


    # ========================================================
    # IMPORTANT:
    #
    # Prefer a frame that contains MORE sibling cores.
    # Then prefer the largest valid structural boundary.
    #
    # Therefore:
    #
    #    [pane][pane][pane][pane]
    #
    # becomes ONE window if a common frame exists.
    # ========================================================

    families.sort(
        key=lambda family: (
            -int(
                family[
                    "child_count"
                ]
            ),
            -float(
                family[
                    "outer_area"
                ]
            ),
            -float(
                family[
                    "content_ratio"
                ]
            ),
        )
    )


    resolved = []

    assigned_core_ids = set()


    for family in families:

        unassigned = [
            child
            for child in family[
                "children"
            ]
            if id(
                child
            )
            not in assigned_core_ids
        ]

        if not unassigned:
            continue


        # If this common frame contains multiple real cores,
        # keep the family together.
        #
        # If it contains one core, it is still allowed as a
        # normal outer-frame promotion.
        chosen = dict(
            family[
                "outer"
            ]
        )


        chosen[
            "structural_frame_family_count"
        ] = len(
            family[
                "children"
            ]
        )

        chosen[
            "structural_common_outer_frame"
        ] = True

        chosen[
            "structural_child_bboxes"
        ] = [
            tuple(
                float(v)
                for v in child[
                    "bbox"
                ]
            )
            for child
            in family[
                "children"
            ]
        ]


        resolved.append(
            chosen
        )


        for child in family[
            "children"
        ]:
            assigned_core_ids.add(
                id(
                    child
                )
            )


    # ========================================================
    # CORES WITH NO VALID OUTER FAMILY
    #
    # Preserve them rather than deleting valid windows.
    # ========================================================

    for core in cores:

        if id(
            core
        ) in assigned_core_ids:
            continue

        fallback = dict(
            core
        )

        fallback[
            "structural_common_outer_frame"
        ] = False

        fallback[
            "structural_frame_family_count"
        ] = 1

        resolved.append(
            fallback
        )


    # ========================================================
    # FINAL DEDUPE
    #
    # Now nested representations are removed, but side-by-side
    # independent windows remain independent unless a validated
    # common outer frame already grouped them.
    # ========================================================

    resolved.sort(
        key=lambda row:
            -box(
                row
            )["area"]
    )


    final = []

    for candidate in resolved:

        duplicate = False

        for kept in final:

            relation = (
                _structural_bbox_relation(
                    candidate,
                    kept,
                )
            )

            if (
                relation[
                    "iou"
                ] >= 0.52
            ):
                duplicate = True
                break

            if (
                relation[
                    "containment"
                ] >= 0.88
            ):
                duplicate = True
                break

        if not duplicate:
            final.append(
                candidate
            )


    final.sort(
        key=lambda row: (
            float(
                row["center"][0]
            ),
            float(
                row["center"][1]
            ),
        )
    )


    return (
        final,
        evaluated,
    )


def detect_structural_facade_windows(
    geometry,
    bounds,
    **_ignored,
):
    """
    General facade physical-window detector.

    IMPORTANT:
    This function is currently used by the
    "Cephe Pencereleri" inspection path only.

    Existing detect_elevation_openings() behavior remains
    untouched.
    """

    geometry = list(
        geometry
        or []
    )

    if (
        not geometry
        or bounds is None
    ):
        return {
            "engine":
                "CAD3D_STRUCTURAL_ELEVATION_WINDOW_RESOLVER_V1",

            "entities":
                [],

            "windows":
                [],

            "window_count":
                0,

            "door_count":
                0,

            "candidate_count":
                0,

            "accepted_signature_count":
                0,
        }


    bounds = tuple(
        float(value)
        for value in bounds
    )

    rx0, ry0, rx1, ry1 = (
        bounds
    )

    width = max(
        rx1 - rx0,
        1.0,
    )

    height = max(
        ry1 - ry0,
        1.0,
    )


    (
        horizontal,
        vertical,
    ) = (
        _extract_axis_segments(
            geometry
        )
    )


    horizontal = (
        _merge_horizontal(
            horizontal,
            y_tolerance=max(
                8.0,
                height * 0.0025,
            ),
            gap_tolerance=max(
                16.0,
                width * 0.003,
            ),
        )
    )


    vertical = (
        _merge_vertical(
            vertical,
            x_tolerance=max(
                8.0,
                width * 0.0025,
            ),
            gap_tolerance=max(
                16.0,
                height * 0.003,
            ),
        )
    )


    ground_y = (
        _detect_ground_line(
            horizontal,
            bounds,
        )
    )


    try:
        candidates = (
            _build_frame_candidates(
                horizontal,
                vertical,
                bounds,
                ground_y,
                all_storeys=True,
            )
        )

    except TypeError as exc:
        raise RuntimeError(
            "ALL_STOREYS_FRAME_CANDIDATE_MODE_REQUIRED"
        ) from exc


    # ========================================================
    # CAD3D_STRUCTURAL_WINDOW_DOOR_ENVELOPE_VETO_V1
    #
    # First identify complete door-like OUTER frames using the
    # existing elevation door classification.
    #
    # These are not final door records for Max. They are only
    # architectural exclusion envelopes for window recognition.
    # ========================================================

    _door_probe_entities = (
        _classify_entities(
            candidates,
            bounds,
            ground_y,
        )
    )

    _door_envelopes = []

    for _entity in _door_probe_entities:

        if str(
            _entity.get(
                "kind",
                "",
            )
            or ""
        ).strip().lower() != "door":
            continue

        _bbox = _entity.get(
            "bbox"
        )

        if (
            not isinstance(
                _bbox,
                (list, tuple),
            )
            or len(_bbox) != 4
        ):
            continue

        try:
            _x0, _y0, _x1, _y1 = (
                float(v)
                for v in _bbox
            )
        except Exception:
            continue

        _door_width = max(
            0.0,
            _x1 - _x0,
        )

        _door_height = max(
            0.0,
            _y1 - _y0,
        )

        _area = (
            _door_width
            * _door_height
        )

        if (
            _area <= 1.0e-9
            or _door_height <= 1.0e-9
        ):
            continue


        # ====================================================
        # CAD3D_SAFE_DOOR_ENVELOPE_V2
        #
        # A door envelope is a LOCAL, predominantly vertical
        # architectural opening.
        #
        # Reject facade-wide / room-wide / multi-opening
        # rectangles even if the legacy classifier happened
        # to call them "door".
        #
        # All thresholds are ratios, never project dimensions.
        # ====================================================

        _door_aspect = (
            _door_width
            / _door_height
        )

        _facade_width = max(
            float(
                bounds[2]
            )
            - float(
                bounds[0]
            ),
            1.0e-9,
        )

        _facade_height = max(
            float(
                bounds[3]
            )
            - float(
                bounds[1]
            ),
            1.0e-9,
        )

        _width_fraction = (
            _door_width
            / _facade_width
        )

        _height_fraction = (
            _door_height
            / _facade_height
        )


        # Normal single/double architectural doors are
        # predominantly vertical or approximately square.
        #
        # Wide facade bands and groups of several openings
        # must never become door exclusion envelopes.
        if not (
            0.18
            <= _door_aspect
            <= 1.35
        ):
            continue


        # A single door should remain a local opening in the
        # facade. This specifically rejects a rectangle
        # spanning several windows/doors.
        if _width_fraction > 0.32:
            continue


        # Very shallow near-ground rectangles are usually
        # sill/plinth/facade geometry rather than doors.
        if _height_fraction < 0.22:
            continue


        _door_envelopes.append(
            {
                "bbox": (
                    _x0,
                    _y0,
                    _x1,
                    _y1,
                ),

                "area":
                    _area,

                "aspect":
                    _door_aspect,

                "width_fraction":
                    _width_fraction,

                "height_fraction":
                    _height_fraction,
            }
        )


    # Prefer larger complete door frames. Smaller nested
    # door-panel rectangles must not become authoritative
    # exclusion envelopes.
    _door_envelopes.sort(
        key=lambda row:
            -float(
                row["area"]
            )
    )

    _resolved_door_envelopes = []

    for _candidate_door in _door_envelopes:

        _cx0, _cy0, _cx1, _cy1 = (
            _candidate_door[
                "bbox"
            ]
        )

        _contained = False

        for _kept_door in _resolved_door_envelopes:

            _kx0, _ky0, _kx1, _ky1 = (
                _kept_door[
                    "bbox"
                ]
            )

            if (
                _cx0 >= _kx0
                and
                _cx1 <= _kx1
                and
                _cy0 >= _ky0
                and
                _cy1 <= _ky1
            ):
                _contained = True
                break

        if not _contained:
            _resolved_door_envelopes.append(
                _candidate_door
            )


    (
        resolved,
        evaluated,
    ) = (
        _resolve_structural_windows(
            candidates,
            horizontal,
            vertical,
        )
    )


    # ========================================================
    # DOOR ENVELOPE VETO
    #
    # A valid physical window may not be a decorative rectangle
    # nested substantially inside a complete door envelope.
    #
    # This is scale-independent:
    # comparisons use containment and relative area only.
    # ========================================================

    _window_resolved_before_door_veto = (
        len(
            resolved
        )
    )

    _suppressed_door_subframes = []

    _window_only_resolved = []

    for _opening in resolved:

        _bbox = _opening.get(
            "bbox"
        )

        if (
            not isinstance(
                _bbox,
                (list, tuple),
            )
            or len(_bbox) != 4
        ):
            _window_only_resolved.append(
                _opening
            )
            continue

        try:
            _ox0, _oy0, _ox1, _oy1 = (
                float(v)
                for v in _bbox
            )
        except Exception:
            _window_only_resolved.append(
                _opening
            )
            continue

        _opening_area = max(
            0.0,
            _ox1 - _ox0,
        ) * max(
            0.0,
            _oy1 - _oy0,
        )

        _reject_as_door_panel = False

        for _door in _resolved_door_envelopes:

            _dx0, _dy0, _dx1, _dy1 = (
                _door[
                    "bbox"
                ]
            )

            _door_area = float(
                _door[
                    "area"
                ]
            )

            if (
                _opening_area <= 1.0e-9
                or _door_area <= 1.0e-9
            ):
                continue

            _ix0 = max(
                _ox0,
                _dx0,
            )

            _iy0 = max(
                _oy0,
                _dy0,
            )

            _ix1 = min(
                _ox1,
                _dx1,
            )

            _iy1 = min(
                _oy1,
                _dy1,
            )

            _intersection = (
                max(
                    0.0,
                    _ix1 - _ix0,
                )
                *
                max(
                    0.0,
                    _iy1 - _iy0,
                )
            )

            _containment = (
                _intersection
                / _opening_area
            )

            _area_ratio = (
                _opening_area
                / _door_area
            )

            _center_x = (
                _ox0 + _ox1
            ) * 0.5

            _center_y = (
                _oy0 + _oy1
            ) * 0.5

            _center_inside = (
                _dx0
                <= _center_x
                <= _dx1
                and
                _dy0
                <= _center_y
                <= _dy1
            )


            # ------------------------------------------------
            # IMPORTANT:
            #
            # Near-identical bbox means this is probably the
            # complete door frame itself. Do NOT reject here;
            # existing _classify_entities() will classify that
            # outer opening as "door".
            #
            # Only smaller nested rectangles are vetoed.
            # ------------------------------------------------

            if (
                _center_inside
                and
                _containment >= 0.82
                and
                _area_ratio <= 0.74
            ):
                _reject_as_door_panel = True

                _suppressed_door_subframes.append(
                    {
                        "window_bbox":
                            tuple(
                                float(v)
                                for v in _bbox
                            ),

                        "door_bbox":
                            tuple(
                                float(v)
                                for v in _door[
                                    "bbox"
                                ]
                            ),

                        "containment":
                            float(
                                _containment
                            ),

                        "area_ratio":
                            float(
                                _area_ratio
                            ),
                    }
                )

                break


        if not _reject_as_door_panel:
            _window_only_resolved.append(
                _opening
            )


    resolved = (
        _window_only_resolved
    )


    print(
        "STRUCTURAL WINDOW DOOR VETO"
        " | DOOR ENVELOPES:",
        len(
            _resolved_door_envelopes
        ),
        "| BEFORE:",
        _window_resolved_before_door_veto,
        "| SUPPRESSED:",
        len(
            _suppressed_door_subframes
        ),
        "| AFTER:",
        len(
            resolved
        ),
    )


    # Existing elevation classification remains useful only
    # to separate a structural ground-level door-like opening
    # from a window-like opening.
    entities = (
        _classify_entities(
            resolved,
            bounds,
            ground_y,
        )
    )


    # Preserve the sill/frame correction already installed,
    # if available. It never creates a window candidate; it
    # only refines the selected frame boundary.
    validator = globals().get(
        "_validate_window_frame_bottoms"
    )

    if callable(
        validator
    ):
        entities = validator(
            entities,
            horizontal,
            bounds,
        )


    entities = (
        _normalize_entities(
            entities
        )
    )


    windows = [
        entity
        for entity in entities
        if str(
            entity.get(
                "kind",
                "",
            )
            or ""
        ).strip().lower()
        == "window"
    ]


    doors = [
        entity
        for entity in entities
        if str(
            entity.get(
                "kind",
                "",
            )
            or ""
        ).strip().lower()
        == "door"
    ]


    return {
        "engine":
            "CAD3D_STRUCTURAL_ELEVATION_WINDOW_RESOLVER_V1",

        "ground_y":
            ground_y,

        "horizontal_count":
            len(
                horizontal
            ),

        "vertical_count":
            len(
                vertical
            ),

        "candidate_count":
            len(
                candidates
            ),

        "evaluated_signature_count":
            len(
                evaluated
            ),

        "accepted_signature_count":
            sum(
                1
                for row in evaluated
                if bool(
                    row.get(
                        "structural_window_accepted",
                        False,
                    )
                )
            ),

        "resolved_physical_opening_count":
            len(
                resolved
            ),

        "entities":
            entities,

        "windows":
            windows,

        "window_count":
            len(
                windows
            ),

        "door_count":
            len(
                doors
            ),
    }


def detect_elevation_openings(
    geometry,
    bounds,
    all_storeys=False,
    validate_window_frames=False,
):
    geometry = list(
        geometry
        or []
    )

    if (
        not geometry
        or bounds is None
    ):
        return {
            "engine":
                ENGINE,

            "ground_y":
                None,

            "candidates":
                [],

            "entities":
                [],
        }

    bounds = tuple(
        float(value)
        for value in bounds
    )

    rx0, ry0, rx1, ry1 = (
        bounds
    )

    width = max(
        rx1 - rx0,
        1.0,
    )

    height = max(
        ry1 - ry0,
        1.0,
    )

    (
        horizontal,
        vertical,
    ) = _extract_axis_segments(
        geometry
    )

    horizontal = _merge_horizontal(
        horizontal,
        y_tolerance=max(
            8.0,
            height * 0.0025,
        ),
        gap_tolerance=max(
            16.0,
            width * 0.003,
        ),
    )

    vertical = _merge_vertical(
        vertical,
        x_tolerance=max(
            8.0,
            width * 0.0025,
        ),
        gap_tolerance=max(
            16.0,
            height * 0.003,
        ),
    )

    ground_y = (
        _detect_ground_line(
            horizontal,
            bounds,
        )
    )

    candidates = (
        _build_frame_candidates(
            horizontal,
            vertical,
            bounds,
            ground_y,
            all_storeys=all_storeys,
        )
    )

    resolved = (
        _resolve_nested_frames(
            candidates,
            bounds,
        )
    )

    resolved = (
        _select_non_overlapping(
            resolved
        )
    )

    entities = (
        _classify_entities(
            resolved,
            bounds,
            ground_y,
        )
    )

    if bool(
        validate_window_frames
    ):
        entities = (
            _validate_window_frame_bottoms(
                entities,
                horizontal,
                bounds,
            )
        )

    entities = (
        _normalize_entities(
            entities
        )
    )

    return {
        "engine":
            ENGINE,

        "ground_y":
            ground_y,

        "ground_y_role":
            "CANDIDATE_DETECTION_ONLY",

        "final_ground_reference_rule":
            GROUND_REFERENCE_RULE,

        "horizontal_count":
            len(horizontal),

        "vertical_count":
            len(vertical),

        "candidate_count":
            len(candidates),

        "entities":
            entities,

        "door_count":
            sum(
                1
                for row in entities
                if row[
                    "kind"
                ] == "door"
            ),

        "window_count":
            sum(
                1
                for row in entities
                if row[
                    "kind"
                ] == "window"
            ),
    }


# ============================================================
# SELF TEST
# ============================================================

def _rect(
    x0,
    y0,
    x1,
    y1,
):
    return [
        {
            "layer":
                "TEST",

            "points": [
                (x0, y0),
                (x1, y0),
                (x1, y1),
                (x0, y1),
                (x0, y0),
            ],
        }
    ]


def self_test():
    geometry = []

    # Ground.
    geometry.append(
        {
            "layer":
                "TEST",

            "points": [
                (0.0, 0.0),
                (10000.0, 0.0),
            ],
        }
    )

    # Window.
    geometry += _rect(
        800.0,
        900.0,
        2000.0,
        2400.0,
    )

    # Door.
    geometry += _rect(
        4000.0,
        50.0,
        5000.0,
        2500.0,
    )

    # Window.
    geometry += _rect(
        7000.0,
        900.0,
        8200.0,
        2400.0,
    )

    result = (
        detect_elevation_openings(
            geometry,
            (
                0.0,
                0.0,
                10000.0,
                6000.0,
            ),
        )
    )

    entities = result[
        "entities"
    ]

    assert len(
        entities
    ) == 3, entities

    assert [
        row["kind"]
        for row in entities
    ] == [
        "window",
        "door",
        "window",
    ], entities

    # Main entrance door bottom is Y=50.
    # This MUST become final Z=0 irrespective of any
    # drawing ground line.
    resolved = apply_main_entrance_ground_reference(
        entities,
        50.0,
    )

    doors = [
        row
        for row in resolved
        if row["kind"] == "door"
    ]

    windows = [
        row
        for row in resolved
        if row["kind"] == "window"
    ]

    assert abs(
        doors[0]["window_bottom_z"]
        - 0.0
    ) < 1.0e-6

    assert abs(
        windows[0]["window_bottom_z"]
        - 850.0
    ) < 1.0e-6

    assert abs(
        windows[0]["window_top_z"]
        - 2350.0
    ) < 1.0e-6

    assert abs(
        windows[0]["window_height"]
        - 1500.0
    ) < 1.0e-6

    assert (
        windows[0]["ground_reference_rule"]
        ==
        "MAIN_ENTRANCE_DOOR_BOTTOM_V1"
    )

    print(
        "ELEVATION OPENING DETECTOR V1 SELF-TEST: OK"
    )


if __name__ == "__main__":
    self_test()
