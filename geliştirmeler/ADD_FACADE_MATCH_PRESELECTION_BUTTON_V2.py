from __future__ import annotations

from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys


ROOT = Path.cwd()

MAIN = ROOT / "src" / "ui" / "main_window.py"
VIEW = ROOT / "src" / "ui" / "cad_view.py"
RUNTIME = ROOT / "src" / "cad" / "facade_runtime.py"

OLD_CAD = (
    Path(r"C:\Users\yildi\Desktop\CAD_to_3D_Max")
    / "src"
    / "cad"
)

VENDOR = (
    ROOT
    / "src"
    / "cad"
    / "_cad_to_3d_max_facade"
)

MARKER = (
    "CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2"
)


# ============================================================
# PRECHECK
# ============================================================

for path in (
    MAIN,
    VIEW,
    RUNTIME,
):
    if not path.exists():
        raise RuntimeError(
            "Eksik dosya: "
            + str(path)
            + " | DOSYALARA DOKUNULMADI."
        )


if not OLD_CAD.exists():
    raise RuntimeError(
        "Eski CAD_to_3D_Max cad klasoru bulunamadi. "
        "DOSYALARA DOKUNULMADI."
    )


main = MAIN.read_text(
    encoding="utf-8-sig"
)

view = VIEW.read_text(
    encoding="utf-8-sig"
)

runtime = RUNTIME.read_text(
    encoding="utf-8-sig"
)


if MARKER in main:
    print(
        MARKER
        + " zaten kurulu. Yeniden uygulanmadi."
    )
    raise SystemExit(0)


# ============================================================
# GENERIC AST FUNCTION REPLACE
# ============================================================

def replace_function(
    text,
    function_name,
    replacement,
):
    tree = ast.parse(text)

    matches = [
        node
        for node in tree.body
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name == function_name
    ]

    if len(matches) != 1:
        raise RuntimeError(
            function_name
            + ": beklenen 1 fonksiyon, bulunan "
            + str(len(matches))
        )

    node = matches[0]

    lines = text.splitlines(
        keepends=True
    )

    lines[
        node.lineno - 1:
        node.end_lineno
    ] = [
        replacement.rstrip()
        + "\n"
    ]

    result = "".join(lines)

    ast.parse(result)

    return result


def replace_once(
    text,
    old,
    new,
    label,
):
    count = text.count(old)

    if count != 1:
        raise RuntimeError(
            label
            + ": beklenen 1 anchor, bulunan "
            + str(count)
            + " | DOSYALARA DOKUNULMADI."
        )

    return text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 1. VENDOR OLD FACADE DEPENDENCIES
#
# facade_matcher'in kullandigi eski src.cad.* modullerini
# recursive olarak kendi izole compatibility klasorumuze al.
#
# CURRENT detector dosyalari DEGISTIRILMEZ.
# ============================================================

seed_modules = {
    "facade_matcher",
    "cad_intelligence",
    "elevation_opening_detector",
    "plan_guided_facade_windows",
}

queue = list(seed_modules)
seen = set()
vendor_sources = {}


while queue:
    module_name = queue.pop(0)

    if module_name in seen:
        continue

    seen.add(module_name)

    source = (
        OLD_CAD
        / (
            module_name.replace(
                ".",
                "/",
            )
            + ".py"
        )
    )

    if not source.exists():
        continue

    text = source.read_text(
        encoding="utf-8-sig"
    )

    try:
        tree = ast.parse(
            text,
            filename=str(source),
        )
    except Exception as exc:
        raise RuntimeError(
            "Eski facade dependency parse edilemedi: "
            + str(source)
        ) from exc

    for node in ast.walk(tree):

        if isinstance(
            node,
            ast.ImportFrom,
        ):
            imported = str(
                node.module
                or ""
            )

            if imported.startswith(
                "src.cad."
            ):
                dependency = imported[
                    len("src.cad.") :
                ]

                dependency_path = (
                    OLD_CAD
                    / (
                        dependency.replace(
                            ".",
                            "/",
                        )
                        + ".py"
                    )
                )

                if dependency_path.exists():
                    queue.append(
                        dependency
                    )

        elif isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                imported = str(
                    alias.name
                    or ""
                )

                if imported.startswith(
                    "src.cad."
                ):
                    dependency = imported[
                        len("src.cad.") :
                    ]

                    dependency_path = (
                        OLD_CAD
                        / (
                            dependency.replace(
                                ".",
                                "/",
                            )
                            + ".py"
                        )
                    )

                    if dependency_path.exists():
                        queue.append(
                            dependency
                        )

    # Eski proje namespace -> izole yeni namespace.
    text = text.replace(
        "src.cad.",
        "cad._cad_to_3d_max_facade.",
    )

    compile(
        text,
        str(source),
        "exec",
    )

    vendor_sources[
        module_name
    ] = text


if "facade_matcher" not in vendor_sources:
    raise RuntimeError(
        "Eski facade_matcher yuklenemedi."
    )


# ============================================================
# 2. PRESELECTION RUNTIME
#
# BUTTON PRESS:
# FULL CAD
# -> old region detector
# -> old main-plan detector
# -> old elevation detector/matcher
# -> physical elevation opening refinement
# -> STORE RESULT
# ============================================================

new_preanalyse = r'''
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
'''


runtime_new = replace_function(
    runtime,
    "preanalyse_facades",
    new_preanalyse,
)


# ============================================================
# 3. VIEWPORT NUMBER LABELS
#
# Same old rule:
# facade anchor gets facade_number
# matching plan_anchor gets SAME facade_number
# ============================================================

view_methods = r'''
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


    def show_facade_match_preview(
        self,
        result,
    ) -> int:
        """
        Same visual numbering concept as CAD_to_3D_Max:

            elevation facade anchor -> N
            matching plan anchor    -> N

        Labels are visual only.
        They never enter CAD geometry or export.
        """

        self.clear_facade_match_preview()

        if not isinstance(
            result,
            dict,
        ):
            return 0

        labels = []

        # ----------------------------------------------------
        # ELEVATION LABELS
        # ----------------------------------------------------

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
                    facade[
                        "facade_number"
                    ]
                )

                anchor = facade[
                    "anchor"
                ]

                point = (
                    float(anchor[0]),
                    float(anchor[1]),
                )

            except Exception:
                continue

            labels.append(
                (
                    number,
                    point,
                )
            )

        # ----------------------------------------------------
        # SAME NUMBER ON MATCHING PLAN SIDE
        # ----------------------------------------------------

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
                    match[
                        "facade_number"
                    ]
                )

                anchor = match[
                    "plan_anchor"
                ]

                point = (
                    float(anchor[0]),
                    float(anchor[1]),
                )

            except Exception:
                continue

            labels.append(
                (
                    number,
                    point,
                )
            )

        created = []

        for number, point in labels:

            item = QGraphicsSimpleTextItem(
                str(number)
            )

            font = QFont()
            font.setPointSize(13)
            font.setBold(True)

            item.setFont(
                font
            )

            # Existing UI language:
            # neutral light gray only.
            item.setBrush(
                QColor(
                    230,
                    230,
                    230,
                )
            )

            item.setPos(
                float(point[0]),
                -float(point[1]),
            )

            item.setZValue(
                3000000
            )

            item.setFlag(
                QGraphicsItem.ItemIgnoresTransformations,
                True,
            )

            item.setAcceptedMouseButtons(
                Qt.NoButton
            )

            self.scene().addItem(
                item
            )

            created.append(
                item
            )

        self._facade_match_preview_items = (
            created
        )

        self.viewport().update()

        return len(created)
'''


view_anchor = (
    "    def begin_plan_selection(self) -> None:\n"
)

if view_anchor not in view:
    raise RuntimeError(
        "cad_view begin_plan_selection anchor bulunamadi."
    )

view_new = view.replace(
    view_anchor,
    view_methods.rstrip()
    + "\n\n\n"
    + view_anchor,
    1,
)


# ============================================================
# 4. MAIN WINDOW BUTTON
# ============================================================

# Button definition.
main_new = replace_once(
    main,
    '''        self.plan_btn = QPushButton("Plan Seç")
        self.plan_btn.setEnabled(False)
        self.plan_btn.clicked.connect(self._begin_plan_selection)
''',
    '''        self.plan_btn = QPushButton("Plan Seç")
        self.plan_btn.setEnabled(False)
        self.plan_btn.clicked.connect(self._begin_plan_selection)

        # CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2
        self.facade_match_btn = QPushButton(
            "Cephe Eşleştirme"
        )

        self.facade_match_btn.setEnabled(
            False
        )

        self.facade_match_btn.clicked.connect(
            self._run_facade_match_preselection
        )
''',
    "FACADE BUTTON DEFINITION",
)


# Button order:
# CAD -> Facade Match -> Plan Select.
main_new = replace_once(
    main_new,
    '''        side.addWidget(load_btn)
        side.addWidget(self.plan_btn)
''',
    '''        side.addWidget(load_btn)
        side.addWidget(self.facade_match_btn)
        side.addWidget(self.plan_btn)
''',
    "FACADE BUTTON SIDEBAR",
)


# ============================================================
# MAIN HANDLER
# ============================================================

handler = r'''
    # CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2
    def _run_facade_match_preselection(
        self,
    ) -> None:
        if self._full_document is None:
            QMessageBox.warning(
                self,
                "Cephe Eşleştirme",
                "Önce Mimari CAD Ekleyin.",
            )
            return

        # This button belongs ONLY to the full-CAD screen.
        if self._selected_document is not None:
            return

        self.statusBar().showMessage(
            "Cepheler ve plan yönleri eşleştiriliyor..."
        )

        try:
            from cad.facade_runtime import (
                preanalyse_facades,
            )

            result = (
                preanalyse_facades(
                    self
                )
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Cephe Eşleştirme",
                str(exc),
            )

            self.statusBar().showMessage(
                "Cephe eşleştirme başarısız."
            )

            return

        main_plan = result.get(
            "main_plan"
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

        if not main_plan:
            QMessageBox.warning(
                self,
                "Cephe Eşleştirme",
                "Ana plan otomatik bulunamadı.",
            )
            return

        if not facades:
            QMessageBox.warning(
                self,
                "Cephe Eşleştirme",
                "Cephe çizimi otomatik bulunamadı.",
            )
            return

        # Visual numbering exists ONLY on full CAD screen.
        label_count = (
            self.view
            .show_facade_match_preview(
                result
            )
        )

        self.statusBar().showMessage(
            "Cephe Eşleştirme | "
            f"{len(facades)} cephe | "
            f"{len(matches)} plan yönü eşleşti | "
            f"{label_count} numara gösteriliyor | "
            "veri kaydedildi"
        )
'''


main_anchor = (
    "    def _begin_plan_selection(self) -> None:\n"
)

if main_anchor not in main_new:
    raise RuntimeError(
        "_begin_plan_selection anchor bulunamadi."
    )

main_new = main_new.replace(
    main_anchor,
    handler.rstrip()
    + "\n\n\n"
    + main_anchor,
    1,
)


# ============================================================
# 5. MAIN/PLAN SCREEN VISIBILITY
# ============================================================

visibility_anchor = '''        if create_3d_button is not None:
            create_3d_button.setVisible(
                bool(plan_selected)
            )
'''

visibility_replacement = '''        if create_3d_button is not None:
            create_3d_button.setVisible(
                bool(plan_selected)
            )

        facade_button = getattr(
            self,
            "facade_match_btn",
            None,
        )

        if facade_button is not None:
            # Main CAD screen only.
            # Never visible inside selected-plan workflow.
            facade_button.setVisible(
                not bool(plan_selected)
            )
'''

main_new = replace_once(
    main_new,
    visibility_anchor,
    visibility_replacement,
    "FACADE BUTTON VISIBILITY",
)


# ============================================================
# 6. ENABLE AFTER CAD LOAD
# ============================================================

main_new = replace_once(
    main_new,
    '''        self.plan_btn.setEnabled(True)
        self.window_btn.setEnabled(False)
''',
    '''        self.plan_btn.setEnabled(True)

        self.facade_match_btn.setEnabled(
            True
        )

        self.facade_match_btn.setVisible(
            True
        )

        self.window_btn.setEnabled(False)
''',
    "OPEN CAD FACADE ENABLE",
)


# ============================================================
# 7. RESTORE PREVIEW WHEN RETURNING TO MAIN MENU
# ============================================================

return_anchor = '''        self.view.set_plan_cleanup_active(False)
        self.view.set_document(document)

        # Yeni ana plan secilebilir.
'''

return_replacement = '''        self.view.set_plan_cleanup_active(False)
        self.view.set_document(document)

        # Stored facade registration survives Plan Sec.
        facade_result = getattr(
            self,
            "_cad3d_facade_preanalysis",
            None,
        )

        if isinstance(
            facade_result,
            dict,
        ):
            self.view.show_facade_match_preview(
                facade_result
            )

        if hasattr(
            self,
            "facade_match_btn",
        ):
            self.facade_match_btn.setVisible(
                True
            )

            self.facade_match_btn.setEnabled(
                True
            )

        # Yeni ana plan secilebilir.
'''

main_new = replace_once(
    main_new,
    return_anchor,
    return_replacement,
    "RETURN MAIN FACADE PREVIEW",
)


# ============================================================
# 8. CLEAR CAD
# ============================================================

clear_anchor = '''        self.view.clear_document()

        self.plan_btn.setEnabled(False)
        self.window_btn.setEnabled(False)
'''

clear_replacement = '''        self.view.clear_facade_match_preview()
        self.view.clear_document()

        self.plan_btn.setEnabled(False)

        if hasattr(
            self,
            "facade_match_btn",
        ):
            self.facade_match_btn.setEnabled(
                False
            )

            self.facade_match_btn.setVisible(
                True
            )

        self.window_btn.setEnabled(False)
'''

main_new = replace_once(
    main_new,
    clear_anchor,
    clear_replacement,
    "CLEAR FACADE BUTTON",
)


# ============================================================
# 9. REMOVE OLD SILENT RUN AFTER PLAN SELECT
#
# New contract:
# user explicitly presses Cephe Eşleştirme BEFORE Plan Sec.
# Plan selection preserves the saved result.
# ============================================================

old_auto_block = '''        # CAD3D_AUTO_FACADE_PORT_V1
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

'''

if old_auto_block in main_new:
    main_new = main_new.replace(
        old_auto_block,
        '''        # CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2
        # Cephe eslestirme verisi Plan Sec oncesinde uretilir.
        # Burada yeniden analiz edilmez ve mevcut veri korunur.

''',
        1,
    )


# ============================================================
# VALIDATE BEFORE WRITE
# ============================================================

compile(
    main_new,
    str(MAIN),
    "exec",
)

compile(
    view_new,
    str(VIEW),
    "exec",
)

compile(
    runtime_new,
    str(RUNTIME),
    "exec",
)

for module_name, text in vendor_sources.items():
    target = (
        VENDOR
        / (
            module_name.replace(
                ".",
                "/",
            )
            + ".py"
        )
    )

    compile(
        text,
        str(target),
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
        "BEFORE_FACADE_MATCH_BUTTON_"
        + stamp
    )
)

backup.mkdir(
    parents=True,
    exist_ok=False,
)

shutil.copy2(
    MAIN,
    backup / "main_window.py",
)

shutil.copy2(
    VIEW,
    backup / "cad_view.py",
)

shutil.copy2(
    RUNTIME,
    backup / "facade_runtime.py",
)

if VENDOR.exists():
    shutil.copytree(
        VENDOR,
        backup
        / "_cad_to_3d_max_facade",
    )


# ============================================================
# WRITE VENDOR PACKAGE
# ============================================================

VENDOR.mkdir(
    parents=True,
    exist_ok=True,
)

(
    VENDOR
    / "__init__.py"
).write_text(
    "# CAD_to_3D_Max facade compatibility package.\n",
    encoding="utf-8",
)


for module_name, text in vendor_sources.items():

    target = (
        VENDOR
        / (
            module_name.replace(
                ".",
                "/",
            )
            + ".py"
        )
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    parent = target.parent

    while (
        parent != VENDOR
        and VENDOR in parent.parents
    ):
        init_file = (
            parent
            / "__init__.py"
        )

        if not init_file.exists():
            init_file.write_text(
                "",
                encoding="utf-8",
            )

        parent = parent.parent

    target.write_text(
        text,
        encoding="utf-8",
    )


# ============================================================
# WRITE ACTIVE FILES
# ============================================================

RUNTIME.write_text(
    runtime_new,
    encoding="utf-8",
)

VIEW.write_text(
    view_new,
    encoding="utf-8",
)

# Main LAST.
MAIN.write_text(
    main_new,
    encoding="utf-8",
)


print("")
print(
    "CAD3D_FACADE_MATCH_BUTTON_PRESELECTION_V2 INSTALLED"
)
print("")
print("FLOW:")
print("  Mimari CAD Ekle")
print("  -> Cephe Esleştirme")
print("  -> plan + cephe same-number preview")
print("  -> data stored")
print("  -> Plan Sec")
print("  -> facade button hidden")
print("  -> stored facade data preserved")
print("")
print("UNCHANGED:")
print("  current window_detector.py")
print("  current door_detector.py")
print("  wall_detector.py")
print("  pivot")
print("  max_bridge.py")
print("  multi_floor_max_send.py")
print("  3DCAD_BRIDGE.ms")
print("")
print("BACKUP:", backup)
print("")
