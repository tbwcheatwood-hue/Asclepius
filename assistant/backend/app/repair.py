"""Read-only repair proposals. Nothing here edits the running program."""

from __future__ import annotations

import os
from pathlib import Path

REPAIR_DIR = Path(__file__).resolve().parents[2] / "repairs"


def health(db_ok: bool) -> dict:
    return {
        "database": "ok" if db_ok else "error",
        "scheduler": "in-process",
        "background_jobs": "none",
        "repair_mode": "proposal-only",
        "detail": (
            "No background repair process is running. "
            "Proposals are saved as diff files and are not applied to the program."
        ),
    }


def propose_diff(explanation: str) -> str:
    text = explanation.strip()
    if not text:
        raise ValueError("An explanation is required")
    if len(text) > 2000:
        raise ValueError("Explanation is too long")
    safe = text.replace("\n", " ")
    return (
        "--- a/assistant/README.md\n"
        "+++ b/assistant/README.md\n"
        "@@\n"
        "+<!-- Proposed note, not applied:\n"
        f"+{safe}\n"
        "+-->\n"
    )


def save_proposal(proposal_id: int, diff: str) -> str:
    REPAIR_DIR.mkdir(parents=True, exist_ok=True)
    target = (REPAIR_DIR / f"proposal-{proposal_id}.diff").resolve()
    if REPAIR_DIR.resolve() not in target.parents:
        raise RuntimeError("Refusing to write outside the repairs directory")
    target.write_text(diff, encoding="utf-8")
    os.chmod(target, 0o644)
    return str(target)


def refuse_source_edit() -> None:
    raise PermissionError("Applying a repair to the running program is not allowed")
