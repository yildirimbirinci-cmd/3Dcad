from __future__ import annotations

import hashlib
from pathlib import Path

from core.paths import project_root


class DwgConversionError(RuntimeError):
    pass


def _stable_output_path(dwg_path: Path) -> Path:
    stat = dwg_path.stat()
    signature = f"{dwg_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", "ignore")
    digest = hashlib.sha1(signature).hexdigest()[:12]
    return project_root() / "data" / "temp" / f"{dwg_path.stem}_{digest}.dxf"


def convert_dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert DWG to a temporary AutoCAD 2018 DXF using AutoCAD ActiveX.

    The user's source DWG is never modified. AutoCAD is opened invisibly when
    possible and the temporary copy is closed without saving back to the DWG.
    """
    dwg_path = Path(dwg_path).expanduser().resolve()
    if not dwg_path.exists():
        raise DwgConversionError(f"DWG bulunamadı: {dwg_path}")

    output = _stable_output_path(dwg_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.stat().st_size > 0:
        return output

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
            app = win32com.client.DispatchEx("AutoCAD.Application")
        except Exception:
            app = win32com.client.Dispatch("AutoCAD.Application")
        try:
            app.Visible = False
        except Exception:
            pass

        doc = app.Documents.Open(str(dwg_path), True)
        # Autodesk AcSaveAsType: ac2018_dxf = 65.
        doc.SaveAs(str(output), 65)
        doc.Close(False)
        doc = None

        if not output.exists() or output.stat().st_size == 0:
            raise DwgConversionError("AutoCAD DXF dosyasını oluşturamadı.")
        return output
    except Exception as exc:
        if isinstance(exc, DwgConversionError):
            raise
        raise DwgConversionError(f"DWG -> DXF dönüşümü başarısız: {exc}") from exc
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
