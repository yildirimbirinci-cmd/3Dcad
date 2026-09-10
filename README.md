# 3Dcad

Clean-start architecture for architectural CAD -> 3D development.

## Current milestone
- Dark PySide6 desktop UI
- DWG and DXF file picker
- DWG -> temporary AutoCAD 2018 DXF conversion (source DWG is untouched)
- DXF read with ezdxf
- Vector CAD rendering in a pan/zoom/fit View
- CAD model is independent from the View layer
- Blocks/DIMENSION/MLEADER/MLINE are recursively decomposed where ezdxf supports it
- No hard-coded project path

## Windows install
```powershell
cd "C:\Users\yildi\Desktop\3Dcad"
.\install.ps1
```

## Run
```powershell
cd "C:\Users\yildi\Desktop\3Dcad"
.\run.ps1
```

## Architecture rule
The graphics view is presentation only. Future wall/door/window/floor analysis must consume the parsed CAD model, never viewport pixels or visible Qt items.
