from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RectangleMatch:
    x0: float
    y0: float
    x1: float
    y1: float
    inner_lines: tuple


@dataclass(frozen=True, slots=True)
class RawRectangle:
    x0: float
    y0: float
    x1: float
    y1: float
    boundary_segments: tuple


def _is_horizontal(seg, angle_tol_deg: float = 3.0) -> bool:
    angle = seg.angle % math.pi
    return min(abs(angle), abs(math.pi - angle)) <= math.radians(angle_tol_deg)


def _is_vertical(seg, angle_tol_deg: float = 3.0) -> bool:
    angle = seg.angle % math.pi
    return abs(angle - math.pi / 2.0) <= math.radians(angle_tol_deg)


def _x_range(seg) -> tuple[float, float]:
    return min(seg.a[0], seg.b[0]), max(seg.a[0], seg.b[0])


def _y_range(seg) -> tuple[float, float]:
    return min(seg.a[1], seg.b[1]), max(seg.a[1], seg.b[1])


def _segment_identity(seg) -> tuple:
    a = (
        round(float(seg.a[0]), 6),
        round(float(seg.a[1]), 6),
    )
    b = (
        round(float(seg.b[0]), 6),
        round(float(seg.b[1]), 6),
    )
    return (a, b) if a <= b else (b, a)


def _find_raw_rectangles(segments) -> list[RawRectangle]:
    horizontal = [seg for seg in segments if _is_horizontal(seg)]
    vertical = [seg for seg in segments if _is_vertical(seg)]

    rectangles: list[RawRectangle] = []
    seen: set[tuple[int, int, int, int]] = set()

    for bottom in horizontal:
        bx0, bx1 = _x_range(bottom)

        for top in horizontal:
            if top is bottom:
                continue

            tx0, tx1 = _x_range(top)

            y0 = min(bottom.my, top.my)
            y1 = max(bottom.my, top.my)

            if y1 <= y0:
                continue

            x0 = max(bx0, tx0)
            x1 = min(bx1, tx1)

            if x1 <= x0:
                continue

            align_tol = max(min(x1 - x0, y1 - y0) * 0.10, 1e-6)

            left_side = None
            right_side = None

            for side in vertical:
                sx = side.mx
                sy0, sy1 = _y_range(side)

                if not (
                    sy0 <= y0 + align_tol
                    and sy1 >= y1 - align_tol
                ):
                    continue

                if abs(sx - x0) <= align_tol:
                    left_side = side

                if abs(sx - x1) <= align_tol:
                    right_side = side

            if left_side is None or right_side is None:
                continue

            signature = (
                round(x0),
                round(y0),
                round(x1),
                round(y1),
            )

            if signature in seen:
                continue

            seen.add(signature)

            rectangles.append(
                RawRectangle(
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    boundary_segments=(
                        bottom,
                        top,
                        left_side,
                        right_side,
                    ),
                )
            )

    return rectangles


def _line_spans_between_crossers(
    seg,
    horizontal_mode: bool,
    rect: RawRectangle,
    tol: float,
) -> bool:
    if horizontal_mode:
        sx0, sx1 = _x_range(seg)
        return (
            abs(sx0 - rect.x0) <= tol
            and abs(sx1 - rect.x1) <= tol
        )

    sy0, sy1 = _y_range(seg)
    return (
        abs(sy0 - rect.y0) <= tol
        and abs(sy1 - rect.y1) <= tol
    )


def _has_matching_parallel_repeat_outside(
    *,
    inner,
    all_parallel,
    horizontal_mode: bool,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    align_tol: float,
) -> bool:
    if horizontal_mode:
        search_distance = max(y1 - y0, align_tol)

        for outside in all_parallel:
            if outside in inner:
                continue

            oy = outside.my

            if y0 - align_tol <= oy <= y1 + align_tol:
                continue

            if oy < y0 - search_distance or oy > y1 + search_distance:
                continue

            ox0, ox1 = _x_range(outside)

            for inside in inner:
                ix0, ix1 = _x_range(inside)

                if (
                    abs(ox0 - ix0) <= align_tol
                    and abs(ox1 - ix1) <= align_tol
                ):
                    return True

    else:
        search_distance = max(x1 - x0, align_tol)

        for outside in all_parallel:
            if outside in inner:
                continue

            ox = outside.mx

            if x0 - align_tol <= ox <= x1 + align_tol:
                continue

            if ox < x0 - search_distance or ox > x1 + search_distance:
                continue

            oy0, oy1 = _y_range(outside)

            for inside in inner:
                iy0, iy1 = _y_range(inside)

                if (
                    abs(oy0 - iy0) <= align_tol
                    and abs(oy1 - iy1) <= align_tol
                ):
                    return True

    return False


def _window_segment_ids(
    rect: RawRectangle,
    inner,
) -> set[tuple]:
    ids = {
        _segment_identity(seg)
        for seg in rect.boundary_segments
    }
    ids.update(_segment_identity(seg) for seg in inner)
    return ids




def _has_two_crossers_through_all_five(
    *,
    rect: RawRectangle,
    inner,
    segments,
    horizontal_mode: bool,
    tol: float,
) -> bool:
    bottom, top, left_side, right_side = rect.boundary_segments

    if horizontal_mode:
        five_parallel = [bottom, top, *inner]
        crossers = [seg for seg in segments if _is_vertical(seg)]

        valid = 0

        for cross in crossers:
            cx = cross.mx
            cy0, cy1 = _y_range(cross)

            crosses_all = True

            for line in five_parallel:
                lx0, lx1 = _x_range(line)
                ly = line.my

                if not (
                    lx0 - tol <= cx <= lx1 + tol
                    and cy0 - tol <= ly <= cy1 + tol
                ):
                    crosses_all = False
                    break

            if crosses_all:
                valid += 1

                if valid >= 2:
                    return True

        return False

    five_parallel = [left_side, right_side, *inner]
    crossers = [seg for seg in segments if _is_horizontal(seg)]

    valid = 0

    for cross in crossers:
        cy = cross.my
        cx0, cx1 = _x_range(cross)

        crosses_all = True

        for line in five_parallel:
            ly0, ly1 = _y_range(line)
            lx = line.mx

            if not (
                ly0 - tol <= cy <= ly1 + tol
                and cx0 - tol <= lx <= cx1 + tol
            ):
                crosses_all = False
                break

        if crosses_all:
            valid += 1

            if valid >= 2:
                return True

    return False




def find_window_rectangles(segments) -> list[RectangleMatch]:
    horizontal = [seg for seg in segments if _is_horizontal(seg)]
    vertical = [seg for seg in segments if _is_vertical(seg)]

    raw_rectangles = _find_raw_rectangles(segments)

    matches: list[RectangleMatch] = []
    used_window_segment_ids: set[tuple] = set()

    for rect in raw_rectangles:
        width = rect.x1 - rect.x0
        height = rect.y1 - rect.y0

        align_tol = 0.0

        bottom, top, left_side, right_side = rect.boundary_segments

        if width >= height:
            # OUTER PARALLEL LINES ARE ONLY bottom + top.
            outer_parallel_ids = {
                _segment_identity(bottom),
                _segment_identity(top),
            }

            inner = []

            for seg in horizontal:
                sid = _segment_identity(seg)

                # Outer rectangle lines are NEVER counted among the 3 inner lines.
                if sid in outer_parallel_ids:
                    continue

                # Must be strictly inside the rectangle.
                if not (
                    rect.y0 + align_tol
                    < seg.my
                    < rect.y1 - align_tol
                ):
                    continue

                # Each inner parallel must span between the two perpendicular sides.
                if not _line_spans_between_crossers(
                    seg,
                    True,
                    rect,
                    align_tol,
                ):
                    continue

                inner.append(seg)

            all_parallel = horizontal
            horizontal_mode = True

        else:
            # OUTER PARALLEL LINES ARE ONLY left + right.
            outer_parallel_ids = {
                _segment_identity(left_side),
                _segment_identity(right_side),
            }

            inner = []

            for seg in vertical:
                sid = _segment_identity(seg)

                # Outer rectangle lines are NEVER counted among the 3 inner lines.
                if sid in outer_parallel_ids:
                    continue

                # Must be strictly inside the rectangle.
                if not (
                    rect.x0 + align_tol
                    < seg.mx
                    < rect.x1 - align_tol
                ):
                    continue

                # Each inner parallel must span between the two perpendicular sides.
                if not _line_spans_between_crossers(
                    seg,
                    False,
                    rect,
                    align_tol,
                ):
                    continue

                inner.append(seg)

            all_parallel = vertical
            horizontal_mode = False

        # EXACTLY 3 INNER parallel lines.
        # The 2 outer rectangle lines are separate and excluded from this count.
        if len(inner) != 3:
            continue

        if not _has_two_crossers_through_all_five(
            rect=rect,
            inner=inner,
            segments=segments,
            horizontal_mode=horizontal_mode,
            tol=align_tol,
        ):
            continue

        if _has_matching_parallel_repeat_outside(
            inner=inner,
            all_parallel=all_parallel,
            horizontal_mode=horizontal_mode,
            x0=rect.x0,
            y0=rect.y0,
            x1=rect.x1,
            y1=rect.y1,
            align_tol=align_tol,
        ):
            continue

        candidate_segment_ids = _window_segment_ids(
            rect,
            inner,
        )

        if candidate_segment_ids & used_window_segment_ids:
            continue

        matches.append(
            RectangleMatch(
                x0=rect.x0,
                y0=rect.y0,
                x1=rect.x1,
                y1=rect.y1,
                inner_lines=tuple(inner),
            )
        )

        used_window_segment_ids.update(
            candidate_segment_ids
        )

    return matches
