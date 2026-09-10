from __future__ import annotations

from pathlib import Path

from cad.model import CadDocument, CadPolyline, CadText


def _clip_segment(
    p0: tuple[float, float],
    p1: tuple[float, float],
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    x0, y0 = p0
    x1, y1 = p1
    dx = x1 - x0
    dy = y1 - y0

    p = (-dx, dx, -dy, dy)
    q = (x0 - xmin, xmax - x0, y0 - ymin, ymax - y0)

    u1 = 0.0
    u2 = 1.0

    for pi, qi in zip(p, q):
        if abs(pi) <= 1e-12:
            if qi < 0.0:
                return None
            continue

        t = qi / pi

        if pi < 0.0:
            if t > u2:
                return None
            if t > u1:
                u1 = t
        else:
            if t < u1:
                return None
            if t < u2:
                u2 = t

    a = (x0 + u1 * dx, y0 + u1 * dy)
    b = (x0 + u2 * dx, y0 + u2 * dy)
    return a, b


def crop_document(
    document: CadDocument,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> CadDocument:
    xmin, xmax = sorted((float(xmin), float(xmax)))
    ymin, ymax = sorted((float(ymin), float(ymax)))

    cropped = CadDocument(
        source_path=Path(document.source_path),
        parsed_path=Path(document.parsed_path),
    )

    cropped.entity_counts = dict(document.entity_counts)
    cropped.skipped_counts = dict(document.skipped_counts)
    cropped.layers = set(document.layers)

    for primitive in document.primitives:
        pts = primitive.points

        if len(pts) < 2:
            continue

        pairs = list(zip(pts, pts[1:]))

        if primitive.closed and len(pts) > 2 and pts[-1] != pts[0]:
            pairs.append((pts[-1], pts[0]))

        current: list[tuple[float, float]] = []

        def flush() -> None:
            nonlocal current

            if len(current) >= 2:
                cropped.primitives.append(
                    CadPolyline(
                        points=tuple(current),
                        layer=primitive.layer,
                        color=primitive.color,
                        closed=False,
                        source_type=primitive.source_type,
                        group_id=primitive.group_id,
                        block_key=primitive.block_key,
                    )
                )

            current = []

        for a, b in pairs:
            clipped = _clip_segment(a, b, xmin, ymin, xmax, ymax)

            if clipped is None:
                flush()
                continue

            ca, cb = clipped

            if not current:
                current = [ca, cb]
            else:
                last = current[-1]

                if (
                    abs(last[0] - ca[0]) <= 1e-7
                    and abs(last[1] - ca[1]) <= 1e-7
                ):
                    current.append(cb)
                else:
                    flush()
                    current = [ca, cb]

        flush()

    for text in document.texts:
        x, y = text.position

        if xmin <= x <= xmax and ymin <= y <= ymax:
            cropped.texts.append(
                CadText(
                    text=text.text,
                    position=text.position,
                    height=text.height,
                    rotation=text.rotation,
                    layer=text.layer,
                    color=text.color,
                    source_type=text.source_type,
                    group_id=text.group_id,
                    block_key=text.block_key,
                )
            )

    return cropped
