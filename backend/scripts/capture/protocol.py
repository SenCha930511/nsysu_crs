"""Supervised write mini-protocol + probes for the live capture kit (todo 4).

Every step that touches the school with a real write gates on ``confirm()`` -
a literal typed ``yes`` from the user at the keyboard. Artifact conventions:
raw bytes as .html plus big5hkscs-decoded .txt, POST wire bodies as .txt.
"""

import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from app.selcrs.decode import decode_body
from app.selcrs.endpoints import CatalogQuery, fetch_catalog_page, fetch_validcode
from app.selcrs.errors import SelcrsError
from scripts.capture.facts import ProbeResult
from scripts.capture.formparse import build_submit_body, find_write_link, scrape_form
from scripts.capture.runtime import (
    SLT_RESULT_URL,
    STUDFUN_URL,
    LiveCtx,
    confirm,
)

COURSE_CODE_RE = re.compile(r"\b[A-Za-z0-9]{8}\b")
_ACCEPT_HINTS = ("成功", "完成", "已選", "重複")
_REJECT_HINTS = ("逾期", "失效", "錯誤", "重新登入", "操作")


def _submit_verdict(text: str) -> str:
    """Best-effort keyword reading of an ssprs response; human-reviewable."""
    accepts = [word for word in _ACCEPT_HINTS if word in text]
    rejects = [word for word in _REJECT_HINTS if word in text]
    if accepts and not rejects:
        return f"looks server-PROCESSED (markers: {'/'.join(accepts)})"
    if rejects:
        return f"looks REJECTED (markers: {'/'.join(rejects)})"
    return "no recognisable marker - read the saved response to judge"


async def read_only_captures(ctx: LiveCtx, results: list[ProbeResult]) -> None:
    """Studfun -> active form (+ALL hidden inputs) -> slt_result; prestep probe."""
    studfun_raw = await ctx.get_page(STUDFUN_URL)
    ctx.save("studfun_1151", studfun_raw)
    ctx.mark_liveness(studfun_raw)
    write_href = find_write_link(scrape_form(decode_body(studfun_raw)))
    ctx.journal.log(f"Studfun write link: {write_href or 'NONE - stage closed or unrecognized'}")
    if write_href is None:
        for probe in ("必修課程確認前置", "GET→POST carry-over", "Referer necessity"):
            results.append(ProbeResult(probe, "UNVERIFIED", "Studfun 無啟用之寫入表單連結"))
        return
    ctx.form_url = urljoin(STUDFUN_URL, write_href)
    variant = "saddstage5" if "saddstage5" in ctx.form_url else "ssform"
    form_raw = await ctx.get_page(ctx.form_url)
    ctx.save(f"{variant}_1151", form_raw)
    form_html = decode_body(form_raw)
    form = scrape_form(form_html)
    ctx.journal.log(f"write form ({variant}): hidden={[name for name, _ in form.hidden]}, "
                    f"actions={form.form_actions}")
    prestep = "必修" in form_html and "確認" in form_html
    results.append(ProbeResult(
        "必修課程確認前置", "CONFIRMED",
        f"表單頁{'出現' if prestep else '未見'}必修確認標記（{variant}_1151.html）"))
    if form.form_actions:
        ctx.submit_url = urljoin(ctx.form_url, form.form_actions[0])
    else:
        ctx.submit_url = ctx.form_url.replace("ssform.asp", "ssprs.asp").replace(
            "saddstage5.asp", "saddstage5prs.asp")
    ctx.journal.log(f"submit URL: {ctx.submit_url}")
    ctx.save("slt_result_1151", await ctx.get_page(SLT_RESULT_URL))


async def _fresh_submit_body(ctx: LiveCtx, overrides: list[tuple[str, str]]) -> str:
    """GET the form again in-session, then rebuild the replay body."""
    fresh_html = decode_body(await ctx.get_page(ctx.form_url))
    return build_submit_body(scrape_form(fresh_html).hidden, overrides)


async def _real_add(ctx: LiveCtx, tag: str, course_code: str) -> str | None:
    """One real ADD with fresh form-replay. Returns the sent body, or None."""
    if not confirm(f"真實加選 {tag}: D1=+ C1={course_code}"):
        ctx.journal.log(f"ADD {tag} skipped by user")
        return None
    body = await _fresh_submit_body(ctx, [("D1", "+"), ("C1", course_code), ("send", "提交")])
    (ctx.fixtures_dir / f"ssprs_post_body_{tag}.txt").write_text(body, encoding="utf-8")
    response = await ctx.post_form(body, referer=ctx.form_url)
    ctx.save(f"ssprs_resp_{tag}", response)
    ctx.mark_liveness(response)
    ctx.journal.log(f"ADD {tag}: server {_submit_verdict(decode_body(response))}")
    return body


async def _carry_over_probe(ctx: LiveCtx, body: str) -> ProbeResult:
    """Fresh GET form, then replay an OLD body verbatim: token/carry-over check."""
    if not confirm("陰性探測：新 GET 表單後『原樣重放』第一次的 POST body"):
        return ProbeResult("GET→POST carry-over", "UNVERIFIED", "探測被使用者略過")
    await ctx.get_page(ctx.form_url)  # spend a fresh GET; body below is the OLD one
    response = await ctx.post_form(body, referer=ctx.form_url)
    ctx.save("ssprs_resp_carryover", response)
    verdict = _submit_verdict(decode_body(response))
    ctx.journal.log(f"carry-over: server {verdict}")
    return ProbeResult("GET→POST carry-over", "UNVERIFIED",
                       f"重放第一次 body 的回應已存 ssprs_resp_carryover.html；{verdict}")


async def _no_referer_probe(ctx: LiveCtx, course_code: str) -> ProbeResult:
    """Resend one POST with the Referer header stripped."""
    if not confirm("Referer 探測：去 Referer 標頭重送一次加選 POST"):
        return ProbeResult("Referer necessity", "UNVERIFIED", "探測被使用者略過")
    body = await _fresh_submit_body(ctx, [("D1", "+"), ("C1", course_code), ("send", "提交")])
    response = await ctx.post_form(body, referer=None)
    ctx.save("ssprs_resp_noreferer", response)
    verdict = _submit_verdict(decode_body(response))
    ctx.journal.log(f"no-Referer: server {verdict}")
    status = "UNVERIFIED" if "no recognisable" in verdict else "CONFIRMED"
    return ProbeResult("Referer necessity", status,
                       f"無 Referer 之 POST 回應已存 ssprs_resp_noreferer.html；{verdict}")


async def _restore_drop(ctx: LiveCtx, course_code: str) -> None:
    if not confirm(f"復原退選: D1=- C1={course_code}（請勿略過，否則課程留在加選狀態）"):
        ctx.journal.log("WARNING: drop skipped by user - course may remain added!")
        return
    body = await _fresh_submit_body(ctx, [("D1", "-"), ("C1", course_code), ("send", "提交")])
    ctx.save("ssprs_resp_drop", await ctx.post_form(body, referer=ctx.form_url))
    ctx.save("slt_result_after_drop", await ctx.get_page(SLT_RESULT_URL))
    ctx.journal.log("DROP sent; slt_result_after_drop saved - 請目視確認已復原")


async def catalog_code_probe(ctx: LiveCtx) -> ProbeResult:
    """Does a dplycourse row carry the 8-char course code? (decides courses.code source)"""
    if not confirm("dplycourse 課號欄探測（會請你手動辨識一個驗證碼圖）"):
        return ProbeResult("dplycourse 8 碼課號欄", "UNVERIFIED", "探測被使用者略過")
    try:
        captcha = await fetch_validcode()
        image_path = Path(tempfile.mkstemp(prefix="capture-validcode-", suffix=".bmp")[1])
        image_path.write_bytes(captcha.image_bytes)
        print(f"驗證碼圖片已存: {image_path}（請用看圖工具開啟辨識）")
        solved = input("ValidCode: ").strip()
        page = await fetch_catalog_page(
            CatalogQuery(year_sem="1151"), validcode=solved, cookies=captcha.cookies
        )
    except SelcrsError as exc:
        ctx.journal.log(f"catalog probe failed: {exc.detail}")
        return ProbeResult("dplycourse 8 碼課號欄", "UNVERIFIED", f"探測失敗: {exc.detail}")
    (ctx.fixtures_dir / "dply_probe.txt").write_text(page, encoding="utf-8")
    matches = COURSE_CODE_RE.findall(page)
    ctx.journal.log(f"dplycourse probe: {len(matches)} 8-char code candidates")
    if not matches:
        return ProbeResult("dplycourse 8 碼課號欄", "UNVERIFIED",
                           "抽查頁未見 8 碼課號（dply_probe.txt），可能依查詢條件而異")
    return ProbeResult("dplycourse 8 碼課號欄", "CONFIRMED",
                       f"抽查頁含 {len(matches)} 個 8 碼候選（樣本: {', '.join(matches[:5])}；dply_probe.txt）")


async def write_protocol(ctx: LiveCtx, results: list[ProbeResult]) -> None:
    print("\n寫入 mini-protocol（每一步真實寫入前都會要求你輸入 yes）:")
    print("  1) 真實加選 #1（同 session 重取表單→重放 hidden→D1=+ C1=<課號>→POST）")
    print("  2) 真實加選 #2（用於 diff 參數是否隨請求旋轉）")
    print("  3) 陰性 carry-over 探測（新 GET 後原樣重放 #1 body）")
    print("  4) Referer 探測（去 Referer 重送一次）")
    print("  5) 復原退選（D1=- C1=<課號>）")
    course_code = input("\n請輸入一門『便宜可逆』課程的課號（將加選後再退選復原）: ").strip()
    body1 = await _real_add(ctx, "1", course_code)
    await _real_add(ctx, "2", course_code)
    if body1 is not None:
        results.append(await _carry_over_probe(ctx, body1))
    results.append(await _no_referer_probe(ctx, course_code))
    await _restore_drop(ctx, course_code)
