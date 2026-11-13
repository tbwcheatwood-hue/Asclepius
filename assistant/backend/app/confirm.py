"""Explicit user confirmation for dismissals and destructive actions."""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ConfirmBody(BaseModel):
    confirmed: bool = Field(default=False, description="Must be true after the user confirms in the UI.")


def require_confirmed(body: ConfirmBody | None = None, *, confirmed: bool = False) -> None:
    ok = confirmed or (body is not None and body.confirmed)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Set confirmed to true after the user approves this action.",
        )
