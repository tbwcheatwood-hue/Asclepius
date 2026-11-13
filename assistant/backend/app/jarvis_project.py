"""Loopback file bridge so JARVIS can read and edit the assistant repo safely."""

from __future__ import annotations

import os
from pathlib import Path

ASSISTANT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = ASSISTANT_DIR.parent

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "jarvis-venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    ".vite",
}
MAX_READ_BYTES = 2_000_000
MAX_WRITE_BYTES = 2_000_000


def manifest() -> dict:
    return {
        "repo_root": str(REPO_ROOT),
        "assistant_dir": str(ASSISTANT_DIR),
        "ui_url": "http://127.0.0.1:9241/",
        "api_url": "http://127.0.0.1:9242/",
        "jarvis_url": os.environ.get("JARVIS_URL", "http://127.0.0.1:47821"),
        "sqlite": str(ASSISTANT_DIR / "data" / "assistant.sqlite"),
        "start": f"{ASSISTANT_DIR / 'start.sh'}",
        "tests": f"cd {ASSISTANT_DIR / 'backend'} && .venv/bin/python -m pytest -q",
        "web_typecheck": f"cd {ASSISTANT_DIR / 'web'} && npm run typecheck",
    }


def resolve_relative(relpath: str) -> Path:
    raw = (relpath or ".").strip().lstrip("/")
    if ".." in Path(raw).parts:
        raise ValueError("Path must stay inside the repository")
    target = (REPO_ROOT / raw).resolve()
    root = REPO_ROOT.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path must stay inside the repository") from exc
    return target


def list_tree(relpath: str = ".", *, max_entries: int = 500) -> dict:
    base = resolve_relative(relpath)
    if not base.exists():
        raise FileNotFoundError("Not found")
    if base.is_file():
        return {
            "path": str(base.relative_to(REPO_ROOT)),
            "kind": "file",
            "size": base.stat().st_size,
        }
    items: list[dict] = []
    for entry in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name in SKIP_DIR_NAMES:
            continue
        rel = str(entry.relative_to(REPO_ROOT))
        if entry.is_dir():
            items.append({"path": rel, "kind": "dir"})
        else:
            items.append({"path": rel, "kind": "file", "size": entry.stat().st_size})
        if len(items) >= max_entries:
            break
    return {
        "path": str(base.relative_to(REPO_ROOT)),
        "kind": "dir",
        "items": items,
        "truncated": len(items) >= max_entries,
    }


def read_text(relpath: str) -> dict:
    path = resolve_relative(relpath)
    if not path.is_file():
        raise FileNotFoundError("Not a file")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(f"File too large ({size} bytes); cap is {MAX_READ_BYTES}")
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "size": size,
    }


def write_text(relpath: str, content: str) -> dict:
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError("Content too large")
    path = resolve_relative(relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path.relative_to(REPO_ROOT)), "size": path.stat().st_size, "ok": True}
