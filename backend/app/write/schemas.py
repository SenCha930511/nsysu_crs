"""Request/response shapes of the write path (plan todo 14; todo 15/16
reuse the same contract: the confirm step consumes what preview minted).

OpIn's priority/drop_confirm_text rules are NOT model-level - they need the
sibling ops plus the resolved course, so the route enforces them as typed
400s; the models carry plain fields only.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OpIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["+", "-"]
    course_id: str = Field(min_length=1, max_length=64)
    priority: int | None = None
    drop_confirm_text: str | None = Field(default=None, max_length=32)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ops: list[OpIn] = Field(min_length=1, max_length=64)


class QuotaOut(BaseModel):
    """The ingest SNAPSHOT of one course's counters (check 5: warning,
    never a block)."""

    model_config = ConfigDict(frozen=True)

    restrict: int | None
    select_n: int | None
    selected_n: int | None
    remaining: int | None
    ingested_at: str | None


class OpVerdictOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    action: str
    course_id: str
    code: str | None
    writable: bool
    verdict: str
    detail: str | None
    warnings: list[str]
    quota: QuotaOut | None


class PreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    variant: str | None
    form_url: str | None
    writable: bool
    ops: list[OpVerdictOut]
    warnings: list[str]
    quota_as_of: str | None
    payload: dict[str, str] | None
    confirm_token: str | None
    payload_hash: str | None
    canonical_ops: str | None
