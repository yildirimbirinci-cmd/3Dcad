from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QLineEdit,
    QComboBox,
    QDoubleSpinBox,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cad.loader import CadLoadError, CadLoader
from cad.plan_selection import crop_document
from cad.window_detector import detect_window_family
from cad.door_detector import detect_interior_doors
from cad.wall_detector import detect_walls
from cad.wall_rulebook import TOL, point_segment_distance, primitive_segments
from export.max_bridge import send_wall_lines_to_max
from ui.cad_view import CadGraphicsView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3Dcad")
        self.resize(1500, 900)
        self.setMinimumSize(1000, 650)

        self._loader = CadLoader(flattening_distance=0.5)
        self._current_path: Path | None = None
        self._full_document = None
        self._selected_document = None
        self._active_floor_document = None

        self._plan_view_active = False
        self._confirmed_floors = []
        self._build_ui()
        self._apply_main_menu_disabled_text_style()
        self._setup_building_elements_menu()
        self._install_global_button_click_glow()
        self._set_plan_tool_buttons_visible(False)
        self._set_cad_menu_mode(False)
        self._set_main_cad_action_buttons_enabled(False)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(285)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 18, 18, 18)
        side.setSpacing(10)

        title = QLabel("3Dcad")
        title.setObjectName("title")

        subtitle = QLabel("Mimari CAD → 3B")
        subtitle.setStyleSheet("color:#858585;")

        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(14)

        self.view = CadGraphicsView()
        self.view.plan_area_selected.connect(self._apply_plan_selection)

        load_btn = QPushButton("Mimari CAD Ekle")
        self._cad_menu_button = load_btn
        load_btn.setObjectName("primary")
        load_btn.clicked.connect(self._handle_cad_menu_button)

        self.plan_btn = QPushButton("Plan Seç")
        self.plan_btn.setEnabled(False)
        self.plan_btn.clicked.connect(self._begin_plan_selection)

        self.interior_door_btn = QPushButton("İç Kapı")

        self.interior_door_btn.setEnabled(True)
        self.interior_door_btn.clicked.connect(self._detect_interior_doors)

        self.wall_btn = QPushButton("Duvar")
        self.wall_btn.setEnabled(True)
        self.wall_btn.clicked.connect(self._detect_walls)
        self.window_btn = QPushButton("Pencere")
        self.window_btn.setEnabled(False)
        self.window_btn.clicked.connect(self._detect_window_family)

        sliding_door_btn = QPushButton("Sürgü Kapı")
        entrance_door_btn = QPushButton("Giriş Kapısı")

        fit_btn = QPushButton("Görünüme Sığdır")
        fit_btn.clicked.connect(self.view.fit_all)

        clear_btn = QPushButton("CAD'i Temizle")
        clear_btn.clicked.connect(self.clear_cad)

        self.generate_3d_btn = QPushButton("3D Oluştur")

        self._create_3d_button = self.generate_3d_btn

        self.generate_3d_btn.setVisible(False)
        self.generate_3d_btn.setObjectName("primary")
        self.generate_3d_btn.setEnabled(False)
        self.generate_3d_btn.clicked.connect(self._create_3d)

        side.addWidget(load_btn)
        side.addWidget(self.plan_btn)
        side.addWidget(self.interior_door_btn)
        side.addWidget(self.wall_btn)
        side.addWidget(self.window_btn)
        side.addWidget(sliding_door_btn)
        side.addWidget(entrance_door_btn)
        side.addWidget(fit_btn)
        side.addWidget(clear_btn)
        side.addWidget(self.generate_3d_btn)
        side.addSpacing(16)

        # ----------------------------------------------------
        # KAT AYARLARI
        # Plan secildikten sonra aktif olur.
        # ----------------------------------------------------

        self.floor_panel = QFrame()
        self.floor_panel.setObjectName("floorPanel")

        floor_layout = QVBoxLayout(self.floor_panel)
        floor_layout.setContentsMargins(0, 0, 0, 0)
        floor_layout.setSpacing(8)

        floor_title = QLabel("KAT AYARLARI")
        floor_title.setObjectName("sectionTitle")
        floor_layout.addWidget(floor_title)

        floor_name_label = QLabel("Kat İsmi")

        self.floor_name_combo = QComboBox()
        self.floor_name_combo.setEnabled(False)
        self.floor_name_combo.currentTextChanged.connect(
            self._update_floor_view_label
        )

        floor_layout.addWidget(floor_name_label)
        floor_layout.addWidget(self.floor_name_combo)

        interfloor_label = QLabel("Kat Arası (cm)")
        self.interfloor_spin = QDoubleSpinBox()
        self.interfloor_spin.setRange(0.0, 1000.0)
        self.interfloor_spin.setDecimals(1)
        self.interfloor_spin.setSingleStep(1.0)
        self.interfloor_spin.setValue(0.0)

        floor_layout.addWidget(interfloor_label)
        floor_layout.addWidget(self.interfloor_spin)

        wall_height_label = QLabel("Duvar Yüksekliği (cm)")
        self.wall_height_spin = QDoubleSpinBox()
        self.wall_height_spin.setRange(1.0, 2000.0)
        self.wall_height_spin.setDecimals(1)
        self.wall_height_spin.setSingleStep(1.0)
        self.wall_height_spin.setValue(280.0)

        floor_layout.addWidget(wall_height_label)
        floor_layout.addWidget(self.wall_height_spin)

        self.confirm_floor_btn = QPushButton("Planı Onayla")
        self.confirm_floor_btn.setObjectName("primary")
        self.confirm_floor_btn.clicked.connect(
            self._confirm_floor_plan
        )

        floor_layout.addWidget(self.confirm_floor_btn)

        self.floor_panel.setEnabled(False)
        self.floor_panel.setVisible(False)

        side.addWidget(self.floor_panel)
        side.addStretch(1)

        layout.addWidget(sidebar)
        layout.addWidget(self.view, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Hazır — DWG veya DXF dosyası ekleyin")

    def _detected_floor_plan_count(self) -> int:
        """
        Ana CAD gorunumundeki ayri plan alanlarinin sayisini dondurur.

        Simdilik mevcut plan secim kayitlari varsa onlar kullanilir.
        En az bir secili plan varsa 1 kabul edilir.

        Sonraki adimda bu fonksiyon dogrudan tum CAD geometrisindeki
        ayri plan kumelerini otomatik tespit edecek.
        """
        stored = getattr(
            self,
            "_floor_plan_regions",
            None,
        )

        if stored:
            return len(stored)

        if self._selected_document is not None:
            return 1

        return 0


    def _floor_name_sequence(self, count: int):
        """
        Algilanan kat sayisi kadar secilebilir kat adi olusturur.
        """

        if count <= 0:
            return ()

        names = (
            "-2. Kat",
            "-1. Kat",
            "Bodrum Kat",
            "Giriş Kat",
            "1. Kat",
            "2. Kat",
            "3. Kat",
            "4. Kat",
            "5. Kat",
            "6. Kat",
            "7. Kat",
            "8. Kat",
            "9. Kat",
            "10. Kat",
        )

        if count >= len(names):
            extra = tuple(
                f"{i}. Kat"
                for i in range(11, 11 + count - len(names))
            )
            names = names + extra

        return names[:count]


    def _refresh_floor_name_choices(self) -> None:
        """
        Kat ismi secim listesini doldurur.
        """

        current = self.floor_name_combo.currentText().strip()

        names = (
            "-2. Kat",
            "-1. Kat",
            "Bodrum Kat",
            "Giriş Kat",
            "1. Kat",
            "2. Kat",
            "3. Kat",
            "4. Kat",
            "5. Kat",
            "6. Kat",
            "7. Kat",
            "8. Kat",
            "9. Kat",
            "10. Kat",
        )

        self.floor_name_combo.blockSignals(True)

        self.floor_name_combo.clear()
        self.floor_name_combo.addItems(names)
        self.floor_name_combo.setEnabled(True)

        if current:
            index = self.floor_name_combo.findText(current)
        else:
            index = self.floor_name_combo.findText("Giriş Kat")

        if index >= 0:
            self.floor_name_combo.setCurrentIndex(index)

        self.floor_name_combo.blockSignals(False)

        self._update_floor_view_label(
            self.floor_name_combo.currentText()
        )

    def _update_floor_view_label(self, floor_name: str = "") -> None:
        """
        Kat dropdown'unda secilen ismi mevcut planin
        altinda view etiketi olarak gosterir.
        """

        if self._selected_document is None:
            self.view.set_floor_label("")
            return

        name = str(floor_name or "").strip()

        if not name and hasattr(self, "floor_name_combo"):
            name = self.floor_name_combo.currentText().strip()

        self.view.set_floor_label(name)


    def _confirm_floor_plan(self) -> None:
        """
        Aktif kat planinin bilgilerini hafizada tutar
        ve kat adini secilen planin altinda gosterir.
        """

        floor_document = getattr(
            self,
            "_active_floor_document",
            None,
        )

        bounds = getattr(
            self,
            "_active_floor_bounds",
            None,
        )

        if floor_document is None or not bounds:
            QMessageBox.warning(
                self,
                "Kat Planı",
                "Önce view içinden bir kat planı seçin.",
            )
            return

        floor_name = (
            self.floor_name_combo.currentText().strip()
        )

        if not floor_name:
            QMessageBox.warning(
                self,
                "Kat Planı",
                "Kat İsmi seçin.",
            )
            return

        floor_data = {
            "name": floor_name,
            "interfloor_cm": float(
                self.interfloor_spin.value()
            ),
            "wall_height_cm": float(
                self.wall_height_spin.value()
            ),
            "bounds": tuple(
                float(value)
                for value in bounds
            ),
            "document": floor_document,
        }

        # Fiziksel kat plani secim sinirlariyla tanimlanir.
        # Ayni plan tekrar onaylanirsa kaydi guncellenir.
        floor_key = tuple(
            round(float(value), 6)
            for value in bounds
        )

        replaced = False

        for index, existing in enumerate(
            self._confirmed_floors
        ):
            existing_bounds = existing.get(
                "bounds",
                (),
            )

            existing_key = tuple(
                round(float(value), 6)
                for value in existing_bounds
            )

            if existing_key == floor_key:
                self._confirmed_floors[index] = floor_data
                replaced = True
                break

        if not replaced:
            self._confirmed_floors.append(
                floor_data
            )

        # Kat adi sadece UI etiketi olarak mevcut view'a eklenir.
        # View crop edilmez ve diger onayli kat isimleri korunur.
        self.view.set_confirmed_floor_label(
            bounds,
            floor_name,
        )

        self._active_floor_document = None
        self._active_floor_bounds = None
        self._floor_selection_mode = False

        self.floor_panel.setVisible(False)
        self.floor_panel.setEnabled(False)

        self.statusBar().showMessage(
            f"{floor_name} onaylandı | "
            f"Kat arası: {floor_data['interfloor_cm']:.1f} cm | "
            f"Duvar: {floor_data['wall_height_cm']:.1f} cm | "
            f"Onaylı kat: {len(self._confirmed_floors)}"
        )

    def _setup_building_elements_menu(self) -> None:

        from PySide6.QtCore import (
            Qt,
            QPropertyAnimation,
            QParallelAnimationGroup,
            QEasingCurve,
        )

        from PySide6.QtWidgets import (
            QWidget,
            QVBoxLayout,
            QPushButton,
            QSizePolicy,
        )

        tool_order = (
            "İç Kapı",
            "Duvar",
            "Pencere",
            "Sürgü Kapı",
            "Giriş Kapısı",
        )

        found = {}

        for button in self.findChildren(QPushButton):
            name = button.text().strip()

            if name in tool_order and name not in found:
                found[name] = button

        missing = [
            name
            for name in tool_order
            if name not in found
        ]

        if missing:
            raise RuntimeError(
                f"Yapi Elemanlari butonlari eksik: {missing}"
            )

        buttons = [
            found[name]
            for name in tool_order
        ]

        parent_widget = buttons[0].parentWidget()

        if parent_widget is None:
            raise RuntimeError("Sidebar parent bulunamadi")

        parent_layout = parent_widget.layout()

        if parent_layout is None:
            raise RuntimeError("Sidebar layout bulunamadi")

        indices = []

        for button in buttons:
            index = parent_layout.indexOf(button)

            if index >= 0:
                indices.append(index)

        if not indices:
            raise RuntimeError(
                "Alt menu butonlari sidebar layout icinde bulunamadi"
            )

        insert_index = min(indices)

        # ====================================================
        # ANA GRUP
        # ====================================================

        group = QWidget(parent_widget)

        group.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )

        group_layout = QVBoxLayout(group)

        group_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        group_layout.setSpacing(0)

        # ====================================================
        # YAPI ELEMANLARI ANA BUTONU
        # ====================================================

        toggle = QPushButton(
            "Yapı Elemanları",
            group,
        )

        toggle.setCheckable(True)
        toggle.setChecked(False)

        toggle.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )

        group_layout.addWidget(toggle)

        # ====================================================
        # AÇILIR CLIP
        # ====================================================

        clip = QWidget(group)

        clip.setMinimumHeight(0)
        clip.setMaximumHeight(0)

        clip.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )

        clip_layout = QVBoxLayout(clip)

        clip_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        clip_layout.setSpacing(0)

        # Üst buton -> alt menu = 5 px
        clip_layout.addSpacing(5)

        # ====================================================
        # GERÇEK ALT MENÜ
        # ====================================================

        submenu = QWidget(clip)

        submenu.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )

        submenu_layout = QVBoxLayout(submenu)

        submenu_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        # Menü satırları arası = 3 px
        submenu_layout.setSpacing(3)

        rows = []

        # ====================================================
        # HER BUTON İÇİN 42 PX MENÜ SATIRI
        # ====================================================

        for button in buttons:

            parent_layout.removeWidget(button)

            # -----------------------------------------------
            # 42 px taşıyıcı MENÜ SATIRI
            # -----------------------------------------------

            row = QWidget(submenu)

            row.setFixedHeight(42)

            row.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )

            row_layout = QVBoxLayout(row)

            row_layout.setContentsMargins(
                0,
                0,
                0,
                0,
            )

            row_layout.setSpacing(0)

            # -----------------------------------------------
            # Mevcut gerçek buton = 22 px
            # -----------------------------------------------

            button.setParent(row)

            button.setFixedHeight(22)

            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)

            button.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )

            # 42 px alanın TAM ORTASINDA
            row_layout.addWidget(
                button,
                0,
                Qt.AlignVCenter,
            )

            submenu_layout.addWidget(row)

            rows.append(row)

        # ====================================================
        # ALT MENÜ TOPLAM YÜKSEKLİĞİ
        #
        # 5 x 42 = 210
        # 4 x 3  = 12
        # toplam = 222
        # ====================================================

        submenu_height = (
            len(rows) * 42
            + (len(rows) - 1) * 3
        )

        submenu.setFixedHeight(
            submenu_height
        )

        clip_layout.addWidget(submenu)

        # Üstten 5 px dahil:
        # 222 + 5 = 227
        clip_height = (
            5 + submenu_height
        )

        group_layout.addWidget(clip)

        parent_layout.insertWidget(
            insert_index,
            group,
        )

        self._building_elements_group = group
        self._building_elements_toggle = toggle
        self._building_elements_clip = clip
        self._building_elements_submenu = submenu
        self._building_elements_buttons = tuple(buttons)
        self._building_elements_rows = tuple(rows)

        self._building_elements_submenu_height = (
            submenu_height
        )

        self._building_elements_clip_height = (
            clip_height
        )

        # ====================================================
        # ANİMASYON
        # ====================================================

        min_animation = QPropertyAnimation(
            clip,
            b"minimumHeight",
            self,
        )

        max_animation = QPropertyAnimation(
            clip,
            b"maximumHeight",
            self,
        )

        for animation in (
            min_animation,
            max_animation,
        ):
            animation.setDuration(170)
            animation.setEasingCurve(
                QEasingCurve.OutCubic
            )

        animation_group = QParallelAnimationGroup(self)

        animation_group.addAnimation(
            min_animation
        )

        animation_group.addAnimation(
            max_animation
        )

        self._building_elements_min_animation = (
            min_animation
        )

        self._building_elements_max_animation = (
            max_animation
        )

        self._building_elements_animation_group = (
            animation_group
        )


        toggle.clicked.connect(
            self._toggle_building_elements_menu
        )

        group.setVisible(False)

        print(
            "BUILDING ELEMENTS 42PX ROW MENU READY | "
            f"row=42 | button=22 | gap=3 | "
            f"submenu={submenu_height} | clip={clip_height}"
        )





    def _install_global_button_click_glow(self) -> None:
        """
        Tum QPushButton nesnelerine ayni click glow uygulanir.

        Glow button SINIRLARI ICINDE cizilir.
        Bu nedenle parent/container tarafindan kirpilmaz.

        Normal durumda efekt gorunmez.
        """

        from PySide6.QtCore import (
            QEvent,
            Property,
            QRectF,
            Qt,
        )
        from PySide6.QtGui import (
            QColor,
            QPainter,
            QPen,
        )
        from PySide6.QtWidgets import (
            QPushButton,
            QWidget,
        )

        class _ButtonGlowOverlay(QWidget):

            def __init__(self, button):
                super().__init__(button)

                self._button = button
                self._strength = 0.0

                self.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                    True,
                )

                self.setAttribute(
                    Qt.WidgetAttribute.WA_TranslucentBackground,
                    True,
                )

                self.setGeometry(button.rect())

                button.installEventFilter(self)

                self.show()
                self.raise_()

            def eventFilter(self, obj, event):

                if (
                    obj is self._button
                    and event.type()
                    in (
                        QEvent.Type.Resize,
                        QEvent.Type.Show,
                    )
                ):
                    self.setGeometry(
                        self._button.rect()
                    )
                    self.raise_()

                return False

            def _get_strength(self):
                return self._strength

            def _set_strength(self, value):
                self._strength = max(
                    0.0,
                    min(1.0, float(value)),
                )
                self.update()

            strength = Property(
                float,
                _get_strength,
                _set_strength,
            )

            def paintEvent(self, event):

                if self._strength <= 0.001:
                    return

                painter = QPainter(self)

                painter.setRenderHint(
                    QPainter.RenderHint.Antialiasing,
                    True,
                )

                painter.setBrush(
                    Qt.BrushStyle.NoBrush
                )

                base_rect = QRectF(
                    self.rect()
                ).adjusted(
                    0.75,
                    0.75,
                    -0.75,
                    -0.75,
                )

                # Ayni glow her button icin:
                # dis kenarda guclu, ice dogru yumusayan 5 katman.
                layers = (
                    (0.0, 235, 1.5),
                    (1.2, 165, 1.5),
                    (2.4, 105, 1.4),
                    (3.6, 60, 1.3),
                    (4.8, 28, 1.2),
                )

                for inset, alpha, width in layers:

                    rect = base_rect.adjusted(
                        inset,
                        inset,
                        -inset,
                        -inset,
                    )

                    if (
                        rect.width() <= 0.0
                        or rect.height() <= 0.0
                    ):
                        continue

                    color = QColor(
                        47,
                        128,
                        255,
                        int(
                            alpha
                            * self._strength
                        ),
                    )

                    painter.setPen(
                        QPen(
                            color,
                            width,
                        )
                    )

                    painter.drawRoundedRect(
                        rect,
                        4.0,
                        4.0,
                    )

                painter.end()

        self._global_button_glow_overlays = {}
        self._global_button_glow_animations = {}
        self._global_button_glow_overlay_class = (
            _ButtonGlowOverlay
        )

        buttons = tuple(
            self.findChildren(QPushButton)
        )

        for button in buttons:

            overlay = _ButtonGlowOverlay(
                button
            )

            self._global_button_glow_overlays[
                button
            ] = overlay

            button.pressed.connect(
                lambda b=button:
                    self._pulse_global_button_click_glow(
                        b
                    )
            )

        has_building_elements = any(
            button.text().strip() == "Yapı Elemanları"
            for button in buttons
        )

        print(
            "UNIFORM INNER CLICK GLOW READY | "
            f"buttons={len(buttons)} | "
            f"building_elements={has_building_elements}"
        )

    def _pulse_global_button_click_glow(
        self,
        button,
    ) -> None:

        if not button.isEnabled():
            return

        from PySide6.QtCore import (
            QPropertyAnimation,
            QEasingCurve,
        )

        overlay = getattr(
            self,
            "_global_button_glow_overlays",
            {},
        ).get(button)

        if overlay is None:
            return

        animations = getattr(
            self,
            "_global_button_glow_animations",
            {},
        )

        old_animation = animations.get(
            button
        )

        if old_animation is not None:
            old_animation.stop()

        # BUTUN BUTONLAR ICIN AYNI DEGERLER
        animation = QPropertyAnimation(
            overlay,
            b"strength",
            self,
        )

        animation.setDuration(1200)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)

        animation.setEasingCurve(
            QEasingCurve.OutCubic
        )

        self._global_button_glow_animations[
            button
        ] = animation

        overlay.setProperty(
            "strength",
            1.0,
        )

        overlay.raise_()

        def cleanup():

            current = getattr(
                self,
                "_global_button_glow_animations",
                {},
            )

            if current.get(button) is animation:
                current.pop(
                    button,
                    None,
                )

            overlay.setProperty(
                "strength",
                0.0,
            )

        animation.finished.connect(
            cleanup
        )

        animation.start()

    def _toggle_building_elements_menu(
        self,
        checked: bool = False,
    ) -> None:

        self._set_building_elements_expanded(
            bool(checked),
            animate=True,
        )

    def _set_building_elements_expanded(
        self,
        expanded: bool,
        animate: bool = True,
    ) -> None:

        group = getattr(
            self,
            "_building_elements_group",
            None,
        )

        toggle = getattr(
            self,
            "_building_elements_toggle",
            None,
        )

        clip = getattr(
            self,
            "_building_elements_clip",
            None,
        )

        animation_group = getattr(
            self,
            "_building_elements_animation_group",
            None,
        )

        min_animation = getattr(
            self,
            "_building_elements_min_animation",
            None,
        )

        max_animation = getattr(
            self,
            "_building_elements_max_animation",
            None,
        )

        if (
            group is None
            or toggle is None
            or clip is None
        ):
            return

        toggle.blockSignals(True)
        toggle.setChecked(bool(expanded))
        toggle.blockSignals(False)

        # Sadece duz metin.
        toggle.setText("Yapı Elemanları")

        target = (
            int(
                getattr(
                    self,
                    "_building_elements_clip_height",
                    127,
                )
            )
            if expanded
            else 0
        )

        current = int(clip.height())

        if (
            not animate
            or animation_group is None
            or min_animation is None
            or max_animation is None
        ):
            clip.setMinimumHeight(target)
            clip.setMaximumHeight(target)

        else:
            animation_group.stop()

            # Animasyon baslangicinda her iki constraint
            # ayni gercek yukseklige getirilir.
            clip.setMinimumHeight(current)
            clip.setMaximumHeight(current)

            min_animation.setStartValue(current)
            min_animation.setEndValue(target)

            max_animation.setStartValue(current)
            max_animation.setEndValue(target)

            animation_group.start()

        clip.updateGeometry()
        group.updateGeometry()

        parent = group.parentWidget()

        if (
            parent is not None
            and parent.layout() is not None
        ):
            parent.layout().invalidate()
            parent.layout().activate()

    def _set_plan_tool_buttons_visible(
        self,
        visible: bool,
    ) -> None:

        group = getattr(
            self,
            "_building_elements_group",
            None,
        )

        if group is None:
            return

        if not visible:
            self._set_building_elements_expanded(
                False,
                animate=False,
            )

        group.setVisible(bool(visible))

    def _set_cad_menu_mode(
        self,
        plan_selected: bool,
    ) -> None:
        button = getattr(
            self,
            "_cad_menu_button",
            None,
        )

        if button is None:
            return

        button.setText(
            "Ana Menü"
            if plan_selected
            else "Mimari CAD Ekle"
        )

        create_3d_button = getattr(
            self,
            "_create_3d_button",
            None,
        )

        if create_3d_button is not None:
            create_3d_button.setVisible(
                bool(plan_selected)
            )


    def _handle_cad_menu_button(self) -> None:
        button = getattr(
            self,
            "_cad_menu_button",
            None,
        )

        if (
            button is not None
            and button.text().strip() == "Ana Menü"
        ):
            self._return_to_loaded_cad_menu()
            return

        self.open_cad()


    def _return_to_loaded_cad_menu(self) -> None:
        """
        Secilmis plan gorunumunden, CAD'in ilk yuklenen
        tam proje gorunumune geri doner.
        """

        document = getattr(
            self,
            "_full_document",
            None,
        )

        if document is None:
            return

        # Ana plan secim durumuna don.
        self._selected_document = None

        if hasattr(self, "_active_floor_document"):
            self._active_floor_document = None

        if hasattr(self, "_active_floor_bounds"):
            self._active_floor_bounds = None

        if hasattr(self, "_floor_selection_mode"):
            self._floor_selection_mode = False

        # Secim overlay durumlarini sifirla.
        if hasattr(self, "_selected_door_candidates"):
            self._selected_door_candidates = ()

        if hasattr(self, "_selected_window_candidates"):
            self._selected_window_candidates = ()

        if hasattr(self, "_selected_wall_candidates"):
            self._selected_wall_candidates = ()

        if hasattr(self, "_door_overlay_visible"):
            self._door_overlay_visible = False

        if hasattr(self, "_window_overlay_visible"):
            self._window_overlay_visible = False

        if hasattr(self, "_wall_overlay_visible"):
            self._wall_overlay_visible = False

        # Kat ayarlari aciksa kapat.
        floor_panel = getattr(
            self,
            "floor_panel",
            None,
        )

        if floor_panel is not None:
            floor_panel.setVisible(False)
            floor_panel.setEnabled(False)

        # Yapı Elemanları ana menude gorunmez.
        if hasattr(
            self,
            "_set_plan_tool_buttons_visible",
        ):
            self._set_plan_tool_buttons_visible(False)

        # Ilk CAD gorunumu.
        self.view.set_plan_cleanup_active(False)
        self.view.set_document(document)

        # Yeni ana plan secilebilir.
        if hasattr(self, "plan_btn"):
            self.plan_btn.setEnabled(True)

        self._set_cad_menu_mode(False)
        self._set_clear_cad_button_visible(True)

        self.statusBar().showMessage(
            "Ana menü — yüklenen CAD projesi gösteriliyor"
        )


    def _apply_main_menu_disabled_text_style(self) -> None:
        """
        Ana ekrandaki pasif butonlarin sadece yazi rengini
        soluk gosterir. Enabled durumdaki gorunum degismez.
        """
        from PySide6.QtWidgets import QPushButton

        target_names = {
            "Plan Seç",
            "Görünüme Sığdır",
            "CAD'i Temizle",
        }

        for button in self.findChildren(QPushButton):
            if button.text().strip() not in target_names:
                continue

            current_style = button.styleSheet() or ""

            rule = """
QPushButton:disabled {
    color: rgba(220, 220, 220, 75);
}
"""

            if rule.strip() not in current_style:
                button.setStyleSheet(
                    current_style + "\n" + rule
                )

    def _set_main_cad_action_buttons_enabled(
        self,
        enabled: bool,
    ) -> None:
        """
        Mimari CAD Ekle HARIC:
        - Plan Seç
        - Görünüme Sığdır
        - CAD'i Temizle

        bu uc buton ayni enabled/disabled durumunu kullanir.
        """

        from PySide6.QtWidgets import QPushButton

        target_names = {
            "Plan Seç",
            "Görünüme Sığdır",
            "CAD'i Temizle",
        }

        disabled_style = """
QPushButton:disabled {
    color: rgba(220, 220, 220, 75);
}
"""

        for button in self.findChildren(QPushButton):
            if button.text().strip() not in target_names:
                continue

            button.setEnabled(bool(enabled))

            current_style = button.styleSheet() or ""

            if disabled_style.strip() not in current_style:
                button.setStyleSheet(
                    current_style
                    + "\n"
                    + disabled_style
                )


    def _set_clear_cad_button_visible(
        self,
        visible: bool,
    ) -> None:
        from PySide6.QtWidgets import QPushButton

        button = getattr(
            self,
            "_clear_cad_button",
            None,
        )

        if button is None:
            for candidate in self.findChildren(QPushButton):
                if candidate.text().strip() == "CAD'i Temizle":
                    button = candidate
                    self._clear_cad_button = candidate
                    break

        if button is not None:
            button.setVisible(bool(visible))


    def _begin_plan_selection(self) -> None:
        """
        Iki kesin mod:

        1. _selected_document YOK:
           Ana CAD alanini crop etmek icin secim.

        2. _selected_document VAR:
           Mevcut view korunarak yalnizca kat plani kimligi secimi.
        """

        if self._full_document is None:
            return

        # ----------------------------------------------------
        # KAT ATAMA SECIMI
        # Ana calisma alani daha once secildiyse bundan sonraki
        # Plan Sec islemleri ASLA ana crop moduna donmez.
        # ----------------------------------------------------
        if self._selected_document is not None:
            self._floor_selection_mode = True

            self.floor_panel.setVisible(False)
            self.floor_panel.setEnabled(False)

            # View degistirilmez.
            # set_document / fit / crop YOK.
            self.view.begin_plan_selection()

            self.statusBar().showMessage(
                "Bilgilerini girmek istediğiniz kat planını seçin."
            )
            return

        # ----------------------------------------------------
        # ILK ANA PLAN SECIMI
        # ----------------------------------------------------
        self._floor_selection_mode = False

        self.floor_panel.setVisible(False)
        self.floor_panel.setEnabled(False)

        self.window_btn.setEnabled(False)

        self.view.set_plan_cleanup_active(False)
        self.view.set_document(self._full_document)
        self.view.begin_plan_selection()

        self.statusBar().showMessage(
            "Plan alanını seçin."
        )

    def _apply_plan_selection(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
    ) -> None:
        """
        Iki farkli secim modu vardir.

        1. Ana plan secimi:
           Secilen alan crop edilerek ana calisma view'i olusturulur.

        2. Kat kimligi secimi:
           View ASLA crop edilmez.
           Sadece mevcut view icinde hangi kat planinin secildigi
           kaydedilir ve Kat Ayarlari paneli acilir.
        """

        # ====================================================
        # SECOND STAGE - FLOOR IDENTITY
        # ====================================================

        if getattr(self, "_floor_selection_mode", False):

            if self._selected_document is None:
                self._floor_selection_mode = False
                return

            floor_document = crop_document(
                self._selected_document,
                xmin,
                ymin,
                xmax,
                ymax,
            )

            if (
                not floor_document.primitives
                and not floor_document.texts
            ):
                self.statusBar().showMessage(
                    "Seçilen alanda kat planı bulunamadı."
                )
                return

            self._floor_selection_mode = False

            # KRITIK:
            # Ana view degistirilmez.
            # Sadece secilen kat geometrisi ayri kaydedilir.
            self._active_floor_document = floor_document
            self._active_floor_bounds = (
                float(xmin),
                float(ymin),
                float(xmax),
                float(ymax),
            )

            self.floor_panel.setVisible(True)
            self.floor_panel.setEnabled(True)

            if hasattr(
                self,
                "_refresh_floor_name_choices",
            ):
                self._refresh_floor_name_choices()

            self.statusBar().showMessage(
                "Kat planı seçildi — kat bilgilerini girin."
            )

            return

        # ====================================================
        # FIRST STAGE - MAIN PLAN AREA
        # ====================================================

        if self._full_document is None:
            return

        selected = crop_document(
            self._full_document,
            xmin,
            ymin,
            xmax,
            ymax,
        )

        if not selected.primitives and not selected.texts:
            self._selected_document = None
            self.window_btn.setEnabled(False)
            self.view.set_plan_cleanup_active(False)
            self.view.set_document(
                self._full_document
            )
            self.statusBar().showMessage(
                "Seçilen alanda CAD verisi bulunamadı"
            )
            return

        self._selected_document = selected
        self._set_cad_menu_mode(True)
        self._set_clear_cad_button_visible(False)

        # Ana plan secildi: analiz araclarini alt menu olarak ac.
        self._set_plan_tool_buttons_visible(True)
        self._active_floor_document = None

        self._plan_view_active = True
        self.plan_btn.setEnabled(True)

        self.floor_panel.setVisible(False)
        self.floor_panel.setEnabled(False)

        # Ana secimden sonra bu view korunur.
        self.view.set_plan_cleanup_active(True)
        self.view.set_document(selected)

        self._prepare_plan_objects()

        self.window_btn.setEnabled(True)

        self.statusBar().showMessage(
            "Plan alanı seçildi — kat seçimi için tekrar Plan Seç'e basın."
        )

    def _prepare_plan_objects(self) -> None:
        document = self._selected_document

        if document is None:
            self._selected_door_candidates = ()
            self._selected_window_candidates = ()
            self._selected_wall_candidates = ()
            self._door_overlay_visible = False
            self._window_overlay_visible = False
            self._wall_overlay_visible = False
            return

        # 1. Once kapilar secilir.
        door_candidates = tuple(detect_interior_doors(document))

        # 2. Sonra pencereler secilir.
        window_result = detect_window_family(document, door_candidates)
        window_candidates = tuple(getattr(window_result, "windows", ()) or ())

        # 3. Sonra duvarlar secilir.
        wall_candidates = tuple(
            detect_walls(
                document,
                door_candidates,
                window_candidates,
            )
        )


        self._selected_door_candidates = door_candidates
        self._selected_window_candidates = window_candidates
        self._selected_wall_candidates = wall_candidates
        self.generate_3d_btn.setEnabled(bool(wall_candidates))

        self._door_overlay_visible = False
        self._window_overlay_visible = False
        self._wall_overlay_visible = False

    def _detect_interior_doors(self) -> None:
        document = self._selected_document

        if document is None:
            return

        candidates = tuple(getattr(self, "_selected_door_candidates", ()) or ())

        if getattr(self, "_door_overlay_visible", False):
            self.view.show_interior_door_primitives(document, ())
            self._door_overlay_visible = False
            return

        primitive_indices = []

        for candidate in candidates:
            primitive_indices.extend(getattr(candidate, "display_primitive_indices", ()) or ())

        self.view.show_interior_door_primitives(
            document,
            tuple(dict.fromkeys(primitive_indices)),
        )
        self._door_overlay_visible = True

    def _detect_walls(self) -> None:
        document = self._selected_document

        if document is None:
            return

        candidates = tuple(getattr(self, "_selected_wall_candidates", ()) or ())

        if getattr(self, "_wall_overlay_visible", False):
            self.view.show_wall_primitives(document, ())
            self._wall_overlay_visible = False
            return

        primitive_indices = []

        for candidate in candidates:
            primitive_index = getattr(candidate, "primitive_index", None)
            if primitive_index is not None:
                primitive_indices.append(primitive_index)

        self.view.show_wall_primitives(
            document,
            tuple(dict.fromkeys(primitive_indices)),
        )
        self._wall_overlay_visible = True

    def _detect_window_family(self) -> None:
        if self._selected_document is None:
            return

        candidates = tuple(getattr(self, "_selected_window_candidates", ()) or ())

        if getattr(self, "_window_overlay_visible", False):
            self.view.show_window_rectangles(())
            self._window_overlay_visible = False
            return

        self.view.show_window_rectangles(candidates)
        self._window_overlay_visible = True

    def open_cad(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Mimari CAD Dosyası Seç",
            str(self._current_path.parent if self._current_path else Path.home()),
            "CAD Dosyaları (*.dwg *.dxf);;DWG Dosyaları (*.dwg);;DXF Dosyaları (*.dxf)",
        )

        if not filename:
            return

        path = Path(filename)
        self.statusBar().showMessage(f"Yükleniyor: {path.name}")

        try:
            document = self._loader.load(path)
        except CadLoadError as exc:
            self.statusBar().showMessage("CAD yüklenemedi")
            QMessageBox.critical(self, "CAD Yükleme Hatası", str(exc))
            return
        except Exception as exc:
            self.statusBar().showMessage("Beklenmeyen bir hata oluştu")
            QMessageBox.critical(self, "Beklenmeyen Hata", str(exc))
            return

        self._current_path = path
        self._full_document = document
        self._set_main_cad_action_buttons_enabled(True)
        self._set_cad_menu_mode(False)
        self._selected_document = None
        self._confirmed_floors = []

        self.view.set_plan_cleanup_active(False)
        self.view.set_document(document)

        self.plan_btn.setEnabled(True)
        self.window_btn.setEnabled(False)



        for name, count in document.entity_counts.items():
            skipped = document.skipped_counts.get(name, 0)
            text = f"{name}: {count}"

            if skipped:
                text += f"   (atlanmış: {skipped})"


        self.statusBar().showMessage(
            "CAD yüklendi — önce Plan Seç ile çalışma alanını seçin"
        )

    def _create_3d(self) -> None:
        confirmed = [
            row
            for row in (
                getattr(
                    self,
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

        # Onaylanmis katlar varsa CAD_to_3D_Max
        # multi-floor transfer menu kullanilir.
        if confirmed:
            from PySide6.QtWidgets import (
                QMenu,
            )

            from export.multi_floor_max_send import (
                ordered_confirmed_floors,
                start_floor_send,
            )

            try:
                ordered = (
                    ordered_confirmed_floors(
                        confirmed
                    )
                )
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Kat Aktarım Hatası",
                    str(exc),
                )
                return

            menu = QMenu(self)

            menu.setStyleSheet(
                """
                QMenu {
                    background-color: #1d1f20;
                    color: #e6e6e6;
                    border: 1px solid #343434;
                    padding: 4px;
                }

                QMenu::item {
                    padding: 6px 24px 6px 10px;
                }

                QMenu::item:selected {
                    background-color: #2a2c2d;
                }

                QMenu::separator {
                    height: 1px;
                    background: #343434;
                    margin: 4px 6px;
                }
                """
            )

            def launch(
                names,
            ):
                try:
                    start_floor_send(
                        self,
                        names,
                    )
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "3D Oluştur Hatası",
                        str(exc),
                    )

            for floor in ordered:
                floor_name = str(
                    floor[
                        "name"
                    ]
                )

                action = menu.addAction(
                    floor_name
                )

                action.triggered.connect(
                    lambda checked=False,
                    name=floor_name:
                        launch(
                            (name,)
                        )
                )

            if len(ordered) > 0:
                menu.addSeparator()

            all_action = menu.addAction(
                "Tüm Katları Gönder"
            )

            all_action.triggered.connect(
                lambda checked=False:
                    launch(None)
            )

            button = self.generate_3d_btn

            menu.exec(
                button.mapToGlobal(
                    button.rect().bottomLeft()
                )
            )

            return

        # Hic kat onaylanmadiysa mevcut tek-plan
        # transfer davranisi aynen korunur.
        document = self._selected_document

        if document is None:
            QMessageBox.warning(
                self,
                "3D Oluştur",
                "Önce Plan Seç ile çalışma alanını seçin.",
            )
            return

        walls = tuple(
            getattr(
                self,
                "_selected_wall_candidates",
                (),
            )
            or ()
        )

        if not walls:
            QMessageBox.warning(
                self,
                "3D Oluştur",
                "Gönderilecek seçilmiş duvar bulunamadı.",
            )
            return

        try:
            result = send_wall_lines_to_max(
                document,
                walls,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "3D Oluştur Hatası",
                str(exc),
            )
            return

        self.statusBar().showMessage(
            "3D Oluştur - "
            f"{result['wall_count']} duvar çizgisi Max'e gönderildi | "
            f"Pivot X={result['pivot_x_mm']:.3f} mm "
            f"Y={result['pivot_y_mm']:.3f} mm"
        )

    def clear_cad(self) -> None:
        self._set_main_cad_action_buttons_enabled(False)
        self._set_cad_menu_mode(False)
        self._set_plan_tool_buttons_visible(False)
        self._confirmed_floors = []
        self._active_floor_document = None
        self._floor_selection_mode = False
        self._plan_view_active = False
        self.floor_panel.setEnabled(False)
        self.floor_panel.setVisible(False)
        self.floor_name_combo.clear()
        self.floor_name_combo.setEnabled(False)
        self.interfloor_spin.setValue(0.0)
        self.wall_height_spin.setValue(280.0)

        self._current_path = None
        self._full_document = None
        self._selected_document = None

        self.view.clear_document()

        self.plan_btn.setEnabled(False)
        self.window_btn.setEnabled(False)


        self.statusBar().showMessage("CAD temizlendi")
