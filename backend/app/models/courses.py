"""courses + ingest_runs: self-scraped catalog rows and their ingestion ledger."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Course(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """One dplycourse row for a given semester.

    `code` (the school's 8-char course number) may be NULL when the catalog
    row carries none; the school allows multiple such rows per semester, so
    UNIQUE(year_sem, code) intentionally relies on Postgres treating NULLs as
    distinct.
    """

    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("year_sem", "code", name="uq_courses_year_sem"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    year_sem: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String(20))
    dept: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(Text)
    class_: Mapped[str | None] = mapped_column("class", Text)
    name_zh: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    credit: Mapped[int | None] = mapped_column(Integer)
    compulsory: Mapped[bool] = mapped_column(Boolean, server_default=func.false())
    restrict: Mapped[int | None] = mapped_column(Integer)
    select_n: Mapped[int | None] = mapped_column(Integer)
    selected_n: Mapped[int | None] = mapped_column(Integer)
    remaining: Mapped[int | None] = mapped_column(Integer)
    teacher: Mapped[str | None] = mapped_column(Text)
    room: Mapped[str | None] = mapped_column(Text)
    class_time: Mapped[list[str] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    english: Mapped[bool] = mapped_column(Boolean, server_default=func.false())
    change: Mapped[str | None] = mapped_column(Text)
    change_desc: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestRun(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """One catalog crawl round; ok=false keeps the last good snapshot servable."""

    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean, server_default=func.false())
    source: Mapped[str] = mapped_column(Text, server_default="self-scrape")
    rows: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
