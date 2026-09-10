$ErrorActionPreference = "Stop"

$root = "C:\Users\yildi\Desktop\3Dcad"
$backupRoot = Join-Path $root "backups"
$detector = Join-Path $root "src\cad\wall_detector.py"

$sourceBackup = Get-ChildItem -Path $backupRoot -Directory |
    Where-Object { $_.Name -like "wall_collinear_helper_parallel_overlap_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $sourceBackup) {
    throw "wall_collinear_helper_parallel_overlap backup not found."
}

$backupDetector = Join-Path $sourceBackup.FullName "wall_detector.py"

if (!(Test-Path $backupDetector)) {
    throw ("Backup wall_detector.py not found: " + $backupDetector)
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$safetyBackup = Join-Path $backupRoot ("before_rollback_collinear_helper_parallel_overlap_" + $stamp)
New-Item -ItemType Directory -Force -Path $safetyBackup | Out-Null

Copy-Item $detector (Join-Path $safetyBackup "wall_detector.py") -Force
Copy-Item $backupDetector $detector -Force

$env:PYTHONPATH = Join-Path $root "src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

& py -3.12 -m py_compile $detector

if ($LASTEXITCODE -ne 0) {
    Copy-Item (Join-Path $safetyBackup "wall_detector.py") $detector -Force
    throw "Rollback compile failed. Current wall_detector.py restored."
}

& py -3.12 -c "from cad.wall_detector import detect_walls, WallCandidate; print('ROLLBACK COLLINEAR HELPER/PARALLEL OVERLAP PASS')"

if ($LASTEXITCODE -ne 0) {
    Copy-Item (Join-Path $safetyBackup "wall_detector.py") $detector -Force
    throw "Rollback import failed. Current wall_detector.py restored."
}

Write-Host ""
Write-Host "COLLINEAR HELPER / PARALLEL OVERLAP PATCH ROLLED BACK" -ForegroundColor Green
Write-Host "Only wall_detector.py was restored to the state immediately before that patch."
Write-Host "Earlier door/window/layer/rule-order fixes remain as they were in that backup."
Write-Host ("Restored from: " + $sourceBackup.FullName)
Write-Host ("Safety backup: " + $safetyBackup)
