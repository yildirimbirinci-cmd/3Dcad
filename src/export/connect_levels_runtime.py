from __future__ import annotations

from collections import defaultdict
import math


ENGINE = "CAD3D_CONNECT_REQUEST_PIPELINE_V1"


def _num(value):
    try:
        value = float(value)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _int(value):
    try:
        return int(value)
    except Exception:
        return None


def _facade_number(row):
    if not isinstance(row, dict):
        return None
    return _int(row.get("facade_number"))


def _bottom_y(row):
    if not isinstance(row, dict):
        return None

    for key in (
        "elevation_bottom_y",
        "bottom_y",
        "y0",
    ):
        value = _num(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")

    if (
        isinstance(box, (tuple, list))
        and len(box) >= 4
    ):
        return _num(box[1])

    return None


def _top_y(row):
    if not isinstance(row, dict):
        return None

    for key in (
        "elevation_top_y",
        "top_y",
        "y1",
    ):
        value = _num(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")

    if (
        isinstance(box, (tuple, list))
        and len(box) >= 4
    ):
        return _num(box[3])

    bottom = _bottom_y(row)
    height = _num(
        row.get(
            "elevation_height"
        )
    )

    if (
        bottom is not None
        and height is not None
    ):
        return bottom + height

    return None


def _merge_intervals(intervals):
    merged = []

    for start, end in sorted(intervals):
        if end <= start:
            continue

        if (
            not merged
            or start > merged[-1][1]
        ):
            merged.append(
                [start, end]
            )
        else:
            merged[-1][1] = max(
                merged[-1][1],
                end,
            )

    return merged


def _horizontal_levels(
    region_geometry,
    bbox,
    source_to_mm,
):
    from cad._cad_to_3d_max_facade.elevation_opening_detector import (
        _extract_axis_segments,
        _merge_horizontal,
    )

    if not (
        isinstance(
            bbox,
            (tuple, list),
        )
        and len(bbox) == 4
    ):
        return []

    x0, y0, x1, y1 = (
        float(value)
        for value in bbox
    )

    width = max(
        x1 - x0,
        1.0e-12,
    )

    horizontal, _vertical = (
        _extract_axis_segments(
            region_geometry
        )
    )

    one_mm_source = (
        1.0
        / max(
            float(source_to_mm),
            1.0e-12,
        )
    )

    horizontal = [
        row
        for row in horizontal
        if (
            float(
                row.get(
                    "x1",
                    -1.0e30,
                )
            )
            >= x0
            and float(
                row.get(
                    "x0",
                    1.0e30,
                )
            )
            <= x1
            and y0
            <= float(
                row.get(
                    "y",
                    -1.0e30,
                )
            )
            <= y1
        )
    ]

    if not horizontal:
        return []

    horizontal = _merge_horizontal(
        horizontal,
        y_tolerance=max(
            one_mm_source,
            1.0e-9,
        ),
        gap_tolerance=max(
            one_mm_source * 2.0,
            1.0e-9,
        ),
    )

    groups = []

    for row in sorted(
        horizontal,
        key=lambda item: float(
            item["y"]
        ),
    ):
        y = float(
            row["y"]
        )

        sx0 = max(
            x0,
            float(
                row["x0"]
            ),
        )

        sx1 = min(
            x1,
            float(
                row["x1"]
            ),
        )

        if sx1 <= sx0:
            continue

        group = None

        for candidate in groups:
            if (
                abs(
                    float(
                        candidate["y"]
                    )
                    - y
                )
                <= one_mm_source
            ):
                group = candidate
                break

        if group is None:
            group = {
                "y": y,
                "ys": [],
                "intervals": [],
            }
            groups.append(
                group
            )

        group[
            "ys"
        ].append(
            y
        )

        group[
            "intervals"
        ].append(
            (
                sx0,
                sx1,
            )
        )

        group[
            "y"
        ] = (
            sum(
                group["ys"]
            )
            / len(
                group["ys"]
            )
        )

    levels = []

    for group in groups:
        intervals = (
            _merge_intervals(
                group[
                    "intervals"
                ]
            )
        )

        union_length = sum(
            end - start
            for start, end
            in intervals
        )

        longest = max(
            (
                end - start
                for start, end
                in intervals
            ),
            default=0.0,
        )

        levels.append(
            {
                "y":
                    float(
                        group["y"]
                    ),

                "coverage":
                    float(
                        union_length
                        / width
                    ),

                "longest_ratio":
                    float(
                        longest
                        / width
                    ),
            }
        )

    return levels


def _best_level(
    levels,
    lower_bound,
    upper_bound,
):
    candidates = [
        row
        for row in levels
        if (
            float(
                lower_bound
            )
            < float(
                row["y"]
            )
            < float(
                upper_bound
            )
        )
    ]

    if not candidates:
        return None

    # No architectural dimension threshold:
    # strongest/longest CAD horizontal wins.
    # Equal structural strength -> upper line wins.
    return max(
        candidates,
        key=lambda row: (
            float(
                row.get(
                    "coverage",
                    0.0,
                )
            ),
            float(
                row.get(
                    "longest_ratio",
                    0.0,
                )
            ),
            float(
                row["y"]
            ),
        ),
    )


def _current_analysis(window):
    result = getattr(
        window,
        "current_facade_match_result",
        None,
    )

    if isinstance(
        result,
        dict,
    ):
        return result

    return {}


def _preanalysis(window):
    result = getattr(
        window,
        "_cad3d_facade_preanalysis",
        None,
    )

    if isinstance(
        result,
        dict,
    ):
        return result

    return {}


def _facades_by_number(preanalysis):
    result = {}

    for facade in (
        preanalysis.get(
            "elevation_facades",
            [],
        )
        or []
    ):
        if not isinstance(
            facade,
            dict,
        ):
            continue

        number = (
            _facade_number(
                facade
            )
        )

        if number is not None:
            result[
                number
            ] = facade

    return result


def _regions_by_id(preanalysis):
    result = {}

    for region in (
        preanalysis.get(
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

        region_id = (
            region.get(
                "region_id"
            )
        )

        if region_id is not None:
            result[
                str(
                    region_id
                )
            ] = region

    return result


def _rows_by_facade(
    analysis,
):
    result = defaultdict(
        list
    )

    for row in (
        analysis.get(
            "plan_guided_facade_windows",
            [],
        )
        or []
    ):
        if not isinstance(
            row,
            dict,
        ):
            continue

        number = (
            _facade_number(
                row
            )
        )

        if number is None:
            continue

        result[
            number
        ].append(
            row
        )

    return result


def _previous_top_for_same_facade(
    rows,
    target_floor_name,
    target_bottom,
):
    previous_tops = []

    for row in rows:
        row_floor = str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip()

        if (
            row_floor
            == target_floor_name
        ):
            continue

        bottom = (
            _bottom_y(
                row
            )
        )

        top = (
            _top_y(
                row
            )
        )

        if (
            bottom is None
            or top is None
        ):
            continue

        if top < target_bottom:
            previous_tops.append(
                top
            )

    if not previous_tops:
        return None

    return max(
        previous_tops
    )


def collect_connect_levels(
    window,
    package,
):
    analysis = (
        _current_analysis(
            window
        )
    )

    preanalysis = (
        _preanalysis(
            window
        )
    )

    floor_name = str(
        package.get(
            "floor_name",
            "",
        )
        or ""
    ).strip()

    wall_height_cm = (
        _num(
            package.get(
                "wall_height_cm"
            )
        )
    )

    if not floor_name:
        raise RuntimeError(
            "Connect icin kat adi eksik."
        )

    if (
        wall_height_cm is None
        or wall_height_cm <= 0.0
    ):
        raise RuntimeError(
            floor_name
            + ": duvar yuksekligi gecersiz."
        )

    if not analysis:
        raise RuntimeError(
            floor_name
            + ": mevcut cephe eslestirme sonucu bulunamadi."
        )

    if not preanalysis:
        raise RuntimeError(
            floor_name
            + ": cephe preanalysis geometrisi bulunamadi."
        )

    from export.max_bridge import (
        _source_to_mm,
    )

    full_document = getattr(
        window,
        "_full_document",
        None,
    )

    if full_document is None:
        full_document = (
            package.get(
                "document"
            )
        )

    source_to_mm = float(
        _source_to_mm(
            full_document
        )
    )

    facades = (
        _facades_by_number(
            preanalysis
        )
    )

    # CAD3D_CONNECT_FULL_DOCUMENT_GEOMETRY_V1
    # Region rows in the serialized/preanalysis result do not carry
    # geometry. Use the already-loaded full CAD geometry and let
    # _horizontal_levels() restrict it to each facade bbox.
    from cad.facade_runtime import (
        _document_geometry,
    )

    full_geometry = list(
        _document_geometry(
            full_document
        )
        or []
    )

    if not full_geometry:
        raise RuntimeError(
            floor_name
            + ": tam CAD geometrisi Connect icin alinamadi."
        )

    all_rows_by_facade = (
        _rows_by_facade(
            analysis
        )
    )

    target_rows = [
        row
        for rows
        in all_rows_by_facade.values()
        for row in rows
        if str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip()
        == floor_name
    ]

    if not target_rows:
        raise RuntimeError(
            floor_name
            + ": cephede eslesmis pencere satiri bulunamadi."
        )

    target_rows_by_facade = (
        defaultdict(
            list
        )
    )

    for row in target_rows:
        number = (
            _facade_number(
                row
            )
        )

        if number is not None:
            target_rows_by_facade[
                number
            ].append(
                row
            )

    facade_datums = {}
    levels_cm = []
    window_rows_used = 0

    for (
        facade_number,
        rows,
    ) in sorted(
        target_rows_by_facade.items()
    ):
        facade = (
            facades.get(
                facade_number
            )
        )

        if not isinstance(
            facade,
            dict,
        ):
            continue

        bottoms = [
            value
            for value in (
                _bottom_y(
                    row
                )
                for row in rows
            )
            if value is not None
        ]

        tops = [
            value
            for value in (
                _top_y(
                    row
                )
                for row in rows
            )
            if value is not None
        ]

        if (
            not bottoms
            or not tops
        ):
            continue

        target_bottom = min(
            bottoms
        )

        previous_top = (
            _previous_top_for_same_facade(
                all_rows_by_facade[
                    facade_number
                ],
                floor_name,
                target_bottom,
            )
        )

        bbox = facade.get(
            "bbox"
        )

        if not (
            isinstance(
                bbox,
                (tuple, list),
            )
            and len(
                bbox
            ) == 4
        ):
            continue

        lower_bound = (
            float(
                bbox[1]
            )
            if previous_top is None
            else float(
                previous_top
            )
        )

        structural_levels = (
            _horizontal_levels(
                full_geometry,
                bbox,
                source_to_mm,
            )
        )

        datum = (
            _best_level(
                structural_levels,
                lower_bound,
                target_bottom,
            )
        )

        if datum is None:
            continue

        datum_y = float(
            datum["y"]
        )

        facade_datums[
            facade_number
        ] = datum_y

        for row in rows:
            bottom = (
                _bottom_y(
                    row
                )
            )

            top = (
                _top_y(
                    row
                )
            )

            if (
                bottom is None
                or top is None
                or top <= bottom
            ):
                continue

            bottom_cm = (
                (
                    bottom
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            top_cm = (
                (
                    top
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            row[
                "floor_datum_y"
            ] = datum_y

            row[
                "window_bottom_local_z_cm"
            ] = float(
                bottom_cm
            )

            row[
                "window_top_local_z_cm"
            ] = float(
                top_cm
            )

            row[
                "window_height_cm"
            ] = float(
                (
                    top
                    - bottom
                )
                * source_to_mm
                / 10.0
            )

            levels_cm.extend(
                (
                    bottom_cm,
                    top_cm,
                )
            )

            window_rows_used += 1

    door_tops_used = 0

    for match in (
        analysis.get(
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

        facade_number = (
            _facade_number(
                match
            )
        )

        datum_y = (
            facade_datums.get(
                facade_number
            )
        )

        if datum_y is None:
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

            kind = str(
                pair.get(
                    "kind",
                    "",
                )
                or ""
            ).strip().casefold()

            if "door" not in kind:
                continue

            bottom = (
                _bottom_y(
                    pair
                )
            )

            top = (
                _top_y(
                    pair
                )
            )

            if (
                bottom is None
                or top is None
                or top <= bottom
            ):
                continue

            local_bottom_cm = (
                (
                    bottom
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            local_top_cm = (
                (
                    top
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            if not (
                -0.001
                <= local_bottom_cm
                < wall_height_cm
            ):
                continue

            if not (
                0.0
                < local_top_cm
                < wall_height_cm
            ):
                continue

            pair[
                "floor_name"
            ] = floor_name

            pair[
                "floor_datum_y"
            ] = datum_y

            pair[
                "door_bottom_local_z_cm"
            ] = float(
                local_bottom_cm
            )

            pair[
                "door_top_local_z_cm"
            ] = float(
                local_top_cm
            )

            pair[
                "door_height_cm"
            ] = float(
                (
                    top
                    - bottom
                )
                * source_to_mm
                / 10.0
            )

            levels_cm.append(
                local_top_cm
            )

            door_tops_used += 1

    unique = []
    seen = set()

    for raw_value in levels_cm:
        value = (
            _num(
                raw_value
            )
        )

        if value is None:
            continue

        if not (
            0.0
            < value
            < wall_height_cm
        ):
            continue

        key = round(
            value,
            6,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        unique.append(
            float(
                key
            )
        )

    unique.sort()

    if not unique:
        raise RuntimeError(
            floor_name
            + ": Connect icin kullanilabilir local Z seviyesi bulunamadi."
        )

    print("")
    print(
        "=== 3DCAD CONNECT REQUEST LEVELS V1 ==="
    )
    print(
        "FLOOR:",
        floor_name,
    )
    print(
        "SOURCE_TO_MM:",
        source_to_mm,
    )
    print(
        "WINDOW ROWS USED:",
        window_rows_used,
    )
    print(
        "DOOR TOPS USED:",
        door_tops_used,
    )
    print(
        "CONNECT LEVELS CM:",
        unique,
    )
    print(
        "========================================"
    )
    print("")

    return tuple(
        unique
    )
