from __future__ import annotations

from copy import deepcopy


ENGINE = "CAD3D_PLAN_GUIDED_FACADE_WINDOWS_V2"

# Hard rejection limits only.
# Ranking inside the gate is continuous.
MAX_WIDTH_ERROR = 0.20
MAX_POSITION_ERROR = 0.25
MAX_SEED_X_ERROR = 0.18
MAX_SEED_Y_ERROR = 0.14


def _float(value):
    try:
        return float(value)
    except Exception:
        return None


def _bbox(value):
    try:
        x0, y0, x1, y1 = (
            float(v)
            for v in value
        )
    except Exception:
        return None

    if x1 <= x0 or y1 <= y0:
        return None

    return (
        x0,
        y0,
        x1,
        y1,
    )


def _center(box):
    return (
        (box[0] + box[2]) * 0.5,
        (box[1] + box[3]) * 0.5,
    )


def _area(box):
    return (
        (box[2] - box[0])
        * (box[3] - box[1])
    )


def _kind(row):
    return str(
        row.get(
            "kind",
            "",
        )
        or ""
    ).strip().lower()


def _facade_number(row):
    try:
        return int(
            row.get(
                "facade_number"
            )
        )
    except Exception:
        return None


def _relative_center(
    opening,
    facade_box,
):
    value = _float(
        opening.get(
            "relative_center"
        )
    )

    if (
        value is not None
        and -0.05 <= value <= 1.05
    ):
        return value

    box = _bbox(
        opening.get(
            "bbox"
        )
    )

    if box is None:
        return None

    cx, _ = _center(
        box
    )

    width = max(
        facade_box[2] - facade_box[0],
        1.0e-9,
    )

    return (
        cx - facade_box[0]
    ) / width


def _plan_sort_key(item):
    index, opening = item

    rel = _float(
        opening.get(
            "relative_center"
        )
    )

    if rel is None:
        return float(index)

    return rel


def _seed_by_plan_index(
    old_pairs,
):
    result = {}

    for pair in old_pairs:
        if _kind(pair) != "window":
            continue

        try:
            index = int(
                pair.get(
                    "plan_index"
                )
            )
        except Exception:
            continue

        result[
            index
        ] = pair

    return result


def _candidate_rows(
    facade,
):
    facade_box = _bbox(
        facade.get(
            "bbox"
        )
    )

    if facade_box is None:
        return []

    result = []

    openings = list(
        facade.get(
            "openings",
            [],
        )
        or []
    )

    for index, opening in enumerate(
        openings
    ):
        if _kind(opening) != "window":
            continue

        box = _bbox(
            opening.get(
                "bbox"
            )
        )

        if box is None:
            continue

        width = _float(
            opening.get(
                "width"
            )
        )

        if width is None:
            width = (
                box[2] - box[0]
            )

        if width <= 1.0e-9:
            continue

        result.append(
            {
                "index":
                    index,

                "opening":
                    opening,

                "bbox":
                    box,

                "center":
                    _center(
                        box
                    ),

                "width":
                    float(
                        width
                    ),

                "area":
                    _area(
                        box
                    ),

                "relative_center":
                    _relative_center(
                        opening,
                        facade_box,
                    ),
            }
        )

    return result


def _same_local_window(
    a,
    b,
    plan_width,
    facade_width,
    facade_height,
):
    ax, ay = a[
        "center"
    ]

    bx, by = b[
        "center"
    ]

    dx = abs(
        ax - bx
    )

    dy = abs(
        ay - by
    )

    return (
        dx
        <= max(
            plan_width * 0.30,
            facade_width * 0.018,
        )
        and
        dy
        <= facade_height * 0.045
    )


def apply_plan_guided_facade_window_filter(
    analysis,
):
    """
    SOURCE OF TRUTH:
        accepted PLAN windows.

    FACADE:
        candidate geometry only.

    A facade candidate becomes a physical window only when
    an accepted plan window can validate it.

    Plan window width is the main dimensional reference.
    Position/order and the old facade match are supporting
    evidence only.

    Unmatched facade candidates are removed BEFORE vertical
    sill/height measurements.
    """

    if not isinstance(
        analysis,
        dict,
    ):
        return analysis

    result = deepcopy(
        analysis
    )

    plan_facades = list(
        result.get(
            "plan_facades",
            [],
        )
        or []
    )

    elevation_facades = list(
        result.get(
            "elevation_facades",
            [],
        )
        or []
    )

    matches = list(
        result.get(
            "matches",
            [],
        )
        or []
    )

    plan_by_side = {}

    for facade in plan_facades:
        side = str(
            facade.get(
                "side",
                "",
            )
            or ""
        ).strip().lower()

        if side:
            plan_by_side[
                side
            ] = facade

    elev_by_number = {}

    for facade in elevation_facades:
        number = _facade_number(
            facade
        )

        if number is not None:
            elev_by_number[
                number
            ] = facade

    accepted_global = []
    unresolved = []

    accepted_indices_by_facade = {}

    total_plan_windows = 0
    total_candidates = 0

    for match in matches:

        facade_number = _facade_number(
            match
        )

        plan_side = str(
            match.get(
                "plan_side",
                "",
            )
            or ""
        ).strip().lower()

        plan_facade = plan_by_side.get(
            plan_side
        )

        elevation_facade = (
            elev_by_number.get(
                facade_number
            )
        )

        if (
            not isinstance(
                plan_facade,
                dict,
            )
            or not isinstance(
                elevation_facade,
                dict,
            )
        ):
            continue

        facade_box = _bbox(
            elevation_facade.get(
                "bbox"
            )
        )

        if facade_box is None:
            continue

        facade_width = max(
            facade_box[2] - facade_box[0],
            1.0e-9,
        )

        facade_height = max(
            facade_box[3] - facade_box[1],
            1.0e-9,
        )

        plan_openings = list(
            plan_facade.get(
                "openings",
                [],
            )
            or []
        )

        plan_windows = [
            (
                index,
                opening,
            )
            for index, opening
            in enumerate(
                plan_openings
            )
            if _kind(
                opening
            )
            == "window"
        ]

        plan_windows.sort(
            key=_plan_sort_key
        )

        total_plan_windows += len(
            plan_windows
        )

        candidates = _candidate_rows(
            elevation_facade
        )

        total_candidates += len(
            candidates
        )

        old_pairs = list(
            match.get(
                "opening_pairs",
                [],
            )
            or []
        )

        door_pairs = [
            deepcopy(
                pair
            )
            for pair in old_pairs
            if _kind(
                pair
            )
            == "door"
        ]

        old_window_pairs = [
            pair
            for pair in old_pairs
            if _kind(
                pair
            )
            == "window"
        ]

        seed_map = (
            _seed_by_plan_index(
                old_window_pairs
            )
        )

        reversed_order = bool(
            match.get(
                "reversed",
                False,
            )
        )

        used = set()

        accepted_pairs = []

        previous_position = -1.0e9

        for sequence, (
            plan_index,
            plan_window,
        ) in enumerate(
            plan_windows
        ):

            plan_width = _float(
                plan_window.get(
                    "width"
                )
            )

            if (
                plan_width is None
                or plan_width <= 1.0e-9
            ):
                unresolved.append(
                    {
                        "facade_number":
                            facade_number,

                        "plan_side":
                            plan_side,

                        "plan_index":
                            plan_index,

                        "reason":
                            "PLAN_WIDTH_MISSING",
                    }
                )

                continue

            plan_rel = _float(
                plan_window.get(
                    "relative_center"
                )
            )

            seed = seed_map.get(
                plan_index
            )

            if (
                seed is None
                and sequence
                < len(
                    old_window_pairs
                )
            ):
                seed = (
                    old_window_pairs[
                        sequence
                    ]
                )

            seed_box = None

            if isinstance(
                seed,
                dict,
            ):
                seed_box = _bbox(
                    seed.get(
                        "elevation_bbox"
                    )
                )

            seed_center = (
                _center(
                    seed_box
                )
                if seed_box is not None
                else None
            )

            feasible = []

            closest_width_error = None

            for candidate in candidates:

                if candidate[
                    "index"
                ] in used:
                    continue

                width_error = (
                    abs(
                        candidate[
                            "width"
                        ]
                        - plan_width
                    )
                    / plan_width
                )

                if (
                    closest_width_error is None
                    or width_error
                    < closest_width_error
                ):
                    closest_width_error = (
                        width_error
                    )

                if (
                    width_error
                    > MAX_WIDTH_ERROR
                ):
                    continue

                candidate_rel = (
                    candidate[
                        "relative_center"
                    ]
                )

                if (
                    candidate_rel is not None
                    and reversed_order
                ):
                    aligned_rel = (
                        1.0
                        - candidate_rel
                    )

                else:
                    aligned_rel = (
                        candidate_rel
                    )

                position_error = 0.0

                if (
                    plan_rel is not None
                    and aligned_rel is not None
                ):
                    position_error = abs(
                        aligned_rel
                        - plan_rel
                    )

                    if (
                        position_error
                        > MAX_POSITION_ERROR
                    ):
                        continue

                    if (
                        aligned_rel
                        < previous_position
                        - 0.02
                    ):
                        continue

                seed_x_error = 0.0
                seed_y_error = 0.0

                if seed_center is not None:

                    cx, cy = (
                        candidate[
                            "center"
                        ]
                    )

                    seed_x_error = (
                        abs(
                            cx
                            - seed_center[0]
                        )
                        / facade_width
                    )

                    seed_y_error = (
                        abs(
                            cy
                            - seed_center[1]
                        )
                        / facade_height
                    )

                    if (
                        seed_x_error
                        > MAX_SEED_X_ERROR
                    ):
                        continue

                    if (
                        seed_y_error
                        > MAX_SEED_Y_ERROR
                    ):
                        continue

                # Width is intentionally dominant.
                cost = (
                    width_error
                    * 20.0
                    +
                    position_error
                    * 4.0
                    +
                    seed_x_error
                    * 3.0
                    +
                    seed_y_error
                    * 7.0
                )

                feasible.append(
                    {
                        **candidate,

                        "width_error":
                            float(
                                width_error
                            ),

                        "position_error":
                            float(
                                position_error
                            ),

                        "aligned_rel":
                            aligned_rel,

                        "cost":
                            float(
                                cost
                            ),
                    }
                )

            if not feasible:

                unresolved.append(
                    {
                        "facade_number":
                            facade_number,

                        "plan_side":
                            plan_side,

                        "plan_index":
                            plan_index,

                        "plan_width":
                            float(
                                plan_width
                            ),

                        "closest_width_error":
                            closest_width_error,

                        "reason":
                            "NO_FACADE_WINDOW_PASSED_PLAN_GATE",
                    }
                )

                continue

            feasible.sort(
                key=lambda row: (
                    row[
                        "cost"
                    ],
                    row[
                        "width_error"
                    ],
                    row[
                        "position_error"
                    ],
                    -row[
                        "area"
                    ],
                )
            )

            best = feasible[0]

            # ------------------------------------------------
            # OUTER FRAME ASSIST
            #
            # First plan width decides dimensional correctness.
            # Only among dimensionally almost equivalent local
            # candidates may the larger enclosing frame win.
            # ------------------------------------------------

            local_ties = []

            for candidate in feasible:

                if (
                    candidate[
                        "width_error"
                    ]
                    > best[
                        "width_error"
                    ]
                    + 0.0125
                ):
                    continue

                if (
                    candidate[
                        "cost"
                    ]
                    > best[
                        "cost"
                    ]
                    + 0.30
                ):
                    continue

                if not _same_local_window(
                    candidate,
                    best,
                    plan_width,
                    facade_width,
                    facade_height,
                ):
                    continue

                local_ties.append(
                    candidate
                )

            if local_ties:

                chosen = max(
                    local_ties,
                    key=lambda row: (
                        row[
                            "area"
                        ],
                        -row[
                            "width_error"
                        ],
                    ),
                )

            else:
                chosen = best

            chosen_index = (
                chosen[
                    "index"
                ]
            )

            # Consume all nested/inner alternatives belonging
            # to the same already-accepted physical window.
            for candidate in candidates:

                if _same_local_window(
                    candidate,
                    chosen,
                    plan_width,
                    facade_width,
                    facade_height,
                ):
                    used.add(
                        candidate[
                            "index"
                        ]
                    )

            used.add(
                chosen_index
            )

            if (
                chosen[
                    "aligned_rel"
                ]
                is not None
            ):
                previous_position = max(
                    previous_position,
                    chosen[
                        "aligned_rel"
                    ],
                )

            box = chosen[
                "bbox"
            ]

            pair = {
                "kind":
                    "window",

                "plan_index":
                    int(
                        plan_index
                    ),

                "elevation_index":
                    int(
                        chosen_index
                    ),

                "plan_center":
                    deepcopy(
                        plan_window.get(
                            "center"
                        )
                    ),

                "plan_width":
                    float(
                        plan_width
                    ),

                "elevation_bbox":
                    [
                        float(v)
                        for v in box
                    ],

                "elevation_center":
                    [
                        float(v)
                        for v in chosen[
                            "center"
                        ]
                    ],

                "elevation_width":
                    float(
                        chosen[
                            "width"
                        ]
                    ),

                "elevation_bottom_y":
                    float(
                        box[1]
                    ),

                "elevation_top_y":
                    float(
                        box[3]
                    ),

                "elevation_height":
                    float(
                        box[3]
                        - box[1]
                    ),

                "plan_guided":
                    True,

                "width_error_ratio":
                    float(
                        chosen[
                            "width_error"
                        ]
                    ),

                "position_error_ratio":
                    float(
                        chosen[
                            "position_error"
                        ]
                    ),

                "selection_cost":
                    float(
                        chosen[
                            "cost"
                        ]
                    ),
            }

            accepted_pairs.append(
                pair
            )

            accepted_indices_by_facade.setdefault(
                facade_number,
                set(),
            ).add(
                chosen_index
            )

            accepted_global.append(
                {
                    **deepcopy(
                        pair
                    ),

                    "facade_number":
                        facade_number,

                    "plan_side":
                        plan_side,
                }
            )

        match[
            "opening_pairs"
        ] = (
            door_pairs
            + accepted_pairs
        )

        match[
            "plan_guided_window_count"
        ] = len(
            accepted_pairs
        )

        match[
            "plan_guided_expected_window_count"
        ] = len(
            plan_windows
        )

    # ========================================================
    # HARD GATE ON ELEVATION OPENINGS
    # ========================================================

    for facade in elevation_facades:

        number = _facade_number(
            facade
        )

        accepted_indices = (
            accepted_indices_by_facade.get(
                number,
                set(),
            )
        )

        openings = list(
            facade.get(
                "openings",
                [],
            )
            or []
        )

        candidate_count = sum(
            1
            for opening in openings
            if _kind(
                opening
            )
            == "window"
        )

        filtered = []

        for index, opening in enumerate(
            openings
        ):

            if _kind(
                opening
            ) != "window":

                filtered.append(
                    opening
                )

                continue

            if index not in accepted_indices:
                continue

            item = deepcopy(
                opening
            )

            item[
                "plan_guided_accepted"
            ] = True

            filtered.append(
                item
            )

        facade[
            "openings"
        ] = filtered

        facade[
            "plan_guided_candidate_window_count"
        ] = candidate_count

        facade[
            "plan_guided_accepted_window_count"
        ] = len(
            accepted_indices
        )

    result[
        "plan_guided_facade_windows"
    ] = accepted_global

    result[
        "plan_guided_unresolved_windows"
    ] = unresolved

    result[
        "plan_guided_applied"
    ] = True

    result[
        "plan_guided_summary"
    ] = {
        "engine":
            ENGINE,

        "plan_windows":
            total_plan_windows,

        "facade_candidates":
            total_candidates,

        "accepted":
            len(
                accepted_global
            ),

        "unresolved":
            len(
                unresolved
            ),
    }

    print("")
    print(
        "=== PLAN GUIDED FACADE WINDOWS V2 ==="
    )

    print(
        "PLAN WINDOWS      :",
        total_plan_windows
    )

    print(
        "FACADE CANDIDATES :",
        total_candidates
    )

    print(
        "ACCEPTED          :",
        len(
            accepted_global
        )
    )

    print(
        "UNRESOLVED        :",
        len(
            unresolved
        )
    )

    for row in accepted_global:

        print(
            "FACADE",
            row[
                "facade_number"
            ],
            "|",
            row[
                "plan_side"
            ],
            "| PLAN W:",
            round(
                row[
                    "plan_width"
                ],
                3
            ),
            "| ELEV W:",
            round(
                row[
                    "elevation_width"
                ],
                3
            ),
            "| ERROR:",
            f"{row['width_error_ratio'] * 100.0:.2f}%"
        )

    if unresolved:

        print(
            "--- UNRESOLVED ---"
        )

        for row in unresolved:
            print(
                row
            )

    print(
        "=== END PLAN GUIDED ==="
    )

    return result


def self_test():

    data = {
        "plan_facades": [
            {
                "side":
                    "bottom",

                "openings": [
                    {
                        "kind":
                            "window",

                        "width":
                            700.0,

                        "relative_center":
                            0.25,
                    },

                    {
                        "kind":
                            "window",

                        "width":
                            1200.0,

                        "relative_center":
                            0.75,
                    },
                ],
            },
        ],

        "elevation_facades": [
            {
                "facade_number":
                    1,

                "bbox":
                    [
                        0.0,
                        0.0,
                        4000.0,
                        3000.0,
                    ],

                "openings": [
                    # wrong inner frame
                    {
                        "kind":
                            "window",

                        "bbox":
                            [
                                825.0,
                                800.0,
                                1225.0,
                                1900.0,
                            ],

                        "width":
                            400.0,

                        "relative_center":
                            0.25,
                    },

                    # correct plan-matched outer frame
                    {
                        "kind":
                            "window",

                        "bbox":
                            [
                                700.0,
                                700.0,
                                1400.0,
                                2100.0,
                            ],

                        "width":
                            700.0,

                        "relative_center":
                            0.25,
                    },

                    # correct second window
                    {
                        "kind":
                            "window",

                        "bbox":
                            [
                                2400.0,
                                700.0,
                                3600.0,
                                2100.0,
                            ],

                        "width":
                            1200.0,

                        "relative_center":
                            0.75,
                    },

                    # false door/panel-like candidate
                    {
                        "kind":
                            "window",

                        "bbox":
                            [
                                3400.0,
                                0.0,
                                3900.0,
                                2500.0,
                            ],

                        "width":
                            500.0,

                        "relative_center":
                            0.93,
                    },
                ],
            },
        ],

        "matches": [
            {
                "facade_number":
                    1,

                "plan_side":
                    "bottom",

                "reversed":
                    False,

                "opening_pairs": [
                    {
                        "kind":
                            "window",

                        "plan_index":
                            0,

                        "elevation_bbox":
                            [
                                650.0,
                                650.0,
                                1450.0,
                                2150.0,
                            ],
                    },

                    {
                        "kind":
                            "window",

                        "plan_index":
                            1,

                        "elevation_bbox":
                            [
                                2350.0,
                                650.0,
                                3650.0,
                                2150.0,
                            ],
                    },
                ],
            },
        ],
    }

    result = (
        apply_plan_guided_facade_window_filter(
            data
        )
    )

    rows = result[
        "plan_guided_facade_windows"
    ]

    assert len(
        rows
    ) == 2, rows

    assert [
        row[
            "elevation_width"
        ]
        for row in rows
    ] == [
        700.0,
        1200.0,
    ], rows

    assert len(
        [
            row
            for row
            in result[
                "elevation_facades"
            ][0][
                "openings"
            ]
            if _kind(
                row
            )
            == "window"
        ]
    ) == 2

    print(
        "PLAN GUIDED V2 SELF TEST: PASS"
    )


if __name__ == "__main__":
    self_test()


# ============================================================
# CAD3D_MULTI_FLOOR_PLAN_WINDOW_SOURCE_V3
#
# AUTHORITATIVE PLAN WINDOW SOURCE:
#     window.multi_floor_3d_packages[*]["windows"]
#
# Those are the exact detect_windows() results already used by
# the deterministic wall/window preparation pipeline.
#
# analysis["plan_facades"] is NOT authoritative anymore when
# this path is used.
# ============================================================

MULTI_FLOOR_ENGINE = (
    "CAD3D_MULTI_FLOOR_PLAN_WINDOW_SOURCE_V3"
)


def _mfpg3_point(
    value,
):
    try:
        return (
            float(value[0]),
            float(value[1]),
        )
    except Exception:
        return None


def _mfpg3_bounds(
    value,
):
    try:
        x0, y0, x1, y1 = (
            float(v)
            for v in value
        )
    except Exception:
        return None

    if (
        x1 <= x0
        or y1 <= y0
    ):
        return None

    return (
        x0,
        y0,
        x1,
        y1,
    )


def _mfpg3_side_and_position(
    window,
    bounds,
):
    """
    Resolve which exterior plan side owns a window.

    Window detector already gives:
        center
        direction
        width

    direction describes the opening axis.

    horizontal window axis -> top/bottom wall
    vertical window axis   -> left/right wall
    """

    center = _mfpg3_point(
        window.get(
            "center"
        )
    )

    direction = _mfpg3_point(
        window.get(
            "direction"
        )
    )

    bounds = _mfpg3_bounds(
        bounds
    )

    if (
        center is None
        or direction is None
        or bounds is None
    ):
        return None

    cx, cy = center
    ux, uy = direction

    x0, y0, x1, y1 = bounds

    width = max(
        x1 - x0,
        1.0e-9,
    )

    height = max(
        y1 - y0,
        1.0e-9,
    )


    if abs(ux) >= abs(uy):

        # Window runs horizontally in plan:
        # therefore belongs to bottom or top facade.
        bottom_distance = abs(
            cy - y0
        )

        top_distance = abs(
            y1 - cy
        )

        side = (
            "bottom"
            if bottom_distance
            <= top_distance
            else "top"
        )

        relative = (
            cx - x0
        ) / width

        axis_value = cx

    else:

        # Window runs vertically in plan:
        # therefore belongs to left or right facade.
        left_distance = abs(
            cx - x0
        )

        right_distance = abs(
            x1 - cx
        )

        side = (
            "left"
            if left_distance
            <= right_distance
            else "right"
        )

        relative = (
            cy - y0
        ) / height

        axis_value = cy


    relative = max(
        0.0,
        min(
            1.0,
            float(relative),
        ),
    )


    return {
        "side":
            side,

        "relative_center":
            relative,

        "axis_value":
            float(
                axis_value
            ),
    }


def build_multi_floor_plan_facades(
    packages,
):
    """
    Convert exact prepared-floor window detections into the
    small plan_facades schema consumed by the existing V2
    matching engine.

    Important:
    rooflights are NOT included.
    """

    packages = list(
        packages
        or []
    )

    grouped = {
        "bottom": [],
        "right": [],
        "top": [],
        "left": [],
    }

    source_total = 0
    rooflight_total = 0

    floor_rows = []


    for package in sorted(
        packages,
        key=lambda row: (
            int(
                row.get(
                    "floor_order",
                    0,
                )
            ),
            int(
                row.get(
                    "selection_index",
                    0,
                )
            ),
        ),
    ):

        bounds = _mfpg3_bounds(
            package.get(
                "source_bounds"
            )
        )

        if bounds is None:
            continue

        floor_order = int(
            package.get(
                "floor_order",
                0,
            )
        )

        floor_name = str(
            package.get(
                "floor_name",
                "",
            )
            or ""
        )

        windows = list(
            package.get(
                "windows",
                [],
            )
            or []
        )

        rooflights = list(
            package.get(
                "rooflights",
                [],
            )
            or []
        )

        source_total += len(
            windows
        )

        rooflight_total += len(
            rooflights
        )

        floor_counts = {
            "bottom": 0,
            "right": 0,
            "top": 0,
            "left": 0,
        }


        for source_index, window in enumerate(
            windows
        ):

            if not isinstance(
                window,
                dict,
            ):
                continue

            width = _float(
                window.get(
                    "width"
                )
            )

            if (
                width is None
                or width <= 1.0e-9
            ):
                continue


            placement = (
                _mfpg3_side_and_position(
                    window,
                    bounds,
                )
            )

            if placement is None:
                continue


            side = placement[
                "side"
            ]

            center = _mfpg3_point(
                window.get(
                    "center"
                )
            )

            record = {
                "kind":
                    "window",

                "center":
                    (
                        list(center)
                        if center is not None
                        else None
                    ),

                "width":
                    float(
                        width
                    ),

                "relative_center":
                    float(
                        placement[
                            "relative_center"
                        ]
                    ),

                "source_axis_value":
                    float(
                        placement[
                            "axis_value"
                        ]
                    ),

                "floor_order":
                    floor_order,

                "floor_name":
                    floor_name,

                "source_window_index":
                    int(
                        source_index
                    ),

                "source_window_id":
                    window.get(
                        "window_id"
                    ),

                "source_confidence":
                    window.get(
                        "confidence"
                    ),

                "source":
                    "multi_floor_3d_packages.windows",
            }


            grouped[
                side
            ].append(
                record
            )

            floor_counts[
                side
            ] += 1


        floor_rows.append(
            {
                "floor_name":
                    floor_name,

                "floor_order":
                    floor_order,

                "window_count":
                    len(
                        windows
                    ),

                "rooflight_count":
                    len(
                        rooflights
                    ),

                "side_counts":
                    floor_counts,
            }
        )


    facades = []


    for side in (
        "bottom",
        "right",
        "top",
        "left",
    ):

        openings = list(
            grouped[
                side
            ]
        )

        openings.sort(
            key=lambda row: (
                float(
                    row[
                        "relative_center"
                    ]
                ),
                int(
                    row[
                        "floor_order"
                    ]
                ),
                int(
                    row[
                        "source_window_index"
                    ]
                ),
            )
        )


        if not openings:
            continue


        facades.append(
            {
                "side":
                    side,

                "openings":
                    openings,

                "detector_window_count":
                    len(
                        openings
                    ),

                "source":
                    "multi_floor_3d_packages.windows",
            }
        )


    mapped_total = sum(
        len(
            row[
                "openings"
            ]
        )
        for row in facades
    )


    if mapped_total != source_total:
        raise RuntimeError(
            "Multi-floor plan window mapping lost windows: "
            f"source={source_total}, mapped={mapped_total}"
        )


    print("")
    print(
        "=== MULTI FLOOR PLAN WINDOW SOURCE V3 ==="
    )

    print(
        "SOURCE WINDOWS :",
        source_total,
    )

    print(
        "ROOFLIGHTS     :",
        rooflight_total,
        "(excluded)",
    )

    print(
        "MAPPED WINDOWS :",
        mapped_total,
    )


    for row in floor_rows:

        print(
            row[
                "floor_name"
            ],
            "| FLOOR:",
            row[
                "floor_order"
            ],
            "| WINDOWS:",
            row[
                "window_count"
            ],
            "| ROOFLIGHTS:",
            row[
                "rooflight_count"
            ],
            "| SIDES:",
            row[
                "side_counts"
            ],
        )


    for facade in facades:

        print(
            "SIDE",
            facade[
                "side"
            ],
            "| EXPECTED:",
            len(
                facade[
                    "openings"
                ]
            ),
        )


    print(
        "=== END MULTI FLOOR PLAN WINDOW SOURCE V3 ==="
    )
    print("")


    return {
        "engine":
            MULTI_FLOOR_ENGINE,

        "plan_facades":
            facades,

        "floor_rows":
            floor_rows,

        "source_window_count":
            source_total,

        "mapped_window_count":
            mapped_total,

        "rooflight_count":
            rooflight_total,
    }


def _mfpg3_unique_matches(
    matches,
):
    """
    facade_matcher output currently may contain duplicate
    facade/side rows.

    Keep one canonical match for each physical facade + side.
    Lowest matcher cost wins.
    """

    best = {}


    for match in matches or []:

        if not isinstance(
            match,
            dict,
        ):
            continue

        try:
            facade_number = int(
                match.get(
                    "facade_number"
                )
            )
        except Exception:
            continue

        side = str(
            match.get(
                "plan_side",
                "",
            )
            or ""
        ).strip().lower()

        if not side:
            continue


        key = (
            facade_number,
            side,
        )


        try:
            cost = float(
                match.get(
                    "cost",
                    float("inf"),
                )
            )
        except Exception:
            cost = float(
                "inf"
            )


        current = best.get(
            key
        )


        if current is None:

            best[
                key
            ] = (
                cost,
                deepcopy(
                    match
                ),
            )

            continue


        if cost < current[0]:

            best[
                key
            ] = (
                cost,
                deepcopy(
                    match
                ),
            )


    result = []


    for (
        _key,
        (
            _cost,
            match,
        ),
    ) in best.items():

        # The old matcher window pairs MUST NOT act as seed
        # positions for this new source.
        #
        # They were generated from the old plan_facades path.
        #
        # Door pairs are retained for entrance / facade
        # registration only.
        match[
            "opening_pairs"
        ] = [
            deepcopy(
                pair
            )
            for pair in (
                match.get(
                    "opening_pairs",
                    [],
                )
                or []
            )
            if _kind(
                pair
            )
            == "door"
        ]

        result.append(
            match
        )


    result.sort(
        key=lambda row: (
            int(
                row.get(
                    "facade_number",
                    0,
                )
            ),
            str(
                row.get(
                    "plan_side",
                    "",
                )
            ),
        )
    )


    return result


def apply_multi_floor_plan_guidance(
    analysis,
    packages,
):
    """
    Feed EXACT prepared-plan windows to the existing candidate
    selector.

    Elevation openings stay candidate-only.
    """

    if not isinstance(
        analysis,
        dict,
    ):
        raise TypeError(
            "analysis must be dict"
        )


    source = (
        build_multi_floor_plan_facades(
            packages
        )
    )


    prepared = deepcopy(
        analysis
    )


    prepared[
        "plan_facades"
    ] = deepcopy(
        source[
            "plan_facades"
        ]
    )


    prepared[
        "matches"
    ] = (
        _mfpg3_unique_matches(
            prepared.get(
                "matches",
                [],
            )
        )
    )


    prepared[
        "plan_window_source"
    ] = {
        "engine":
            MULTI_FLOOR_ENGINE,

        "source":
            "multi_floor_3d_packages.windows",

        "source_window_count":
            source[
                "source_window_count"
            ],

        "mapped_window_count":
            source[
                "mapped_window_count"
            ],

        "rooflight_count":
            source[
                "rooflight_count"
            ],

        "floors":
            deepcopy(
                source[
                    "floor_rows"
                ]
            ),
    }


    result = (
        apply_plan_guided_facade_window_filter(
            prepared
        )
    )


    # --------------------------------------------------------
    # Restore floor/source metadata onto accepted pairs.
    # --------------------------------------------------------

    plan_by_side = {
        str(
            row.get(
                "side",
                "",
            )
        ).strip().lower():
            list(
                row.get(
                    "openings",
                    [],
                )
                or []
            )

        for row in (
            source[
                "plan_facades"
            ]
        )
    }


    for row in (
        result.get(
            "plan_guided_facade_windows",
            [],
        )
        or []
    ):

        side = str(
            row.get(
                "plan_side",
                "",
            )
            or ""
        ).strip().lower()


        try:
            index = int(
                row.get(
                    "plan_index"
                )
            )
        except Exception:
            continue


        openings = (
            plan_by_side.get(
                side,
                []
            )
        )


        if not (
            0 <= index < len(
                openings
            )
        ):
            continue


        source_window = (
            openings[
                index
            ]
        )


        row[
            "floor_order"
        ] = int(
            source_window.get(
                "floor_order",
                0,
            )
        )

        row[
            "floor_name"
        ] = str(
            source_window.get(
                "floor_name",
                "",
            )
            or ""
        )

        row[
            "source_window_index"
        ] = int(
            source_window.get(
                "source_window_index",
                index,
            )
        )

        row[
            "plan_window_source"
        ] = (
            "multi_floor_3d_packages.windows"
        )


    for match in (
        result.get(
            "matches",
            [],
        )
        or []
    ):

        side = str(
            match.get(
                "plan_side",
                "",
            )
            or ""
        ).strip().lower()

        openings = (
            plan_by_side.get(
                side,
                []
            )
        )


        for pair in (
            match.get(
                "opening_pairs",
                [],
            )
            or []
        ):

            if _kind(
                pair
            ) != "window":
                continue


            try:
                index = int(
                    pair.get(
                        "plan_index"
                    )
                )
            except Exception:
                continue


            if not (
                0 <= index
                < len(
                    openings
                )
            ):
                continue


            source_window = (
                openings[
                    index
                ]
            )


            pair[
                "floor_order"
            ] = int(
                source_window.get(
                    "floor_order",
                    0,
                )
            )

            pair[
                "floor_name"
            ] = str(
                source_window.get(
                    "floor_name",
                    "",
                )
                or ""
            )

            pair[
                "source_window_index"
            ] = int(
                source_window.get(
                    "source_window_index",
                    index,
                )
            )

            pair[
                "plan_window_source"
            ] = (
                "multi_floor_3d_packages.windows"
            )


    summary = dict(
        result.get(
            "plan_guided_summary",
            {}
        )
        or {}
    )

    summary[
        "source_engine"
    ] = MULTI_FLOOR_ENGINE

    summary[
        "source"
    ] = (
        "multi_floor_3d_packages.windows"
    )

    summary[
        "source_window_count"
    ] = source[
        "source_window_count"
    ]

    summary[
        "mapped_window_count"
    ] = source[
        "mapped_window_count"
    ]

    summary[
        "rooflights_excluded"
    ] = source[
        "rooflight_count"
    ]

    result[
        "plan_guided_summary"
    ] = summary


    return result


def finalize_multi_floor_facade_guidance(
    window,
):
    """
    Run AFTER prepare_multi_floor_3d() has produced exact
    plan-window packages.

    RAW facade analysis is written before filtering.
    """

    from pathlib import Path
    import json

    from cad._cad_to_3d_max_facade.facade_matcher import (
        auto_analyse_dwg_facades,
    )


    packages = list(
        getattr(
            window,
            "multi_floor_3d_packages",
            [],
        )
        or []
    )


    if not packages:
        raise RuntimeError(
            "multi_floor_3d_packages is empty"
        )


    cad_data = (
        getattr(
            window,
            "cad_data",
            None,
        )
        or getattr(
            window.preview,
            "cad_data",
            None,
        )
    )


    if not isinstance(
        cad_data,
        dict,
    ):
        raise RuntimeError(
            "DWG cad_data missing"
        )


    full_geometry = list(
        cad_data.get(
            "geometry",
            [],
        )
        or []
    )


    if not full_geometry:
        raise RuntimeError(
            "DWG geometry empty"
        )


    raw = (
        auto_analyse_dwg_facades(
            full_geometry
        )
    )


    root = Path(
        __file__
    ).resolve().parents[2]

    log_dir = (
        root
        / "logs"
    )

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    raw_path = (
        log_dir
        / "facade_match_RAW_before_plan_guided.json"
    )


    raw_path.write_text(
        json.dumps(
            raw,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


    result = (
        apply_multi_floor_plan_guidance(
            raw,
            packages,
        )
    )


    guided_path = (
        log_dir
        / "facade_match_plan_guided.json"
    )


    guided_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


    # Keep the runtime file as the final accepted result.
    runtime_path = (
        log_dir
        / "facade_match_runtime.json"
    )


    runtime_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


    window._cad3d_raw_facade_match_result = (
        raw
    )

    window.current_facade_match_result = (
        result
    )

    window.multi_floor_facade_guidance_result = (
        result
    )


    summary = dict(
        result.get(
            "plan_guided_summary",
            {}
        )
        or {}
    )


    expected = int(
        summary.get(
            "source_window_count",
            0,
        )
        or 0
    )

    accepted = int(
        summary.get(
            "accepted",
            0,
        )
        or 0
    )


    window.multi_floor_facade_guidance_ok = (
        expected > 0
        and accepted == expected
    )


    print("")
    print(
        "=== MULTI FLOOR FACADE GUIDANCE V3 ==="
    )

    print(
        "PLAN SOURCE WINDOWS:",
        expected,
    )

    print(
        "ACCEPTED WINDOWS   :",
        accepted,
    )

    print(
        "UNRESOLVED         :",
        max(
            0,
            expected - accepted,
        ),
    )

    print(
        "COMPLETE           :",
        bool(
            window
            .multi_floor_facade_guidance_ok
        ),
    )

    print(
        "RAW LOG            :",
        raw_path,
    )

    print(
        "GUIDED LOG         :",
        guided_path,
    )

    print(
        "=== END MULTI FLOOR FACADE GUIDANCE V3 ==="
    )
    print("")


    return {
        "ok":
            bool(
                window
                .multi_floor_facade_guidance_ok
            ),

        "expected":
            expected,

        "accepted":
            accepted,

        "unresolved":
            max(
                0,
                expected - accepted,
            ),

        "raw_log":
            str(
                raw_path
            ),

        "guided_log":
            str(
                guided_path
            ),
    }


def _mfpg3_self_test():
    packages = [
        {
            "floor_name":
                "Ground",

            "floor_order":
                0,

            "selection_index":
                0,

            "source_bounds":
                (
                    0.0,
                    0.0,
                    1000.0,
                    800.0,
                ),

            "windows": [
                {
                    "center":
                        (
                            100.0,
                            30.0,
                        ),

                    "direction":
                        (
                            1.0,
                            0.0,
                        ),

                    "width":
                        100.0,
                },

                {
                    "center":
                        (
                            900.0,
                            770.0,
                        ),

                    "direction":
                        (
                            1.0,
                            0.0,
                        ),

                    "width":
                        120.0,
                },

                {
                    "center":
                        (
                            970.0,
                            400.0,
                        ),

                    "direction":
                        (
                            0.0,
                            1.0,
                        ),

                    "width":
                        130.0,
                },
            ],

            "rooflights":
                [],
        },

        {
            "floor_name":
                "First",

            "floor_order":
                1,

            "selection_index":
                1,

            "source_bounds":
                (
                    2000.0,
                    2000.0,
                    3000.0,
                    2800.0,
                ),

            "windows": [
                {
                    "center":
                        (
                            2100.0,
                            2030.0,
                        ),

                    "direction":
                        (
                            1.0,
                            0.0,
                        ),

                    "width":
                        100.0,
                },
            ],

            "rooflights": [
                {
                    "width":
                        50.0,
                }
            ],
        },
    ]

    result = (
        build_multi_floor_plan_facades(
            packages
        )
    )

    assert (
        result[
            "source_window_count"
        ]
        == 4
    ), result

    assert (
        result[
            "mapped_window_count"
        ]
        == 4
    ), result

    assert (
        result[
            "rooflight_count"
        ]
        == 1
    ), result

    print(
        "MULTI FLOOR PLAN WINDOW SOURCE V3 SELF TEST: PASS"
    )


