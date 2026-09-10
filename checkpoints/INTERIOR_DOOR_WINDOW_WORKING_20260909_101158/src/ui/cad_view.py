from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from cad.model import CadDocument


class CadGraphicsView(QGraphicsView):
    plan_area_selected = Signal(float, float, float, float)

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
        self._window_overlays: list[QGraphicsPathItem] = []
        self._door_overlays: list[QGraphicsPathItem] = []

        self._plan_select_mode = False
        self._plan_start: QPointF | None = None
        self._plan_preview: QGraphicsRectItem | None = None

    def set_document(self, document: CadDocument) -> None:
        self._document = document
        scene = self.scene()
        scene.clear()

        self._window_overlays = []
        self._door_overlays = []
        self._plan_select_mode = False
        self._plan_start = None
        self._plan_preview = None
        self.unsetCursor()
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        for primitive in document.primitives:
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

        for text in document.texts:
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

    def begin_plan_selection(self) -> None:
        if self._document is None:
            return

        self._plan_select_mode = True
        self._plan_start = None
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)

        if self._plan_preview is not None:
            self.scene().removeItem(self._plan_preview)
            self._plan_preview = None

    def mousePressEvent(self, event) -> None:
        if self._plan_select_mode and event.button() == Qt.LeftButton:
            self._plan_start = self.mapToScene(event.position().toPoint())

            if self._plan_preview is not None:
                self.scene().removeItem(self._plan_preview)

            self._plan_preview = QGraphicsRectItem()
            pen = QPen(QColor("#ffffff"))
            pen.setCosmetic(True)
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(1.0)
            self._plan_preview.setPen(pen)
            self._plan_preview.setBrush(Qt.NoBrush)
            self._plan_preview.setZValue(1000000)
            self.scene().addItem(self._plan_preview)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._plan_select_mode
            and self._plan_start is not None
            and self._plan_preview is not None
        ):
            current = self.mapToScene(event.position().toPoint())
            self._plan_preview.setRect(
                QRectF(self._plan_start, current).normalized()
            )
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._plan_select_mode
            and event.button() == Qt.LeftButton
            and self._plan_start is not None
            and self._plan_preview is not None
        ):
            end = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._plan_start, end).normalized()

            self._plan_start = None
            self._plan_select_mode = False
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.unsetCursor()

            if self._plan_preview is not None:
                self.scene().removeItem(self._plan_preview)
                self._plan_preview = None

            if rect.width() <= 0.0 or rect.height() <= 0.0:
                event.accept()
                return

            xmin = float(rect.left())
            xmax = float(rect.right())

            cad_y1 = float(-rect.top())
            cad_y2 = float(-rect.bottom())
            ymin = min(cad_y1, cad_y2)
            ymax = max(cad_y1, cad_y2)

            self.plan_area_selected.emit(xmin, ymin, xmax, ymax)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def show_window_rectangles(self, candidates) -> None:
        for item in self._window_overlays:
            self.scene().removeItem(item)

        self._window_overlays = []

        pen = QPen(QColor("#ff0000"))
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
    def clear_document(self) -> None:
        self._document = None
        self.scene().clear()
        self._window_overlays = []
        self._door_overlays = []
        self._plan_select_mode = False
        self._plan_start = None
        self._plan_preview = None
        self.unsetCursor()
        self.setDragMode(QGraphicsView.ScrollHandDrag)

    def fit_all(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if not rect.isNull():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)

        factor = 1.18 if delta > 0 else 1 / 1.18
        self.scale(factor, factor)
