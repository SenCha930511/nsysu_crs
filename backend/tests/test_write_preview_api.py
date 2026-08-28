"""POST /api/write/preview contract tests (plan todo 14; QA qa/14-*.log part).

Hermetic, patterned on test_stage_api.py: the school is a scripted
get_studfun/get_write_form pair (monkeypatched at app.api.write), the
catalog is a stubbed resolve_course map, Redis is FakeRedis, sessions are
seeded directly, and every request carries a valid CSRF pair (middleware
semantics themselves live in test_write_csrf.py).

The 9 plan checks are all triggered here: stage gate (409), live session
(401), 無課號, 衝堂 (selections + staged batch, clashing code surfaced),
quota warnings, 不在已選, 同批加退混雜, priority/row-limit 400s, and
typed_confirmation_missing - plus the full-pass payload preview deep-equal
and the minted single-use confirm_token record.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import create_site_session, store_selcrs
from app.config import Settings
from app.main import create_app
from app.selcrs.errors import SelcrsUnavailable
from app.selections.parse import SelectionItem
from app.selections.store import SelectionsSnapshot, store_snapshot
from app.write.catalog import COURSE_NOT_FOUND, CourseInfo
from app.write.csrf import csrf_cookie_name
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
TEST_COOKIE_VALUE = "QA-SECRET-COOKIE-6b7a5941e3"
STUDENT = "M153000024"
CSRF = "qa14-csrf-token"
FORM_URL = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
    "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)
STAGE5_FORM_URL = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/stage5/saddstage5.asp"
    "?X1=01&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)


def _load(name: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / name).read_bytes().decode(encoding)


def _course(
    code: str,
    *,
    class_time: tuple[str, ...] = ("", "", "", "", "", "", ""),
    remaining: int | None = 10,
) -> CourseInfo:
    return CourseInfo(
        course_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"qa14.{code}")),
        code=code,
        class_time=class_time,
        restrict=60,
        select_n=50,
        selected_n=40,
        remaining=remaining,
        ingested_at="2026-08-28T03:10:00+08:00",
    )


DEFAULT_CATALOG = {
    # day1 periods 3,4 / day7 periods 8,9 / day3 periods 2,3,4: no clashes.
    "GEAE2526": _course("GEAE2526", class_time=("34", "", "", "", "", "", "")),
    "MEME101B": _course("MEME101B", class_time=("", "", "", "", "", "", "89")),
    "M3046243": _course("M3046243", class_time=("", "", "234", "", "", "", "")),
}


def _item(
    code: str | None,
    *,
    times: str | None = None,
    course_id: str | None = None,
    course_no: str | None = None,
) -> SelectionItem:
    return SelectionItem(
        code=code,
        course_no=course_no if course_no is not None else (code or "CSE515"),
        state="選上",
        dept="資工碩",
        name="高等電腦網路",
        credit=3,
        compulsory_elective="必",
        teacher="某人",
        room_text="",
        points_priority=None,
        stage="0",
        year_semest_note="期",
        times=times,
        room=None,
        unknown=True,
        course_id=course_id,
    )


@dataclass
class StubSchool:
    studfun_script: object
    form_script: object | None = None
    studfun_calls: int = 0
    form_calls: int = 0

    async def get_studfun(self, cookies) -> str:
        self.studfun_calls += 1
        return self.studfun_script()

    async def get_write_form(self, cookies, form_url: str) -> str:
        self.form_calls += 1
        assert self.form_script is not None, "a form GET was not expected here"
        return self.form_script(form_url)


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    school: StubSchool
    catalog: dict[str, CourseInfo] = field(default_factory=dict)
    join_results: dict[str, CourseInfo] = field(default_factory=dict)

    async def seed_session(self, *, with_jar: bool = True) -> str:
        session_id = await create_site_session(self.redis, STUDENT)
        if with_jar:
            await store_selcrs(
                self.redis,
                session_id,
                json.dumps([["ASPSESSIONIDQATEST", TEST_COOKIE_VALUE]]),
                sliding_ttl=1800,
                hard_ttl=7200,
            )
        return session_id

    async def seed_selections(self, session_id: str, items: list[SelectionItem]) -> None:
        await store_snapshot(
            self.redis,
            session_id,
            SelectionsSnapshot(synced_at="2026-08-28T09:00:00+08:00", items=items),
        )

    def preview(self, session_id: str, ops: list[dict]) -> httpx.Response:
        return self.client.post(
            "/api/write/preview",
            json={"ops": ops},
            cookies={"session_id": session_id, csrf_cookie_name(session_id): CSRF},
            headers={"X-CSRF-Token": CSRF},
        )


def _make_harness(
    monkeypatch, studfun, form=None, catalog=None, *, flag: bool = False
) -> Harness:
    settings = Settings(app_secret="qa14-test-secret", feature_first_round_write=flag)
    app = create_app(settings)
    school = StubSchool(studfun_script=studfun, form_script=form)
    harness = Harness(
        client=TestClient(app), redis=FakeRedis(), school=school, catalog=catalog or {}
    )

    async def stub_resolve(db, *, year_sem, ident):
        return harness.catalog.get(ident, COURSE_NOT_FOUND)

    async def stub_resolve_ids(db, *, year_sem, course_ids):
        return {
            raw: harness.join_results[raw] for raw in course_ids if raw in harness.join_results
        }

    monkeypatch.setattr("app.api.write_probe.get_studfun", school.get_studfun)
    monkeypatch.setattr("app.api.write_probe.get_write_form", school.get_write_form)
    monkeypatch.setattr("app.api.write.resolve_course", stub_resolve)
    monkeypatch.setattr("app.api.write.resolve_courses_by_ids", stub_resolve_ids)
    harness.client.__enter__()
    harness.client.app.state.redis = harness.redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(studfun, form=None, catalog=None, **kwargs) -> Harness:
        harness = _make_harness(monkeypatch, studfun, form, catalog, **kwargs)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


def _open_ssform() -> str:
    return _load("studfun_open_ssform_provisional.html")


def _open_stage5() -> str:
    return _load("studfun_open_stage5_provisional.html")


def _closed() -> str:
    return _load("studfun_closed_live_1151.html")


def _unavailable() -> str:
    raise SelcrsUnavailable("scripted unknown school shape")


def _ssform(form_url: str) -> str:
    return _load("ssform_provisional.html", "big5hkscs")


def _stage5_form(form_url: str) -> str:
    return _load("saddstage5_provisional.html", "big5hkscs")


def _prestep_form(form_url: str) -> str:
    return _load("ssform_prestep_provisional.html")


def _add(code: str, priority: int) -> dict:
    return {"action": "+", "course_id": code, "priority": priority}


def _drop(code: str, confirm: str | None = None) -> dict:
    return {"action": "-", "course_id": code, "drop_confirm_text": confirm}


def _expected_ssprs_payload() -> dict[str, str]:
    payload = {
        "step": "2", "X1": "09", "X2": "0", "DEG_COD": "B", "college": "1",
        "dept": "36", "grade": "1", "SCH_COD": "2", "USE_YR": "115",
        "EDU": "B", "MAX_ADD": "15",
        "D1": "-", "C1": "M3046243", "T1": "",
        "D2": "+", "C2": "GEAE2526", "T2": "01",
        "D3": "+", "C3": "MEME101B", "T3": "02",
        "send": "提交",
    }
    for row in range(4, 16):
        payload[f"D{row}"], payload[f"C{row}"], payload[f"T{row}"] = "N", "", ""
    return payload


# ---------- happy path (QA qa/14-preview.log) ----------


@pytest.mark.anyio
async def test_happy_two_adds_one_typed_drop_payload_deep_equal_and_token(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243")])

    response = harness.preview(
        sid, [_add("GEAE2526", 1), _add("MEME101B", 2), _drop("M3046243", "M3046243")]
    )

    assert response.status_code == 200
    body = response.json()
    assert body["writable"] is True
    assert body["stage"] == "加退選" and body["variant"] == "ssform"
    assert body["form_url"] == FORM_URL
    assert [op["verdict"] for op in body["ops"]] == ["ok", "ok", "ok"]
    assert body["canonical_ops"] == "-:M3046243:|+:GEAE2526:01|+:MEME101B:02"
    # payload preview deep-equal to the literal expectation (3 ops, 15 rows)
    assert body["payload"] == _expected_ssprs_payload()
    # confirm_token minted + stored single-use with the todo-15 record fields
    token = body["confirm_token"]
    assert token and "=" not in token
    record = json.loads(harness.redis.peek(f"confirm:{token}"))
    assert record == {
        "student_no": STUDENT,
        "canonical_ops": body["canonical_ops"],
        "variant": "ssform",
        "form_url": FORM_URL,
    }
    assert harness.redis.remaining_ttl(f"confirm:{token}") == 300
    # payload_hash = sha256("student_no|canonical_ops")
    expect = hashlib.sha256(f"{STUDENT}|{body['canonical_ops']}".encode()).hexdigest()
    assert body["payload_hash"] == expect
    # quota snapshot rides as warnings, never a block
    assert body["warnings"] == ["quota_snapshot"]
    assert body["quota_as_of"] == "2026-08-28T03:10:00+08:00"
    assert [op["code"] for op in body["ops"]] == ["GEAE2526", "MEME101B", "M3046243"]


@pytest.mark.anyio
async def test_drop_of_catalog_missing_selection_resolves_via_own_selections(harness_factory):
    # Given: a selected course the stub catalog does NOT know (no GEAE9999 row)
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("GEAE9999")])

    # When: dropping it
    response = harness.preview(sid, [_drop("GEAE9999", "GEAE9999")])

    # Then: the student's own selections supply the identity; op passes and the
    # payload carries the 課別代號 verbatim in the C slot
    assert response.status_code == 200
    body = response.json()
    assert body["writable"] is True
    assert [op["verdict"] for op in body["ops"]] == ["ok"]
    assert body["payload"]["C1"] == "GEAE9999"


@pytest.mark.anyio
async def test_stage_probe_is_fresh_on_every_preview(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243")])

    harness.preview(sid, [_add("GEAE2526", 1)])
    harness.preview(sid, [_add("GEAE2526", 1)])

    assert harness.school.studfun_calls == 2  # no cached stage between previews
    assert harness.school.form_calls == 2


# ---------- per-op verdicts (QA qa/14-invalid.log) ----------


@pytest.mark.anyio
async def test_unknown_course_gets_no_code_verdict(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()

    response = harness.preview(sid, [_add("NOSUCH01", 1)])

    body = response.json()
    assert body["writable"] is False
    assert body["confirm_token"] is None and body["payload"] is None
    op = body["ops"][0]
    assert (op["verdict"], op["writable"], op["code"]) == ("無課號", False, None)


@pytest.mark.anyio
async def test_catalog_row_with_null_code_gets_no_code_verdict(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    catalog["CODELESS"] = CourseInfo(
        course_id=str(uuid.uuid4()), code=None, class_time=()
    )
    harness = harness_factory(_open_ssform, _ssform, catalog)
    sid = await harness.seed_session()

    body = harness.preview(sid, [_add("CODELESS", 1)]).json()
    assert body["ops"][0]["verdict"] == "無課號"
    assert body["writable"] is False


@pytest.mark.anyio
async def test_add_conflicting_a_synced_selection_reports_the_clashing_code(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    catalog["GEAE2526"] = _course("GEAE2526", class_time=("", "", "23", "", "", "", ""))
    harness = harness_factory(_open_ssform, _ssform, catalog)
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243", times="三2,3,4")])

    body = harness.preview(sid, [_add("GEAE2526", 1)]).json()

    op = body["ops"][0]
    assert (op["verdict"], op["writable"]) == ("衝堂", False)
    assert op["detail"] == "M3046243"  # the clashing code, per plan
    assert body["confirm_token"] is None


@pytest.mark.anyio
async def test_add_conflicting_a_catalog_joined_selection_uses_its_class_time(harness_factory):
    catalog_row_id = str(uuid.uuid4())
    catalog = dict(DEFAULT_CATALOG)
    catalog["GEAE2526"] = _course("GEAE2526", class_time=("", "", "", "", "56", "", ""))
    harness = harness_factory(_open_ssform, _ssform, catalog)
    harness.join_results[catalog_row_id] = _course(
        "CAT00001", class_time=("", "", "", "", "5B", "", "")
    )
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("CAT00001", course_id=catalog_row_id)])

    body = harness.preview(sid, [_add("GEAE2526", 1)]).json()
    assert body["ops"][0]["verdict"] == "衝堂"
    assert body["ops"][0]["detail"] == "CAT00001"


@pytest.mark.anyio
async def test_two_staged_adds_clash_deterministically(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    catalog["AAAA0001"] = _course("AAAA0001", class_time=("45", "", "", "", "", "", ""))
    harness = harness_factory(_open_ssform, _ssform, catalog)
    sid = await harness.seed_session()

    ops = [_add("GEAE2526", 1), _add("AAAA0001", 2)]  # both day1, share period 4
    body = harness.preview(sid, ops).json()

    assert body["ops"][0]["verdict"] == "ok"  # first staged add wins
    assert body["ops"][1]["verdict"] == "衝堂"
    assert body["ops"][1]["detail"] == "GEAE2526"
    assert body["writable"] is False


@pytest.mark.anyio
async def test_drop_of_a_course_not_in_latest_selections_gets_verdict(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243")])

    body = harness.preview(sid, [_drop("GEAE2526", "GEAE2526")]).json()
    assert body["ops"][0]["verdict"] == "不在已選"
    assert body["writable"] is False


@pytest.mark.anyio
async def test_same_course_added_and_dropped_gets_mixed_verdict_on_both(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243")])

    body = harness.preview(sid, [_add("M3046243", 1), _drop("M3046243", "M3046243")]).json()
    assert [op["verdict"] for op in body["ops"]] == ["同批加退混雜", "同批加退混雜"]
    assert body["writable"] is False
    assert body["confirm_token"] is None


@pytest.mark.anyio
async def test_full_remaining_is_a_warning_never_a_block(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    catalog["GEAE2526"] = _course("GEAE2526", class_time=("34", "", "", "", "", "", ""), remaining=0)
    harness = harness_factory(_open_ssform, _ssform, catalog)
    sid = await harness.seed_session()

    body = harness.preview(sid, [_add("GEAE2526", 1)]).json()
    assert body["writable"] is True  # stale quota surfaces as WARNING only
    assert body["ops"][0]["warnings"] == ["remaining_zero"]
    assert body["ops"][0]["quota"]["remaining"] == 0
    assert body["confirm_token"]


# ---------- request-shape 400s (QA qa/14-invalid.log) ----------


@pytest.mark.anyio
async def test_add_without_priority_is_400_priority_required(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    response = harness.preview(sid, [{"action": "+", "course_id": "GEAE2526"}])
    assert (response.status_code, response.json()["detail"]) == (400, "priority_required")


@pytest.mark.anyio
async def test_drop_with_priority_is_400_priority_forbidden(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    response = harness.preview(sid, [_drop("M3046243", "M3046243") | {"priority": 1}])
    assert (response.status_code, response.json()["detail"]) == (400, "priority_forbidden")


@pytest.mark.anyio
async def test_out_of_range_priority_is_400(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    for priority in (0, 21):
        response = harness.preview(sid, [_add("GEAE2526", priority)])
        assert (response.status_code, response.json()["detail"]) == (400, "priority_invalid")


@pytest.mark.anyio
async def test_duplicate_priority_within_batch_is_400(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add("GEAE2526", 1), _add("MEME101B", 1)])
    assert (response.status_code, response.json()["detail"]) == (400, "priority_duplicate")


@pytest.mark.anyio
async def test_ops_over_the_variant_limit_is_400(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    for i in range(1, 17):
        catalog[f"BULK{i:04d}"] = _course(f"BULK{i:04d}")
    harness = harness_factory(_open_ssform, _ssform, catalog)
    sid = await harness.seed_session()
    ops = [_add(f"BULK{i:04d}", i) for i in range(1, 17)]  # 16 > ssform's 15
    response = harness.preview(sid, ops)
    assert (response.status_code, response.json()["detail"]) == (400, "ops_limit_exceeded")


@pytest.mark.anyio
async def test_drop_without_the_typed_code_is_400(harness_factory):
    harness = harness_factory(_open_ssform, _ssform, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    await harness.seed_selections(sid, [_item("M3046243")])
    for confirm in (None, "M3046244", "m3046243"):
        response = harness.preview(sid, [_drop("M3046243", confirm)])
        assert (response.status_code, response.json()["detail"]) == (
            400,
            "typed_confirmation_missing",
        )


# ---------- stage gate / sessions (QA qa/14-invalid.log) ----------


@pytest.mark.anyio
async def test_closed_stage_is_409_stage_unavailable(harness_factory):
    harness = harness_factory(_closed)
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add("GEAE2526", 1)])
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "stage_unavailable"
    assert body["stage"] == "關閉" and body["need_confirmation"] is False


@pytest.mark.anyio
async def test_prestep_stage_is_409_with_need_confirmation(harness_factory):
    harness = harness_factory(_open_ssform, _prestep_form)
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add("GEAE2526", 1)])
    assert response.status_code == 409
    assert response.json()["need_confirmation"] is True


@pytest.mark.anyio
async def test_missing_selcrs_jar_is_401_with_zero_school_calls(harness_factory):
    harness = harness_factory(_open_ssform, _ssform)
    sid = await harness.seed_session(with_jar=False)
    response = harness.preview(sid, [_add("GEAE2526", 1)])
    assert (response.status_code, response.json()["detail"]) == (401, "SELCRS_EXPIRED")
    assert harness.school.studfun_calls == 0


@pytest.mark.anyio
async def test_unavailable_studfun_is_503(harness_factory):
    harness = harness_factory(_unavailable)
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add("GEAE2526", 1)])
    assert (response.status_code, response.json()["detail"]) == (503, "school_unavailable")


# ---------- stage5 variant ----------


@pytest.mark.anyio
async def test_stage5_flag_off_is_409(harness_factory):
    harness = harness_factory(_open_stage5, _stage5_form, dict(DEFAULT_CATALOG))
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add("GEAE2526", 1)])
    assert response.status_code == 409
    assert response.json()["stage"] == "初選"


@pytest.mark.anyio
async def test_stage5_flag_on_builds_the_ten_row_payload(harness_factory):
    harness = harness_factory(_open_stage5, _stage5_form, dict(DEFAULT_CATALOG), flag=True)
    sid = await harness.seed_session()

    response = harness.preview(sid, [_add("GEAE2526", 7)])

    body = response.json()
    assert body["writable"] is True and body["variant"] == "stage5"
    assert body["form_url"] == STAGE5_FORM_URL
    payload = body["payload"]
    assert payload["step"] == "1" and payload["MAX_ADD"] == "10" and payload["send"] == "提交"
    assert (payload["D1"], payload["C1"], payload["T1"]) == ("+", "GEAE2526", "07")
    assert "D11" not in payload
    assert body["canonical_ops"] == "+:GEAE2526:07"
    record = json.loads(harness.redis.peek(f"confirm:{body['confirm_token']}"))
    assert record["variant"] == "stage5" and record["form_url"] == STAGE5_FORM_URL


@pytest.mark.anyio
async def test_stage5_limit_is_ten_ops(harness_factory):
    catalog = dict(DEFAULT_CATALOG)
    for i in range(1, 12):
        catalog[f"BULK{i:04d}"] = _course(f"BULK{i:04d}")
    harness = harness_factory(_open_stage5, _stage5_form, catalog, flag=True)
    sid = await harness.seed_session()
    response = harness.preview(sid, [_add(f"BULK{i:04d}", i) for i in range(1, 12)])
    assert (response.status_code, response.json()["detail"]) == (400, "ops_limit_exceeded")


def test_preview_requires_a_site_session_and_csrf(harness_factory):
    harness = harness_factory(_closed)
    response = harness.client.post("/api/write/preview", json={"ops": [_add("GEAE2526", 1)]})
    assert response.status_code == 403  # CSRF gate runs before auth
    assert response.json() == {"detail": "csrf_failed"}
