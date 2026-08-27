"""Tests for --run-readonly dispatch, --creds-env loading, and marker helpers."""

import os
from datetime import datetime
from pathlib import Path

import pytest

from scripts.capture.__main__ import EXIT_CREDS_REJECTED, main
from scripts.capture.creds import (
    Credentials,
    CredentialsRejected,
    load_credentials,
    mask_student_id,
)
from scripts.capture.readonly import _fragments_with_hints, first_table_header_cells
from scripts.capture.windows import TAIPEI

OUTSIDE = datetime(2026, 8, 27, 21, 0, tzinfo=TAIPEI)

VALID_ENV = "STUDENT_ID=M1530024\nSPASSWORD=hunter2-secret\n"


def _write_env(path: Path, content: str = VALID_ENV, mode: int = 0o600) -> Path:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_mask_student_id_keeps_first4_last2() -> None:
    assert mask_student_id("M1530024") == "M153****24"
    assert mask_student_id("ABCDEF12") == "ABCD****12"


def test_mask_student_id_short_ids_fully_hidden() -> None:
    assert mask_student_id("M1530") == "****"
    assert mask_student_id("") == "****"


def test_load_credentials_happy_path(tmp_path) -> None:
    env = _write_env(tmp_path / "creds.env")
    creds = load_credentials(env, repo_root=tmp_path / "repo")
    assert creds == Credentials(student_id="M1530024", password="hunter2-secret")


def test_load_credentials_refuses_path_inside_repo(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _write_env(repo / "creds.env")
    with pytest.raises(CredentialsRejected):
        load_credentials(env, repo_root=repo)


def test_load_credentials_refuses_group_or_other_readable(tmp_path) -> None:
    for mode in (0o640, 0o604, 0o644):
        env = _write_env(tmp_path / f"creds-{mode:o}.env", mode=mode)
        with pytest.raises(CredentialsRejected):
            load_credentials(env, repo_root=tmp_path / "repo")


def test_load_credentials_refuses_missing_file(tmp_path) -> None:
    with pytest.raises(CredentialsRejected):
        load_credentials(tmp_path / "nope.env", repo_root=tmp_path / "repo")


def test_load_credentials_refuses_missing_required_keys(tmp_path) -> None:
    env = _write_env(tmp_path / "creds.env", "STUDENT_ID=M1530024\n")
    with pytest.raises(CredentialsRejected) as excinfo:
        load_credentials(env, repo_root=tmp_path / "repo")
    assert "SPASSWORD" in str(excinfo.value)
    assert "hunter2" not in str(excinfo.value)


def test_run_readonly_dispatches_without_window_guard(tmp_path) -> None:
    # Given a moment OUTSIDE every window - the read-only mode must still run
    called: list[Credentials | None] = []

    def impl(creds: Credentials | None) -> int:
        called.append(creds)
        return 0

    code = main(
        ["--run-readonly"],
        now=OUTSIDE,
        qa_dir=tmp_path,
        readonly_impl=impl,
    )

    assert code == 0
    assert called == [None]
    assert not (tmp_path / "04-not-in-window.log").exists()


def test_run_readonly_passes_creds_env_to_impl(tmp_path) -> None:
    env = _write_env(tmp_path / "creds.env")
    called: list[Credentials | None] = []

    def impl(creds: Credentials | None) -> int:
        called.append(creds)
        return 0

    code = main(
        ["--run-readonly", "--creds-env", str(env)],
        qa_dir=tmp_path,
        readonly_impl=impl,
    )

    assert code == 0
    assert called == [Credentials(student_id="M1530024", password="hunter2-secret")]


def test_creds_env_rejection_exits_with_code_and_stderr(tmp_path, capsys) -> None:
    env = _write_env(tmp_path / "creds.env", mode=0o644)
    called: list[Credentials | None] = []

    code = main(
        ["--run-readonly", "--creds-env", str(env)],
        qa_dir=tmp_path,
        readonly_impl=lambda creds: called.append(creds) or 0,
    )

    assert code == EXIT_CREDS_REJECTED
    assert called == []
    err = capsys.readouterr().err
    assert "[CREDS] Refusing" in err
    assert "hunter2-secret" not in err
    assert "M1530024" not in err


def test_fragments_with_hints_extracts_marker_lines() -> None:
    html = "<html><body><script>alert('學號碼密碼不符！')</script>\n<p>其他文字</p></body>"
    fragments = _fragments_with_hints(html, ("密碼", "不符"))
    assert fragments == ["alert('學號碼密碼不符！')"]


def test_first_table_header_cells_summarizes_layout() -> None:
    html = "<table><tr><td>學號</td><td>姓名</td><td>課號</td></tr><tr><td>1</td></tr></table>"
    assert first_table_header_cells(html) == ["學號", "姓名", "課號"]
    assert first_table_header_cells("<p>no table here</p>") == []
