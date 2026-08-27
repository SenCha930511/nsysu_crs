"""Interactive live-capture orchestrator for the 115-1 selection window (todo 4).

USER-RUN ONLY: run at your own keyboard, inside a selection window, with your
own student credentials. Credentials live in memory only for the login phase
and are never written to any file or log; the journal records cookie NAMES
(never values) and never the student id.

Flow (artifacts into backend/tests/fixtures/, conclusions into
docs/verified-facts.md under ``## live-verified (115-1 window)``, journal into
qa/04-capture.log):
  SSO2 login x2 (single-session probe) -> read-only captures (Studfun, active
  write form + ALL hidden inputs, slt_result) -> supervised write
  mini-protocol (2 real ADDs, carry-over + Referer probes, DROP restore) ->
  dplycourse course-code probe -> one deliberate wrong-password login.
Every real write gates on an explicit typed ``yes`` (see protocol.py).
"""

import getpass
import time
from pathlib import Path

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsError
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome
from scripts.capture.creds import Credentials
from scripts.capture.facts import ProbeResult, append_live_section
from scripts.capture.formparse import looks_like_login_page
from scripts.capture.protocol import (
    catalog_code_probe,
    read_only_captures,
    write_protocol,
)
from scripts.capture.runtime import (
    FACTS_PATH,
    FIXTURES_DIR,
    QA_DIR,
    SLT_RESULT_URL,
    Journal,
    LiveCtx,
    confirm,
    sso2_attempt,
)
from scripts.capture.windows import SelectionWindow


def _ttl_probe(ctx: LiveCtx) -> ProbeResult:
    probes = "、".join(f"t+{m}min={'活' if alive else '亡'}" for m, alive in ctx.liveness)
    alive_all = all(alive for _, alive in ctx.liveness)
    if alive_all:
        return ProbeResult("selcrs session TTL", "CONFIRMED",
                           f"觀測區間記錄：{probes}（僅代表本次會話觀測區間）")
    return ProbeResult("selcrs session TTL", "CONFIRMED", f"出現失效：{probes}")


async def _sso2_fail_capture(ctx: LiveCtx, student_no: str, results: list[ProbeResult]) -> None:
    print("\n最後一步：刻意的『錯誤密碼』登入 1 次（只為錄下學校失敗頁，僅 1 次）。")
    if not confirm("執行一次刻意的錯誤密碼 SSO2 登入"):
        ctx.journal.log("wrong-password capture skipped by user")
        return
    bad_password = getpass.getpass("請輸入一個『刻意的』錯誤密碼: ")
    try:
        outcome, raw, _jar = await sso2_attempt(student_no, bad_password)
    finally:
        del bad_password
    ctx.save("sso2_fail_1151", raw)
    marker_hit = FAILURE_MARKER in "".join(decode_body(raw).split())
    ctx.journal.log(f"wrong-password outcome={outcome}, marker {'FOUND' if marker_hit else 'MISSING'}")
    results.append(ProbeResult(
        "SSO2 成功/失敗標記", "CONFIRMED" if marker_hit else "UNVERIFIED",
        f"失敗頁 sso2_fail_1151.html outcome={outcome}，"
        f"標記「{FAILURE_MARKER}」{'命中' if marker_hit else '未命中（請人工檢視）'}"))


async def _login_phase(
    ctx: LiveCtx, results: list[ProbeResult], creds: Credentials | None = None
) -> str | None:
    """Two SSO2 logins (single-session probe). Returns the student_no, or None to abort."""
    if creds is not None:
        student_no, password = creds.student_id, creds.password
    else:
        student_no = getpass.getpass("學號（僅記憶體）: ").strip()
        password = getpass.getpass("選課密碼（僅記憶體）: ")
    ctx.t0 = time.monotonic()
    outcome1, _raw1, jar1 = await sso2_attempt(student_no, password)
    ctx.journal.log(f"SSO2 #1 outcome={outcome1}")
    if outcome1 is not Sso2Outcome.SUCCESS:
        ctx.journal.log("正確密碼的登入未成功 — 中止（若輸入錯誤請重新執行）。")
        return None
    ctx.journal.log("單 session 探測：立即第二次登入，再測第一顆 cookie 死活…")
    outcome2, _raw2, jar2 = await sso2_attempt(student_no, password)
    del password
    ctx.journal.log(f"SSO2 #2 outcome={outcome2}")
    if outcome2 is not Sso2Outcome.SUCCESS:
        ctx.journal.log("第二次登入未成功（學校可能限制連登）— 請稍候重跑。")
        return None
    probe_ctx = LiveCtx(window=ctx.window, fixtures_dir=ctx.fixtures_dir,
                        journal=ctx.journal, jar=jar1)
    first_alive = not looks_like_login_page(decode_body(await probe_ctx.get_page(SLT_RESULT_URL)))
    ctx.liveness.append((0.0, True))
    ctx.jar = jar1 if first_alive else jar2
    survivorship = "第一" if first_alive else "第二"
    verdict = ("仍然有效（學校允許並存 session）" if first_alive
               else "已失效（單一活躍 session：新登入取代舊的）")
    results.append(ProbeResult(
        "單 session 行為（連登兩次前者死活）", "CONFIRMED",
        f"第二次登入後第一顆 cookie {verdict}；後續錄製使用{survivorship}顆。"))
    return student_no


async def run_capture(
    window: SelectionWindow,
    *,
    fixtures_dir: Path = FIXTURES_DIR,
    qa_dir: Path = QA_DIR,
    facts_path: Path = FACTS_PATH,
    creds: Credentials | None = None,
) -> int:
    """Full interactive capture. Returns a process exit code."""
    journal = Journal()
    ctx = LiveCtx(window=window, fixtures_dir=fixtures_dir, journal=journal)
    results: list[ProbeResult] = []
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    try:
        journal.log(f"=== todo-4 live capture | window {window.name} ===")
        journal.log("學號與密碼僅存在於記憶體；任何檔案/log 都不會出現它們或 cookie 值。")
        student_no = await _login_phase(ctx, results, creds)
        if student_no is None:
            return 1
        await read_only_captures(ctx, results)
        if ctx.form_url:
            await write_protocol(ctx, results)
        else:
            journal.log("無啟用表單連結 — 略過寫入 mini-protocol。")
        results.append(await catalog_code_probe(ctx))
        await _sso2_fail_capture(ctx, student_no, results)
        results.append(_ttl_probe(ctx))
        append_live_section(facts_path, window.name, results)
        journal.log(f"verified facts updated ({len(results)} probes)。完成。")
        return 0
    except SelcrsError as exc:
        journal.log(f"學校端異常：{exc.detail} — 已保留已錄製之部分成果。")
        return 3
    finally:
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "04-capture.log").write_text("\n".join(journal.lines) + "\n", encoding="utf-8")
