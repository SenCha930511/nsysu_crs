"""plans + plan_items: multi plan CRUD with per-plan priority ordering (1-20)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StudentPlan(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """A named candidate course plan owned by one student."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE", name="fk_plans_student_id_students"),
        index=True,
    )
    name: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=func.false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlanItem(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """One course entry inside a plan; priority 1-20 doubles as wish ordering."""

    __tablename__ = "plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "course_id", name="uq_plan_items_plan_id"),
        CheckConstraint(
            "priority BETWEEN 1 AND 20",
            name="ck_plan_items_priority_between_1_20",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE", name="fk_plan_items_plan_id_plans"),
        index=True,
    )
    course_id: Mapped[str] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
