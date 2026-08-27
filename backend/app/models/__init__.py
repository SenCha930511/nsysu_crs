"""ORM models for the NSYSU course wrapper.

Security invariant (plan todo 2, enforced by grep + tests): NO model persists
any credential material - selcrs session artifacts live only in Redis keys
`selcrs:{site_session_id}` with a short TTL (see docs/architecture.md).
"""

from app.models.base import Base
from app.models.courses import Course, IngestRun
from app.models.plans import PlanItem, StudentPlan
from app.models.students import Student
from app.models.write import WriteAudit, WriteAuditArchiveMeta, WriteJob

__all__ = [
    "Base",
    "Course",
    "IngestRun",
    "PlanItem",
    "Student",
    "StudentPlan",
    "WriteAudit",
    "WriteAuditArchiveMeta",
    "WriteJob",
]
