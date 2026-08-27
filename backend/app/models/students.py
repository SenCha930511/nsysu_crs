"""students: the only identity row we persist. No credentials by design."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Student(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """One row per student who has logged in at least once."""

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    student_no: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
