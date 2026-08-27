"""Postgres side of a successful login (plan todo 8): identity upsert + supersede.

- First login creates the ``students`` row; later logins find it
  (``ON CONFLICT DO NOTHING`` on the natural key).
- Single-session rule (site-side policy; the school provably tolerates
  concurrent sessions - docs/verified-facts.md live-verified (d)): a new
  login SUPERSEDES this student's still-active write jobs
  (``queued``/``running`` -> ``session_superseded``), atomically in the same
  transaction, and never blocks the login itself.
"""

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.students import Student
from app.models.write import WriteJob

_ACTIVE_STATUSES: Final = ("queued", "running")
_SUPERSEDED_STATUS: Final = "session_superseded"


@dataclass(frozen=True, slots=True)
class LoginDbResult:
    """Outcome of persisting one successful login."""

    student_id: uuid.UUID
    superseded_jobs: int


async def record_successful_login(
    session_factory: async_sessionmaker[AsyncSession], student_no: str
) -> LoginDbResult:
    """Upsert the student row and supersede active write jobs, one transaction."""
    async with session_factory() as session, session.begin():
        await session.execute(
            pg_insert(Student)
            .values(student_no=student_no)
            .on_conflict_do_nothing(index_elements=[Student.student_no])
        )
        student_id = (
            await session.execute(
                select(Student.id).where(Student.student_no == student_no)
            )
        ).scalar_one()
        result = await session.execute(
            update(WriteJob)
            .where(
                WriteJob.student_id == student_id,
                WriteJob.status.in_(_ACTIVE_STATUSES),
            )
            .values(status=_SUPERSEDED_STATUS, finished_at=func.now())
        )
    return LoginDbResult(
        student_id=student_id, superseded_jobs=getattr(result, "rowcount", 0) or 0
    )
