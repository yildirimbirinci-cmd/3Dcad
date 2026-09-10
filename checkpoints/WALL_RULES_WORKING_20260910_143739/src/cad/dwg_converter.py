from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from core.paths import project_root


class DwgConversionError(RuntimeError):
    pass


def _fresh_paths(dwg_path: Path) -> tuple[Path, Path]:
    """
    Every load operation gets completely new temporary paths.

    No previous DWG snapshot or DXF can ever be reused.
    """
    temp_dir = project_root() / "data" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    token = f"{time.time_ns()}_{uuid.uuid4().hex[:10]}"

    snapshot = temp_dir / f"{dwg_path.stem}_{token}_SOURCE.dwg"
    output = temp_dir / f"{dwg_path.stem}_{token}.dxf"

    return snapshot, output


def convert_dwg_to_dxf(dwg_path: Path) -> Path:
    """
    Convert the CURRENT ON-DISK DWG to a completely fresh DXF.

    Rules:
    - Never reuse an old DXF.
    - Never open a previously cached DWG.
    - Make a fresh byte-for-byte snapshot of the current source DWG.
    - Open that fresh snapshot in AutoCAD.
    - Export to a unique DXF path.
    - Never modify the source DWG.
    """

    dwg_path = Path(dwg_path).expanduser().resolve()

    if not dwg_path.exists():
        raise DwgConversionError(f"DWG bulunamadı: {dwg_path}")

    if dwg_path.stat().st_size <= 0:
        raise DwgConversionError(f"DWG boş: {dwg_path}")

    snapshot, output = _fresh_paths(dwg_path)

    try:
        # Read the source DWG from disk NOW.
        # This prevents an old temporary/cached DWG from being reused.
        shutil.copy2(dwg_path, snapshot)

        if not snapshot.exists() or snapshot.stat().st_size <= 0:
            raise DwgConversionError(
                "Güncel DWG snapshot oluşturulamadı."
            )

        try:
            import pythoncom
            import win32com.client
        except Exception as exc:
            raise DwgConversionError(
                "DWG okumak için Windows + AutoCAD + pywin32 gerekiyor. "
                "DXF dosyaları AutoCAD olmadan doğrudan açılabilir."
            ) from exc

        app = None
        doc = None

        pythoncom.CoInitialize()

        try:
            try:
                app = win32com.client.DispatchEx(
                    "AutoCAD.Application"
                )
            except Exception:
                app = win32com.client.Dispatch(
                    "AutoCAD.Application"
                )

            try:
                app.Visible = False
            except Exception:
                pass

            # Open the freshly copied DWG, never the old cached source.
            doc = app.Documents.Open(
                str(snapshot),
                True,
            )

            # Autodesk AcSaveAsType:
            # ac2018_dxf = 65
            doc.SaveAs(
                str(output),
                65,
            )

            doc.Close(False)
            doc = None

            if not output.exists():
                raise DwgConversionError(
                    "AutoCAD yeni DXF dosyasını oluşturamadı."
                )

            if output.stat().st_size <= 0:
                raise DwgConversionError(
                    "AutoCAD boş DXF dosyası oluşturdu."
                )

            return output

        except Exception as exc:
            if isinstance(exc, DwgConversionError):
                raise

            raise DwgConversionError(
                f"DWG -> DXF dönüşümü başarısız: {exc}"
            ) from exc

        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass

            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass

            pythoncom.CoUninitialize()

    finally:
        # Snapshot is needed only during conversion.
        # The fresh DXF is intentionally retained because CadDocument
        # stores parsed_path.
        try:
            if snapshot.exists():
                snapshot.unlink()
        except Exception:
            pass