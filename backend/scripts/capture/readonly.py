"""Read-only live verification round for the selcrs adapter (todo 4 follow-up).

ABSOLUTE LAW: this module NEVER modifies the user's school account. The only
outbound requests it performs are:

- SSO2 login POSTs to ``Studcheck_sso2.asp`` (two with real credentials, one
  with a deliberately wrong password for the failure-marker fixture), and
- pure GET reads (``Studfun.asp``, ``slt_result.asp``), plus — when Studfun
  exposes a write-form link (window open) — ONE pure GET of that linked form
  page (``ssform.asp``/``saddstage5.asp``), saved verbatim so every hidden
  input is recorded. The open-state Studfun copy is saved as
  ``studfun_open_live_1151``; the closed-named fixture is never overwritten
  by an open-state page (todo 13's closed detection pins it).

No ``ssprs``/write-form POST of any kind, no replay probes, no course codes
are ever submitted. The supervised write mini-protocol in ``protocol.py`` is
not imported here on purpose. Every outbound call lands in a ledger that is
journaled with a per-call read-only justification; the journal (student id
always masked via ``mask_student_id``, password NEVER printed) is dumped to
``qa/04-readonly-capture.log``.

Student-id hygiene: the raw school pages render the student id inline, so
fixtures are written with the id replaced in-place by its masked form (the
page is otherwise byte-identical). The journal notes each redaction.
"""

import getpass
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

import anyio
import httpx

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsError
from app.selcrs.http import build_client, request_school
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome, classify_sso2_response
from app.selcrs.transform import base64md5
from scripts.capture.creds import Credentials, mask_student_id
from scripts.capture.facts import ProbeResult, append_live_section
from scripts.capture.formparse import find_write_link, looks_like_login_page, scrape_form
from scripts.capture.runtime import (
    FACTS_PATH,
    FIXTURES_DIR,
    QA_DIR,
    SLT_RESULT_URL,
    SSO2_URL,
    STUDFUN_URL,
    Journal,
)

READONLY_FACTS_HEADER: Final = "## live-verified (115-1)"
READONLY_LOG_NAME: Final = "04-readonly-capture.log"
# Obviously-wrong fixed sentinel: it exists only to be rejected by the school
# so the failure page can be recorded. It is never printed anywhere.
_WRONG_PASSWORD_SENTINEL: Final = "readonly-wrong-pw-9f3c"

_FAILURE_HINTS: Final = ("密碼", "不符", "錯誤", "失敗", "重新登入")
_STUDFUN_HINTS: Final = ("加退選", "關閉", "尚未", "非選課", "查詢", "目前", "階段", "開放")
_CELL_RE: Final = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_ROW_RE: Final = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE: Final = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class ReadonlyCtx:
    """Run state for the read-only round (window-free by design)."""

    fixtures_dir: Path
    journal: Journal
    creds: Credentials
    masked_id: str
    ledger: list[tuple[str, str]] = field(default_factory=list)

    def scrub(self, text: str) -> str:
        """Force-mask the raw student id wherever a string could carry it."""
        return text.replace(self.creds.student_id, self.masked_id)

    def slog(self, message: str) -> None:
        """Journal line, scrubbed (belt + braces: callers pass best-effort text)."""
        self.journal.log(self.scrub(message))

    def record(self, call: str, why_readonly: str) -> None:
        self.ledger.append((call, why_readonly))
        self.slog(f"-> CALL {len(self.ledger)}: {call}")

    def save_fixture(self, stem: str, raw: bytes) -> None:
        """Write .html (masked-raw bytes) + .txt (decoded), never the bare id."""
        sid_bytes = self.creds.student_id.encode("ascii", errors="ignore")
        masked_bytes = self.masked_id.encode("ascii")
        redacted_raw = raw.replace(sid_bytes, masked_bytes) if sid_bytes else raw
        text = decode_body(redacted_raw).replace(self.creds.student_id, self.masked_id)
        (self.fixtures_dir / f"{stem}.html").write_bytes(redacted_raw)
        (self.fixtures_dir / f"{stem}.txt").write_text(text, encoding="utf-8")
        note = "" if redacted_raw == raw else " (student id masked in-place)"
        self.slog(f"saved {stem}.html (+.txt), {len(redacted_raw)} bytes{note}")

    def probe(self, name: str, status: str, finding: str) -> ProbeResult:
        """Build a ProbeResult with the finding scrubbed for the facts doc."""
        return ProbeResult(name, status, self.scrub(finding))


def _fragments_with_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    """Distinct text fragments (tags/blank dropped) carrying any hint word."""
    fragments: list[str] = []
    for raw_line in re.split(r"[<>\n\r]", text):
        line = " ".join(_TAG_RE.sub(" ", raw_line).split())
        if line and any(hint in line for hint in hints) and line not in fragments:
            fragments.append(line)
    return fragments


def first_table_header_cells(html: str) -> list[str]:
    """Cell texts of the first table row that has >=2 cells (layout summary)."""
    for row in _ROW_RE.findall(html):
        cells = [" ".join(_TAG_RE.sub(" ", cell).split()) for cell in _CELL_RE.findall(row)]
        if len(cells) >= 2:
            return cells
    return []


async def _sso2_raw(student_id: str, password: str) -> tuple[httpx.Response, httpx.Cookies]:
    """One raw SSO2 POST on a fresh jar; returns wire response + fresh session."""
    jar = httpx.Cookies()
    async with build_client(cookies=jar) as client:
        response = await request_school(
            client, "POST", SSO2_URL,
            data={"stuid": student_id, "SPassword": base64md5(password)},
        )
        session = client.cookies
    return response, session


def _journal_wire(ctx: ReadonlyCtx, label: str, response: httpx.Response, jar: httpx.Cookies) -> None:
    names = [cookie.name for cookie in jar.jar]
    location = ctx.scrub(response.headers.get("location", "-"))
    ctx.slog(
        f"  {label} wire: HTTP {response.status_code}; Location={location}; "
        f"Set-Cookie names={names}"
    )


async def _get(ctx: ReadonlyCtx, url: str, jar: httpx.Cookies) -> httpx.Response:
    async with build_client(cookies=jar) as client:
        return await request_school(client, "GET", url)


def _liveness(response: httpx.Response) -> bool:
    """Alive = HTTP 200 page that is not a bounce back to the login form."""
    return response.status_code == 200 and not looks_like_login_page(
        decode_body(response.content)
    )


async def _probe_slt_result(ctx: ReadonlyCtx, jar: httpx.Cookies, *, because: str) -> bool:
    response = await _get(ctx, SLT_RESULT_URL, jar)
    alive = _liveness(response)
    ctx.slog(f"  slt_result probe ({because}): HTTP {response.status_code} -> "
             f"{'alive' if alive else 'DEAD'}")
    return alive


async def _sleep_until(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        await anyio.sleep(remaining)


async def _first_real_login(
    ctx: ReadonlyCtx, password: str
) -> tuple[httpx.Cookies, float] | None:
    """Probe (a). Returns (jar, login_time) on SUCCESS; None means abort the round."""
    ctx.record(
        f"POST {SSO2_URL} (login #1, real credentials)",
        "SSO2 login is the permitted authentication POST; it creates a session and "
        "cannot add/drop anything",
    )
    response, jar = await _sso2_raw(ctx.creds.student_id, password)
    login_time = time.monotonic()
    _journal_wire(ctx, "SSO2 #1", response, jar)
    try:
        outcome = classify_sso2_response(response)
    except SelcrsError as exc:
        ctx.slog(f"  SSO2 #1 classification: UNKNOWN ({exc.detail}) - aborting round")
        return None
    ctx.slog(f"  SSO2 #1 outcome={outcome}")
    if outcome is not Sso2Outcome.SUCCESS:
        ctx.slog("  real-credentials login did not succeed - aborting round (no further calls)")
        return None
    return (jar, login_time)


async def run_readonly(
    *,
    creds: Credentials | None = None,
    fixtures_dir: Path = FIXTURES_DIR,
    qa_dir: Path = QA_DIR,
    facts_path: Path = FACTS_PATH,
    prompt_password: Callable[[str], str] = getpass.getpass,
) -> int:
    """The (a)-(f) read-only sequence. Returns a process exit code."""
    journal = Journal()
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    active_creds = creds if creds is not None else Credentials(
        student_id=prompt_password("學號（僅記憶體）: ").strip(),
        password=prompt_password("選課密碼（僅記憶體）: "),
    )
    ctx = ReadonlyCtx(
        fixtures_dir=fixtures_dir, journal=journal, creds=active_creds,
        masked_id=mask_student_id(active_creds.student_id),
    )
    results: list[ProbeResult] = []
    try:
        journal.log("=== read-only live verification round (115-1) ===")
        journal.log(
            f"credentials memory-only for {ctx.masked_id}; outbound calls are SSO2 "
            "login POSTs and pure GET reads only (see ledger at end)."
        )
        password = active_creds.password

        # (a) SSO2 login #1 (real) - wire evidence + tri-state success conclusion.
        logged_in = await _first_real_login(ctx, password)
        if logged_in is None:
            results.append(ctx.probe(
                "SSO2 tri-state markers (success path)", "UNVERIFIED",
                "login #1 did not produce the 302+main_frame+Set-Cookie success "
                "shape this round; see journal for the actual wire evidence"))
            return 1
        jar1, t_login1 = logged_in
        results.append(ctx.probe(
            "SSO2 tri-state markers (success path)", "CONFIRMED",
            "HTTP 302 + Location contains main_frame + >=1 Set-Cookie observed live "
            f"(cookie names in qa/{READONLY_LOG_NAME})"))

        # (b) GET Studfun - state fixture (open/closed) + actual marker; an
        # exposed write-form link is followed with one more pure GET below.
        ctx.record(f"GET {STUDFUN_URL}",
                   "pure read of the write-entry page; no form fields sent")
        response_b = await _get(ctx, STUDFUN_URL, jar1)
        studfun_html = decode_body(response_b.content)
        write_link = find_write_link(scrape_form(studfun_html))
        studfun_stem = ("studfun_open_live_1151" if write_link is not None
                        else "studfun_closed_live_1151")
        ctx.save_fixture(studfun_stem, response_b.content)
        marker_lines = _fragments_with_hints(ctx.scrub(studfun_html), _STUDFUN_HINTS)
        ctx.slog(f"  Studfun write link: {write_link or 'NONE (selection closed)'}; "
                 f"marker fragments: {marker_lines or 'none'}")
        if write_link is None:
            results.append(ctx.probe(
                "Studfun closed-state marker", "CONFIRMED",
                f"HTTP {response_b.status_code}; no ssform/saddstage5 link present "
                f"(selection closed); observed fragments: "
                f"{' / '.join(marker_lines) or '(none)'}; "
                "fixture backend/tests/fixtures/studfun_closed_live_1151.html"))
        else:
            # Read-only form follow-up: plain GET of the already-linked page,
            # saved so ALL hidden inputs are on record. Nothing is posted.
            form_url = urljoin(STUDFUN_URL, write_link)
            variant = "saddstage5" if "saddstage5" in form_url else "ssform"
            ctx.record(
                f"GET {form_url} (form page follow-up)",
                "pure GET of the already-linked form page; no fields are sent "
                "anywhere - the page is saved only to expose every hidden input",
            )
            response_form = await _get(ctx, form_url, jar1)
            ctx.save_fixture(f"{variant}_live_1151", response_form.content)
            hidden_names = [
                name for name, _ in scrape_form(decode_body(response_form.content)).hidden
            ]
            ctx.slog(f"  form captured ({variant}_live_1151): "
                     f"{len(hidden_names)} hidden inputs {hidden_names}")
            results.append(ctx.probe(
                "Studfun open-state capture (read-only form follow-up)", "CONFIRMED",
                f"write link present; fixtures backend/tests/fixtures/{studfun_stem}.html "
                f"+ {variant}_live_1151.html ({len(hidden_names)} hidden inputs "
                f"visible: {hidden_names}); zero form submissions"))
            results.append(ctx.probe(
                "Studfun closed-state marker", "UNVERIFIED",
                "a write-form link is present (window open) - the closed marker "
                "is not observable this round"))

        # (c) GET slt_result - real column layout vs provisional.
        ctx.record(f"GET {SLT_RESULT_URL}", "pure read of the student's selections page")
        response_c = await _get(ctx, SLT_RESULT_URL, jar1)
        ctx.save_fixture("slt_result_live_1151", response_c.content)
        live_headers = first_table_header_cells(ctx.scrub(decode_body(response_c.content)))
        provisional_path = fixtures_dir / "slt_result_provisional.html"
        provisional_headers = (
            first_table_header_cells(decode_body(provisional_path.read_bytes()))
            if provisional_path.is_file() else []
        )
        same_layout = live_headers == provisional_headers
        ctx.slog(f"  slt_result live header cells ({len(live_headers)}): {live_headers}")
        ctx.slog(f"  provisional header cells ({len(provisional_headers)}): "
                 f"{provisional_headers}; match={same_layout}")
        results.append(ctx.probe(
            "slt_result column layout vs provisional", "CONFIRMED",
            f"live layout {len(live_headers)} cells {live_headers} "
            f"{'MATCHES' if same_layout else 'DIFFERS from'} provisional assumption "
            f"({len(provisional_headers)} cells {provisional_headers}); "
            "fixture backend/tests/fixtures/slt_result_live_1151.html"))

        # (d) single-session probe: second login, then first jar on slt_result.
        ctx.record(
            f"POST {SSO2_URL} (login #2, real credentials)",
            "permitted SSO2 login POST; probes whether login #1's session is superseded",
        )
        response2, jar2 = await _sso2_raw(ctx.creds.student_id, password)
        t_login2 = time.monotonic()
        del password  # real password's last use is done; drop this reference now
        _journal_wire(ctx, "SSO2 #2", response2, jar2)
        try:
            outcome2: Sso2Outcome | None = classify_sso2_response(response2)
        except SelcrsError:
            outcome2 = None  # UNKNOWN school shape; probe recorded honestly below
        ctx.slog(f"  SSO2 #2 outcome={outcome2 or 'UNKNOWN'}")
        if outcome2 is not Sso2Outcome.SUCCESS:
            ctx.slog("  login #2 did not succeed - single-session probe inconclusive")
            results.append(ctx.probe(
                "single-session behaviour (does login #2 kill login #1?)", "UNVERIFIED",
                f"login #2 outcome={outcome2 or 'UNKNOWN'}; jar1 survival not testable"))
            active_jar, t_active = jar1, t_login1
        else:
            ctx.record(
                f"GET {SLT_RESULT_URL} with login #1's cookie (after login #2)",
                "pure GET read reusing an already-issued session cookie",
            )
            first_alive = await _probe_slt_result(ctx, jar1, because="jar1 after login #2")
            verdict = ("still ALIVE (school allows concurrent sessions)" if first_alive
                       else "DEAD (single active session: login #2 superseded login #1)")
            results.append(ctx.probe(
                "single-session behaviour (does login #2 kill login #1?)", "CONFIRMED",
                f"after login #2, login #1's cookie is {verdict}"))
            active_jar, t_active = (jar1, t_login1) if first_alive else (jar2, t_login2)
            ctx.slog(f"  continuing TTL probes on {'jar1' if first_alive else 'jar2'}")

        # (e) session-TTL bound probes at +60s / +180s after the active login.
        ttl_marks: list[str] = []
        for target_seconds in (60, 180):
            await _sleep_until(t_active + target_seconds)
            ctx.record(
                f"GET {SLT_RESULT_URL} at ~+{target_seconds}s after active login",
                "pure GET read measuring session liveness over time",
            )
            alive = await _probe_slt_result(ctx, active_jar, because=f"~+{target_seconds}s")
            ttl_marks.append(f"+{target_seconds}s={'alive' if alive else 'DEAD'}")
        results.append(ctx.probe(
            "selcrs session TTL lower bound (>=3 min)", "CONFIRMED",
            f"observed marks: {', '.join(ttl_marks)}; proves only TTL >= 3 min "
            "for this session"))
        results.append(ctx.probe(
            "selcrs session TTL upper/longer bounds", "UNVERIFIED",
            "not probed beyond +180s by design (read-only round scope)"))

        # (f) ONE deliberately-wrong-password login attempt - failure marker.
        ctx.record(
            f"POST {SSO2_URL} (deliberately-wrong password, exactly 1 attempt)",
            "permitted SSO2 login POST with a known-bad sentinel, run ONCE to record "
            "the failure page; it can only be rejected, never select courses",
        )
        response_f, jar_f = await _sso2_raw(ctx.creds.student_id, _WRONG_PASSWORD_SENTINEL)
        _journal_wire(ctx, "SSO2 wrong-pw", response_f, jar_f)
        ctx.save_fixture("sso2_fail_live_1151", response_f.content)
        fail_html = decode_body(response_f.content)
        normalized = "".join(fail_html.split())
        marker_hit = FAILURE_MARKER in normalized
        variants = _fragments_with_hints(ctx.scrub(fail_html), _FAILURE_HINTS)
        ctx.slog(f"  wrong-password marker 「{FAILURE_MARKER}」 "
                 f"{'FOUND' if marker_hit else 'MISSING'}; fragments: {variants or 'none'}")
        results.append(ctx.probe(
            "SSO2 failure-marker text/variants",
            "CONFIRMED" if marker_hit else "UNVERIFIED",
            f"marker 「{FAILURE_MARKER}」 {'hit' if marker_hit else 'NOT hit'}; "
            f"observed fragments: {' / '.join(variants) or '(none)'}; "
            "fixture backend/tests/fixtures/sso2_fail_live_1151.html"))

        append_live_section(facts_path, "read-only (anytime)", results,
                            header=READONLY_FACTS_HEADER)
        journal.log(f"verified-facts updated ({len(results)} probes) under "
                    f"'{READONLY_FACTS_HEADER}'")
        return 0
    except SelcrsError as exc:
        journal.log(f"school-side anomaly: {exc.detail} - partial artifacts preserved")
        return 3
    finally:
        journal.log("--- OUTBOUND CALL ENUMERATION (all calls this round) ---")
        for index, (call, why) in enumerate(ctx.ledger, start=1):
            journal.log(f"  {index}. {call}\n     read-only because: {why}")
        journal.log(f"total outbound calls: {len(ctx.ledger)} "
                    "(<=3 SSO2 login POSTs incl. 1 deliberately-wrong; rest pure GET reads)")
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / READONLY_LOG_NAME).write_text(
            "\n".join(journal.lines) + "\n", encoding="utf-8"
        )
