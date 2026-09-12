from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from cad.model import CadDocument


_CAD3D_ANNOTATION_SOURCE_TYPES = {
    "TEXT", "MTEXT", "DIMENSION", "LEADER", "MLEADER", "HATCH", "POINT",
}

def _cad3d_is_annotation_primitive(primitive):
    return str(getattr(primitive, "source_type", "") or "").upper() in _CAD3D_ANNOTATION_SOURCE_TYPES

class CadGraphicsView(QGraphicsView):
    plan_area_selected = Signal(float, float, float, float)

    # CAD_TO_3D_MAX_PIVOT_PORT_V1
    pivot_committed = Signal(float, float, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#191A1B"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

        self._document: CadDocument | None = None
        self._plan_cleanup_active = False
        self._window_overlays: list[QGraphicsPathItem] = []
        self._door_overlays: list[QGraphicsPathItem] = []
        self._wall_overlays: list[QGraphicsPathItem] = []
        self._confirmed_floor_labels: dict[tuple[float, float, float, float], QGraphicsSimpleTextItem] = {}
        self._floor_label_item: QGraphicsSimpleTextItem | None = None

        self._plan_select_mode = False
        self._plan_start: QPointF | None = None
        self._plan_preview: QGraphicsRectItem | None = None

        # CAD_TO_3D_MAX_PIVOT_STATE_V1
        self.pivot_edit_enabled = False
        self.pivot_drag_active = False
        self.pivot_point_cad = None
        self.pivot_hover_cad = None
        self.pivot_snap_kind = ""
        self.pivot_reference_geometry = None
        self.pivot_reference_origin = None
        self.pivot_snap_radius_px = 14.0

        # CAD3D_FLOOR_EDIT_REUSE_GHOST_PAN_V2
        self._pivot_pan_active = False
        self._pivot_pan_last_global = None

        # Visual-only master floor projection.
        self._pivot_ghost_geometry = ()
        self._pivot_ghost_origin = None


    def set_plan_cleanup_active(self, active: bool) -> None:
        self._plan_cleanup_active = bool(active)

    def set_document(self, document: CadDocument) -> None:
        self._document = document
        scene = self.scene()
        scene.clear()
        self._confirmed_floor_labels = {}

        self._window_overlays = []
        self._door_overlays = []
        self._wall_overlays = []
        self._floor_label_item = None
        self._plan_select_mode = False
        self._plan_start = None
        self._plan_preview = None
        self.unsetCursor()
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        for primitive in document.primitives:
            if getattr(self, "_plan_cleanup_active", False) and _cad3d_is_annotation_primitive(primitive):
                continue
            if len(primitive.points) < 2:
                continue

            path = QPainterPath()
            x0, y0 = primitive.points[0]
            path.moveTo(x0, -y0)

            for x, y in primitive.points[1:]:
                path.lineTo(x, -y)

            if primitive.closed:
                path.closeSubpath()

            r, g, b = primitive.color
            if max(r, g, b) < 65:
                r, g, b = 215, 215, 215

            item = QGraphicsPathItem(path)
            pen = QPen(QColor(r, g, b))
            pen.setCosmetic(True)
            pen.setWidthF(1.0)
            item.setPen(pen)
            scene.addItem(item)

        for text in (() if getattr(self, "_plan_cleanup_active", False) else document.texts):
            r, g, b = text.color
            if max(r, g, b) < 65:
                r, g, b = 215, 215, 215

            item = QGraphicsSimpleTextItem(text.text)
            font = QFont("Arial")
            font.setPixelSize(max(1, int(round(text.height))))
            item.setFont(font)
            item.setBrush(QColor(r, g, b))

            x, y = text.position
            item.setPos(x, -y)
            item.setRotation(-text.rotation)
            scene.addItem(item)

        rect = scene.itemsBoundingRect()
        if not rect.isNull():
            pad = max(rect.width(), rect.height()) * 0.02
            scene.setSceneRect(rect.adjusted(-pad, -pad, pad, pad))
            self.fit_all()

    def set_floor_label(self, text: str) -> None:
        """
        Secili kat adini plan geometrisinin altinda gosterir.

        Bu sadece UI etiketidir.
        CAD primitive'i veya Max export geometrisi degildir.
        """

        scene = self.scene()

        if self._floor_label_item is not None:
            if self._floor_label_item.scene() is not None:
                scene.removeItem(self._floor_label_item)

            self._floor_label_item = None

        text = str(text or "").strip()

        if not text:
            return

        geometry_items = [
            item
            for item in scene.items()
            if isinstance(item, QGraphicsPathItem)
            and item not in self._wall_overlays
            and item not in self._door_overlays
            and item not in self._window_overlays
        ]

        if geometry_items:
            rect = geometry_items[0].sceneBoundingRect()

            for item in geometry_items[1:]:
                rect = rect.united(
                    item.sceneBoundingRect()
                )
        else:
            rect = scene.itemsBoundingRect()

        if rect.isNull():
            return

        label = QGraphicsSimpleTextItem(text)

        font = QFont("Arial")
        font.setBold(True)
        font.setPointSize(12)

        label.setFont(font)
        label.setBrush(
            QColor("#f0f0f0")
        )
        label.setZValue(2000000)

        label_rect = label.boundingRect()

        gap = max(
            rect.height() * 0.025,
            label_rect.height() * 0.75,
        )

        x = (
            rect.center().x()
            - label_rect.width() * 0.5
        )

        y = (
            rect.bottom()
            + gap
        )

        label.setPos(x, y)

        scene.addItem(label)
        self._floor_label_item = label



    # ========================================================
    # CAD_to_3D_Max style viewport pivot
    # ========================================================

    # PIVOT_GHOST_SCENEITEM_MOUSE_ZOOM_V2
    def set_pivot_edit_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.pivot_edit_enabled = bool(
            enabled
        )

        self.pivot_drag_active = False

        if self.pivot_edit_enabled:
            self._plan_select_mode = False

            self.setDragMode(
                QGraphicsView.NoDrag
            )

            # Mevcut kayitli pivot varsa preview
            # dogrudan onun uzerinde acilir.
            if (
                self.pivot_point_cad
                is not None
            ):
                self.pivot_hover_cad = (
                    self.pivot_point_cad
                )

            else:
                # Yeni katta Pivot Belirle'ye basildigi anda
                # mouse'un mevcut CAD konumunu kullan.
                try:
                    from PySide6.QtGui import QCursor

                    viewport_point = (
                        self.viewport().mapFromGlobal(
                            QCursor.pos()
                        )
                    )

                    if (
                        self.viewport()
                        .rect()
                        .contains(
                            viewport_point
                        )
                        and self._document
                        is not None
                    ):
                        (
                            point,
                            snap_kind,
                        ) = self._snap_pivot(
                            viewport_point
                        )

                        self.pivot_hover_cad = (
                            point
                        )

                        self.pivot_snap_kind = (
                            snap_kind
                        )

                    else:
                        self.pivot_hover_cad = (
                            None
                        )

                except Exception:
                    self.pivot_hover_cad = None

            self.viewport().setCursor(
                Qt.CrossCursor
            )

        else:
            self.pivot_hover_cad = None

            if not getattr(
                self,
                "_plan_select_mode",
                False,
            ):
                self.setDragMode(
                    QGraphicsView.ScrollHandDrag
                )

                self.viewport().unsetCursor()

        self._refresh_pivot_ghost_item()

        self.viewport().update()



    def set_pivot_reference_geometry(
        self,
        geometry,
        origin=None,
    ) -> None:
        cleaned = []

        for item in geometry or ():
            if isinstance(
                item,
                dict,
            ):
                raw_points = item.get(
                    "points",
                    (),
                )
            else:
                raw_points = item

            points = []

            for value in raw_points or ():
                try:
                    if (
                        hasattr(
                            value,
                            "x",
                        )
                        and hasattr(
                            value,
                            "y",
                        )
                    ):
                        x_value = value.x

                        if callable(x_value):
                            x_value = x_value()

                        y_value = value.y

                        if callable(y_value):
                            y_value = y_value()

                        x = float(
                            x_value
                        )

                        y = float(
                            y_value
                        )

                    else:
                        x = float(
                            value[0]
                        )

                        y = float(
                            value[1]
                        )

                except (
                    TypeError,
                    ValueError,
                    IndexError,
                    AttributeError,
                ):
                    continue

                points.append(
                    (
                        x,
                        y,
                    )
                )

            if len(points) >= 2:
                cleaned.append(
                    tuple(points)
                )

        self.pivot_reference_geometry = tuple(
            cleaned
        )

        if origin is None:
            self.pivot_reference_origin = None

        else:
            try:
                self.pivot_reference_origin = (
                    float(origin[0]),
                    float(origin[1]),
                )

            except (
                TypeError,
                ValueError,
                IndexError,
            ):
                self.pivot_reference_origin = None

        self.viewport().update()


    def _ensure_pivot_ghost_item(
        self,
    ):
        scene = self.scene()

        item = getattr(
            self,
            "_pivot_ghost_item",
            None,
        )

        if item is not None:
            try:
                if item.scene() is scene:
                    return item
            except RuntimeError:
                pass

        item = QGraphicsPathItem()

        pen = QPen(
            QColor(
                215,
                220,
                225,
                115,
            )
        )

        pen.setCosmetic(
            True
        )

        pen.setWidthF(
            1.2
        )

        item.setPen(
            pen
        )

        item.setBrush(
            Qt.NoBrush
        )

        item.setZValue(
            2500000
        )

        item.setAcceptedMouseButtons(
            Qt.NoButton
        )

        scene.addItem(
            item
        )

        self._pivot_ghost_item = (
            item
        )

        return item


    def _refresh_pivot_ghost_item(
        self,
        point=None,
    ) -> None:
        item = getattr(
            self,
            "_pivot_ghost_item",
            None,
        )

        origin = getattr(
            self,
            "_pivot_ghost_origin",
            None,
        )

        ghost_path = getattr(
            self,
            "_pivot_ghost_path",
            None,
        )

        if item is None:
            return

        try:
            if (
                ghost_path is None
                or ghost_path.isEmpty()
                or not isinstance(
                    origin,
                    (tuple, list),
                )
                or len(origin) < 2
                or not self.pivot_edit_enabled
            ):
                item.setVisible(
                    False
                )
                return

            candidate = point

            if candidate is None:
                candidate = (
                    self.pivot_hover_cad
                    if self.pivot_hover_cad
                    is not None
                    else self.pivot_point_cad
                )

            if candidate is None:
                item.setVisible(
                    False
                )
                return

            dx = (
                float(candidate[0])
                - float(origin[0])
            )

            dy = (
                float(candidate[1])
                - float(origin[1])
            )

            # CAD +Y = scene -Y
            item.setPos(
                dx,
                -dy,
            )

            item.setVisible(
                True
            )

        except RuntimeError:
            self._pivot_ghost_item = (
                None
            )


    def set_pivot_ghost_geometry(
        self,
        geometry,
        origin,
    ) -> None:
        """
        Master/reference floor preview.

        Geometry is constructed ONCE as a scene path.
        During pivot placement only item position changes.
        """

        cleaned = []

        path = QPainterPath()

        for item_data in geometry or ():
            if isinstance(
                item_data,
                dict,
            ):
                raw_points = item_data.get(
                    "points",
                    (),
                )
            else:
                raw_points = item_data

            points = []

            for value in raw_points or ():
                try:
                    point = (
                        float(value[0]),
                        float(value[1]),
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

            cleaned.append(
                tuple(points)
            )

            first = points[0]

            path.moveTo(
                float(first[0]),
                -float(first[1]),
            )

            for current in points[1:]:
                path.lineTo(
                    float(current[0]),
                    -float(current[1]),
                )

        self._pivot_ghost_geometry = tuple(
            cleaned
        )

        self._pivot_ghost_path = (
            path
        )

        try:
            self._pivot_ghost_origin = (
                float(origin[0]),
                float(origin[1]),
            )

        except (
            TypeError,
            ValueError,
            IndexError,
        ):
            self._pivot_ghost_origin = (
                None
            )

        ghost_item = (
            self._ensure_pivot_ghost_item()
        )

        ghost_item.setPath(
            path
        )

        self._refresh_pivot_ghost_item()

        self.viewport().update()


    def clear_pivot_ghost(
        self,
    ) -> None:
        item = getattr(
            self,
            "_pivot_ghost_item",
            None,
        )

        if item is not None:
            try:
                scene = item.scene()

                if scene is not None:
                    scene.removeItem(
                        item
                    )
            except RuntimeError:
                pass

        self._pivot_ghost_item = None
        self._pivot_ghost_geometry = ()
        self._pivot_ghost_origin = None
        self._pivot_ghost_path = None

        self.viewport().update()


    def set_pivot_point(
        self,
        point,
        snap_kind="",
    ) -> None:
        if point is None:
            self.pivot_point_cad = None
            self.pivot_hover_cad = None
            self.pivot_snap_kind = ""

            self._refresh_pivot_ghost_item()

            self.viewport().update()
            return

        self.pivot_point_cad = (
            float(point[0]),
            float(point[1]),
        )

        self.pivot_hover_cad = (
            self.pivot_point_cad
        )

        self.pivot_snap_kind = str(
            snap_kind or ""
        )

        self._refresh_pivot_ghost_item(
            self.pivot_point_cad
        )

        self.viewport().update()



    def clear_pivot(
        self,
    ) -> None:
        self.pivot_edit_enabled = False
        self.pivot_drag_active = False

        self.pivot_point_cad = None
        self.pivot_hover_cad = None
        self.pivot_snap_kind = ""

        self.pivot_reference_geometry = None
        self.pivot_reference_origin = None

        self._pivot_pan_active = False
        self._pivot_pan_last_global = None

        self.clear_pivot_ghost()

        if not getattr(
            self,
            "_plan_select_mode",
            False,
        ):
            self.setDragMode(
                QGraphicsView.ScrollHandDrag
            )

            self.viewport().unsetCursor()

        self.viewport().update()


    @staticmethod
    def _pivot_nearest_point_on_segment(point, a, b):
        px, py = point
        ax, ay = a
        bx, by = b

        dx = bx - ax
        dy = by - ay
        length2 = dx * dx + dy * dy

        if length2 <= 1.0e-18:
            return a

        t = (
            ((px - ax) * dx + (py - ay) * dy)
            / length2
        )

        t = max(0.0, min(1.0, t))

        return (
            ax + dx * t,
            ay + dy * t,
        )


    def _pivot_pixel_distance(
        self,
        cad_point,
        viewport_point,
    ) -> float:
        from PySide6.QtCore import QPointF
        import math

        screen = self.mapFromScene(
            QPointF(
                float(cad_point[0]),
                -float(cad_point[1]),
            )
        )

        return math.hypot(
            float(screen.x() - viewport_point.x()),
            float(screen.y() - viewport_point.y()),
        )


    def _snap_pivot(self, viewport_point):
        """
        CAD_to_3D_Max davranisi:
        - snap mesafesi ekran pikselidir;
        - reference geometry ayridir;
        - tum CAD primitive'leri snap havuzu degildir;
        - once referans/orijin ve gercek vertex;
        - sonra referans segment govdesi;
        - radius disinda serbest CAD noktasi.
        """
        scene_point = self.mapToScene(viewport_point)

        raw = (
            float(scene_point.x()),
            -float(scene_point.y()),
        )

        radius = float(
            getattr(
                self,
                "pivot_snap_radius_px",
                14.0,
            )
        )

        origin = getattr(
            self,
            "pivot_reference_origin",
            None,
        )

        if origin is not None:
            distance = self._pivot_pixel_distance(
                origin,
                viewport_point,
            )

            if distance <= radius:
                return (
                    (float(origin[0]), float(origin[1])),
                    "reference_origin",
                )

        geometry = tuple(
            getattr(
                self,
                "pivot_reference_geometry",
                (),
            )
            or ()
        )

        # ----------------------------------------------------
        # 1. WALL VERTEX / ENDPOINT
        # ----------------------------------------------------
        best_point = None
        best_distance = radius + 1.0

        for points in geometry:
            for point in points:
                distance = self._pivot_pixel_distance(
                    point,
                    viewport_point,
                )

                if distance < best_distance:
                    best_distance = distance
                    best_point = point

        if best_point is not None and best_distance <= radius:
            return (
                (
                    float(best_point[0]),
                    float(best_point[1]),
                ),
                "wall_vertex",
            )

        # ----------------------------------------------------
        # 2. WALL SEGMENT BODY
        # ----------------------------------------------------
        best_point = None
        best_distance = radius + 1.0

        for points in geometry:
            for a, b in zip(points, points[1:]):
                nearest = self._pivot_nearest_point_on_segment(
                    raw,
                    a,
                    b,
                )

                distance = self._pivot_pixel_distance(
                    nearest,
                    viewport_point,
                )

                if distance < best_distance:
                    best_distance = distance
                    best_point = nearest

        if best_point is not None and best_distance <= radius:
            return (
                (
                    float(best_point[0]),
                    float(best_point[1]),
                ),
                "wall_segment",
            )

        return raw, "free"



    # CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2
    def clear_facade_match_preview(
        self,
    ) -> None:
        items = list(
            getattr(
                self,
                "_facade_match_preview_items",
                (),
            )
            or ()
        )

        for item in items:
            try:
                if item.scene() is self.scene():
                    self.scene().removeItem(
                        item
                    )
            except RuntimeError:
                pass

        self._facade_match_preview_items = []

        self.viewport().update()


    # FACADE_MATCH_LABEL_LAYOUT_V3
    def show_facade_match_preview(
        self,
        result,
    ) -> int:
        """
        Facade matching visual preview.

        RULES:
        - plan numbers are OUTSIDE the matched plan side;
        - elevation numbers are ABOVE elevation drawings;
        - all numbers are RED;
        - labels are visual only;
        - result data is unchanged;
        - viewport automatically fits after labels are created.
        """

        self.clear_facade_match_preview()

        if not isinstance(
            result,
            dict,
        ):
            return 0


        def clean_bbox(
            value,
        ):
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


        labels = []


        # ====================================================
        # MAIN PLAN BOUNDS
        #
        # Plan-side numbers are no longer allowed inside
        # the floor-plan drawing.
        # ====================================================

        main_plan = result.get(
            "main_plan"
        )

        plan_box = None

        if isinstance(
            main_plan,
            dict,
        ):
            plan_box = clean_bbox(
                main_plan.get(
                    "bbox"
                )
            )


        # ====================================================
        # ELEVATION NUMBERS
        #
        # Number is always centered ABOVE the actual
        # elevation bounding box.
        # ====================================================

        seen_facades = set()

        for facade in (
            result.get(
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

            try:
                number = int(
                    facade.get(
                        "facade_number"
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if number in seen_facades:
                continue

            box = clean_bbox(
                facade.get(
                    "bbox"
                )
            )

            if box is None:
                continue

            seen_facades.add(
                number
            )

            x0, y0, x1, y1 = box

            width = (
                x1 - x0
            )

            height = (
                y1 - y0
            )

            center_x = (
                x0 + x1
            ) * 0.5

            # Generic spacing proportional to drawing size.
            gap = max(
                height * 0.08,
                width * 0.015,
                1.0,
            )

            # CAD +Y = upward.
            # Therefore y1 + gap is ABOVE the elevation.
            label_point = (
                center_x,
                y1 + gap,
            )

            labels.append(
                (
                    "facade",
                    number,
                    label_point,
                )
            )


        # ====================================================
        # PLAN NUMBERS
        #
        # Same facade number is placed OUTSIDE the matching
        # plan side.
        # ====================================================

        seen_plan_labels = set()

        if plan_box is not None:

            px0, py0, px1, py1 = (
                plan_box
            )

            plan_width = (
                px1 - px0
            )

            plan_height = (
                py1 - py0
            )

            center_x = (
                px0 + px1
            ) * 0.5

            center_y = (
                py0 + py1
            ) * 0.5

            plan_gap = max(
                min(
                    plan_width,
                    plan_height,
                )
                * 0.04,
                1.0,
            )

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

                try:
                    number = int(
                        match.get(
                            "facade_number"
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                side = str(
                    match.get(
                        "plan_side",
                        "",
                    )
                    or ""
                ).strip().lower()

                key = (
                    number,
                    side,
                )

                if key in seen_plan_labels:
                    continue

                if side == "bottom":
                    point = (
                        center_x,
                        py0 - plan_gap,
                    )

                elif side == "top":
                    point = (
                        center_x,
                        py1 + plan_gap,
                    )

                elif side == "left":
                    point = (
                        px0 - plan_gap,
                        center_y,
                    )

                elif side == "right":
                    point = (
                        px1 + plan_gap,
                        center_y,
                    )

                else:
                    continue

                seen_plan_labels.add(
                    key
                )

                labels.append(
                    (
                        "plan",
                        number,
                        point,
                    )
                )


        # ====================================================
        # DRAW LABELS
        # ====================================================

        created = []

        for (
            label_kind,
            number,
            cad_point,
        ) in labels:

            label = QGraphicsSimpleTextItem(
                str(number)
            )

            font = QFont(
                "Arial"
            )

            font.setPointSize(
                14
            )

            font.setBold(
                True
            )

            label.setFont(
                font
            )

            # Requested facade numbering color.
            label.setBrush(
                QColor(
                    255,
                    0,
                    0,
                )
            )

            label.setFlag(
                QGraphicsItem.ItemIgnoresTransformations,
                True,
            )

            label.setAcceptedMouseButtons(
                Qt.NoButton
            )

            label.setZValue(
                3000000
            )

            scene_x = float(
                cad_point[0]
            )

            # CAD +Y -> scene -Y
            scene_y = -float(
                cad_point[1]
            )

            label_rect = (
                label.boundingRect()
            )

            label.setPos(
                scene_x
                - label_rect.width()
                * 0.5,

                scene_y
                - label_rect.height()
                * 0.5,
            )

            self.scene().addItem(
                label
            )

            created.append(
                label
            )


        self._facade_match_preview_items = (
            created
        )

        self.viewport().update()


        # ====================================================
        # AUTO FIT
        #
        # Existing fit_all() uses scene.itemsBoundingRect().
        # Therefore CAD + outside plan labels + elevation
        # labels are fitted together.
        # ====================================================

        if created:
            self.fit_all()

        self.viewport().update()

        print("")
        print(
            "=== FACADE MATCH LABEL LAYOUT V3 ==="
        )
        print(
            "PLAN LABELS OUTSIDE:",
            len(
                seen_plan_labels
            ),
        )
        print(
            "FACADE LABELS ABOVE:",
            len(
                seen_facades
            ),
        )
        print(
            "COLOR: RED"
        )
        print(
            "AUTO FIT: YES"
        )
        print(
            "=== END FACADE LABEL LAYOUT ==="
        )
        print("")

        return len(
            created
        )


    def begin_plan_selection(self) -> None:
        self.set_pivot_edit_enabled(False)
        if self._document is None:
            return

        self._plan_select_mode = True
        self._plan_start = None
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)

        if self._plan_preview is not None:
            self.scene().removeItem(self._plan_preview)
            self._plan_preview = None


    def mousePressEvent(
        self,
        event,
    ) -> None:

        # MIDDLE = PAN
        if (
            event.button()
            == Qt.MiddleButton
        ):
            self._pivot_pan_active = (
                True
            )

            self._pivot_pan_last_global = (
                event.globalPosition().toPoint()
            )

            self.viewport().setCursor(
                Qt.ClosedHandCursor
            )

            event.accept()
            return

        # LEFT = PIVOT
        if (
            self.pivot_edit_enabled
            and event.button()
            == Qt.LeftButton
            and self._document is not None
        ):
            (
                point,
                snap_kind,
            ) = self._snap_pivot(
                event.position().toPoint()
            )

            self.pivot_point_cad = (
                point
            )

            self.pivot_hover_cad = (
                point
            )

            self.pivot_snap_kind = (
                snap_kind
            )

            self.pivot_drag_active = (
                True
            )

            self._refresh_pivot_ghost_item(
                point
            )

            self.viewport().setCursor(
                Qt.SizeAllCursor
            )

            self.viewport().update()

            event.accept()
            return

        # LEFT = PLAN SELECTION
        if (
            self._plan_select_mode
            and event.button()
            == Qt.LeftButton
        ):
            self._plan_start = (
                self.mapToScene(
                    event.position().toPoint()
                )
            )

            if (
                self._plan_preview
                is not None
            ):
                self.scene().removeItem(
                    self._plan_preview
                )

            self._plan_preview = (
                QGraphicsRectItem()
            )

            pen = QPen(
                QColor("#ffffff")
            )

            pen.setCosmetic(
                True
            )

            pen.setStyle(
                Qt.DashLine
            )

            pen.setWidthF(
                1.0
            )

            self._plan_preview.setPen(
                pen
            )

            self._plan_preview.setBrush(
                Qt.NoBrush
            )

            self._plan_preview.setZValue(
                1000000
            )

            self.scene().addItem(
                self._plan_preview
            )

            event.accept()
            return

        super().mousePressEvent(
            event
        )


    def mouseMoveEvent(
        self,
        event,
    ) -> None:

        # MIDDLE PAN ALWAYS HAS PRIORITY
        if (
            getattr(
                self,
                "_pivot_pan_active",
                False,
            )
            and getattr(
                self,
                "_pivot_pan_last_global",
                None,
            )
            is not None
        ):
            current = (
                event.globalPosition().toPoint()
            )

            delta = (
                current
                - self._pivot_pan_last_global
            )

            self._pivot_pan_last_global = (
                current
            )

            hbar = (
                self.horizontalScrollBar()
            )

            vbar = (
                self.verticalScrollBar()
            )

            hbar.setValue(
                hbar.value()
                - delta.x()
            )

            vbar.setValue(
                vbar.value()
                - delta.y()
            )

            event.accept()
            return

        # PIVOT HOVER / DRAG
        if (
            self.pivot_edit_enabled
            and self._document is not None
        ):
            (
                point,
                snap_kind,
            ) = self._snap_pivot(
                event.position().toPoint()
            )

            self.pivot_hover_cad = (
                point
            )

            self.pivot_snap_kind = (
                snap_kind
            )

            if self.pivot_drag_active:
                self.pivot_point_cad = (
                    point
                )

            self._refresh_pivot_ghost_item(
                point
            )

            self.viewport().update()

            event.accept()
            return

        # PLAN SELECTION
        if (
            self._plan_select_mode
            and self._plan_start
            is not None
            and self._plan_preview
            is not None
        ):
            current = (
                self.mapToScene(
                    event.position().toPoint()
                )
            )

            self._plan_preview.setRect(
                QRectF(
                    self._plan_start,
                    current,
                ).normalized()
            )

            event.accept()
            return

        super().mouseMoveEvent(
            event
        )


    def mouseReleaseEvent(
        self,
        event,
    ) -> None:

        # END MIDDLE PAN
        if (
            getattr(
                self,
                "_pivot_pan_active",
                False,
            )
            and event.button()
            == Qt.MiddleButton
        ):
            self._pivot_pan_active = (
                False
            )

            self._pivot_pan_last_global = (
                None
            )

            if self.pivot_edit_enabled:
                self.viewport().setCursor(
                    Qt.CrossCursor
                )

            elif getattr(
                self,
                "_plan_select_mode",
                False,
            ):
                self.viewport().setCursor(
                    Qt.CrossCursor
                )

            else:
                self.viewport().unsetCursor()

            event.accept()
            return

        # PIVOT COMMIT
        if (
            self.pivot_edit_enabled
            and self.pivot_drag_active
            and event.button()
            == Qt.LeftButton
        ):
            (
                point,
                snap_kind,
            ) = self._snap_pivot(
                event.position().toPoint()
            )

            self.pivot_point_cad = (
                point
            )

            self.pivot_hover_cad = (
                point
            )

            self.pivot_snap_kind = (
                snap_kind
            )

            self.pivot_drag_active = (
                False
            )

            self.pivot_edit_enabled = (
                False
            )

            self._refresh_pivot_ghost_item(
                point
            )

            self.setDragMode(
                QGraphicsView.ScrollHandDrag
            )

            self.viewport().unsetCursor()
            self.viewport().update()

            self.pivot_committed.emit(
                float(point[0]),
                float(point[1]),
                str(snap_kind),
            )

            event.accept()
            return

        # PLAN SELECTION COMMIT
        if (
            self._plan_select_mode
            and event.button()
            == Qt.LeftButton
            and self._plan_start
            is not None
            and self._plan_preview
            is not None
        ):
            end = self.mapToScene(
                event.position().toPoint()
            )

            rect = QRectF(
                self._plan_start,
                end,
            ).normalized()

            self._plan_start = None
            self._plan_select_mode = False

            self.setDragMode(
                QGraphicsView.ScrollHandDrag
            )

            self.unsetCursor()

            if (
                self._plan_preview
                is not None
            ):
                self.scene().removeItem(
                    self._plan_preview
                )

                self._plan_preview = (
                    None
                )

            if (
                rect.width() <= 0.0
                or rect.height() <= 0.0
            ):
                event.accept()
                return

            xmin = float(
                rect.left()
            )

            xmax = float(
                rect.right()
            )

            cad_y1 = float(
                -rect.top()
            )

            cad_y2 = float(
                -rect.bottom()
            )

            ymin = min(
                cad_y1,
                cad_y2,
            )

            ymax = max(
                cad_y1,
                cad_y2,
            )

            self.plan_area_selected.emit(
                xmin,
                ymin,
                xmax,
                ymax,
            )

            event.accept()
            return

        super().mouseReleaseEvent(
            event
        )

    def _show_window_rectangles_base(self, candidates) -> None:
        for item in self._window_overlays:
            self.scene().removeItem(item)

        self._window_overlays = []

        pen = QPen(QColor("#ff8c00"))
        pen.setCosmetic(True)
        pen.setWidthF(2.0)

        for candidate in candidates:
            corners = candidate.corners
            if not corners or len(corners) != 4:
                continue

            path = QPainterPath()
            x0, y0 = corners[0]
            path.moveTo(x0, -y0)

            for x, y in corners[1:]:
                path.lineTo(x, -y)

            path.closeSubpath()

            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(1000000)

            self.scene().addItem(item)
            self._window_overlays.append(item)



    # WINDOW_VIEW_INSIDE_LINES_V1
    def show_window_rectangles(self, candidates) -> None:
        # Once window detection has expanded candidate.lines with
        # geometry inside the detected rectangle, show those lines too.
        # Only explicitly selected window geometry is displayed.
        # Rectangle boundary geometry must not be drawn as selection.
        for item in list(getattr(self, "_window_overlays", ())):
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)

        self._window_overlays.clear()

        pen = QPen(QColor("#ff8c00"))
        pen.setWidthF(2.0)
        pen.setCosmetic(True)

        for candidate in candidates:
            for a, b in getattr(candidate, "lines", ()) or ():
                path = QPainterPath()
                path.moveTo(float(a[0]), -float(a[1]))
                path.lineTo(float(b[0]), -float(b[1]))

                item = self.scene().addPath(path, pen)
                item.setZValue(1000001)
                self._window_overlays.append(item)
    def show_interior_door_primitives(
        self,
        document,
        primitive_indices,
    ) -> None:
        for item in self._door_overlays:
            self.scene().removeItem(item)

        self._door_overlays = []

        pen = QPen(QColor("#00ff00"))
        pen.setCosmetic(True)
        pen.setWidthF(2.0)

        for index in primitive_indices:
            if index < 0 or index >= len(document.primitives):
                continue

            primitive = document.primitives[index]
            points = tuple(primitive.points)

            if len(points) < 2:
                continue

            path = QPainterPath()
            x0, y0 = points[0]
            path.moveTo(float(x0), -float(y0))

            for x, y in points[1:]:
                path.lineTo(float(x), -float(y))

            if primitive.closed:
                path.closeSubpath()

            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(1000001)

            self.scene().addItem(item)
            self._door_overlays.append(item)
    def show_wall_primitives(
        self,
        document,
        primitive_indices,
    ) -> None:
        for item in self._wall_overlays:
            self.scene().removeItem(item)

        self._wall_overlays = []

        pen = QPen(QColor("#008cff"))
        pen.setCosmetic(True)
        pen.setWidthF(2.0)

        for index in primitive_indices:
            if index < 0 or index >= len(document.primitives):
                continue

            primitive = document.primitives[index]
            points = tuple(primitive.points)

            if len(points) < 2:
                continue

            path = QPainterPath()
            x0, y0 = points[0]
            path.moveTo(float(x0), -float(y0))

            for x, y in points[1:]:
                path.lineTo(float(x), -float(y))

            if primitive.closed:
                path.closeSubpath()

            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(1000002)

            self.scene().addItem(item)
            self._wall_overlays.append(item)
    # WALL_WINDOW_CONNECTOR_CANONICAL_V2
    # WALL_HIDE_NONWALL_LINES_V2


    def hide_non_wall_lines(self) -> None:
        wall_items = set(
            getattr(self, "_wall_overlays", ()) or ()
        )

        for item in self.scene().items():
            if item in wall_items:
                item.setVisible(True)
                continue

            if item.__class__.__name__ == "QGraphicsPathItem":
                item.setVisible(False)

    def set_confirmed_floor_label(
        self,
        bounds,
        floor_name: str,
    ) -> None:
        """
        Onaylanan kat adini, secilen kat planinin altinda gosterir.
        Bu bir UI etiketidir; CAD geometrisine dahil edilmez.
        """

        if not bounds or len(bounds) != 4:
            return

        xmin, ymin, xmax, ymax = (
            float(value)
            for value in bounds
        )

        key = (
            round(xmin, 6),
            round(ymin, 6),
            round(xmax, 6),
            round(ymax, 6),
        )

        scene = self.scene()

        old_item = self._confirmed_floor_labels.get(key)

        if old_item is not None:
            try:
                if old_item.scene() is scene:
                    scene.removeItem(old_item)
            except RuntimeError:
                pass

        label = QGraphicsSimpleTextItem(
            str(floor_name).strip()
        )

        font = QFont("Arial")
        font.setPointSize(11)
        font.setBold(True)

        label.setFont(font)
        label.setBrush(QColor("#ffffff"))

        # Zoom seviyesinden bagimsiz okunabilir kalsin.
        label.setFlag(
            QGraphicsItem.ItemIgnoresTransformations,
            True,
        )

        label.setZValue(3000000)

        center_x = (xmin + xmax) * 0.5

        # CAD view Y eksenini ters ciziyor.
        # CAD ymin, ekrandaki planin alt kenaridir.
        scene_bottom_y = -ymin

        plan_height = abs(ymax - ymin)
        gap = max(plan_height * 0.015, 1.0)

        # Yazinin kendi genisligini hesaba katarak
        # planin altinda tam ortala.
        label_rect = label.boundingRect()
        label_x = center_x - (label_rect.width() * 0.5)

        label.setPos(
            label_x,
            scene_bottom_y + gap,
        )

        scene.addItem(label)

        self._confirmed_floor_labels[key] = label


    def clear_confirmed_floor_labels(self) -> None:
        scene = self.scene()

        for item in tuple(
            self._confirmed_floor_labels.values()
        ):
            try:
                if item.scene() is scene:
                    scene.removeItem(item)
            except RuntimeError:
                pass

        self._confirmed_floor_labels = {}




    def drawForeground(
        self,
        painter,
        rect,
    ) -> None:
        super().drawForeground(
            painter,
            rect,
        )

        point = None

        if (
            getattr(
                self,
                "pivot_edit_enabled",
                False,
            )
            and getattr(
                self,
                "pivot_hover_cad",
                None,
            )
            is not None
        ):
            point = (
                self.pivot_hover_cad
            )

        else:
            point = getattr(
                self,
                "pivot_point_cad",
                None,
            )

        if point is None:
            return

        center = QPointF(
            float(point[0]),
            -float(point[1]),
        )

        scale = abs(
            float(
                self.transform().m11()
            )
        )

        if scale <= 1.0e-12:
            scale = 1.0

        # LARGE PIVOT ICON
        axis = (
            28.0 / scale
        )

        box = (
            8.0 / scale
        )

        x_pen = QPen(
            QColor(
                220,
                70,
                70,
            )
        )

        x_pen.setCosmetic(
            True
        )

        x_pen.setWidthF(
            3.0
        )

        painter.setPen(
            x_pen
        )

        painter.drawLine(
            QPointF(
                center.x() - axis,
                center.y(),
            ),
            QPointF(
                center.x() + axis,
                center.y(),
            ),
        )

        y_pen = QPen(
            QColor(
                80,
                205,
                115,
            )
        )

        y_pen.setCosmetic(
            True
        )

        y_pen.setWidthF(
            3.0
        )

        painter.setPen(
            y_pen
        )

        painter.drawLine(
            QPointF(
                center.x(),
                center.y() - axis,
            ),
            QPointF(
                center.x(),
                center.y() + axis,
            ),
        )

        center_pen = QPen(
            QColor(
                225,
                235,
                245,
            )
        )

        center_pen.setCosmetic(
            True
        )

        center_pen.setWidthF(
            2.0
        )

        painter.setPen(
            center_pen
        )

        painter.setBrush(
            Qt.NoBrush
        )

        painter.drawRect(
            QRectF(
                center.x() - box,
                center.y() - box,
                box * 2.0,
                box * 2.0,
            )
        )


    def clear_document(self) -> None:
        self.clear_pivot()
        self._confirmed_floor_labels = {}
        self._document = None
        self._plan_cleanup_active = False
        self.scene().clear()
        self._window_overlays = []
        self._door_overlays = []
        self._wall_overlays = []
        self._plan_select_mode = False
        self._plan_start = None
        self._plan_preview = None
        self.unsetCursor()
        self.setDragMode(QGraphicsView.ScrollHandDrag)

    def fit_all(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if not rect.isNull():
            self.fitInView(rect, Qt.KeepAspectRatio)


    def wheelEvent(
        self,
        event,
    ) -> None:
        delta = (
            event.angleDelta().y()
        )

        if delta == 0:
            super().wheelEvent(
                event
            )
            return

        mouse_pos = (
            event.position().toPoint()
        )

        # CAD/scene coordinate currently exactly under mouse.
        scene_under_mouse = (
            self.mapToScene(
                mouse_pos
            )
        )

        factor = (
            1.18
            if delta > 0
            else 1.0 / 1.18
        )

        current_scale = abs(
            float(
                self.transform().m11()
            )
        )

        proposed_scale = (
            current_scale
            * factor
        )

        # Generic viewport safety only.
        if (
            proposed_scale < 1.0e-7
            or proposed_scale > 1.0e7
        ):
            event.accept()
            return

        old_anchor = (
            self.transformationAnchor()
        )

        self.setTransformationAnchor(
            QGraphicsView.NoAnchor
        )

        self.scale(
            factor,
            factor,
        )

        # After scaling, find where the SAME CAD point moved
        # on the viewport.
        moved_view_pos = (
            self.mapFromScene(
                scene_under_mouse
            )
        )

        correction_x = (
            moved_view_pos.x()
            - mouse_pos.x()
        )

        correction_y = (
            moved_view_pos.y()
            - mouse_pos.y()
        )

        hbar = (
            self.horizontalScrollBar()
        )

        vbar = (
            self.verticalScrollBar()
        )

        hbar.setValue(
            hbar.value()
            + correction_x
        )

        vbar.setValue(
            vbar.value()
            + correction_y
        )

        self.setTransformationAnchor(
            old_anchor
        )

        # Pivot mode remains live after zoom.
        if (
            self.pivot_edit_enabled
            and self._document is not None
        ):
            (
                point,
                snap_kind,
            ) = self._snap_pivot(
                mouse_pos
            )

            self.pivot_hover_cad = (
                point
            )

            self.pivot_snap_kind = (
                snap_kind
            )

            if self.pivot_drag_active:
                self.pivot_point_cad = (
                    point
                )

            self._refresh_pivot_ghost_item(
                point
            )

        self.viewport().update()

        event.accept()
