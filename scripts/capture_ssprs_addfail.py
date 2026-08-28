#!/usr/bin/env python3
"""One-shot live capture of the REAL ssprs failure response (todo-15 gap).

The 10:04 live probe proved login -> preview(200) -> submit(202) -> worker ->
job DONE end-to-end, but the per-op outcome came back ``parse_failed`` because
``app.write.response`` was built against synthetic ``provisional`` fixtures.
This script records the REAL reply to ONE impossible ADD (the nonexistent
school code ZZ999999), so the parser can be rebuilt against recorded fact.

Safety contract (ABSOLUTE LAW, same as scripts/send_probe.py):
- Exactly ONE POST is sent: add the NONEXISTENT school code ZZ999999. The
  school can only reject it, so the run is read-equivalent for the user's
  real selections - nothing real can change, so nothing needs restoring.
- Credentials come from --creds-env (STUDENT_ID/SPASSWORD file outside the
  repo, chmod 600) via the capture kit; the password stays memory-only and
  is deleted right after the one SSO2 login.
- The window guard applies: outside a selection window the school serves no
  write form and the script refuses.
- The student id is masked (M153****24) inside BOTH artifacts before they
  are written (byte-level replace; the id is ASCII so this is byte-safe).
  Cookie VALUES and the password are never printed or saved.

Artifacts (canonical live fixture, superseding the provisional ones):
    backend/tests/fixtures/ssprs_resp_addfail_live_1151.html  raw bytes
    backend/tests/fixtures/ssprs_resp_addfail_live_1151.txt   decode_body() text
    backend/tests/fixtures/ssprs_post_body_addfail_live_1151.txt  sent wire body

Run inside a selection window against the school directly (no compose needed):
    uv run --python 3.12 --project backend python scripts/capture_ssprs_addfail.py \
      --creds-env /path/to/creds.env

Exit codes: 0 captured; 1 flow error (login failed / no write form link /
non-ssprs variant); 2 not inside a selection window; 4 creds rejected.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import anyio  # noqa: E402

from app.selcrs.decode import decode_body  # noqa: E402
from app.selcrs.sso2 import Sso2Outcome  # noqa: E402
from scripts.capture.creds import (  # noqa: E402
    CredentialsRejected,
    load_credentials,
    mask_student_id,
)
from scripts.capture.formparse import (  # noqa: E402
    build_submit_body,
    find_write_link,
    scrape_form,
)
from scripts.capture.runtime import (  # noqa: E402
    FIXTURES_DIR,
    STUDFUN_URL,
    Journal,
    LiveCtx,
    sso2_attempt,
)
from scripts.capture.windows import (  # noqa: E402
    TAIPEI,
    active_window,
    refusal_text,
)

PROBE_CODE = "ZZ999999"
FIXTURE_STEM = "ssprs_resp_addfail_live_1151"
POST_BODY_STEM = "ssprs_post_body_addfail_live_1151"

#: Diagnostic marker scan only (the rebuilt parser owns classification).
_SCAN_MARKERS = (
    "成功",
    "失敗",
    "查無",
    "無此課程",
    "額滿",
    "衝堂",
    "已選",
    "重複",
    "必修",
    "找不到",
)


def _mask_bytes(raw: bytes, student_id: str, masked: str) -> bytes:
    """Byte-level student-id mask (the id is ASCII on every selcrs page)."""
    return raw.replace(student_id.encode("ascii"), masked.encode("ascii"))


async def _capture(creds_env: Path) -> int:
    journal = Journal()
    moment = datetime.now(TAIPEI)
    window = active_window(moment)
    if window is None:
        print(refusal_text(moment))
        return 2
    try:
        creds = load_credentials(creds_env, repo_root=REPO_ROOT)
    except CredentialsRejected as exc:
        print(f"[CREDS] Refusing: {exc}", file=sys.stderr)
        return 4
    masked = mask_student_id(creds.student_id)
    journal.log(f"=== todo-15 ssprs add-fail live capture | window {window.name} | student {masked} ===")
    journal.log("ONE POST only: D1=+ C1=ZZ999999 T1=01 (nonexistent code; the school can only say no).")

    student_id = creds.student_id  # kept ONLY for the post-response byte mask
    outcome, _login_raw, jar = await sso2_attempt(student_id, creds.password)
    del creds
    journal.log(f"SSO2 outcome={outcome}")
    if outcome is not Sso2Outcome.SUCCESS:
        journal.log("login did not succeed - aborting; no write attempted")
        return 1

    ctx = LiveCtx(window=window, fixtures_dir=FIXTURES_DIR, journal=journal, jar=jar)
    ctx.t0 = time.monotonic()

    studfun_raw = await ctx.get_page(STUDFUN_URL)
    ctx.mark_liveness(studfun_raw)
    link = find_write_link(scrape_form(decode_body(studfun_raw)))
    if link is None:
        journal.log("no active write form link on Studfun - aborting; no write attempted")
        return 1
    if "ssform.asp" not in link:
        journal.log("active write form is NOT the ssform 加退選 variant - this capture pins "
                    "the ssprs response, so it aborts without writing")
        return 1
    ctx.form_url = urljoin(STUDFUN_URL, link)
    journal.log(f"write form URL: {ctx.form_url}")

    # Replay model: fresh same-session GET of the form right before the POST.
    form_raw = await ctx.get_page(ctx.form_url)
    ctx.mark_liveness(form_raw)
    form = scrape_form(decode_body(form_raw))
    # LIVE-VERIFIED (ssform_live_1151.html): the form's STATIC action is the
    # 暫存/draft endpoint (ssform.asp); the real 送出 submit is pinned by the
    # 送出 button's onclick JS: step=2 + f1.action='ssprs.asp'. Posting to the
    # static action re-renders the form (that is what broke the 10:04 probe).
    ctx.submit_url = urljoin(ctx.form_url, "ssprs.asp")
    journal.log(f"submit URL: {ctx.submit_url} (live-verified: 送出 button pins f1.action)")

    # Browser-faithful 送出 body: hidden verbatim except step=2, D/C/T row 1
    # carrying the op, rest rows N + cleared (what Validator()-passing JS sends).
    hidden_map = dict(form.hidden)
    rows_raw = hidden_map.get("MAX_ADD", "15")
    rows = int(rows_raw) if rows_raw.isdigit() else 15
    overrides: list[tuple[str, str]] = [("D1", "+"), ("C1", PROBE_CODE), ("T1", "01")]
    for row in range(2, rows + 1):
        overrides.extend([(f"D{row}", "N"), (f"C{row}", ""), (f"T{row}", "")])
    overrides.extend([("step", "2"), ("send", "提交")])
    body = build_submit_body(form.hidden, overrides)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / f"{POST_BODY_STEM}.txt").write_text(body, encoding="utf-8")
    journal.log(f"saved {POST_BODY_STEM}.txt (D/C/T replay body)")

    response = await ctx.post_form(body, referer=ctx.form_url)
    ctx.mark_liveness(response)

    # Mask BEFORE the bytes hit disk; the decoded text derives from the
    # already-masked bytes so the raw id never exists on disk.
    masked_raw = _mask_bytes(response, student_id, masked)
    del student_id
    (FIXTURES_DIR / f"{FIXTURE_STEM}.html").write_bytes(masked_raw)
    text = decode_body(masked_raw)
    (FIXTURES_DIR / f"{FIXTURE_STEM}.txt").write_text(text, encoding="utf-8")
    journal.log(f"saved {FIXTURE_STEM}.html (+.txt), {len(masked_raw)} bytes, id masked")

    hits = [m for m in _SCAN_MARKERS if m in text]
    journal.log(
        f"diagnostics: code-in-response={PROBE_CODE in text}; markers={hits or 'NONE'}"
    )
    journal.log("capture complete - rebuild the parser against this fixture.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--creds-env",
        type=Path,
        required=True,
        help="STUDENT_ID/SPASSWORD env file (outside the repo, chmod 600)",
    )
    args = parser.parse_args()
    return anyio.run(_capture, args.creds_env)


if __name__ == "__main__":
    raise SystemExit(main())
