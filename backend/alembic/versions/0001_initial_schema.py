"""initial schema: Redis-only credential policy + idempotency index

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-27

All constraint/index names are explicit and match app/models one-to-one, so
future `alembic revision --autogenerate` runs stay diff-free.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("student_no", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_students"),
        sa.UniqueConstraint("student_no", name="uq_students_student_no"),
    )

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
        "courses",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("year_sem", sa.Text(), nullable=False),
        sa.Column("code", sa.CHAR(8), nullable=True),
        sa.Column("dept", sa.Text(), nullable=True),
        sa.Column("grade", sa.Text(), nullable=True),
        sa.Column("class", sa.Text(), nullable=True),
        sa.Column("name_zh", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("credit", sa.Integer(), nullable=True),
        sa.Column(
            "compulsory", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("restrict", sa.Integer(), nullable=True),
        sa.Column("select_n", sa.Integer(), nullable=True),
        sa.Column("selected_n", sa.Integer(), nullable=True),
        sa.Column("remaining", sa.Integer(), nullable=True),
        sa.Column("teacher", sa.Text(), nullable=True),
        sa.Column("room", sa.Text(), nullable=True),
        sa.Column("class_time", pg.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", pg.JSONB(), nullable=True),
        sa.Column("english", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("change", sa.Text(), nullable=True),
        sa.Column("change_desc", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_courses"),
        sa.UniqueConstraint("year_sem", "code", name="uq_courses_year_sem"),
    )

    op.create_table(
        "ingest_runs",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source", sa.Text(), server_default="self-scrape", nullable=False),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_runs"),
    )

    op.create_table(
        "write_jobs",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ops", pg.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled', 'session_superseded')",
            name="ck_write_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_write_jobs_student_id_students"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_write_jobs"),
    )
    op.create_index("ix_write_jobs_student_id", "write_jobs", ["student_id"])
    # Partial unique index: one active (queued|running) job per payload at most -
    # the DB-enforced double-click / replay idempotency guarantee.
    op.create_index(
        "uq_write_jobs_active_payload_hash",
        "write_jobs",
        ["payload_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "write_audit",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("school_msg", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("stuid_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["write_jobs.id"], name="fk_write_audit_job_id_write_jobs"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_write_audit"),
    )
    op.create_index("ix_write_audit_job_id", "write_audit", ["job_id"])

    op.create_table(
        "write_audit_archive_meta",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_write_audit_archive_meta"),
    )


def downgrade() -> None:
    op.drop_table("write_audit_archive_meta")
    op.drop_index("ix_write_audit_job_id", table_name="write_audit")
    op.drop_table("write_audit")
    op.drop_index("uq_write_jobs_active_payload_hash", table_name="write_jobs")
    op.drop_index("ix_write_jobs_student_id", table_name="write_jobs")
    op.drop_table("write_jobs")
    op.drop_table("ingest_runs")
    op.drop_table("courses")
    op.drop_index("ix_plan_items_plan_id", table_name="plan_items")
    op.drop_table("plan_items")
    op.drop_index("ix_plans_student_id", table_name="plans")
    op.drop_table("plans")
    op.drop_table("students")
