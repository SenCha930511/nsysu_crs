"""courses.code CHAR(8) -> VARCHAR(20) for the 課別代號 identity

Revision ID: 0002_course_code_varchar20
Revises: 0001_initial_schema
Create Date: 2026-08-28

2026-08-28 identifier discovery (read-only probes logged at
qa/probe-crsno-desc.txt): the school write form accepts the 課別代號
(CSE515 resolves at chk_crsno_desc.asp; the 8-char 課程代碼 does NOT), and
every catalog row carries its 課別代號 in the showoutline CrsDat= link.
Derived codes overflow the legacy CHAR(8) (32 of 2596 rows are 9 chars).
All rows are code=NULL right now, so the widening collides with no data.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_course_code_varchar20"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "courses",
        "code",
        existing_type=sa.CHAR(length=8),
        type_=sa.String(length=20),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Codes longer than 8 cannot fit back; null them as the honest reversal.
    op.execute("UPDATE courses SET code = NULL WHERE length(code) > 8")
    op.alter_column(
        "courses",
        "code",
        existing_type=sa.String(length=20),
        type_=sa.CHAR(length=8),
        existing_nullable=True,
    )
