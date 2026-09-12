from __future__ import annotations


ENGINE = "CAD3D_MULTI_STOREY_FACADE_MATCH_V9"


def _bbox(region):
    box = region.get(
        "bbox",
        [0.0, 0.0, 0.0, 0.0],
    )

    return tuple(
        float(value)
        for value in box[:4]
    )


def _area(region):
    x0, y0, x1, y1 = _bbox(
        region
    )

    return max(
        0.0,
        x1 - x0,
    ) * max(
        0.0,
        y1 - y0,
    )


def _aspect(region):
    x0, y0, x1, y1 = _bbox(
        region
    )

    width = max(
        1.0e-9,
        x1 - x0,
    )

    height = max(
        1.0e-9,
        y1 - y0,
    )

    return width / height


def _region_summary(
    region,
    storey_index,
):
    return {
        "storey_index":
            int(storey_index),

        "region_id":
            region.get(
                "region_id"
            ),

        "bbox":
            list(
                _bbox(region)
            ),

        "item_count":
            int(
                region.get(
                    "item_count",
                    0,
                )
                or 0
            ),

        "semantic_count":
            int(
                region.get(
                    "semantic_count",
                    0,
                )
                or 0
            ),

        "furniture_count":
            int(
                region.get(
                    "furniture_count",
                    0,
                )
                or 0
            ),
    }


def _plan_candidate_score(
    region,
    main_region,
):
    if (
        region.get("region_id")
        ==
        main_region.get("region_id")
    ):
        return None

    item_count = int(
        region.get(
            "item_count",
            0,
        )
        or 0
    )

    semantic_count = int(
        region.get(
            "semantic_count",
            0,
        )
        or 0
    )

    main_items = max(
        1,
        int(
            main_region.get(
                "item_count",
                0,
            )
            or 0
        ),
    )

    main_semantic = max(
        1,
        int(
            main_region.get(
                "semantic_count",
                0,
            )
            or 0
        ),
    )

    # Roof/elevation regions generally do not have the
    # semantic architectural-plan structure that floor
    # plans have.
    if semantic_count <= 0:
        return None

    # Reject small details / legends / notes.
    if item_count < max(
        120,
        int(main_items * 0.20),
    ):
        return None

    if semantic_count < max(
        25,
        int(main_semantic * 0.08),
    ):
        return None

    main_area = max(
        1.0,
        _area(main_region),
    )

    candidate_area = _area(
        region
    )

    area_ratio = (
        candidate_area
        / main_area
    )

    # A second-storey plan should have a footprint
    # comparable to the main floor plan.
    if not (
        0.35
        <= area_ratio
        <= 2.50
    ):
        return None

    main_aspect = _aspect(
        main_region
    )

    candidate_aspect = _aspect(
        region
    )

    aspect_error = abs(
        candidate_aspect
        - main_aspect
    ) / max(
        main_aspect,
        1.0e-9,
    )

    if aspect_error > 0.55:
        return None

    item_ratio = min(
        1.0,
        item_count
        / main_items,
    )

    semantic_ratio = min(
        1.0,
        semantic_count
        / main_semantic,
    )

    area_similarity = (
        1.0
        - min(
            1.0,
            abs(
                1.0
                - area_ratio
            ),
        )
    )

    aspect_similarity = (
        1.0
        - min(
            1.0,
            aspect_error,
        )
    )

    return (
        area_similarity * 4.0
        + aspect_similarity * 3.0
        + item_ratio * 2.0
        + semantic_ratio
    )


def _find_storey_regions(
    regions,
    main_plan,
):
    main_id = main_plan.get(
        "region_id"
    )

    main_region = next(
        (
            region
            for region in regions
            if (
                region.get(
                    "region_id"
                )
                == main_id
            )
        ),
        None,
    )

    if main_region is None:
        return []

    ranked = []

    for region in regions:
        score = _plan_candidate_score(
            region,
            main_region,
        )

        if score is None:
            continue

        ranked.append(
            (
                float(score),
                region,
            )
        )

    ranked.sort(
        key=lambda row: row[0],
        reverse=True,
    )

    # Current requirement:
    # ground floor + one upper floor.
    result = [
        main_region
    ]

    if ranked:
        result.append(
            ranked[0][1]
        )

    return result


def _side_anchor(
    bbox,
    side,
):
    x0, y0, x1, y1 = (
        float(value)
        for value in bbox
    )

    cx = (
        x0 + x1
    ) * 0.5

    cy = (
        y0 + y1
    ) * 0.5

    width = max(
        1.0,
        x1 - x0,
    )

    height = max(
        1.0,
        y1 - y0,
    )

    pad = max(
        width,
        height,
    ) * 0.040

    if side == "top":
        return [
            cx,
            y1 + pad,
        ]

    if side == "bottom":
        return [
            cx,
            y0 - pad,
        ]

    if side == "left":
        return [
            x0 - pad,
            cy,
        ]

    if side == "right":
        return [
            x1 + pad,
            cy,
        ]

    return [
        cx,
        cy,
    ]


def attach_multi_storey_plan_matches(
    analysis,
    regions,
):
    if not isinstance(
        analysis,
        dict,
    ):
        return analysis

    main_plan = analysis.get(
        "main_plan"
    )

    ground_matches = list(
        analysis.get(
            "matches",
            [],
        )
        or []
    )

    if (
        not isinstance(
            main_plan,
            dict,
        )
        or not ground_matches
    ):
        analysis[
            "multi_storey_match"
        ] = {
            "engine":
                ENGINE,

            "ok":
                False,

            "reason":
                "MAIN_PLAN_OR_GROUND_MATCHES_MISSING",
        }

        return analysis

    storey_regions = (
        _find_storey_regions(
            list(
                regions
                or []
            ),
            main_plan,
        )
    )

    if not storey_regions:
        return analysis

    main_region = storey_regions[0]

    ground_result = []

    for source in ground_matches:
        row = dict(
            source
        )

        row[
            "storey_index"
        ] = 0

        row[
            "plan_region_id"
        ] = main_region.get(
            "region_id"
        )

        row[
            "storey_match_source"
        ] = (
            "GROUND_FLOOR_PHYSICAL_MATCH"
        )

        ground_result.append(
            row
        )

    all_matches = list(
        ground_result
    )

    storey_groups = [
        {
            "storey_index":
                0,

            "plan_region_id":
                main_region.get(
                    "region_id"
                ),

            "matches":
                ground_result,
        }
    ]

    # Upper storeys DO NOT solve facade identity again.
    # Building orientation is inherited from the proven
    # ground-floor facade correspondence.
    for storey_index, region in enumerate(
        storey_regions[1:],
        start=1,
    ):
        bbox = _bbox(
            region
        )

        inherited = []

        for source in ground_result:
            side = source.get(
                "plan_side"
            )

            if side not in (
                "top",
                "bottom",
                "left",
                "right",
            ):
                continue

            row = {
                "facade_number":
                    source.get(
                        "facade_number"
                    ),

                "plan_side":
                    side,

                "plan_anchor":
                    _side_anchor(
                        bbox,
                        side,
                    ),

                # Keep same elevation anchor so the existing
                # overlay can continue showing the elevation
                # number without any UI rewrite.
                "facade_anchor":
                    source.get(
                        "facade_anchor"
                    ),

                "reversed":
                    source.get(
                        "reversed",
                        False,
                    ),

                "storey_index":
                    int(
                        storey_index
                    ),

                "plan_region_id":
                    region.get(
                        "region_id"
                    ),

                "storey_match_source":
                    (
                        "INHERITED_BUILDING_ORIENTATION"
                    ),

                # Window/opening correspondence for this
                # storey will be populated separately.
                "opening_pairs":
                    [],
            }

            inherited.append(
                row
            )

            all_matches.append(
                row
            )

        storey_groups.append(
            {
                "storey_index":
                    int(
                        storey_index
                    ),

                "plan_region_id":
                    region.get(
                        "region_id"
                    ),

                "matches":
                    inherited,
            }
        )

    analysis[
        "storey_plan_regions"
    ] = [
        _region_summary(
            region,
            index,
        )
        for index, region
        in enumerate(
            storey_regions
        )
    ]

    analysis[
        "storey_matches"
    ] = storey_groups

    # Existing UI reads "matches".
    # Flattening here causes the same facade numbers to
    # appear on BOTH floor plans.
    analysis[
        "matches"
    ] = all_matches

    analysis[
        "multi_storey_match"
    ] = {
        "engine":
            ENGINE,

        "ok":
            len(
                storey_regions
            ) >= 2,

        "storey_count":
            len(
                storey_regions
            ),

        "rule":
            (
                "UPPER_STOREYS_INHERIT_GROUND_"
                "FLOOR_FACADE_ORIENTATION"
            ),
    }

    return analysis


def self_test():
    regions = [
        {
            "region_id": "GROUND",
            "bbox": [
                0.0,
                0.0,
                18000.0,
                11000.0,
            ],
            "item_count": 2300,
            "semantic_count": 1800,
            "furniture_count": 2,
        },
        {
            "region_id": "FIRST",
            "bbox": [
                22000.0,
                0.0,
                37000.0,
                11000.0,
            ],
            "item_count": 900,
            "semantic_count": 420,
            "furniture_count": 5,
        },
        {
            "region_id": "ROOF",
            "bbox": [
                42000.0,
                0.0,
                59000.0,
                11000.0,
            ],
            "item_count": 700,
            "semantic_count": 0,
            "furniture_count": 0,
        },
        {
            "region_id": "DETAIL",
            "bbox": [
                0.0,
                15000.0,
                3000.0,
                17000.0,
            ],
            "item_count": 100,
            "semantic_count": 80,
            "furniture_count": 0,
        },
    ]

    analysis = {
        "main_plan": {
            "region_id": "GROUND",
        },

        "matches": [
            {
                "facade_number": 1,
                "plan_side": "bottom",
                "plan_anchor": [9000.0, -500.0],
                "facade_anchor": [10000.0, -5000.0],
            },
            {
                "facade_number": 2,
                "plan_side": "right",
                "plan_anchor": [18500.0, 5500.0],
                "facade_anchor": [20000.0, -5000.0],
            },
            {
                "facade_number": 3,
                "plan_side": "left",
                "plan_anchor": [-500.0, 5500.0],
                "facade_anchor": [30000.0, -5000.0],
            },
            {
                "facade_number": 4,
                "plan_side": "top",
                "plan_anchor": [9000.0, 11500.0],
                "facade_anchor": [40000.0, -5000.0],
            },
        ],
    }

    result = (
        attach_multi_storey_plan_matches(
            analysis,
            regions,
        )
    )

    assert (
        result[
            "multi_storey_match"
        ][
            "storey_count"
        ]
        == 2
    ), result

    assert [
        row[
            "region_id"
        ]
        for row in result[
            "storey_plan_regions"
        ]
    ] == [
        "GROUND",
        "FIRST",
    ], result

    assert (
        len(
            result["matches"]
        )
        == 8
    ), result

    upper = [
        row
        for row in result[
            "matches"
        ]
        if (
            row.get(
                "storey_index"
            )
            == 1
        )
    ]

    assert {
        (
            row[
                "plan_side"
            ],
            row[
                "facade_number"
            ],
        )
        for row in upper
    } == {
        ("bottom", 1),
        ("right", 2),
        ("left", 3),
        ("top", 4),
    }, upper

    print(
        "MULTI STOREY FACADE MATCH V9 SELF-TEST: OK"
    )

    print(
        "GROUND + FIRST FLOOR DETECTED"
    )

    print(
        "ROOF PLAN EXCLUDED"
    )

    print(
        "UPPER FLOOR INHERITS FACADE ORIENTATION"
    )


if __name__ == "__main__":
    self_test()
