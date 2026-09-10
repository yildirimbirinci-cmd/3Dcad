from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import disassemble
from ezdxf.colors import aci2rgb
from ezdxf.path import make_path

from cad.dwg_converter import convert_dwg_to_dxf
from cad.model import CadDocument, CadPolyline, CadText, RGB


class CadLoadError(RuntimeError):
    pass


_TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


class CadLoader:
    def __init__(self, flattening_distance: float = 0.5) -> None:
        self.flattening_distance = max(float(flattening_distance), 1e-4)

    def load(self, source_path: str | Path) -> CadDocument:
        source = Path(source_path).expanduser().resolve()

        if not source.exists():
            raise CadLoadError(f"Dosya bulunamadı: {source}")

        suffix = source.suffix.lower()

        if suffix == ".dwg":
            parsed = convert_dwg_to_dxf(source)
        elif suffix == ".dxf":
            parsed = source
        else:
            raise CadLoadError("Yalnızca DWG ve DXF dosyaları destekleniyor.")

        try:
            doc = ezdxf.readfile(parsed)
        except Exception as exc:
            raise CadLoadError(f"DXF okunamadı: {exc}") from exc

        result = CadDocument(source_path=source, parsed_path=parsed)
        counts: Counter[str] = Counter()
        skipped: Counter[str] = Counter()

        try:
            for top_index, top_entity in enumerate(doc.modelspace()):
                top_type = top_entity.dxftype()

                group_id = None
                block_key = None

                if top_type == "INSERT":
                    handle = str(getattr(top_entity.dxf, "handle", "") or "")
                    group_id = f"I:{handle or top_index}"

                    # Opaque identity only. No semantic interpretation.
                    raw_block_key = str(getattr(top_entity.dxf, "name", "") or "")
                    block_key = raw_block_key or None

                decomposed = disassemble.recursive_decompose([top_entity])

                for entity in decomposed:
                    entity_type = entity.dxftype()
                    counts[entity_type] += 1

                    layer = str(getattr(entity.dxf, "layer", "0"))
                    result.layers.add(layer)

                    try:
                        if entity_type in _TEXT_TYPES:
                            text = self._entity_to_text(
                                doc,
                                entity,
                                layer,
                                group_id,
                                block_key,
                            )
                            if text is not None:
                                result.texts.append(text)
                            else:
                                skipped[entity_type] += 1
                            continue

                        primitives = self._entity_to_polylines(
                            doc,
                            entity,
                            layer,
                            group_id,
                            block_key,
                        )
                    except Exception:
                        skipped[entity_type] += 1
                        continue

                    if primitives:
                        result.primitives.extend(primitives)
                    else:
                        skipped[entity_type] += 1

        except Exception as exc:
            raise CadLoadError(f"CAD entity ayrıştırma hatası: {exc}") from exc

        result.entity_counts = dict(sorted(counts.items()))
        result.skipped_counts = dict(sorted(skipped.items()))

        if not result.primitives and not result.texts:
            raise CadLoadError("Görüntülenebilir CAD içeriği bulunamadı.")

        return result

    def _entity_to_text(
        self,
        doc,
        entity,
        layer: str,
        group_id: str | None,
        block_key: str | None,
    ) -> CadText | None:
        entity_type = entity.dxftype()
        color = self._resolve_color(doc, entity, layer)

        if entity_type == "MTEXT":
            content = entity.plain_text()
            insert = entity.dxf.insert
            height = float(getattr(entity.dxf, "char_height", 1.0) or 1.0)
            rotation = float(getattr(entity.dxf, "rotation", 0.0) or 0.0)
        else:
            if hasattr(entity, "plain_text"):
                content = entity.plain_text()
            else:
                content = str(getattr(entity.dxf, "text", ""))

            insert = getattr(entity.dxf, "insert", None)

            if insert is None:
                return None

            height = float(getattr(entity.dxf, "height", 1.0) or 1.0)
            rotation = float(getattr(entity.dxf, "rotation", 0.0) or 0.0)

        content = str(content).replace("\\P", "\n").strip()

        if not content:
            return None

        height = abs(height) or 1.0

        return CadText(
            text=content,
            position=(float(insert.x), float(insert.y)),
            height=height,
            rotation=rotation,
            layer=layer,
            color=color,
            source_type=entity_type,
            group_id=group_id,
            block_key=block_key,
        )

    def _entity_to_polylines(
        self,
        doc,
        entity,
        layer: str,
        group_id: str | None,
        block_key: str | None,
    ) -> list[CadPolyline]:
        entity_type = entity.dxftype()
        color = self._resolve_color(doc, entity, layer)

        if entity_type == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end

            return [
                CadPolyline(
                    points=((float(s.x), float(s.y)), (float(e.x), float(e.y))),
                    layer=layer,
                    color=color,
                    closed=False,
                    source_type=entity_type,
                    group_id=group_id,
                    block_key=block_key,
                )
            ]

        if entity_type in {"SOLID", "TRACE", "3DFACE"}:
            points = []

            for name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                p = getattr(entity.dxf, name, None)

                if p is not None:
                    xy = (float(p.x), float(p.y))

                    if not points or xy != points[-1]:
                        points.append(xy)

            if len(points) >= 2:
                return [
                    CadPolyline(
                        points=tuple(points),
                        layer=layer,
                        color=color,
                        closed=True,
                        source_type=entity_type,
                        group_id=group_id,
                        block_key=block_key,
                    )
                ]

            return []

        if entity_type == "POINT":
            p = entity.dxf.location
            r = self.flattening_distance * 2.0
            pts = []

            for i in range(9):
                a = math.tau * i / 8.0
                pts.append(
                    (
                        float(p.x + math.cos(a) * r),
                        float(p.y + math.sin(a) * r),
                    )
                )

            return [
                CadPolyline(
                    points=tuple(pts),
                    layer=layer,
                    color=color,
                    closed=True,
                    source_type=entity_type,
                    group_id=group_id,
                    block_key=block_key,
                )
            ]

        if entity_type in {
            "ARC",
            "CIRCLE",
            "ELLIPSE",
            "SPLINE",
            "LWPOLYLINE",
            "POLYLINE",
            "HELIX",
            "HATCH",
        }:
            path = make_path(entity)
            vertices = list(
                path.flattening(
                    distance=self.flattening_distance,
                    segments=8,
                )
            )

            if len(vertices) < 2:
                return []

            points = tuple((float(v.x), float(v.y)) for v in vertices)
            closed = bool(getattr(path, "is_closed", False))

            return [
                CadPolyline(
                    points=points,
                    layer=layer,
                    color=color,
                    closed=closed,
                    source_type=entity_type,
                    group_id=group_id,
                    block_key=block_key,
                )
            ]

        return []

    @staticmethod
    def _resolve_color(doc, entity, layer: str) -> RGB:
        try:
            true_color = getattr(entity.dxf, "true_color", None)

            if true_color:
                return (
                    (true_color >> 16) & 255,
                    (true_color >> 8) & 255,
                    true_color & 255,
                )

            aci = int(getattr(entity.dxf, "color", 256))

            if aci in (0, 256):
                try:
                    aci = abs(int(doc.layers.get(layer).color))
                except Exception:
                    aci = 7

            if 1 <= aci <= 255:
                rgb = aci2rgb(aci)
                return int(rgb.r), int(rgb.g), int(rgb.b)

        except Exception:
            pass

        return 215, 221, 231
