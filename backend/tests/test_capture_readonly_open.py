"""Tests for the read-only capture kit's open-window extension (todo 13 kit).

Two guarantee axes, both hermetic (school traffic scripted through the
module's ``_sso2_raw``/``_get`` seams; the +60s/+180s TTL sleeps stubbed):

- link-follow: an open Studfun (ssform/saddstage5 link present) makes
  ``--run-readonly`` save ``studfun_open_live_1151`` plus the verbatim form
  page (``ssform_live_1151`` / ``saddstage5_live_1151``) and issue exactly
  one extra pure GET; the closed state saves only ``studfun_closed_live_1151``
  and never follows a form link.
- read-only hardness: a source grep of the readonly runner proves no POST
  exists outside the single SSO2-login helper (and no client-level ``.post()``
  call exists at all) — the form follow-up can only ever be a GET.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from scripts.capture import readonly
from scripts.capture.creds import Credentials
from scripts.capture.readonly import _WRONG_PASSWORD_SENTINEL
from scripts.capture.runtime import SLT_RESULT_URL, STUDFUN_URL

FIXTURES = Path(__file__).parent / "fixtures"

FORM_URL_SSFORM = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
    "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)
FORM_URL_STAGE5 = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/stage5/saddstage5.asp"
    "?X1=01&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _response(
    status: int, body: bytes, *, set_cookie: str | None = None, location: str | None = None
) -> httpx.Response:
    headers: dict[str, str] = {}
    if set_cookie is not None:
        headers["set-cookie"] = set_cookie
    if location is not None:
        headers["location"] = location
    return httpx.Response(status, headers=headers, content=body)


@dataclass
class FakeSchool:
    """Scripted school wire for run_readonly's _sso2_raw/_get seams."""

    studfun_body: bytes
    form_bodies: dict[str, bytes]
    get_urls: list[str] = field(default_factory=list)
    sso2_passwords: list[str] = field(default_factory=list)

    async def sso2_raw(self, student_id: str, password: str):
        self.sso2_passwords.append(password)
        if password == _WRONG_PASSWORD_SENTINEL:
            fail = "資料錯誤﹕學號碼密碼不符，請重新登錄！".encode("utf-8")
            return _response(200, fail), httpx.Cookies()
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", "session")
        return (
            _response(
                302, b"", location="main_frame.asp", set_cookie="ASPSESSIONIDQATEST=session"
            ),
            jar,
        )

    async def get(self, ctx, url: str, jar: httpx.Cookies) -> httpx.Response:
        self.get_urls.append(url)
        if url == STUDFUN_URL:
            return _response(200, self.studfun_body)
        if url == SLT_RESULT_URL:
            return _response(200, _bytes("slt_result_live_1151.html"))
        for marker, name in self.form_bodies.items():
            if marker in url:
                return _response(200, name)
        raise AssertionError(f"unexpected GET: {url}")


def _install(monkeypatch, school: FakeSchool) -> None:
    async def _no_sleep(deadline: float) -> None:
        return None

    monkeypatch.setattr(readonly, "_sso2_raw", school.sso2_raw)
    monkeypatch.setattr(readonly, "_get", school.get)
    monkeypatch.setattr(readonly, "_sleep_until", _no_sleep)


async def _run(monkeypatch, tmp_path, school: FakeSchool) -> tuple[int, Path, Path]:
    _install(monkeypatch, school)
    fixtures_dir = tmp_path / "fixtures"
    qa_dir = tmp_path / "qa"
    code = await readonly.run_readonly(
        creds=Credentials(student_id="M1530024", password="secret-pw"),
        fixtures_dir=fixtures_dir,
        qa_dir=qa_dir,
        facts_path=tmp_path / "verified-facts.md",
    )
    return code, fixtures_dir, qa_dir


# ---------- link-follow: open ssform ----------


@pytest.mark.anyio
async def test_open_ssform_studfun_saves_open_copy_and_form_page(monkeypatch, tmp_path):
    school = FakeSchool(
        studfun_body=_bytes("studfun_open_ssform_provisional.html"),
        form_bodies={"ssform.asp": _bytes("ssform_provisional.html")},
    )

    code, fixtures_dir, qa_dir = await _run(monkeypatch, tmp_path, school)

    assert code == 0
    # open-state Studfun copy; the closed-named fixture is NOT written
    assert (fixtures_dir / "studfun_open_live_1151.html").is_file()
    assert not (fixtures_dir / "studfun_closed_live_1151.html").exists()
    # full form page captured, raw + decoded, hidden inputs visible
    assert (fixtures_dir / "ssform_live_1151.html").is_file()
    decoded = (fixtures_dir / "ssform_live_1151.txt").read_text(encoding="utf-8")
    assert "MAX_ADD" in decoded and "DEG_COD" in decoded
    # exactly ONE extra GET, to the resolved form URL
    assert school.get_urls.count(FORM_URL_SSFORM) == 1
    assert not any("saddstage5.asp" in url for url in school.get_urls)
    # journal carries the follow-up + an explicit ledger entry
    journal = (qa_dir / "04-readonly-capture.log").read_text(encoding="utf-8")
    assert "ssform_live_1151" in journal
    assert "form page follow-up" in journal


@pytest.mark.anyio
async def test_open_stage5_studfun_saves_saddstage5_form_page(monkeypatch, tmp_path):
    school = FakeSchool(
        studfun_body=_bytes("studfun_open_stage5_provisional.html"),
        form_bodies={"saddstage5.asp": _bytes("saddstage5_provisional.html")},
    )

    code, fixtures_dir, _qa_dir = await _run(monkeypatch, tmp_path, school)

    assert code == 0
    assert (fixtures_dir / "studfun_open_live_1151.html").is_file()
    assert (fixtures_dir / "saddstage5_live_1151.html").is_file()
    assert not (fixtures_dir / "ssform_live_1151.html").exists()
    assert school.get_urls.count(FORM_URL_STAGE5) == 1


# ---------- link-follow: closed (no form link present) ----------


@pytest.mark.anyio
async def test_closed_studfun_never_follows_a_form_link(monkeypatch, tmp_path):
    school = FakeSchool(
        studfun_body=_bytes("studfun_closed_live_1151.html"),
        form_bodies={},  # any form GET would raise in the fake
    )

    code, fixtures_dir, _qa_dir = await _run(monkeypatch, tmp_path, school)

    assert code == 0
    assert (fixtures_dir / "studfun_closed_live_1151.html").is_file()
    assert not (fixtures_dir / "studfun_open_live_1151.html").exists()
    assert not (fixtures_dir / "ssform_live_1151.html").exists()
    assert not (fixtures_dir / "saddstage5_live_1151.html").exists()
    assert not any("ssform.asp" in url or "saddstage5.asp" in url for url in school.get_urls)


# ---------- read-only hardness (source grep) ----------


def test_readonly_runner_posts_nothing_outside_sso2_login() -> None:
    src = Path(readonly.__file__).read_text(encoding="utf-8")

    # No client-level httpx posts anywhere in the module at all.
    assert ".post(" not in src

    # Exactly one quoted POST literal exists module-wide...
    assert src.count('"POST"') == 1

    # ...and it lives inside the SSO2-login helper, nowhere else.
    blocks = re.split(r"\n(?:async )?def ", src)
    offenders = [
        block.split("(", 1)[0]
        for block in blocks
        if '"POST"' in block and not block.startswith("_sso2_raw(")
    ]
    assert offenders == []
