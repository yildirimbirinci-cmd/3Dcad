from __future__ import annotations

from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
BACKUPS = ROOT / "geliştirmeler" / "backups"

candidates = sorted(
    [
        p
        for p in BACKUPS.glob("WINDOW_PAIR_TOPOLOGY_V5_*")
        if p.is_dir()
    ],
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not candidates:
    raise RuntimeError(
        "WINDOW_PAIR_TOPOLOGY_V5 backup klasoru bulunamadi."
    )

backup = candidates[0]

mapping = {
    "connect_levels_runtime.py":
        ROOT / "src" / "export" / "connect_levels_runtime.py",
    "multi_floor_max_send.py":
        ROOT / "src" / "export" / "multi_floor_max_send.py",
    "3DCAD_BRIDGE.ms":
        ROOT / "max" / "3DCAD_BRIDGE.ms",
}

missing = [
    name
    for name in mapping
    if not (backup / name).is_file()
]

if missing:
    raise RuntimeError(
        "Backup eksik: "
        + ", ".join(missing)
    )

for name, target in mapping.items():
    shutil.copy2(
        backup / name,
        target,
    )

# Remove stale sidecar introduced by V5 if present.
sidecar = (
    ROOT
    / "data"
    / "cache"
    / "max_bridge"
    / "window_pair_topology_records.txt"
)

if sidecar.exists():
    sidecar.unlink()

print("")
print("ROLLBACK COMPLETE")
print("RESTORED FROM:")
print(" ", backup)
print("")
print("RESTORED:")
for name, target in mapping.items():
    print(" ", target)
print("")
print("REMOVED V5 SIDECAR:")
print(" ", sidecar)
print("")
print("STATE:")
print("  WINDOW_PAIR_TOPOLOGY_V5 removed")
print("  MAX_CONNECT_BATCH_V3 restored")
print("")
