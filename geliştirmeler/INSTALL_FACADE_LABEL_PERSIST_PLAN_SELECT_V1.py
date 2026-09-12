from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "src" / "ui" / "main_window.py"
MARKER = "CAD3D_FACADE_LABEL_PERSIST_PLAN_SELECT_V1"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadı: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

if MARKER in text:
    print("ALREADY INSTALLED:", MARKER)
    raise SystemExit(0)

old = '''        self.view.set_plan_cleanup_active(False)
        self.view.set_document(self._full_document)
        self.view.begin_plan_selection()

        self.statusBar().showMessage(
'''

new = '''        self.view.set_plan_cleanup_active(False)
        self.view.set_document(self._full_document)
        self.view.begin_plan_selection()

        # CAD3D_FACADE_LABEL_PERSIST_PLAN_SELECT_V1
        # set_document()/begin_plan_selection() rebuilds the scene.
        # Restore ONLY the existing visual labels; do not re-run
        # facade analysis or alter its result.
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

        self.statusBar().showMessage(
'''

count = text.count(old)
if count != 1:
    raise RuntimeError(
        f"Beklenen Plan Sec baglanti noktasi 1 kez bulunmaliydi; bulunan: {count}. Dosya degistirilmedi."
    )

patched = text.replace(old, new, 1)

ast.parse(patched)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"FACADE_LABEL_PERSIST_PLAN_SELECT_V1_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / "main_window.py"
shutil.copy2(TARGET, backup)

TARGET.write_text(patched, encoding="utf-8")
ast.parse(TARGET.read_text(encoding="utf-8-sig"))

print("")
print("FACADE_LABEL_PERSIST_PLAN_SELECT_V1 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("")
print("BEHAVIOR:")
print("  Plan Sec clicked")
print("  -> full CAD scene rebuilt")
print("  -> existing facade preanalysis labels restored")
print("  -> NO facade re-analysis")
print("  -> NO detector/export/Max change")
print("")
