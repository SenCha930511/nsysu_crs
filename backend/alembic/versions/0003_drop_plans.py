"""drop plans + plan_items (feature retired by user decision, 2026-08-28)

Revision ID: 0003_drop_plans
Revises: 0002_course_code_varchar20
Create Date: 2026-08-28

Every plans API/route/store was removed in the same change; these two tables
no longer have any reader or writer. Git history keeps the full feature for
any resurrection.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_drop_plans"
down_revision: str | None = "0002_course_code_varchar20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("plan_items")
    op.drop_table("plans")


def downgrade() -> None:
    op.create_table(
        "plan_items",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 20", name="ck_plan_items_priority_between_1_20"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_plan_items_plan_id_plans", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_items"),
        sa.UniqueConstraint("plan_id", "course_id", name="uq_plan_items_plan_id"),
    )
    op.create_index("ix_plan_items_plan_id", "plan_items", ["plan_id"])
    op.create_table(
        "plans",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_plans_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
    )
    op.create_index("ix_plans_student_id", "plans", ["student_id"])
