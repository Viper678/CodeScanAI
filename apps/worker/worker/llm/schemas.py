"""Pydantic schemas for Gemma LLM responses.

These shapes mirror the JSON contract documented in docs/SCAN_RULES.md
``Scan type 1 — Security`` and ``Scan type 2 — Bug report``. ``extra="forbid"``
keeps model drift loud: an unknown key is a validation error, not silent data
loss.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LlmFinding(BaseModel):
    """One finding emitted by Gemma."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    message: str = Field(max_length=1000)
    recommendation: str | None = Field(default=None, max_length=500)
    severity: Literal["critical", "high", "medium", "low", "info"]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    rule_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _line_order(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class FindingsResponse(BaseModel):
    """Top-level wrapper Gemma returns: ``{"findings": [...]}``."""

    model_config = ConfigDict(extra="forbid")

    findings: list[LlmFinding] = Field(default_factory=list)
