from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ensure_runtime_dirs() -> None:
    root = project_root()
    for relative in ("data/input", "data/output", "data/temp", "logs", "backups"):
        (root / relative).mkdir(parents=True, exist_ok=True)
