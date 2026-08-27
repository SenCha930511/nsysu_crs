"""Todo-14 QA driver: scripted mock-school flows for qa/14-*.log evidence.

Runs the REAL app (create_app) with the school adapter seams stubbed
(get_studfun / get_write_form / resolve_course / resolve_courses_by_ids /
auth login), FakeRedis, direct attribute assignment. No live traffic, no
compose contact, no real secrets. Prints one grep-friendly verdict per step.

Usage: cd backend && uv run python -m scripts.qa14_evidence --scenario preview|invalid|csrf|replay
"""

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.api.write as write_api
from app.api import write_probe
from app.auth.sessions import create_site_session, store_selcrs
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.sso2 import Sso2Outcome
from app.selections.parse import SelectionItem
from app.selections.store import SelectionsSnapshot, store_snapshot
from app.write.canonical import CanonicalOp, canonical_ops
from app.write.catalog import COURSE_NOT_FOUND, CourseInfo
from app.write.confirm import ConfirmRecord, consume_confirm, store_confirm
from app.write.csrf import csrf_cookie_name
from app.write.payload import (
    build_payload_ssprs,
    build_payload_stage5,
    parse_form_hidden_inputs,
    parse_send_value,
)
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
STUDENT = "M153000024"
CSRF = "qa14-csrf-token"
FAILURES: list[str] = []


def _verdict(ok: bool, label: str, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" :: {detail}" if ok is False else (f" :: {detail}" if detail else "")))
    if not ok:
        FAILURES.append(label)


def _load(name: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / name).read_bytes().decode(encoding)


def _course(code, class_time=("", "", "", "", "", "", ""), remaining=10):
    return CourseInfo(
        course_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"qa14.{code}")),
        code=code,
        class_time=class_time,
        restrict=60, select_n=50, selected_n=40, remaining=remaining,
        ingested_at="2026-08-28T03:10:00+08:00",
    )


CATALOG = {
    "GEAE2526": _course("GEAE2526", ("34", "", "", "", "", "", "")),
    "MEME101B": _course("MEME101B", ("", "", "", "", "", "", "89")),
    "M3046243": _course("M3046243", ("", "", "234", "", "", "", "")),
}


def _item(code, times=None, course_id=None):
    return SelectionItem(
        code=code, course_no="CSE515", state="選上", dept="資工碩", name="高等電腦網路",
        credit=3, compulsory_elective="必", teacher="某人", room_text="",
        points_priority=None, stage="0", year_semest_note="期", times=times,
        room=None, unknown=True, course_id=course_id,
    )


class Rig:
    """One scripted app instance. The endpoint seams are MODULE attributes,
    so creating a second Rig rebinds them globally - every preview() call
    re-installs ITS OWN stubs first to make interleaved rigs safe."""

    def __init__(self, studfun, form=None, catalog=None, *, flag=False) -> None:
        settings = Settings(app_secret="qa14-evidence-secret", feature_first_round_write=flag)
        app = create_app(settings)
        self.catalog = catalog if catalog is not None else dict(CATALOG)
        self._studfun_script = studfun
        self._form_script = form
        self.studfun_calls = 0
        self.form_calls = 0
        self.client = TestClient(app)
        self.client.__enter__()
        self.redis = FakeRedis()
        app.state.redis = self.redis
        self._install()

    def _install(self) -> None:
        async def stub_studfun():
            self.studfun_calls += 1
            return self._studfun_script()

        async def stub_form(form_url):
            self.form_calls += 1
            return self._form_script(form_url)

        async def stub_resolve(db, *, year_sem, ident):
            return self.catalog.get(ident, COURSE_NOT_FOUND)

        async def stub_resolve_ids(db, *, year_sem, course_ids):
            return {}

        write_probe.get_studfun = stub_studfun
        write_probe.get_write_form = stub_form
        write_api.resolve_course = stub_resolve
        write_api.resolve_courses_by_ids = stub_resolve_ids

    async def session(self, *, with_jar=True, selections=()):
        sid = await create_site_session(self.redis, STUDENT)
        if with_jar:
            await store_selcrs(
                self.redis, sid, json.dumps([["ASPSESSIONIDQATEST", "QA14-COOKIE"]]),
                sliding_ttl=1800, hard_ttl=7200,
            )
        if selections:
            await store_snapshot(self.redis, sid, SelectionsSnapshot(
                synced_at="2026-08-28T09:00:00+08:00", items=list(selections)))
        return sid

    def preview(self, sid, ops, *, csrf=CSRF, header=CSRF):
        self._install()  # module-global seams: last installer wins
        cookies = {"session_id": sid}
        if csrf is not None:
            cookies[csrf_cookie_name(sid)] = csrf
        headers = {} if header is None else {"X-CSRF-Token": header}
        return self.client.post("/api/write/preview", json={"ops": ops}, cookies=cookies, headers=headers)

    def close(self):
        self.client.__exit__(None, None, None)


def _add(code, priority):
    return {"action": "+", "course_id": code, "priority": priority}


def _drop(code, confirm=None):
    return {"action": "-", "course_id": code, "drop_confirm_text": confirm}


OPEN_SS = lambda: _load("studfun_open_ssform_provisional.html")
CLOSED = lambda: _load("studfun_closed_live_1151.html")
SS_FORM = lambda url: _load("ssform_provisional.html", "big5hkscs")

# ----------------------------------------------------------------- preview


async def scenario_preview() -> None:
    rig = Rig(OPEN_SS, SS_FORM)
    sid = await rig.session(selections=[_item("M3046243")])
    response = rig.preview(sid, [_add("GEAE2526", 1), _add("MEME101B", 2), _drop("M3046243", "M3046243")])
    body = response.json()

    _verdict(response.status_code == 200, "happy: 2 adds 1 drop(typed code) -> HTTP 200", f"status={response.status_code}")
    _verdict(body["writable"] is True, "happy: batch writable")
    _verdict([o["verdict"] for o in body["ops"]] == ["ok", "ok", "ok"], "happy: per-op verdicts ok")
    _verdict(body["canonical_ops"] == "-:M3046243:|+:GEAE2526:01|+:MEME101B:02",
             "happy: canonical_ops", body["canonical_ops"])

    expected = {
        "step": "2", "X1": "09", "X2": "0", "DEG_COD": "B", "college": "1", "dept": "36",
        "grade": "1", "SCH_COD": "2", "USE_YR": "115", "EDU": "B", "MAX_ADD": "15",
        "D1": "-", "C1": "M3046243", "T1": "",
        "D2": "+", "C2": "GEAE2526", "T2": "01",
        "D3": "+", "C3": "MEME101B", "T3": "02",
        "send": "提交",
    }
    for row in range(4, 16):
        expected[f"D{row}"], expected[f"C{row}"], expected[f"T{row}"] = "N", "", ""
    _verdict(body["payload"] == expected, "happy: payload preview deep-equal to expectation",
             f"{len(body['payload'])} keys" if body["payload"] == expected else f"mismatch: {body['payload']}")

    token = body["confirm_token"]
    record = json.loads(rig.redis.peek(f"confirm:{token}")) if token else None
    _verdict(bool(token), "happy: confirm_token minted", (token or "")[:24] + "...")
    _verdict(record is not None and record["student_no"] == STUDENT
             and record["canonical_ops"] == body["canonical_ops"]
             and record["variant"] == "ssform" and record["form_url"].endswith("ssform.asp?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"),
             "happy: confirm:{token} record fields")
    _verdict(rig.redis.remaining_ttl(f"confirm:{token}") == 300, "happy: confirm TTL == 300s")
    expect_hash = hashlib.sha256(f"{STUDENT}|{body['canonical_ops']}".encode()).hexdigest()
    _verdict(body["payload_hash"] == expect_hash, "happy: payload_hash == sha256(student_no|canonical_ops)")
    _verdict(body["warnings"] == ["quota_snapshot"] and body["quota_as_of"] == "2026-08-28T03:10:00+08:00",
             "happy: quota snapshot warnings (non-blocking)")

    rig.preview(sid, [_add("GEAE2526", 1)])
    _verdict(rig.studfun_calls == 2 and rig.form_calls == 2, "freshness: stage probed fresh on every preview",
             f"studfun={rig.studfun_calls} form={rig.form_calls}")
    rig.close()


# ----------------------------------------------------------------- invalid


async def scenario_invalid() -> None:
    rig = Rig(OPEN_SS, SS_FORM)

    sid = await rig.session()
    r = rig.preview(sid, [_add("NOSUCH01", 1)]).json()
    _verdict(r["ops"][0]["verdict"] == "無課號" and r["writable"] is False, "invalid#1 未知識別 -> verdict 無課號")

    rig.catalog["CODELESS"] = CourseInfo(course_id=str(uuid.uuid4()), code=None, class_time=())
    r = rig.preview(sid, [_add("CODELESS", 1)]).json()
    _verdict(r["ops"][0]["verdict"] == "無課號", "invalid#2 code 為 NULL -> verdict 無課號")

    rig2 = Rig(OPEN_SS, SS_FORM, catalog={
        "GEAE2526": _course("GEAE2526", ("", "", "23", "", "", "", "")), "M3046243": CATALOG["M3046243"]})
    sid2 = await rig2.session(selections=[_item("M3046243", times="三2,3,4")])
    r = rig2.preview(sid2, [_add("GEAE2526", 1)]).json()
    _verdict(r["ops"][0]["verdict"] == "衝堂" and r["ops"][0]["detail"] == "M3046243",
             "invalid#3 加選衝已選 -> verdict 衝堂 + the clashing code")

    rig.catalog["AAAA0001"] = _course("AAAA0001", ("45", "", "", "", "", "", ""))
    r = rig.preview(sid, [_add("GEAE2526", 1), _add("AAAA0001", 2)]).json()
    _verdict(r["ops"][1]["verdict"] == "衝堂" and r["ops"][1]["detail"] == "GEAE2526",
             "invalid#4 同批加選互衝 -> verdict 衝堂 detail=先前者")

    r = rig.preview(sid, [_drop("M3046243", "M3046243")]).json()
    _verdict(r["ops"][0]["verdict"] == "不在已選", "invalid#5 退選不在已選 -> verdict 不在已選")

    sid3 = await rig.session(selections=[_item("M3046243")])
    r = rig.preview(sid3, [_add("M3046243", 1), _drop("M3046243", "M3046243")]).json()
    _verdict([o["verdict"] for o in r["ops"]] == ["同批加退混雜", "同批加退混雜"],
             "invalid#6 同課同批 +- 混雜 -> both verdicts")

    cases = [
        (sid, [{"action": "+", "course_id": "GEAE2526"}], "priority_required", "invalid#7 加選缺志願"),
        (sid, [_drop("M3046243", "M3046243") | {"priority": 1}], "priority_forbidden", "invalid#8 退選帶志願"),
        (sid, [_add("GEAE2526", 21)], "priority_invalid", "invalid#9 志願 21 越界"),
        (sid, [_add("GEAE2526", 1), _add("MEME101B", 1)], "priority_duplicate", "invalid#10 志願重複"),
    ]
    for c_sid, ops, detail, label in cases:
        r = rig.preview(c_sid, ops)
        _verdict(r.status_code == 400 and r.json()["detail"] == detail, f"{label} -> 400 {detail}")

    bulk = dict(CATALOG)
    bulk.update({f"BULK{i:04d}": _course(f"BULK{i:04d}") for i in range(1, 17)})
    rig_b = Rig(OPEN_SS, SS_FORM, catalog=bulk)
    sid_b = await rig_b.session()
    r = rig_b.preview(sid_b, [_add(f"BULK{i:04d}", i) for i in range(1, 17)])
    _verdict(r.status_code == 400 and r.json()["detail"] == "ops_limit_exceeded",
             "invalid#11 16 ops > ssform 15 -> 400 ops_limit_exceeded")
    rig_b.close()

    r = rig.preview(sid3, [_drop("M3046243", "M3046244")])
    _verdict(r.status_code == 400 and r.json()["detail"] == "typed_confirmation_missing",
             "invalid#12 退選課號打錯 -> 400 typed_confirmation_missing")

    rig_closed = Rig(CLOSED)
    sid_c = await rig_closed.session()
    r = rig_closed.preview(sid_c, [_add("GEAE2526", 1)])
    _verdict(r.status_code == 409 and r.json()["detail"] == "stage_unavailable",
             "invalid#13 關閉階段 -> 409 stage_unavailable")
    rig_closed.close()

    rig_pre = Rig(OPEN_SS, lambda url: _load("ssform_prestep_provisional.html"))
    sid_p = await rig_pre.session()
    r = rig_pre.preview(sid_p, [_add("GEAE2526", 1)])
    _verdict(r.status_code == 409 and r.json()["need_confirmation"] is True,
             "invalid#14 必修確認前置 -> 409 need_confirmation")
    rig_pre.close()

    sid_e = await rig.session(with_jar=False)
    r = rig.preview(sid_e, [_add("GEAE2526", 1)])
    _verdict(r.status_code == 401 and r.json()["detail"] == "SELCRS_EXPIRED",
             "invalid#15 selcrs 逾時 -> 401 SELCRS_EXPIRED")

    rig_full = Rig(OPEN_SS, SS_FORM, catalog={
        "GEAE2526": _course("GEAE2526", ("34", "", "", "", "", "", ""), remaining=0)})
    sid_f = await rig_full.session()
    r = rig_full.preview(sid_f, [_add("GEAE2526", 1)]).json()
    _verdict(r["writable"] is True and r["ops"][0]["warnings"] == ["remaining_zero"],
             "invalid#16 名額快照為 0 -> warning 不阻擋")
    rig_full.close()
    rig.close()
    rig2.close()


# -------------------------------------------------------------------- csrf


async def scenario_csrf() -> None:
    rig = Rig(CLOSED)  # closed stage: a passed gate is visible as 409
    sid = await rig.session()

    r = rig.preview(sid, [_add("GEAE2526", 1)], header=None)
    _verdict(r.status_code == 403 and r.json()["detail"] == "csrf_failed" and rig.studfun_calls == 0,
             "csrf#1 X-CSRF-Token 缺 -> 403, school untouched")
    r = rig.preview(sid, [_add("GEAE2526", 1)], header="wrong-token")
    _verdict(r.status_code == 403 and rig.studfun_calls == 0, "csrf#2 token 不符 -> 403")
    r = rig.preview(sid, [_add("GEAE2526", 1)], header=CSRF)
    passed = r.status_code == 409 and rig.studfun_calls == 1
    slid = any(h.startswith(f"{csrf_cookie_name(sid)}={CSRF}") and "Max-Age=900" in h
               for h in r.headers.get_list("set-cookie"))
    _verdict(passed, "csrf#3 token 正確 -> gate 通過 (closed stage 409)")
    _verdict(slid, "csrf#4 通過後滑動續期 Max-Age=900")

    async def stub_login(student_no, password):
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", "QA14-COOKIE")
        return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)

    async def stub_record(factory, student_no):
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    auth_api.login_sso2 = stub_login
    auth_api.record_successful_login = stub_record
    login = rig.client.post("/api/auth/login", json={"student_no": STUDENT, "password": "qa14"})
    cookies = login.headers.get_list("set-cookie")
    new_sid = next(p[len("session_id="):] for h in cookies for p in h.split("; ") if p.startswith("session_id="))
    csrf_cookie = next((h for h in cookies if h.startswith(f"{csrf_cookie_name(new_sid)}=")), "")
    ok = (csrf_cookie and all(f in csrf_cookie for f in ("HttpOnly", "Secure", "SameSite=lax", "Max-Age=900")))
    token = login.json().get("csrf_token", "")
    _verdict(bool(ok), "csrf#5 login 發 csrf_{session_id} cookie (httpOnly+Secure+Lax+900s)")
    _verdict(bool(token) and csrf_cookie.split("; ")[0] == f"{csrf_cookie_name(new_sid)}={token}",
             "csrf#6 body 回顯 token == cookie 值 (httpOnly 下同源通道)")
    login2 = rig.client.post("/api/auth/login", json={"student_no": STUDENT, "password": "qa14"})
    _verdict(login2.json()["csrf_token"] != token, "csrf#7 重新登入 rotate")
    rig.close()


# ------------------------------------------------------------------ replay


async def scenario_replay() -> None:
    redis = FakeRedis()
    record = ConfirmRecord(
        student_no=STUDENT, canonical_ops="-:M3046243:|+:GEAE2526:01",
        variant="ssform", form_url="https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp?X1=09")
    await store_confirm(redis, "qa14-replay-token", record, ttl=300)
    first = await consume_confirm(redis, "qa14-replay-token")
    second = await consume_confirm(redis, "qa14-replay-token")
    _verdict(first == record, "replay#1 confirm 消費一次 -> record 取回")
    _verdict(second is None, "replay#2 第二次 consume -> None (todo15 對應 409)")

    ops = canonical_ops([CanonicalOp("-", "M3046243"), CanonicalOp("+", "GEAE2526", 1), CanonicalOp("+", "MEME101B", 20)])
    for name, builder, rows in (
        ("ssform_provisional.html", build_payload_ssprs, 15),
        ("saddstage5_provisional.html", build_payload_stage5, 10),
    ):
        html = _load(name, "big5hkscs")
        hidden = parse_form_hidden_inputs(html)
        payload = builder(ops[:2], {**hidden, "send": parse_send_value(html) or "提交"})
        verbatim = all(payload[key] == value for key, value in hidden.items())
        slot_keys = {f"{c}{i}" for i in range(1, rows + 1) for c in "DCT"}
        extras_ok = set(payload) - set(hidden) - {"send"} == slot_keys
        _verdict(verbatim and extras_ok, f"replay-integrity {name}: 非 D/C/T hidden 全數原樣通過",
                 f"{len(hidden)} hidden fields verbatim, {len(slot_keys)} slot keys owned")
    print(
        f"  proof: D1/C1/T1={payload['D1']}/{payload['C1']}/{payload['T1']!r}"
        f" D2/C2/T2={payload['D2']}/{payload['C2']}/{payload['T2']!r}"
    )


SCENARIOS = {
    "preview": scenario_preview,
    "invalid": scenario_invalid,
    "csrf": scenario_csrf,
    "replay": scenario_replay,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    args = parser.parse_args()
    import anyio

    anyio.run(SCENARIOS[args.scenario])
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)} failing checks)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
