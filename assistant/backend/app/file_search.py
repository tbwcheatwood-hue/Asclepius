"""Search files under user-approved roots only."""

from __future__ import annotations

import os
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".cache", "snap"}
MAX_DEPTH = 7
MAX_RESULTS = 40
MAX_FILE_BYTES = 50_000_000


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Documents", home]
    return [p for p in roots if p.is_dir()]


def parse_roots(raw: str) -> list[Path]:
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return default_roots()
    out: list[Path] = []
    for line in lines:
        path = Path(line).expanduser()
        if path.is_dir():
            out.append(path.resolve())
    return out or default_roots()


def _allowed(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def search(roots_raw: str, query: str) -> list[dict]:
    needle = query.strip().lower()
    if len(needle) < 2:
        return []
    roots = parse_roots(roots_raw)
    hits: list[dict] = []
    for root in roots:
        _walk(root, root, needle, 0, roots, hits)
        if len(hits) >= MAX_RESULTS:
            break
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:MAX_RESULTS]


def _walk(
    root: Path,
    current: Path,
    needle: str,
    depth: int,
    roots: list[Path],
    hits: list[dict],
) -> None:
    if depth > MAX_DEPTH or len(hits) >= MAX_RESULTS:
        return
    try:
        names = sorted(os.listdir(current))
    except OSError:
        return
    for name in names:
        if name.startswith("."):
            continue
        path = current / name
        if not _allowed(path, roots):
            continue
        try:
            if path.is_dir():
                if name in SKIP_DIRS:
                    continue
                _walk(root, path, needle, depth + 1, roots, hits)
                continue
            if not path.is_file():
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        lower = name.lower()
        if needle in lower:
            score = 3 if lower.startswith(needle) else 1
            hits.append({"path": str(path), "name": name, "score": score})
