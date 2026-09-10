from __future__ import annotations

from pathlib import Path


_TEXT_SUFFIXES = {".py", ".json", ".qss", ".md", ".txt"}
_SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", "backups", "gelistirmeler", "geli\u015ftirmeler"}

# Common first characters/sequences produced when UTF-8 Turkish text is decoded incorrectly.
_SUSPICIOUS = (
    chr(0x00C3),
    chr(0x00C4),
    chr(0x00C5),
    chr(0x00E2) + chr(0x20AC),
)


def assert_project_text_is_clean_utf8(root: Path) -> None:
    problems: list[str] = []

    for base_name in ("src", "config", "tools"):
        base = root / base_name
        if not base.exists():
            continue

        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            if any(part in _SKIP_PARTS for part in path.parts):
                continue

            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                problems.append(f"{path}: invalid UTF-8 ({exc})")
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                if any(marker in line for marker in _SUSPICIOUS):
                    problems.append(f"{path}:{line_no}: possible mojibake")
                    break

    if problems:
        raise RuntimeError(
            "3Dcad text encoding guard blocked startup.\\n"
            + "\\n".join(problems[:20])
        )
