from __future__ import annotations

# CAD3D_AUTO_FACADE_PORT_V1
#
# CAD_to_3D_Max facade algorithms are kept in the private
# _cad_to_3d_max_facade compatibility package.
#
# THIS MODULE ONLY adapts current 3Dcad data structures.
#
# It does NOT modify:
# - window detector
# - door detector
# - wall detector
# - pivot
# - BASE_Z
# - Max sender
# - MaxScript
# - viewport geometry

from copy import deepcopy
import json
import math
from pathlib import Path
from statistics import median

from cad.door_detector import (
    detect_interior_doors,
)

from cad.window_detector import (
    detect_window_family,
)

from export.multi_floor_max_send import (
    floor_index_from_name,
)

from cad._cad_to_3d_max_facade import (
    facade_matcher as legacy_facade,
)

from cad._cad_to_3d_max_facade.elevation_opening_detector import (
    detect_elevation_openings as detect_physical_elevation_openings,
)

from cad._cad_to_3d_max_facade import (
    plan_guided_facade_windows as legacy_guidance,
)


ENGINE = "CAD3D_AUTO_FACADE_PORT_V1"

PLAN_WINDOW_SOURCE = (
    "3Dcad.confirmed_floors.window_detector"
)


def _project_root() -> Path:
    return (
        Path(__file__)
        .resolve()
        .parents[2]
    )


def _write_json(
    filename,
    payload,
):
    target = (
        _project_root()
        / "logs"
        / filename
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
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


def _bounds_tuple(value):
    if not (
        isinstance(
            value,
            (tuple, list),
        )
        and len(value) == 4
    ):
        return None

    try:
        x0, y0, x1, y1 = (
            float(v)
            for v in value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if x0 > x1:
        x0, x1 = x1, x0

    if y0 > y1:
        y0, y1 = y1, y0

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


def _intersection_area(
    a,
    b,
):
    a = _bounds_tuple(a)
    b = _bounds_tuple(b)

    if (
        a is None
        or b is None
    ):
        return 0.0

    x0 = max(
        a[0],
        b[0],
    )

    y0 = max(
        a[1],
        b[1],
    )

    x1 = min(
        a[2],
        b[2],
    )

    y1 = min(
        a[3],
        b[3],
    )

    return (
        max(
            0.0,
            x1 - x0,
        )
        *
        max(
            0.0,
            y1 - y0,
        )
    )


def _document_geometry(
    document,
):
    if document is None:
        return []

    output = []

    for primitive in (
        getattr(
            document,
            "primitives",
            (),
        )
        or ()
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
                point = (
                    float(raw_point[0]),
                    float(raw_point[1]),
                )
            except (
                TypeError,
                ValueError,
                IndexError,
            ):
                continue

            points.append(
                point
            )

        if len(points) < 2:
            continue

        closed = bool(
            getattr(
                primitive,
                "closed",
                False,
            )
        )

        # The old geometry pipeline consumed explicit
        # closing segments.
        if (
            closed
            and len(points) > 2
            and points[0] != points[-1]
        ):
            points.append(
                points[0]
            )

        source_type = str(
            getattr(
                primitive,
                "source_type",
                "",
            )
            or ""
        )

        output.append(
            {
                "points":
                    [
                        [
                            float(point[0]),
                            float(point[1]),
                        ]
                        for point in points
                    ],

                "layer":
                    str(
                        getattr(
                            primitive,
                            "layer",
                            "",
                        )
                        or ""
                    ),

                "closed":
                    closed,

                "source_closed":
                    closed,

                "type":
                    (
                        source_type
                        or (
                            "LWPOLYLINE"
                            if len(points) > 2
                            else "LINE"
                        )
                    ),

                "source_type":
                    source_type,
            }
        )

    return output


def _region_diagnostic(
    region,
):
    if not isinstance(
        region,
        dict,
    ):
        return {}

    return {
        "region_id":
            region.get(
                "region_id"
            ),

        "bbox":
            region.get(
                "bbox"
            ),

        "item_count":
            region.get(
                "item_count",
                0,
            ),

        "semantic_count":
            region.get(
                "semantic_count",
                0,
            ),

        "furniture_count":
            region.get(
                "furniture_count",
                0,
            ),

        "hatch_count":
            region.get(
                "hatch_count",
                0,
            ),

        "generic_count":
            region.get(
                "generic_count",
                0,
            ),
    }


def _choose_main_region(
    regions,
    selected_bounds,
):
    selected_bounds = (
        _bounds_tuple(
            selected_bounds
        )
    )

    overlapping = []

    if selected_bounds is not None:
        for region in regions:
            area = _intersection_area(
                region.get(
                    "bbox"
                ),
                selected_bounds,
            )

            if area <= 0.0:
                continue

            overlapping.append(
                (
                    float(area),
                    region,
                )
            )

    overlapping.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    candidates = [
        row[1]
        for row in overlapping
    ]

    main_plan = None

    if candidates:
        main_plan = (
            legacy_facade
            .choose_main_plan_region(
                candidates
            )
        )

        # New 3Dcad already has an authoritative user-selected
        # plan area. If old semantic scoring cannot classify it,
        # use the strongest overlapping drawing island.
        if main_plan is None:
            main_plan = (
                candidates[0]
            )

    if main_plan is None:
        main_plan = (
            legacy_facade
            .choose_main_plan_region(
                regions
            )
        )

    return main_plan



def preanalyse_facades(
    window,
):
    """
    CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2

    Explicit PRE-PLAN-SELECTION facade workflow.

    The full CAD is analysed before Plan Sec.

    Exact old CAD_to_3D_Max registration method:
        detect drawing regions
        choose main plan
        choose elevations
        build plan facades
        match facade number <-> plan side

    The registration result survives Plan Sec and becomes
    the base data for later plan-guided vertical measurements.
    """

    full_document = getattr(
        window,
        "_full_document",
        None,
    )

    if full_document is None:
        raise RuntimeError(
            "Once Mimari CAD Ekleyin."
        )

    geometry = (
        _document_geometry(
            full_document
        )
    )

    if not geometry:
        raise RuntimeError(
            "CAD geometrisi bos."
        )

    # --------------------------------------------------------
    # EXACT OLD PRESELECTION / REGISTRATION METHOD
    # --------------------------------------------------------

    result = (
        legacy_facade
        .auto_analyse_dwg_facades(
            geometry
        )
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Cephe analiz sonucu gecersiz."
        )

    main_plan = result.get(
        "main_plan"
    )

    if not isinstance(
        main_plan,
        dict,
    ):
        raise RuntimeError(
            "Ana plan otomatik bulunamadi."
        )

    elevation_facades = list(
        result.get(
            "elevation_facades",
            [],
        )
        or []
    )

    if not elevation_facades:
        raise RuntimeError(
            "Cephe cizimi otomatik bulunamadi."
        )

    # --------------------------------------------------------
    # Keep the OLD facade registration / numbering,
    # but refine the physical openings with the newer
    # proven elevation opening detector.
    # --------------------------------------------------------

    region_by_id = {}

    for region in (
        result.get(
            "regions",
            [],
        )
        or []
    ):
        if not isinstance(
            region,
            dict,
        ):
            continue

        region_id = region.get(
            "region_id"
        )

        if region_id is not None:
            region_by_id[
                str(region_id)
            ] = region

    refined_count = 0

    for facade in elevation_facades:

        if not isinstance(
            facade,
            dict,
        ):
            continue

        region_id = str(
            facade.get(
                "region_id",
                "",
            )
            or ""
        )

        region = region_by_id.get(
            region_id
        )

        if not isinstance(
            region,
            dict,
        ):
            continue

        bbox = facade.get(
            "bbox"
        )

        if not (
            isinstance(
                bbox,
                (tuple, list),
            )
            and len(bbox) == 4
        ):
            continue

        try:
            box = tuple(
                float(value)
                for value in bbox
            )
        except Exception:
            continue

        region_geometry = list(
            region.get(
                "geometry",
                [],
            )
            or []
        )

        if not region_geometry:
            continue

        try:
            detection = (
                detect_physical_elevation_openings(
                    region_geometry,
                    box,
                    all_storeys=True,
                )
            )

        except TypeError:
            detection = (
                detect_physical_elevation_openings(
                    region_geometry,
                    box,
                )
            )

        except Exception as exc:
            print(
                "FACADE PHYSICAL OPENING WARNING:",
                region_id,
                repr(exc),
            )
            continue

        entities = [
            dict(row)
            for row in (
                detection.get(
                    "entities",
                    [],
                )
                or []
            )
            if isinstance(
                row,
                dict,
            )
        ]

        if not entities:
            continue

        facade[
            "openings"
        ] = entities

        facade[
            "signature"
        ] = [
            str(
                row.get(
                    "signature_kind",
                    row.get(
                        "kind",
                        "",
                    ),
                )
                or ""
            )
            for row in entities
        ]

        facade[
            "detection_engine"
        ] = detection.get(
            "engine"
        )

        facade[
            "window_count"
        ] = detection.get(
            "window_count",
            0,
        )

        facade[
            "door_count"
        ] = detection.get(
            "door_count",
            0,
        )

        refined_count += 1

    result[
        "elevation_facades"
    ] = elevation_facades

    result[
        "engine"
    ] = (
        "CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2"
    )

    result[
        "legacy_registration_engine"
    ] = getattr(
        legacy_facade,
        "ENGINE",
        "",
    )

    result[
        "facade_analysis_stage"
    ] = "RAW_PRESELECTION_ONLY"

    result[
        "plan_guided_applied"
    ] = False

    result[
        "preselection_ready"
    ] = True

    result[
        "physical_facades_refined"
    ] = int(
        refined_count
    )

    # --------------------------------------------------------
    # RUNTIME STATE
    #
    # IMPORTANT:
    # Plan Sec MUST NOT delete this.
    # --------------------------------------------------------

    window._cad3d_facade_preanalysis = (
        result
    )

    window.current_facade_match_result = (
        result
    )

    # --------------------------------------------------------
    # PERSISTENT DATA
    # --------------------------------------------------------

    runtime_log = _write_json(
        "facade_match_runtime.json",
        result,
    )

    raw_log = _write_json(
        "facade_windows_button_RAW.json",
        result,
    )

    cache_path = (
        _project_root()
        / "data"
        / "cache"
        / "facade"
        / "facade_preselection.json"
    )

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    facades = list(
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

    print("")
    print(
        "=== 3DCAD FACADE MATCH PRESELECTION V2 ==="
    )

    print(
        "FACADES:",
        len(facades),
    )

    print(
        "PLAN/FACADE MATCHES:",
        len(matches),
    )

    for match in matches:
        print(
            "FACADE",
            match.get(
                "facade_number"
            ),
            "<-> PLAN",
            match.get(
                "plan_side"
            ),
            "| COST:",
            match.get(
                "cost"
            ),
        )

    print(
        "PHYSICAL FACADES REFINED:",
        refined_count,
    )

    print(
        "RUNTIME LOG:",
        runtime_log,
    )

    print(
        "RAW LOG:",
        raw_log,
    )

    print(
        "CACHE:",
        cache_path,
    )

    print(
        "=== END FACADE MATCH PRESELECTION ==="
    )
    print("")

    return result


def _window_candidate_record(
    candidate,
):
    corners = []

    for raw in (
        getattr(
            candidate,
            "corners",
            (),
        )
        or ()
    ):
        try:
            corners.append(
                (
                    float(raw[0]),
                    float(raw[1]),
                )
            )
        except (
            TypeError,
            ValueError,
            IndexError,
        ):
            continue

    if len(corners) != 4:
        return None

    cx = (
        sum(
            point[0]
            for point in corners
        )
        / 4.0
    )

    cy = (
        sum(
            point[1]
            for point in corners
        )
        / 4.0
    )

    edges = []

    for index in range(4):
        a = corners[index]
        b = corners[
            (index + 1)
            % 4
        ]

        dx = (
            b[0]
            - a[0]
        )

        dy = (
            b[1]
            - a[1]
        )

        length = math.hypot(
            dx,
            dy,
        )

        if length <= 1.0e-9:
            continue

        edges.append(
            (
                length,
                dx / length,
                dy / length,
            )
        )

    if not edges:
        return None

    width, ux, uy = max(
        edges,
        key=lambda row:
            row[0],
    )

    return {
        "center":
            (
                float(cx),
                float(cy),
            ),

        "direction":
            (
                float(ux),
                float(uy),
            ),

        "width":
            float(width),

        "source":
            PLAN_WINDOW_SOURCE,
    }


def _build_current_packages(
    window,
):
    floors = [
        row
        for row in (
            getattr(
                window,
                "_confirmed_floors",
                (),
            )
            or ()
        )
        if isinstance(
            row,
            dict,
        )
    ]

    packages = []

    for selection_index, floor in enumerate(
        floors
    ):
        document = floor.get(
            "document"
        )

        bounds = _bounds_tuple(
            floor.get(
                "bounds"
            )
        )

        floor_name = str(
            floor.get(
                "name",
                "",
            )
            or ""
        ).strip()

        if (
            document is None
            or bounds is None
            or not floor_name
        ):
            continue

        floor_order = (
            floor_index_from_name(
                floor_name
            )
        )

        # Preserve current 3Dcad detector order dependency:
        # current window detector receives current door results.
        doors = tuple(
            detect_interior_doors(
                document
            )
        )

        window_result = (
            detect_window_family(
                document,
                doors,
            )
        )

        candidates = tuple(
            getattr(
                window_result,
                "windows",
                (),
            )
            or ()
        )

        windows = []

        for source_index, candidate in enumerate(
            candidates
        ):
            record = (
                _window_candidate_record(
                    candidate
                )
            )

            if record is None:
                continue

            record[
                "source_window_index"
            ] = int(
                source_index
            )

            windows.append(
                record
            )

        packages.append(
            {
                "floor_name":
                    floor_name,

                "floor_order":
                    int(
                        floor_order
                    ),

                "selection_index":
                    int(
                        selection_index
                    ),

                "source_bounds":
                    bounds,

                # IMPORTANT:
                # Current detector output is authoritative.
                # No additional rooflight exclusion is introduced.
                "windows":
                    windows,

                "rooflights":
                    [],
            }
        )

    packages.sort(
        key=lambda row:
            (
                int(
                    row[
                        "floor_order"
                    ]
                ),
                int(
                    row[
                        "selection_index"
                    ]
                ),
            )
    )

    return packages


def _side_widths(
    packages,
):
    values = {
        "bottom": [],
        "right": [],
        "top": [],
        "left": [],
    }

    for package in packages:
        bounds = _bounds_tuple(
            package.get(
                "source_bounds"
            )
        )

        if bounds is None:
            continue

        width = max(
            bounds[2] - bounds[0],
            1.0,
        )

        height = max(
            bounds[3] - bounds[1],
            1.0,
        )

        values[
            "bottom"
        ].append(
            width
        )

        values[
            "top"
        ].append(
            width
        )

        values[
            "left"
        ].append(
            height
        )

        values[
            "right"
        ].append(
            height
        )

    return {
        side:
            (
                float(
                    median(rows)
                )
                if rows
                else 1.0
            )
        for side, rows
        in values.items()
    }


def _registration_plan_facades(
    source,
    packages,
):
    """
    Old raw facade matcher needs expected_width, anchor
    and signature fields.

    Multi-floor V3 intentionally stores a smaller schema,
    so these fields are added only for facade registration.
    """

    facades = deepcopy(
        source.get(
            "plan_facades",
            [],
        )
        or []
    )

    expected_widths = (
        _side_widths(
            packages
        )
    )

    for facade in facades:
        side = str(
            facade.get(
                "side",
                "",
            )
            or ""
        ).strip().lower()

        openings = list(
            facade.get(
                "openings",
                [],
            )
            or []
        )

        widths = []

        for opening in openings:
            try:
                value = float(
                    opening.get(
                        "width",
                        0.0,
                    )
                    or 0.0
                )
            except Exception:
                value = 0.0

            if value > 0.0:
                widths.append(
                    value
                )

        typical = (
            float(
                median(
                    widths
                )
            )
            if widths
            else 0.0
        )

        for opening in openings:
            try:
                width = float(
                    opening.get(
                        "width",
                        0.0,
                    )
                    or 0.0
                )
            except Exception:
                width = 0.0

            if (
                typical > 0.0
                and width
                > typical * 1.65
            ):
                opening[
                    "signature_kind"
                ] = "wide_window"
            else:
                opening[
                    "signature_kind"
                ] = "window"

        facade[
            "expected_width"
        ] = float(
            expected_widths.get(
                side,
                1.0,
            )
        )

        facade[
            "anchor"
        ] = (
            0.0,
            0.0,
        )

        facade[
            "signature"
        ] = [
            opening.get(
                "signature_kind",
                "window",
            )
            for opening
            in openings
        ]

    return facades


def _rewrite_source_metadata(
    result,
):
    if not isinstance(
        result,
        dict,
    ):
        return result

    source_info = result.get(
        "plan_window_source"
    )

    if isinstance(
        source_info,
        dict,
    ):
        source_info[
            "source"
        ] = PLAN_WINDOW_SOURCE

        # Explicit current policy:
        # no rooflight exclusion is performed here.
        source_info[
            "rooflight_count"
        ] = 0

    for row in (
        result.get(
            "plan_guided_facade_windows",
            [],
        )
        or []
    ):
        if isinstance(
            row,
            dict,
        ):
            row[
                "plan_window_source"
            ] = PLAN_WINDOW_SOURCE

    for match in (
        result.get(
            "matches",
            [],
        )
        or []
    ):
        if not isinstance(
            match,
            dict,
        ):
            continue

        for pair in (
            match.get(
                "opening_pairs",
                [],
            )
            or []
        ):
            if not isinstance(
                pair,
                dict,
            ):
                continue

            if str(
                pair.get(
                    "kind",
                    "",
                )
                or ""
            ).strip().lower() != "window":
                continue

            pair[
                "plan_window_source"
            ] = PLAN_WINDOW_SOURCE

    summary = dict(
        result.get(
            "plan_guided_summary",
            {},
        )
        or {}
    )

    summary[
        "source"
    ] = PLAN_WINDOW_SOURCE

    summary[
        "rooflights_excluded"
    ] = 0

    summary[
        "rooflight_policy"
    ] = (
        "NO_SPECIAL_ROOFLIGHT_EXCLUSION"
    )

    result[
        "plan_guided_summary"
    ] = summary

    result[
        "cad3d_facade_port"
    ] = {
        "engine":
            ENGINE,

        "plan_window_source":
            PLAN_WINDOW_SOURCE,

        "rooflight_exclusion":
            False,
    }

    return result


def refresh_facade_matches(
    window,
):
    """
    Rebuild facade matching from CURRENT confirmed-floor
    window detections.

    This is called after each floor confirmation.
    """

    raw = getattr(
        window,
        "_cad3d_facade_preanalysis",
        None,
    )

    if not isinstance(
        raw,
        dict,
    ):
        raw = (
            preanalyse_facades(
                window
            )
        )

    elevation_facades = list(
        raw.get(
            "elevation_facades",
            [],
        )
        or []
    )

    packages = (
        _build_current_packages(
            window
        )
    )

    if not packages:
        window.current_facade_match_result = (
            raw
        )
        return raw

    source = (
        legacy_guidance
        .build_multi_floor_plan_facades(
            packages
        )
    )

    registration_facades = (
        _registration_plan_facades(
            source,
            packages,
        )
    )

    analysis = deepcopy(
        raw
    )

    analysis[
        "plan_facades"
    ] = registration_facades

    analysis[
        "matches"
    ] = (
        legacy_facade
        .match_facades(
            registration_facades,
            elevation_facades,
        )
    )

    # Exact final CAD_to_3D_Max V3 plan-guided method.
    result = (
        legacy_guidance
        .apply_multi_floor_plan_guidance(
            analysis,
            packages,
        )
    )

    result = (
        _rewrite_source_metadata(
            result
        )
    )

    window._cad3d_facade_packages = (
        packages
    )

    window.current_facade_match_result = (
        result
    )

    result_path = _write_json(
        "facade_windows_button_RESULT.json",
        result,
    )

    summary = dict(
        result.get(
            "plan_guided_summary",
            {},
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

    print("")
    print(
        "=== 3DCAD AUTO FACADE PORT V1 ==="
    )
    print(
        "CONFIRMED FLOORS:",
        len(
            packages
        ),
    )
    print(
        "ELEVATION FACADES:",
        len(
            elevation_facades
        ),
    )
    print(
        "PLAN WINDOWS:",
        expected,
    )
    print(
        "FACADE MATCH ROWS:",
        len(
            result.get(
                "matches",
                [],
            )
            or []
        ),
    )
    print(
        "ACCEPTED WINDOWS:",
        accepted,
    )
    print(
        "UNRESOLVED:",
        max(
            0,
            expected - accepted,
        ),
    )
    print(
        "RESULT LOG:",
        result_path,
    )
    print(
        "=== END AUTO FACADE PORT ==="
    )
    print("")

    return result
