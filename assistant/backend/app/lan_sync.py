"""Safe file listing and transfer within approved sync roots."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

from fastapi import HTTPException

from . import file_search


def sync_roots(conn: sqlite3.Connection) -> list[Path]:
    row = conn.execute("SELECT value FROM settings WHERE key = 'file_search_roots'").fetchone()
    raw = row["value"] if row else ""
    return file_search.parse_roots(raw)


def resolve_sync_path(conn: sqlite3.Connection, relative: str) -> Path:
    rel = relative.strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(400, "Invalid path.")
    roots = sync_roots(conn)
    for root in roots:
        candidate = (root / rel).resolve()
        if file_search._allowed(candidate, roots):
            return candidate
    raise HTTPException(403, "Path is outside approved sync folders.")


def list_sync_dir(conn: sqlite3.Connection, relative: str = "") -> dict:
    base = resolve_sync_path(conn, relative) if relative else None
    roots = sync_roots(conn)
    if base is None:
        return {
            "entries": [
                {"name": root.name or str(root), "path": str(root), "kind": "root", "size": 0}
                for root in roots
            ]
        }
    if not base.is_dir():
        raise HTTPException(400, "Not a directory.")
    entries = []
    prefix = relative.strip().strip("/")
    try:
        for name in sorted(os.listdir(base)):
            if name.startswith("."):
                continue
            path = base / name
            if not file_search._allowed(path, roots):
                continue
            kind = "directory" if path.is_dir() else "file"
            size = path.stat().st_size if path.is_file() else 0
            child_path = f"{prefix}/{name}" if prefix else name
            entries.append({"name": name, "path": child_path, "kind": kind, "size": size})
    except OSError as exc:
        raise HTTPException(400, f"Could not read folder: {exc}") from exc
    return {"entries": entries, "path": relative}


def file_metadata(path: Path) -> dict:
    stat = path.stat()
    digest = hashlib.sha256()
    if path.is_file() and stat.st_size <= file_search.MAX_FILE_BYTES:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return {"size": stat.st_size, "sha256": digest.hexdigest() if path.is_file() else ""}


def prepare_upload(conn: sqlite3.Connection, relative: str, expected_sha: str, size: int) -> dict:
    if size > file_search.MAX_FILE_BYTES:
        raise HTTPException(400, "File is too large for sync.")
    target = resolve_sync_path(conn, relative)
    exists = target.is_file()
    current = file_metadata(target) if exists else None
    if exists and current and current["sha256"] and expected_sha and current["sha256"] != expected_sha:
        return {
            "conflict": True,
            "message": "A different file already exists at this path. Rename or resolve before overwriting.",
            "existing_sha256": current["sha256"],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    return {"conflict": False, "path": relative}
