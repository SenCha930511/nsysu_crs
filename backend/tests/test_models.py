"""Model-layer invariants (tests-after strategy, per .omo plan todo 2)."""

import re

from sqlalchemy import Table

import app.models  # noqa: F401  (import for side effect: registers all tables on Base.metadata)
from app.models.base import Base

_EXPECTED_TABLES = (
    "students",
    "plans",
    "plan_items",
    "courses",
    "ingest_runs",
    "write_jobs",
    "write_audit",
    "write_audit_archive_meta",
)

_CREDENTIAL_NAME = re.compile(r"password|passwd|cookie|credential", re.IGNORECASE)


def test_models_register_exactly_the_planned_tables() -> None:
    # Given the models package is imported
    # When we inspect the shared metadata
    # Then exactly the 8 planned tables are registered (no selcrs_sessions, no extras)
    assert set(Base.metadata.tables) == set(_EXPECTED_TABLES)
    assert "selcrs_sessions" not in Base.metadata.tables


def _assert_table_is_credential_free(table: Table) -> None:
    assert not _CREDENTIAL_NAME.search(table.name), f"table name: {table.name}"
    for column in table.columns:
        assert not _CREDENTIAL_NAME.search(column.name), (
            f"credential-like column {table.name}.{column.name}"
        )


def test_no_column_or_table_carries_credential_material() -> None:
    # Given every registered table
    # When we scan table names and column names
    # Then none matches password|passwd|cookie|credential (selcrs keys stay in Redis)
    for table in Base.metadata.tables.values():
        _assert_table_is_credential_free(table)


def test_write_jobs_has_partial_unique_index_on_active_payload_hash() -> None:
    # Given the write_jobs table metadata (source of truth for migrations)
    write_jobs = Base.metadata.tables["write_jobs"]

    # When we collect its unique indexes
    unique_indexes = [index for index in write_jobs.indexes if index.unique]

    # Then exactly one covers payload_hash with a WHERE over queued/running only
    assert len(unique_indexes) == 1
    index = unique_indexes[0]
    assert index.name == "uq_write_jobs_active_payload_hash"
    assert [column.name for column in index.columns] == ["payload_hash"]
    where_clause = index.dialect_options["postgresql"]["where"]
    assert where_clause is not None
    for status in ("queued", "running"):
        assert status in str(where_clause)
    for status in ("done", "failed", "cancelled", "session_superseded"):
        assert status not in str(where_clause)
