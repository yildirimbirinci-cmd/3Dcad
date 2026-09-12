from __future__ import annotations

from pathlib import Path
from datetime import datetime
import shutil
import sys


ROOT = Path.cwd()

if ROOT.name.lower() != "3dcad":
    raise RuntimeError(
        "3Dcad proje kokunde calistirin. DOSYALARA DOKUNULMADI."
    )

OLD_ROOT = Path(
    r"C:\Users\yildi\Desktop\CAD_to_3D_Max"
)

MAIN = (
    ROOT
    / "src"
    / "ui"
    / "main_window.py"
)

RUNTIME = (
    ROOT
    / "src"
    / "cad"
    / "facade_runtime.py"
)

VENDOR_DIR = (
    ROOT
    / "src"
    / "cad"
    / "_cad_to_3d_max_facade"
)

MARKER = "CAD3D_AUTO_FACADE_PORT_V1"


if not MAIN.exists():
    raise RuntimeError(
        "src/ui/main_window.py bulunamadi."
    )


main_text = MAIN.read_text(
    encoding="utf-8-sig"
)


if MARKER in main_text:
    required = (
        RUNTIME,
        VENDOR_DIR / "facade_matcher.py",
        VENDOR_DIR / "elevation_opening_detector.py",
        VENDOR_DIR / "plan_guided_facade_windows.py",
    )

    if all(path.exists() for path in required):
        print(
            "CAD3D_AUTO_FACADE_PORT_V1 ALREADY INSTALLED"
        )
        sys.exit(0)

    raise RuntimeError(
        "Facade marker mevcut fakat runtime dosyalari eksik. "
        "DOSYALARA DOKUNULMADI."
    )


OLD_CAD = (
    OLD_ROOT
    / "src"
    / "cad"
)

source_files = {
    "facade_matcher.py":
        OLD_CAD / "facade_matcher.py",

    "elevation_opening_detector.py":
        OLD_CAD / "elevation_opening_detector.py",

    "plan_guided_facade_windows.py":
        OLD_CAD / "plan_guided_facade_windows.py",

    "cad_intelligence.py":
        OLD_CAD / "cad_intelligence.py",
}


for name, path in source_files.items():
    if not path.exists():
        raise RuntimeError(
            "Eski kaynak bulunamadi: "
            + str(path)
            + " | DOSYALARA DOKUNULMADI."
        )


vendor_texts = {}

for name, path in source_files.items():
    text = path.read_text(
        encoding="utf-8-sig"
    )

    text = text.replace(
        "from src.cad.cad_intelligence",
        "from cad._cad_to_3d_max_facade.cad_intelligence",
    )

    text = text.replace(
        "from src.cad.elevation_opening_detector",
        "from cad._cad_to_3d_max_facade.elevation_opening_detector",
    )

    text = text.replace(
        "from src.cad.facade_matcher",
        "from cad._cad_to_3d_max_facade.facade_matcher",
    )

    vendor_texts[name] = text


runtime_text = r'''from __future__ import annotations

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
    Silent old-style facade discovery.

    Runs against FULL CAD, not viewport state.
    Selected plan bounds are used only to identify the
    main plan region.
    """

    full_document = getattr(
        window,
        "_full_document",
        None,
    )

    selected_document = getattr(
        window,
        "_selected_document",
        None,
    )

    if full_document is None:
        raise RuntimeError(
            "Tam CAD dokumani yok."
        )

    geometry = (
        _document_geometry(
            full_document
        )
    )

    if not geometry:
        raise RuntimeError(
            "Tam CAD geometrisi bos."
        )

    selected_bounds = getattr(
        selected_document,
        "bounds",
        None,
    )

    full_bounds = (
        legacy_facade
        .geometry_bounds(
            geometry
        )
    )

    regions = list(
        legacy_facade
        .detect_drawing_regions(
            geometry
        )
        or []
    )

    main_plan = (
        _choose_main_region(
            regions,
            selected_bounds,
        )
    )

    if main_plan is None:
        result = {
            "engine":
                ENGINE,

            "legacy_engine":
                getattr(
                    legacy_facade,
                    "ENGINE",
                    "",
                ),

            "full_bounds":
                full_bounds,

            "regions":
                [
                    _region_diagnostic(
                        region
                    )
                    for region
                    in regions
                ],

            "main_plan":
                None,

            "plan_facades":
                [],

            "elevation_facades":
                [],

            "matches":
                [],
        }

        window._cad3d_facade_preanalysis = (
            result
        )

        window.current_facade_match_result = (
            result
        )

        _write_json(
            "facade_windows_button_RAW.json",
            result,
        )

        return result

    elevation_regions = list(
        legacy_facade
        .choose_elevation_regions(
            regions,
            main_plan,
        )
        or []
    )

    elevation_facades = []

    for region in elevation_regions:
        box = _bounds_tuple(
            region.get(
                "bbox"
            )
        )

        if box is None:
            continue

        region_geometry = list(
            region.get(
                "geometry",
                [],
            )
            or []
        )

        # New application can contain several storeys
        # inside one elevation drawing.
        try:
            detection = (
                detect_physical_elevation_openings(
                    region_geometry,
                    box,
                    all_storeys=True,
                )
            )

        except TypeError:
            # Compatibility with an older detector signature.
            detection = (
                detect_physical_elevation_openings(
                    region_geometry,
                    box,
                )
            )

        openings = [
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

        height = max(
            box[3] - box[1],
            1.0,
        )

        elevation_facades.append(
            {
                "facade_number":
                    region.get(
                        "facade_number"
                    ),

                "region_id":
                    region.get(
                        "region_id"
                    ),

                "bbox":
                    box,

                "anchor":
                    (
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

                "signature":
                    [
                        str(
                            opening.get(
                                "signature_kind",
                                opening.get(
                                    "kind",
                                    "",
                                ),
                            )
                            or ""
                        )
                        for opening
                        in openings
                    ],

                "detection_engine":
                    detection.get(
                        "engine"
                    ),

                "window_count":
                    detection.get(
                        "window_count",
                        0,
                    ),

                "door_count":
                    detection.get(
                        "door_count",
                        0,
                    ),
            }
        )

    result = {
        "engine":
            ENGINE,

        "legacy_engine":
            getattr(
                legacy_facade,
                "ENGINE",
                "",
            ),

        "full_bounds":
            full_bounds,

        "regions":
            [
                _region_diagnostic(
                    region
                )
                for region
                in regions
            ],

        "main_plan":
            _region_diagnostic(
                main_plan
            ),

        "plan_facades":
            [],

        "elevation_facades":
            elevation_facades,

        "matches":
            [],
    }

    window._cad3d_facade_preanalysis = (
        result
    )

    window.current_facade_match_result = (
        result
    )

    raw_path = _write_json(
        "facade_windows_button_RAW.json",
        result,
    )

    print("")
    print(
        "=== 3DCAD AUTO FACADE PREANALYSIS V1 ==="
    )
    print(
        "DRAWING REGIONS:",
        len(regions),
    )
    print(
        "ELEVATION FACADES:",
        len(
            elevation_facades
        ),
    )
    print(
        "RAW LOG:",
        raw_path,
    )
    print(
        "=== END AUTO FACADE PREANALYSIS ==="
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
'''


def replace_once(
    text,
    old,
    new,
    label,
):
    count = text.count(
        old
    )

    if count != 1:
        raise RuntimeError(
            f"{label}: beklenen 1 anchor, bulunan {count}. "
            "DOSYALARA DOKUNULMADI."
        )

    return text.replace(
        old,
        new,
        1,
    )


# ============================================================
# MAIN WINDOW HOOKS
# ============================================================

old = '''        # CAD_TO_3D_MAX_PIVOT_SESSION_V1
        self.floor_pivots = {}
        self.ground_pivot_reference = None
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""


    def _build_ui(self) -> None:
'''

new = '''        # CAD_TO_3D_MAX_PIVOT_SESSION_V1
        self.floor_pivots = {}
        self.ground_pivot_reference = None
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""

        # CAD3D_AUTO_FACADE_PORT_V1
        self._cad3d_facade_preanalysis = None
        self._cad3d_facade_packages = []
        self.current_facade_match_result = None


    def _build_ui(self) -> None:
'''

main_new = replace_once(
    main_text,
    old,
    new,
    "INIT FACADE STATE",
)


old = '''        self._prepare_plan_objects()

        self.window_btn.setEnabled(True)
'''

new = '''        self._prepare_plan_objects()

        # CAD3D_AUTO_FACADE_PORT_V1
        # Old final behavior:
        # facade regions are analysed silently after main Plan Sec.
        self._cad3d_facade_preanalysis = None
        self._cad3d_facade_packages = []
        self.current_facade_match_result = None

        try:
            from cad.facade_runtime import (
                preanalyse_facades,
            )

            preanalyse_facades(
                self
            )

        except Exception as exc:
            print(
                "AUTO FACADE PREANALYSIS WARNING:",
                repr(exc),
            )

        self.window_btn.setEnabled(True)
'''

main_new = replace_once(
    main_new,
    old,
    new,
    "PLAN SELECT FACADE HOOK",
)


old = '''        self._save_pivot_records()

        # Kat adi sadece UI etiketi olarak mevcut view'a eklenir.
'''

new = '''        self._save_pivot_records()

        # CAD3D_AUTO_FACADE_PORT_V1
        # Confirmed floors are now the authoritative plan-window source.
        try:
            from cad.facade_runtime import (
                refresh_facade_matches,
            )

            refresh_facade_matches(
                self
            )

        except Exception as exc:
            # Facade analysis must never invalidate an otherwise valid
            # floor confirmation.
            print(
                "AUTO FACADE MATCH WARNING:",
                repr(exc),
            )

        # Kat adi sadece UI etiketi olarak mevcut view'a eklenir.
'''

main_new = replace_once(
    main_new,
    old,
    new,
    "FLOOR CONFIRM FACADE HOOK",
)


old = '''        self._current_path = path
        self._full_document = document
        self._set_main_cad_action_buttons_enabled(True)
        self._set_cad_menu_mode(False)
        self._selected_document = None
        self._confirmed_floors = []
'''

new = '''        self._current_path = path
        self._full_document = document
        self._set_main_cad_action_buttons_enabled(True)
        self._set_cad_menu_mode(False)
        self._selected_document = None
        self._confirmed_floors = []

        # CAD3D_AUTO_FACADE_PORT_V1
        self._cad3d_facade_preanalysis = None
        self._cad3d_facade_packages = []
        self.current_facade_match_result = None
'''

main_new = replace_once(
    main_new,
    old,
    new,
    "OPEN CAD FACADE RESET",
)


old = '''    def clear_cad(self) -> None:
        self.floor_pivots = {}
        self.ground_pivot_reference = None
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""

        if hasattr(self, "pivot_floor_btn"):
'''

new = '''    def clear_cad(self) -> None:
        self.floor_pivots = {}
        self.ground_pivot_reference = None
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""

        # CAD3D_AUTO_FACADE_PORT_V1
        self._cad3d_facade_preanalysis = None
        self._cad3d_facade_packages = []
        self.current_facade_match_result = None

        if hasattr(self, "pivot_floor_btn"):
'''

main_new = replace_once(
    main_new,
    old,
    new,
    "CLEAR CAD FACADE RESET",
)


# ============================================================
# VALIDATE EVERYTHING BEFORE WRITING
# ============================================================

compile(
    main_new,
    str(MAIN),
    "exec",
)

compile(
    runtime_text,
    str(RUNTIME),
    "exec",
)

for name, text in vendor_texts.items():
    compile(
        text,
        str(
            VENDOR_DIR
            / name
        ),
        "exec",
    )


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

backup = (
    ROOT
    / "checkpoints"
    / (
        "BEFORE_AUTO_FACADE_PORT_"
        + stamp
    )
)

backup.mkdir(
    parents=True,
    exist_ok=False,
)

shutil.copy2(
    MAIN,
    backup
    / "main_window.py",
)

if RUNTIME.exists():
    shutil.copy2(
        RUNTIME,
        backup
        / "facade_runtime.py",
    )

if VENDOR_DIR.exists():
    shutil.copytree(
        VENDOR_DIR,
        backup
        / "_cad_to_3d_max_facade",
    )


# ============================================================
# ATOMIC WRITE
# ============================================================

VENDOR_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def atomic_write(
    target,
    text,
):
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = target.with_name(
        target.name
        + ".tmp_facade_port"
    )

    temp.write_text(
        text,
        encoding="utf-8",
    )

    temp.replace(
        target
    )


atomic_write(
    VENDOR_DIR
    / "__init__.py",
    (
        "# CAD_to_3D_Max proven facade compatibility layer.\n"
    ),
)

for name, text in vendor_texts.items():
    atomic_write(
        VENDOR_DIR
        / name,
        text,
    )

atomic_write(
    RUNTIME,
    runtime_text,
)

# Main is written LAST.
# Marker therefore means the complete installation exists.
atomic_write(
    MAIN,
    main_new,
)


print("")
print("CAD3D_AUTO_FACADE_PORT_V1 INSTALLED")
print("BACKUP:", backup)
print("VENDOR:", VENDOR_DIR)
print("RUNTIME:", RUNTIME)
print("MAIN:", MAIN)
print("")
print("UNCHANGED:")
print("  window_detector.py")
print("  door_detector.py")
print("  wall_detector.py")
print("  multi_floor_max_send.py")
print("  max_bridge.py")
print("  cad_view.py")
print("  3DCAD_BRIDGE.ms")
print("")
