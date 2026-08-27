"""GET /api/stage contract tests (plan todo 13; QA qa/13-stage.log part 2).

Hermetic, patterned on test_selections_api.py: the school is a scripted
get_studfun/get_write_form stub pair (monkeypatched at app.api.stage), Redis
is FakeRedis, sessions are seeded directly. Drift is asserted to be an HTTP
200 未知 + machine reason (NEVER an exception), and the writable matrix pins:
ssform open -> writable; stage5 -> writable only when
FEATURE_FIRST_ROUND_WRITE=true; closed/unknown/need_confirmation -> never.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import create_site_session, store_selcrs
from app.config import Settings
from app.main import create_app
from app.selcrs.errors import SelcrsUnavailable

from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
TEST_COOKIE_VALUE = "QA-SECRET-COOKIE-6b7a5941e3"

StudfunScript = Callable[[httpx.Cookies], str]
FormScript = Callable[[httpx.Cookies, str], str]


def _load(name: str, encoding: str = "utf-8") -> str:
    # New fixtures are UTF-8; the superseded provisional ones are raw big5 bytes.
    return (FIXTURES / name).read_bytes().decode(encoding)


@dataclass
class StubSchool:
    """Scriptable stand-ins for adapter get_studfun + get_write_form."""

    studfun_script: StudfunScript
    form_script: FormScript | None = None
    studfun_calls: int = 0
    form_urls: list[str] = field(default_factory=list)

    async def get_studfun(self, cookies: httpx.Cookies) -> str:
        self.studfun_calls += 1
        return self.studfun_script(cookies)

    async def get_write_form(self, cookies: httpx.Cookies, form_url: str) -> str:
        self.form_urls.append(form_url)
        assert self.form_script is not None, "a form GET was not expected here"
        return self.form_script(cookies, form_url)


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    school: StubSchool

    async def seed_session(self, *, with_jar: bool = True) -> str:
        session_id = await create_site_session(self.redis, "M153000024")
        if with_jar:
            await store_selcrs(
                self.redis,
                session_id,
                '[["ASPSESSIONIDQATEST", "' + TEST_COOKIE_VALUE + '"]]',
                sliding_ttl=1800,
                hard_ttl=7200,
            )
        return session_id

    def stage(self, session_id: str) -> httpx.Response:
        return self.client.get("/api/stage", cookies={"session_id": session_id})


def _make_harness(
    monkeypatch, studfun: StudfunScript, form: FormScript | None = None, *, flag: bool = False
) -> Harness:
    settings = Settings(app_secret="qa13-test-secret", feature_first_round_write=flag)
    app = create_app(settings)
    school = StubSchool(studfun_script=studfun, form_script=form)
    redis = FakeRedis()
    harness = Harness(client=TestClient(app), redis=redis, school=school)
    monkeypatch.setattr("app.api.stage.get_studfun", school.get_studfun)
    monkeypatch.setattr("app.api.stage.get_write_form", school.get_write_form)
    harness.client.__enter__()
    harness.client.app.state.redis = redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(studfun: StudfunScript, form: FormScript | None = None, **kwargs) -> Harness:
        harness = _make_harness(monkeypatch, studfun, form, **kwargs)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


def _closed(cookies: httpx.Cookies) -> str:
    return _load("studfun_closed_live_1151.html")


def _open_ssform(cookies: httpx.Cookies) -> str:
    return _load("studfun_open_ssform_provisional.html")


def _open_stage5(cookies: httpx.Cookies) -> str:
    return _load("studfun_open_stage5_provisional.html")


def _drift(cookies: httpx.Cookies) -> str:
    return _load("studfun_drift.html")


def _normal_form(cookies: httpx.Cookies, form_url: str) -> str:
    return _load("ssform_provisional.html", "big5hkscs")


def _prestep_form(cookies: httpx.Cookies, form_url: str) -> str:
    return _load("ssform_prestep_provisional.html")


def _unavailable(cookies: httpx.Cookies) -> str:
    raise SelcrsUnavailable("scripted unknown school shape")


def _unavailable_form(cookies: httpx.Cookies, form_url: str) -> str:
    raise SelcrsUnavailable("scripted form fetch failure")


# ---------- 關閉 (real live fixture) ----------


@pytest.mark.anyio
async def test_closed_stage_reports_keyword_closed_never_writable(harness_factory):
    harness = harness_factory(_closed)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "關閉"
    assert body["variant"] is None
    assert body["params"] is None
    assert body["need_confirmation"] is False
    assert body["writable"] is False
    assert body["reason"] == "closed_heading"
    assert "+" in body["checked_at"] or body["checked_at"].endswith("Z")
    assert harness.school.form_urls == []  # closed: no form GET at all


# ---------- 加退選 open (ssform) ----------


@pytest.mark.anyio
async def test_open_ssform_reports_add_drop_and_follows_form_link(harness_factory):
    harness = harness_factory(_open_ssform, _normal_form)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "加退選"
    assert body["variant"] == "ssform"
    assert body["reason"] == "ssform_link"
    assert body["writable"] is True
    assert body["need_confirmation"] is False
    assert body["params"] == {
        "X1": "09",
        "X2": "0",
        "EDU": "B",
        "DEG_COD": "B",
        "college": "1",
        "dept": "36",
        "grade": "1",
        "SCH_COD": "2",
        "USE_YR": "115",
    }
    # The form follow-up is the same-session GET of the RESOLVED link.
    assert harness.school.form_urls == [
        "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
        "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
    ]


@pytest.mark.anyio
async def test_prestep_form_gates_writable_and_marks_need_confirmation(harness_factory):
    harness = harness_factory(_open_ssform, _prestep_form)
    sid = await harness.seed_session()

    body = harness.stage(sid).json()

    assert body["stage"] == "加退選"
    assert body["need_confirmation"] is True
    assert body["writable"] is False  # blocked until the school-site step is done


# ---------- 初選 open (stage5) — FEATURE_FIRST_ROUND_WRITE mapping ----------


@pytest.mark.anyio
async def test_stage5_first_round_not_writable_when_flag_off(harness_factory):
    harness = harness_factory(_open_stage5, _normal_form)
    sid = await harness.seed_session()

    body = harness.stage(sid).json()

    assert body["stage"] == "初選"
    assert body["variant"] == "stage5"
    assert body["writable"] is False  # FEATURE_FIRST_ROUND_WRITE default false


@pytest.mark.anyio
async def test_stage5_first_round_writable_only_when_flag_on(harness_factory):
    harness = harness_factory(_open_stage5, _normal_form, flag=True)
    sid = await harness.seed_session()

    body = harness.stage(sid).json()

    assert body["stage"] == "初選"
    assert body["writable"] is True


# ---------- drift -> 未知 + machine reason, NEVER an exception ----------


@pytest.mark.anyio
async def test_drift_is_200_unknown_with_reason_never_writable(harness_factory):
    harness = harness_factory(_drift)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 200  # shape drift is a VALUE, never a 5xx
    body = response.json()
    assert body["stage"] == "未知"
    assert body["variant"] is None
    assert body["params"] is None
    assert body["writable"] is False  # unknown NEVER maps to writable
    assert body["reason"] == "drift_no_marker"
    assert harness.school.form_urls == []


# ---------- session / school failure routing ----------


@pytest.mark.anyio
async def test_login_bounce_from_school_is_401_selcrs_expired(harness_factory):
    def bounced(cookies: httpx.Cookies) -> str:
        return '<html><body><form action="Studcheck_sso2.asp">請先登錄</form></body></html>'

    harness = harness_factory(bounced)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 401
    assert response.json() == {"detail": "SELCRS_EXPIRED"}


@pytest.mark.anyio
async def test_missing_selcrs_jar_is_401_with_zero_school_calls(harness_factory):
    harness = harness_factory(_closed)
    sid = await harness.seed_session(with_jar=False)

    response = harness.stage(sid)

    assert response.status_code == 401
    assert response.json() == {"detail": "SELCRS_EXPIRED"}
    assert harness.school.studfun_calls == 0


@pytest.mark.anyio
async def test_unavailable_studfun_is_503_never_401(harness_factory):
    harness = harness_factory(_unavailable)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 503
    assert response.json() == {"detail": "school_unavailable"}


@pytest.mark.anyio
async def test_unavailable_form_followup_is_503(harness_factory):
    harness = harness_factory(_open_ssform, _unavailable_form)
    sid = await harness.seed_session()

    response = harness.stage(sid)

    assert response.status_code == 503
    assert response.json() == {"detail": "school_unavailable"}


def test_stage_requires_a_site_session(harness_factory):
    harness = harness_factory(_closed)
    response = harness.client.get("/api/stage")
    assert response.status_code == 401
    assert response.json() == {"detail": "not_authenticated"}
