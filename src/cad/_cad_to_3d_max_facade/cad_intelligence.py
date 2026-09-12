from __future__ import annotations

import argparse
import math
import re
import statistics
import unicodedata
from collections import defaultdict


def _finite(value, default=0.0):
    try:
        value = float(value)
    except Exception:
        return float(default)
    return value if math.isfinite(value) else float(default)


def _percentile(values, q, default=0.0):
    values = sorted(float(v) for v in values if float(v) > 0.0 and math.isfinite(float(v)))
    if not values:
        return float(default)
    if len(values) == 1:
        return values[0]
    q = max(0.0, min(1.0, float(q)))
    pos = (len(values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    t = pos - lo
    return values[lo] * (1.0 - t) + values[hi] * t


def _angle_delta_deg(a, b):
    d = abs((float(a) - float(b)) % 180.0)
    return min(d, 180.0 - d)


def _normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


_HINTS = {
    "wall": (
        "WALL", "PARTITION", "BRICK", "BLOCK", "MASONRY", "TIMBER FRAME",
        "STRUCTURAL WALL", "DUVAR", "WAND", "MURO", "MUR",
    ),
    "door": ("DOOR", "KAPI", "TUER", "TUR", "PORTE", "PUERTA"),
    "window": ("WINDOW", "GLAZ", "PENCERE", "FENSTER", "FENETRE", "VENTANA"),
    "furniture": ("FURN", "FURNITURE", "MOBILYA", "MOBEL", "MEUBLE"),
    "annotation": (
        "DIM", "DIMS", "DIMENSION", "TEXT", "NOTE", "ANNO", "TITLE", "GRID",
        "LEVEL", "AXIS", "CENTERLINE", "CENTRELINE", "HATCH",
    ),
    "roof": ("ROOF", "EAVE", "EAVES", "CANOPY", "CATI", "DACH", "TOIT"),
    "stair": ("STAIR", "STAIRS", "MERDIVEN", "TREPPE", "ESCALIER"),
}


def semantic_category(layer_name):
    text = _normalize_text(layer_name)
    if not text:
        return "unknown"
    for category in ("door", "window", "furniture", "annotation", "roof", "stair", "wall"):
        for token in _HINTS[category]:
            token_norm = _normalize_text(token)
            if token_norm and token_norm in text:
                return category
    return "unknown"


def _item_closed(item):
    return bool(item.get("closed") or item.get("source_closed") or item.get("is_closed"))


def extract_segments(geometry, layers=None):
    allowed = None if layers is None else {str(x).strip() for x in layers}
    segments = []
    for geometry_index, item in enumerate(geometry or []):
        layer = str(item.get("layer") or "").strip()
        if allowed is not None and layer not in allowed:
            continue
        points = item.get("points") or []
        if len(points) < 2:
            continue
        pairs = list(zip(points, points[1:]))
        if _item_closed(item) and points[0] != points[-1]:
            pairs.append((points[-1], points[0]))
        for segment_index, (p0, p1) in enumerate(pairs):
            try:
                x1 = float(p0[0]); y1 = float(p0[1])
                x2 = float(p1[0]); y2 = float(p1[1])
            except Exception:
                continue
            dx = x2 - x1; dy = y2 - y1
            length = math.hypot(dx, dy)
            if not math.isfinite(length) or length <= 1e-9:
                continue
            segments.append({
                "id": len(segments),
                "geometry_index": geometry_index,
                "segment_index": segment_index,
                "layer": layer,
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "length": length,
                "angle_deg": math.degrees(math.atan2(dy, dx)) % 180.0,
                "source_closed": _item_closed(item),
            })
    return segments


def _coerce_cleanup_segments(raw_segments):
    result = []
    for idx, seg in enumerate(raw_segments or []):
        try:
            if "a" in seg and "b" in seg:
                x1, y1 = float(seg["a"][0]), float(seg["a"][1])
                x2, y2 = float(seg["b"][0]), float(seg["b"][1])
            else:
                x1, y1 = float(seg["x1"]), float(seg["y1"])
                x2, y2 = float(seg["x2"]), float(seg["y2"])
        except Exception:
            continue
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 1e-9:
            continue
        result.append({
            "id": idx,
            "layer": str(seg.get("layer") or "").strip(),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "length": length,
            "angle_deg": math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0,
            "source_closed": bool(seg.get("source_closed")),
        })
    return result


def _bounds(segments):
    if not segments:
        return (0.0, 0.0, 1.0, 1.0)
    xs = []; ys = []
    for s in segments:
        xs.extend((s["x1"], s["x2"]))
        ys.extend((s["y1"], s["y2"]))
    return min(xs), min(ys), max(xs), max(ys)


def _drawing_scale(segments):
    x0, y0, x1, y1 = _bounds(segments)
    diagonal = max(1e-9, math.hypot(x1 - x0, y1 - y0))
    lengths = [s["length"] for s in segments]
    median = _percentile(lengths, 0.50, diagonal * 0.01)
    p10 = _percentile(lengths, 0.10, median)
    p75 = _percentile(lengths, 0.75, median)
    return {
        "drawing_diagonal": diagonal,
        "median_length": median,
        "p10_length": p10,
        "p75_length": p75,
    }


def _pair_relation(a, b, angle_tol_deg, max_gap, min_overlap_ratio, min_overlap):
    if _angle_delta_deg(a["angle_deg"], b["angle_deg"]) > angle_tol_deg:
        return None
    ax = a["x2"] - a["x1"]; ay = a["y2"] - a["y1"]
    alen = a["length"]
    if alen <= 1e-9:
        return None
    ux = ax / alen; uy = ay / alen
    nx = -uy; ny = ux
    amx = (a["x1"] + a["x2"]) * 0.5
    amy = (a["y1"] + a["y2"]) * 0.5
    bmx = (b["x1"] + b["x2"]) * 0.5
    bmy = (b["y1"] + b["y2"]) * 0.5
    gap = abs((bmx - amx) * nx + (bmy - amy) * ny)
    if gap <= 1e-9 or gap > max_gap:
        return None
    a0 = min(a["x1"] * ux + a["y1"] * uy, a["x2"] * ux + a["y2"] * uy)
    a1 = max(a["x1"] * ux + a["y1"] * uy, a["x2"] * ux + a["y2"] * uy)
    b0 = min(b["x1"] * ux + b["y1"] * uy, b["x2"] * ux + b["y2"] * uy)
    b1 = max(b["x1"] * ux + b["y1"] * uy, b["x2"] * ux + b["y2"] * uy)
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    shorter = min(a["length"], b["length"])
    if shorter <= 1e-9:
        return None
    ratio = overlap / shorter
    if overlap < min_overlap or ratio < min_overlap_ratio:
        return None
    return {"gap": gap, "overlap": overlap, "ratio": ratio}


def _cluster_gaps(records, scale):
    if not records:
        return []
    diagonal = scale["drawing_diagonal"]
    median_length = scale["median_length"]
    base_tol = max(diagonal * 0.00012, median_length * 0.012, 1e-6)
    rows = sorted(records, key=lambda r: r["gap"])
    clusters = []
    for row in rows:
        best = None
        best_error = None
        for cluster in clusters:
            center = cluster["weighted_sum"] / max(cluster["weight"], 1e-9)
            tol = max(base_tol, center * 0.075)
            error = abs(row["gap"] - center)
            if error <= tol and (best_error is None or error < best_error):
                best = cluster; best_error = error
        if best is None:
            best = {"items": [], "weighted_sum": 0.0, "weight": 0.0}
            clusters.append(best)
        weight = max(row.get("overlap", 1.0), 1e-6)
        best["items"].append(row)
        best["weighted_sum"] += row["gap"] * weight
        best["weight"] += weight
    families = []
    for cluster in clusters:
        items = cluster["items"]
        if len(items) < 3:
            continue
        center = cluster["weighted_sum"] / max(cluster["weight"], 1e-9)
        tolerance = max(base_tol * 1.5, center * 0.10)
        families.append({
            "gap": float(center),
            "count": len(items),
            "tolerance": float(tolerance),
            "support": float(sum(x.get("overlap", 0.0) for x in items)),
        })
    families.sort(key=lambda f: (f["count"], f["support"]), reverse=True)
    return families[:8]


def infer_parallel_gap_families(segments):
    segments = list(segments or [])
    if len(segments) < 2:
        return []
    scale = _drawing_scale(segments)
    diagonal = scale["drawing_diagonal"]
    lengths = [s["length"] for s in segments]
    p10 = _percentile(lengths, 0.10, scale["median_length"])
    min_overlap = max(p10 * 0.30, diagonal * 0.00015)
    max_gap = max(diagonal * 0.08, scale["median_length"] * 1.5)
    ranked = sorted(segments, key=lambda s: s["length"], reverse=True)[:600]
    records = []
    for i, a in enumerate(ranked):
        for b in ranked[i + 1:]:
            rec = _pair_relation(a, b, 2.5, max_gap, 0.34, min_overlap)
            if rec is not None:
                records.append(rec)
    return _cluster_gaps(records, scale)


def _matches_family(gap, families):
    best = None
    for idx, family in enumerate(families):
        error = abs(gap - family["gap"])
        if error <= family["tolerance"]:
            score = error / max(family["tolerance"], 1e-9)
            if best is None or score < best[0]:
                best = (score, idx, family)
    return best


def find_parallel_pairs(segments, gap_families=None):
    segments = list(segments or [])
    if len(segments) < 2:
        return []
    scale = _drawing_scale(segments)
    families = list(gap_families or infer_parallel_gap_families(segments))
    if not families:
        return []
    min_overlap = max(scale["p10_length"] * 0.30, scale["drawing_diagonal"] * 0.00015)
    max_gap = max(f["gap"] + f["tolerance"] for f in families)
    pairs = []
    ranked = sorted(segments, key=lambda s: s["length"], reverse=True)[:700]
    for i, a in enumerate(ranked):
        for b in ranked[i + 1:]:
            rec = _pair_relation(a, b, 2.5, max_gap, 0.34, min_overlap)
            if rec is None:
                continue
            match = _matches_family(rec["gap"], families)
            if match is None:
                continue
            _, family_index, family = match
            pairs.append({
                "a": a,
                "b": b,
                "gap": rec["gap"],
                "overlap": rec["overlap"],
                "ratio": rec["ratio"],
                "family_index": family_index,
                "family_gap": family["gap"],
                "family_tolerance": family["tolerance"],
            })
    return pairs


def infer_cad_profile(geometry):
    segments = extract_segments(geometry)
    if not segments:
        return {
            "engine": "GENERIC_CAD_INTELLIGENCE_V1",
            "primary_structural_layer": None,
            "structural_layers": [],
            "opening_layers": [],
            "gap_families": [],
            "confidence": 0.0,
            "layer_scores": [],
        }
    scale = _drawing_scale(segments)
    global_families = infer_parallel_gap_families(segments)
    by_layer = defaultdict(list)
    item_closed = defaultdict(lambda: [0, 0])
    for s in segments:
        by_layer[s["layer"]].append(s)
    for item in geometry or []:
        layer = str(item.get("layer") or "").strip()
        if not layer:
            continue
        item_closed[layer][1] += 1
        if _item_closed(item):
            item_closed[layer][0] += 1
    max_total_length = max(sum(s["length"] for s in rows) for rows in by_layer.values())
    layer_scores = []
    for layer, rows in by_layer.items():
        total_length = sum(s["length"] for s in rows)
        local_families = infer_parallel_gap_families(rows) if len(rows) >= 4 else []
        pairs = find_parallel_pairs(rows, local_families or global_families)
        pair_segments = {p["a"]["id"] for p in pairs} | {p["b"]["id"] for p in pairs}
        pair_coverage = len(pair_segments) / max(1, len(rows))
        pair_density = min(1.0, len(pairs) / max(1.0, len(rows) * 0.75))
        family_strength = min(1.0, sum(f["count"] for f in (local_families[:3])) / max(1.0, len(rows)))
        length_share = total_length / max(max_total_length, 1e-9)
        closed_a, closed_b = item_closed[layer]
        closed_ratio = closed_a / max(1, closed_b)
        category = semantic_category(layer)
        semantic_bonus = {
            "wall": 0.45,
            "door": -0.65,
            "window": -0.65,
            "furniture": -0.75,
            "annotation": -0.90,
            "roof": -0.45,
            "stair": -0.25,
            "unknown": 0.0,
        }.get(category, 0.0)
        score = (
            2.40 * pair_coverage
            + 1.40 * pair_density
            + 0.80 * family_strength
            + 0.70 * length_share
            + 0.15 * closed_ratio
            + semantic_bonus
        )
        layer_scores.append({
            "layer": layer,
            "category": category,
            "score": float(score),
            "segment_count": len(rows),
            "total_length": float(total_length),
            "pair_count": len(pairs),
            "pair_coverage": float(pair_coverage),
            "gap_families": local_families[:5],
        })
    layer_scores.sort(key=lambda r: (r["score"], r["total_length"]), reverse=True)
    # CAD3D_STRUCTURAL_SEMANTIC_AUTHORITY_V3
    #
    # Structural WALL inference must never elect an explicit stair
    # layer as a wall source. Stair geometry remains available in
    # the full CAD geometry for the stair detector.
    usable = [
        r
        for r in layer_scores
        if r["category"]
        not in {
            "door",
            "window",
            "furniture",
            "annotation",
            "roof",
            "stair",
        }
    ]
    if not usable:
        usable = layer_scores[:]
    primary = usable[0]["layer"] if usable else None
    top_score = usable[0]["score"] if usable else 0.0
    second_score = usable[1]["score"] if len(usable) > 1 else top_score - 1.0
    structural_layers = []
    if usable:
        for row in usable:
            if row["layer"] == primary:
                structural_layers.append(row["layer"])
                continue
            if row["score"] >= top_score - 0.55 and row["pair_coverage"] >= 0.18:
                structural_layers.append(row["layer"])
    opening_layers = sorted({
        str(item.get("layer") or "").strip()
        for item in geometry or []
        if semantic_category(item.get("layer")) in {"door", "window"}
        and str(item.get("layer") or "").strip()
    })
    confidence = max(0.0, min(1.0, 0.55 + 0.16 * (top_score - second_score))) if primary else 0.0
    return {
        "engine": "GENERIC_CAD_INTELLIGENCE_V1",
        "primary_structural_layer": primary,
        "structural_layers": structural_layers,
        "opening_layers": opening_layers,
        "gap_families": global_families,
        "confidence": float(confidence),
        "layer_scores": layer_scores,
        **scale,
    }


def infer_cleanup_profile(raw_segments):
    segments = _coerce_cleanup_segments(raw_segments)
    scale = _drawing_scale(segments)
    families = infer_parallel_gap_families(segments)
    median = scale["median_length"]
    p75 = scale["p75_length"]
    dominant_gap = families[0]["gap"] if families else median
    max_dash_length = max(median * 3.45, p75 * 1.55)
    max_dash_gap = max(median * 3.35, dominant_gap * 1.45, p75 * 1.50)
    min_run_span = max(median * 6.35, dominant_gap * 2.45, p75 * 3.60)
    return {
        "engine": "GENERIC_CAD_INTELLIGENCE_V1",
        "gap_families": families,
        "max_dash_length": float(max_dash_length),
        "max_dash_gap": float(max_dash_gap),
        "min_run_span": float(min_run_span),
        **scale,
    }


def _rotate_point(x, y, angle_deg):
    a = math.radians(angle_deg)
    c = math.cos(a); s = math.sin(a)
    return (x * c - y * s, x * s + y * c)


def _synthetic_wall_layer(layer, gap, angle_deg, offset_x=0.0, offset_y=0.0):
    rows = []
    for base in (0.0, 650.0, 1300.0):
        for side in (0.0, gap):
            p0 = _rotate_point(0.0, base + side, angle_deg)
            p1 = _rotate_point(1800.0, base + side, angle_deg)
            rows.append({"layer": layer, "points": [(p0[0] + offset_x, p0[1] + offset_y), (p1[0] + offset_x, p1[1] + offset_y)]})
    return rows


def self_test():
    g1 = []
    g1 += _synthetic_wall_layer("X17", 180.0, 17.0)
    g1 += [
        {"layer": "notes_44", "points": [(0, 2600), (2400, 2600)]},
        {"layer": "zzDoors", "points": [(200, 200), (260, 260), (320, 200)]},
        {"layer": "chairs", "points": [(3000, 0), (3050, 0), (3050, 50), (3000, 50), (3000, 0)], "closed": True},
    ]
    p1 = infer_cad_profile(g1)
    assert p1["primary_structural_layer"] == "X17", p1["layer_scores"][:3]
    assert any(abs(f["gap"] - 180.0) < 25.0 for f in p1["gap_families"]), p1["gap_families"]

    g2 = []
    g2 += _synthetic_wall_layer("foo_42", 73.5, 31.0, 100.0, -80.0)
    g2 += [
        {"layer": "L99", "points": [(0, 4000), (4000, 4000)]},
        {"layer": "L99", "points": [(0, 4300), (4000, 4300)]},
    ]
    p2 = infer_cad_profile(g2)
    assert p2["primary_structural_layer"] == "foo_42", p2["layer_scores"][:3]
    assert any(abs(f["gap"] - 73.5) < 14.0 for f in p2["gap_families"]), p2["gap_families"]

    cp = infer_cleanup_profile(extract_segments(g1))
    assert cp["max_dash_length"] > 0.0
    assert cp["min_run_span"] > cp["max_dash_length"]
    print("GENERIC CAD INTELLIGENCE SELF-TEST: OK")
    print("TEST-1 PRIMARY:", p1["primary_structural_layer"], "CONF:", round(p1["confidence"], 3))
    print("TEST-2 PRIMARY:", p2["primary_structural_layer"], "CONF:", round(p2["confidence"], 3))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
