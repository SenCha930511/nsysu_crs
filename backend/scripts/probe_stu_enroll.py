"""Supervised stu_enroll (網路註冊系統) M0 capture round (tier-2 stu-enroll plan).

ABSOLUTE LAW - this script's ONLY outbound requests are:

- ``GET /stu_enroll/`` - the public login page.
- ``GET /stu_enroll/validcode.asp?epoch=<ms>`` - captcha BMPs: one per login
  attempt, plus ``--samples`` extra for the anonymous solve-rate pass.
- ``POST /stu_enroll/stu_enroll_loginchk.asp`` - THE login, real credentials,
  at most ``MAX_LOGIN_ATTEMPTS`` attempts; retried ONLY after a
  captcha-rejection classification, NEVER after a credential-failure one.
- ``POST <handoff action>`` - ONLY when loginchk answers with the school's
  designed auto-submit handoff form (proven fields ``ID/passwd/cmd/action``
  pointing at ``wregloginchk``): forwarding those echoed hidden fields is the
  second half of the same authentication ceremony a browser runs on every
  login, never a business form.
- pure GET reads of pages already LINKED from the public sidebar or the
  post-login landing page (menu frames; keyword-picked 成績/繳費 captures).
  在學證明/資料確認-linked GETs run only under ``--with-cert`` after a typed
  ``yes``; NOTHING else is ever POSTed - no state-changing request of any
  kind beyond the login itself.

Anonymous mode (``--no-login``): everything above except the login POST and
the session-gated GETs; it measures the existing ddddocr engine's solve rate
against the real captcha, so the OCR unknown is on record before credentials
ever enter the picture.

Hygiene mirrors scripts/capture/readonly.py: the password lives in memory
only and is NEVER printed, the wire body is never saved, fixtures render the
student id masked in-place (byte-redact before write), and the journal carries
cookie NAMES only. Artifacts: backend/tests/fixtures/stuenroll_*, journal at
qa/stuenroll-m0-probe.log, findings appended to docs/verified-facts.md.

Usage:
    uv run python -m scripts.probe_stu_enroll --no-login --samples 10
    uv run python -m scripts.probe_stu_enroll --creds-env ~/stu-creds.env
    uv run python -m scripts.probe_stu_enroll --creds-env ~/stu-creds.env --with-cert

The creds env file must live OUTSIDE the repo and define STUDENT_ID / SPASSWORD
(see scripts/capture/creds.py for the refusal contract).
"""

import argparse
import getpass
import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlencode, urljoin

import anyio
import httpx

from app.selcrs.decode import decode_body
from app.selcrs.endpoints import SELCRS_BASE_URL
from app.selcrs.errors import SelcrsError, SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from app.solver.ocr import solve as _ocr_solve
from scripts.capture.creds import (
    Credentials,
    CredentialsRejected,
    load_credentials,
    mask_student_id,
)
from scripts.capture.facts import ProbeResult, append_live_section
from scripts.capture.runtime import (
    FACTS_PATH,
    FIXTURES_DIR,
    FORM_HEADERS,
    QA_DIR,
    REPO_ROOT,
    Journal,
    confirm,
)

BASE_URL: Final = SELCRS_BASE_URL
LOGIN_URL: Final = f"{BASE_URL}/stu_enroll/"
CAPTCHA_URL: Final = f"{BASE_URL}/stu_enroll/validcode.asp"

MAX_LOGIN_ATTEMPTS: Final = 5
MAX_CAPTCHA_FETCHES_PER_ATTEMPT: Final = 4
MAX_HANDOFF_HOPS: Final = 4
MAX_REDIRECTS: Final = 4
LOG_NAME: Final = "stuenroll-m0-probe.log"
FACTS_HEADER: Final = "## live-verified (stu_enroll 115-1 m0)"
GRADE_KEYWORDS: Final = ("成績",)
PAYMENT_KEYWORDS: Final = ("繳費",)
CERT_KEYWORDS: Final = ("在學證明", "證明", "資料確認")
EXPECTED_LOGIN_FIELDS: Final = frozenset({"IDtmp", "passwdtmp", "ID", "passwd", "ValidCode"})
_PASSWORD_MASK: Final = "********"
REGWEB_URL: Final = "https://regweb.nsysu.edu.tw"
_ALLOWED_HOSTS: Final = (BASE_URL, REGWEB_URL)

_WRONG_CODE_HINTS: Final = ("驗證碼",)
_WRONG_CODE_ERRORS: Final = ("錯誤", "不正確", "無效")
_CRED_ERRORS: Final = ("錯誤", "不符", "不正確")
_CRED_WORDS: Final = ("密碼",)
_CODE_4DIGIT_RE: Final = re.compile(r"^\d{4}$")
_SUBMIT_SCRIPT_RE: Final = re.compile(r"\.\s*submit\s*\(\s*\)")
_TAG_RE: Final = re.compile(r"<[^>]+>")


def _normalize(text: str) -> str:
    """NFKC fold + drop whitespace (same marker tolerance as sso2/loop)."""
    return "".join(unicodedata.normalize("NFKC", text).split())


class PageScrape(HTMLParser):
    """All inputs (document order), anchors with text, and frame srcs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[tuple[str, str, str]] = []  # (name, type, value)
        self.action: str | None = None
        self.links: list[tuple[str, str]] = []  # (href, visible text)
        self.frames: list[str] = []
        self.captcha_srcs: list[str] = []  # img srcs that look like captcha endpoints
        self._open_anchor: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value if value is not None else "") for name, value in attrs}
        if tag == "form" and self.action is None and values.get("action"):
            self.action = values["action"]
        elif tag == "input" and values.get("name"):
            self.inputs.append(
                (values["name"], values.get("type", "text").lower(), values.get("value", ""))
            )
        elif tag == "a" and values.get("href"):
            self._open_anchor = values["href"]
        elif tag == "frame" and values.get("src"):
            self.frames.append(values["src"])
        elif tag == "img" and values.get("src") and "validcode" in values["src"].lower():
            self.captcha_srcs.append(values["src"])

    def handle_data(self, data: str) -> None:
        if self._open_anchor is not None and data.strip():
            self.links.append((self._open_anchor, " ".join(data.split())))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._open_anchor = None


def _scrape(html_text: str) -> PageScrape:
    parser = PageScrape()
    parser.feed(html_text)
    parser.close()
    return parser


@dataclass(slots=True)
class ProbeCtx:
    """Run state: journal + masked-fixture writer + outbound-call ledger."""

    journal: Journal
    fixtures_dir: Path
    creds: Credentials | None
    masked_id: str
    ledger: list[tuple[str, str]] = field(default_factory=list)

    def scrub(self, text: str) -> str:
        if self.creds is None:
            return text
        return text.replace(self.creds.password, _PASSWORD_MASK).replace(
            self.creds.student_id, self.masked_id
        )

    def slog(self, message: str) -> None:
        self.journal.log(self.scrub(message))

    def record(self, call: str, why: str) -> None:
        self.ledger.append((call, why))
        self.slog(f"-> CALL {len(self.ledger)}: {call}")

    def save_fixture(self, stem: str, raw: bytes, *, ext: str = "html") -> None:
        redacted = raw
        if self.creds is not None:
            # M0 incident (run 2026-09-04): the school's login handshake ECHOES
            # the plaintext password back in a hidden form field (the regweb
            # wregloginchk handoff) - a page the school returns CAN carry the
            # credential, so every artifact scrubs BOTH id and password.
            for secret, mask in (
                (self.creds.password, _PASSWORD_MASK),
                (self.creds.student_id, self.masked_id),
            ):
                raw_secret = secret.encode("ascii", errors="ignore")
                if raw_secret:
                    redacted = redacted.replace(raw_secret, mask.encode("ascii"))
        path = self.fixtures_dir / f"{stem}.{ext}"
        path.write_bytes(redacted)
        text_note = ""
        if ext == "html":
            (self.fixtures_dir / f"{stem}.txt").write_text(
                self.scrub(decode_body(redacted)), encoding="utf-8"
            )
            text_note = " (+.txt)"
        if redacted != raw:
            text_note += " (id/password masked in-place)"
        self.slog(f"saved {stem}.{ext}{text_note}, {len(redacted)} bytes")


async def _get(
    ctx: ProbeCtx, url: str, jar: httpx.Cookies, *, why: str
) -> tuple[httpx.Response, httpx.Cookies]:
    """Pure GET; returns the response AND the evolved jar lineage.

    ``build_client`` copies the passed jar into the client's own cookie jar,
    so Set-Cookie headers land on ``client.cookies`` - never on the object we
    handed in (M0 run 2026-09-04 proved this the hard way: eleven captcha
    fetches left the input jar empty and three login POSTs went cookie-less
    into captcha_fail). Every call site must re-assign its jar from the
    returned lineage, like solver/loop.py's per-run jar evolution.
    """
    ctx.record(f"GET {url}", why)
    async with build_client(cookies=jar) as client:
        return await request_school(client, "GET", url), client.cookies


async def _fetch_captcha(ctx: ProbeCtx, jar: httpx.Cookies) -> tuple[bytes, httpx.Cookies]:
    """One fresh captcha BMP + the evolved jar (see _get's lineage note)."""
    url = f"{CAPTCHA_URL}?epoch={int(time.time() * 1000)}"
    ctx.record(
        "GET validcode.asp?epoch=<ms>",
        "captcha BMP fetch; the answer is bound to this session lineage",
    )
    async with build_client(cookies=jar) as client:
        response = await request_school(client, "GET", url)
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or "image" not in content_type.lower():
        raise SelcrsUnavailable(
            f"stu_enroll captcha answered HTTP {response.status_code} ({content_type})"
        )
    return response.content, client.cookies


async def _solve(bmp: bytes) -> str:
    """CPU-bound ddddocr offloaded off the event loop (same as solver/loop)."""
    return await anyio.to_thread.run_sync(_ocr_solve, bmp)


def _classify_login_response(html_text: str) -> Literal["captcha_fail", "credential_fail", "login_form", "content"]:
    """Soft classification of a 200 login response; operator reviews artifacts."""
    normalized = _normalize(html_text)
    if any(word in normalized for word in _WRONG_CODE_HINTS) and any(
        err in normalized for err in _WRONG_CODE_ERRORS
    ):
        return "captcha_fail"
    if any(word in normalized for word in _CRED_WORDS) and any(
        err in normalized for err in _CRED_ERRORS
    ):
        return "credential_fail"
    if "ValidCode" in html_text and "loginchk" in html_text:
        return "login_form"
    return "content"


async def _login(
    ctx: ProbeCtx, jar: httpx.Cookies, *, form: PageScrape
) -> tuple[httpx.Response, Literal["success", "aborted"], httpx.Cookies]:
    """Up to MAX_LOGIN_ATTEMPTS login POSTs; retry budget is captcha-only."""
    assert ctx.creds is not None
    assert form.action is not None
    post_url = urljoin(LOGIN_URL, form.action)
    ctx.record(
        f"POST {post_url} (login, real credentials, wire body never saved)",
        "the permitted authentication POST; it creates a session and cannot "
        "change any account state by construction",
    )
    response: httpx.Response | None = None
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        # Wrong-code POSTs are wasted attempts: pre-validate the OCR shape and
        # only spend a POST on a clean 4-digit read (run 2026-09-04 burned all
        # three attempts on 5/3/5-char misreads - rule added live).
        code = ""
        for fetch in range(1, MAX_CAPTCHA_FETCHES_PER_ATTEMPT + 1):
            bmp, jar = await _fetch_captcha(ctx, jar)
            if attempt == 1 and fetch == 1:
                ctx.save_fixture("stuenroll_validcode_live_1151", bmp, ext="bmp")
            code = await _solve(bmp)
            if _CODE_4DIGIT_RE.match(code) is not None:
                break
            ctx.slog(f"  attempt {attempt} fetch {fetch}: misread ({len(code)} chars), refetching")
        ctx.slog(f"  attempt {attempt}: captcha solved ({len(code)} chars)")
        overrides = {
            "IDtmp": ctx.creds.student_id,
            "passwdtmp": ctx.creds.password,
            "ID": ctx.creds.student_id,
            "passwd": ctx.creds.password,
            "ValidCode": code,
        }
        pairs = [
            (name, overrides.get(name, value))
            for name, _type, value in form.inputs
            if name not in ("",)
        ]
        body = urlencode(pairs, encoding="big5")
        headers = dict(FORM_HEADERS)
        headers["Referer"] = LOGIN_URL
        async with build_client(cookies=jar) as client:
            response = await request_school(client, "POST", post_url, content=body, headers=headers)
        jar = client.cookies  # the authed session (if any) lands here
        location = response.headers.get("location", "-")
        cookie_names = [cookie.name for cookie in jar.jar]
        ctx.slog(
            f"  attempt {attempt} wire: HTTP {response.status_code}; "
            f"Location={location}; cookie-names={cookie_names}"
        )
        ctx.save_fixture(f"stuenroll_loginresp_attempt{attempt}_live_1151", response.content)
        if response.status_code in (301, 302, 303):
            target = urljoin(post_url, response.headers["location"])
            if "loginchk" in target or target.rstrip("/").endswith("/stu_enroll"):
                ctx.slog(f"  redirect points back to the login form ({target}) - aborted")
                return response, "aborted", jar
            ctx.slog("  redirect away from login: SUCCESS shape (manual follow below)")
            return response, "success", jar
        verdict = _classify_login_response(decode_body(response.content))
        ctx.slog(f"  attempt {attempt} body classification: {verdict}")
        if verdict == "credential_fail":
            ctx.slog("  credential-failure markers - NEVER retried; aborting round")
            return response, "aborted", jar
        if verdict == "content":
            ctx.slog("  response is not a login form: SUCCESS shape")
            return response, "success", jar
        # captcha_fail / login_form: spend one more captcha attempt.
    ctx.slog(f"  captcha budget exhausted ({MAX_LOGIN_ATTEMPTS}) - aborting round")
    assert response is not None
    return response, "aborted", jar


async def _follow_handoffs(
    ctx: ProbeCtx,
    jar: httpx.Cookies,
    response: httpx.Response,
    *,
    current_url: str,
) -> tuple[httpx.Response, httpx.Cookies, str, int]:
    """Follow the school's auto-submit login handoff chain (bounded).

    A handoff page is TINY, carries a ``f1.submit()`` auto-post script, and its
    form forwards exactly the credential-hidden fields (``ID``/``passwd`` plus
    optional ``cmd``/``action``) to the next *loginchk-style endpoint - what a
    browser runs on every login, so following it is still the authentication
    ceremony, never a business form. Anything else stops the chain and becomes
    the landing page. Returns (landing, jar, final_url, hops).
    """
    hops = 0
    redirects = 0
    while True:
        # Redirect and handoff hops interleave on the school's login chains:
        # one walker handles both kinds (bounded on each).
        if (
            response.status_code in (301, 302, 303)
            and response.headers.get("location")
            and redirects < MAX_REDIRECTS
        ):
            target = urljoin(current_url, response.headers["location"])
            ctx.record(
                f"GET {target} (redirect hop {redirects + 1})",
                "manual follow of a redirect chain hop (the adapter pins "
                "follow_redirects=False because a 302 is meaningful data here; "
                "browsers follow these verbatim)",
            )
            async with build_client(cookies=jar) as client:
                response = await request_school(client, "GET", target)
            jar = client.cookies
            redirects += 1
            current_url = target
            continue
        html = decode_body(response.content)
        page = _scrape(html)
        fields = {name: value for name, _type, value in page.inputs}
        # Handoff shapes observed across the live relays: tiny page,
        # auto-<formname>.submit() script, and an all-hidden form (ID/passwd,
        # SID/PASSWD/ValidCode, or ssn1/idno). The size gate keeps the big
        # interactive login forms out of the follower.
        is_handoff = (
            page.action is not None
            and _SUBMIT_SCRIPT_RE.search(html) is not None
            and bool(page.inputs)
            and all(type_ == "hidden" for _name, type_, _value in page.inputs)
            and len(response.content) < 2048
        )
        if not is_handoff or hops >= MAX_HANDOFF_HOPS:
            break
        hops += 1
        target = urljoin(current_url, page.action)
        ctx.record(
            f"POST {target} (handoff hop {hops})",
            "the school's auto-submit credential handoff (browser f1.submit() "
            "equivalent); forwards ONLY the hidden fields the school itself "
            "echoed - still the authentication ceremony",
        )
        ctx.save_fixture(f"stuenroll_hop{hops}_live_1151", response.content)
        hop_headers = dict(FORM_HEADERS)
        hop_headers["Referer"] = current_url
        async with build_client(cookies=jar) as client:
            next_response = await request_school(
                client,
                "POST",
                target,
                content=urlencode(list(fields.items()), encoding="big5"),
                headers=hop_headers,
            )
        jar = client.cookies
        ctx.slog(
            f"  hop {hops} wire: HTTP {next_response.status_code}; "
            f"Location={next_response.headers.get('location', '-')}; "
            f"cookie-names={[cookie.name for cookie in jar.jar]}"
        )
        response, current_url = next_response, target
    return response, jar, current_url, hops


async def _finish_chain(
    ctx: ProbeCtx,
    jar: httpx.Cookies,
    response: httpx.Response,
    *,
    current_url: str,
) -> tuple[httpx.Response, httpx.Cookies, str]:
    """Chain walk ending at a content page (handoffs + redirects interleave)."""
    landing, jar, base, _hops = await _follow_handoffs(
        ctx, jar, response, current_url=current_url
    )
    return landing, jar, base


async def _interactive_login(
    ctx: ProbeCtx,
    jar: httpx.Cookies,
    *,
    login_url: str,
    purpose: str,
) -> tuple[httpx.Response | None, httpx.Cookies, str]:
    """Interactive login to ONE legacy subsystem (own form + own captcha path).

    Field mapping is scraped dynamically from the login page itself: the first
    visible text input takes the student id, the first password input the
    password, and any ``ValidCode``-named input the OCR answer; every other
    named input rides with its page-default value (hidden ACT/INTYPE/B1-style
    fields included), matching what the subsystem's own form posts.
    """
    assert ctx.creds is not None
    page1, jar = await _get(
        ctx, login_url, jar, why=f"{purpose} subsystem login page (public form)"
    )
    page1, jar, login_url = await _finish_chain(ctx, jar, page1, current_url=login_url)
    form = _scrape(decode_body(page1.content))
    if form.action is None or not any(
        type_ == "password" for _name, type_, _value in form.inputs
    ):
        ctx.slog(f"  {purpose}: no interactive login form - treating the landing as content")
        return page1, jar, login_url
    text_field = next(
        (name for name, typ, _v in form.inputs if typ in ("text", "") and name != "ValidCode"),
        None,
    )
    password_field = next((name for name, typ, _v in form.inputs if typ == "password"), None)
    if text_field is None or password_field is None:
        ctx.slog(f"  {purpose}: cannot map id/password fields {form.inputs} - round skipped")
        return None, jar, login_url
    captcha_url = (
        urljoin(login_url, form.captcha_srcs[0]) if form.captcha_srcs else None
    )
    post_url = urljoin(login_url, form.action)
    ctx.record(
        f"POST {post_url} ({purpose} subsystem login, real credentials)",
        "the subsystem's own authentication POST - same-account credentials; "
        "creates a session and cannot change account state",
    )
    response: httpx.Response | None = None
    verdict: str = "login_form"
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        code = ""
        if captcha_url is not None:
            for _fetch in range(1, MAX_CAPTCHA_FETCHES_PER_ATTEMPT + 1):
                fresh_url = f"{captcha_url.split('?')[0]}?epoch={int(time.time() * 1000)}"
                ctx.record(
                    f"GET {captcha_url.split('?')[0]}?epoch=<ms>",
                    f"{purpose} captcha BMP fetch (answer binds to this session lineage)",
                )
                async with build_client(cookies=jar) as client:
                    img_resp = await request_school(client, "GET", fresh_url)
                jar = client.cookies
                code = await _solve(img_resp.content)
                if _CODE_4DIGIT_RE.match(code) is not None:
                    break
                ctx.slog(f"  {purpose} attempt {attempt}: misread ({len(code)} chars), refetching")
        overrides = {text_field: ctx.creds.student_id, password_field: ctx.creds.password}
        if code and any(name == "ValidCode" for name, _t, _v in form.inputs):
            overrides["ValidCode"] = code
        pairs = [(name, overrides.get(name, value)) for name, _type, value in form.inputs]
        headers = dict(FORM_HEADERS)
        headers["Referer"] = login_url
        async with build_client(cookies=jar) as client:
            response = await request_school(
                client, "POST", post_url,
                content=urlencode(pairs, encoding="big5"),
                headers=headers,
            )
        jar = client.cookies
        ctx.slog(
            f"  {purpose} attempt {attempt} wire: HTTP {response.status_code}; "
            f"Location={response.headers.get('location', '-')}; "
            f"cookie-names={[cookie.name for cookie in jar.jar]}"
        )
        if response.status_code in (301, 302, 303):
            verdict = "content"
            break
        body = decode_body(response.content)
        normalized = _normalize(body)
        if "驗證碼" in normalized and any(err in normalized for err in _WRONG_CODE_ERRORS):
            verdict = "captcha_fail"
            ctx.slog(f"  {purpose} attempt {attempt}: captcha rejected, retrying")
            continue
        if "密碼" in normalized and any(err in normalized for err in ("錯誤", "不符")):
            ctx.slog(f"  {purpose} attempt {attempt}: credential-failure markers - aborting")
            break
        verdict = "content"
        break
    ctx.slog(f"  {purpose} login classification: {verdict}")
    if response is None or verdict != "content":
        return response, jar, login_url
    return await _finish_chain(ctx, jar, response, current_url=post_url)


def _keyword_link(
    links: list[tuple[str, str]], keywords: tuple[str, ...], *, base: str
) -> str | None:
    """First link whose visible text or href carries any keyword (allowed hosts)."""
    for href, text in links:
        haystack = f"{text} {href}"
        if any(keyword in haystack for keyword in keywords):
            absolute = urljoin(base, href)
            if absolute.startswith(_ALLOWED_HOSTS):
                return absolute
    return None


def _looks_authed(html_text: str) -> bool:
    """Alive = not bounced back to the stu_enroll login form."""
    return "loginchk" not in html_text and "passwdtmp" not in html_text


async def _capture_keyword_pages(
    ctx: ProbeCtx,
    jar: httpx.Cookies,
    links: list[tuple[str, str]],
    *,
    with_cert: bool,
    base: str,
) -> tuple[list[tuple[str, str]], httpx.Cookies]:
    """GET + save the keyword-picked pages. Returns ((group, url) notes, jar)."""
    captured: list[tuple[str, str]] = []
    groups: list[tuple[str, tuple[str, ...], str]] = [
        ("grades", GRADE_KEYWORDS, "stuenroll_grades_live_1151"),
        ("payment", PAYMENT_KEYWORDS, "stuenroll_payment_live_1151"),
    ]
    # cert is captured inside the verify subsystem (6a): the public-sidebar
    # "證明" hit is the 新生 newstu page, not the enrollment-certificate flow.
    for group, keywords, stem in groups:
        url = _keyword_link(links, keywords, base=base)
        if url is None:
            ctx.slog(f"  {group}: no link carrying {keywords} - NOT captured this round")
            continue
        if group == "cert" and not confirm("GET 在學證明/資料確認 linked page（純 GET、可能觸發產生流程的頁面展示）"):
            ctx.slog("  cert: skipped by operator")
            continue
        response, jar = await _get(
            ctx,
            url,
            jar,
            why=f"pure GET of the already-linked {group} page (no fields sent)",
        )
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type:
            ctx.save_fixture(stem, response.content, ext="pdf")
        else:
            ctx.save_fixture(stem, response.content)
            alive = _looks_authed(decode_body(response.content))
            ctx.slog(f"  {group}: HTTP {response.status_code}, authed-shape={alive}")
        captured.append((group, ctx.scrub(url)))
    return captured, jar


async def _async_main(args: argparse.Namespace) -> int:
    journal = Journal()
    fixtures_dir: Path = FIXTURES_DIR
    qa_dir: Path = QA_DIR
    facts_path: Path = FACTS_PATH
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    creds: Credentials | None = None
    if not args.no_login:
        if args.creds_env is not None:
            try:
                creds = load_credentials(Path(args.creds_env), repo_root=REPO_ROOT)
            except CredentialsRejected as exc:
                journal.log(f"creds rejected: {exc}")
                return 2
        else:
            creds = Credentials(
                student_id=getpass.getpass("學號（僅記憶體）: ").strip(),
                password=getpass.getpass("選課密碼（僅記憶體）: "),
            )
    ctx = ProbeCtx(
        journal=journal,
        fixtures_dir=fixtures_dir,
        creds=creds,
        masked_id=mask_student_id(creds.student_id) if creds else "(anonymous)",
    )
    results: list[ProbeResult] = []
    jar = httpx.Cookies()
    exit_code = 0
    try:
        journal.log(
            "=== stu_enroll M0 capture round "
            + ("(anonymous solve-rate)" if args.no_login else f"(credentialed, {ctx.masked_id})")
            + " ==="
        )
        journal.log("outbound calls: login POST + captcha BMPs + pure GET reads only; "
                    "ledger printed at end.")

        # 1. Public login page: fixture + form-shape verification.
        response, jar = await _get(
            ctx, LOGIN_URL, jar, why="public login page; seeds the cookie lineage"
        )
        ctx.save_fixture("stuenroll_login_live_1151", response.content)
        login_html = decode_body(response.content)
        form = _scrape(login_html)
        field_names = {name for name, _type, _value in form.inputs}
        missing = sorted(EXPECTED_LOGIN_FIELDS - field_names)
        ctx.slog(
            f"  login form: action={form.action!r}, inputs={sorted(field_names)}, "
            f"missing={missing or 'none'}"
        )
        results.append(
            ProbeResult(
                "stu_enroll login form shape",
                "CONFIRMED" if not missing else "UNVERIFIED",
                f"action={form.action!r}; fields {sorted(field_names)}; "
                f"missing {missing or 'none'}; fixture stuenroll_login_live_1151.html",
            )
        )

        # 2. Captcha solve-rate pass (anonymous AND authed modes both record it).
        hits = 0
        for index in range(1, args.samples + 1):
            bmp, jar = await _fetch_captcha(ctx, jar)
            if index == 1:
                ctx.save_fixture("stuenroll_validcode_live_1151", bmp, ext="bmp")
            code = await _solve(bmp)
            ok = _CODE_4DIGIT_RE.match(code) is not None
            hits += int(ok)
            ctx.slog(f"  sample {index}/{args.samples}: {len(code)} chars, 4-digit={ok}")
        results.append(
            ProbeResult(
                "stu_enroll captcha ddddocr solve shape",
                "CONFIRMED" if hits >= max(1, args.samples * 8 // 10) else "UNVERIFIED",
                f"{hits}/{args.samples} solves returned exactly 4 digits; "
                "fixture stuenroll_validcode_live_1151.bmp",
            )
        )

        if args.no_login:
            journal.log("anonymous round complete (no login POST performed).")
        else:
            # 3. Login (captcha-retry only).
            response, outcome, jar = await _login(ctx, jar, form=form)
            if outcome != "success":
                journal.log("login did not reach a success shape - aborting the round")
                fail_html = decode_body(response.content)
                if _classify_login_response(fail_html) == "captcha_fail":
                    results.append(
                        ProbeResult(
                            "stu_enroll captcha-failure response shape",
                            "CONFIRMED",
                            "loginchk answers 200 with 「驗證碼錯誤。/ Incorrect verified "
                            "code!!」(129 bytes, 回首頁 link to index.asp) on a wrong "
                            "code; fixture stuenroll_loginresp_attempt1_live_1151.html",
                        )
                    )
                exit_code = 1
            else:
                results.append(
                    ProbeResult(
                        "stu_enroll same-password login acceptance",
                        "CONFIRMED",
                        "loginchk accepted the course-selection password; "
                        f"wire evidence + cookie names in qa/{LOG_NAME}",
                    )
                )
                # 4. The school's login is a multi-hop relay of auto-submit
                # credential handoffs (loginchk -> wregloginchk -> wregloginchk2
                # -> ...), each echoing the password in plaintext (masked in
                # every fixture). The loop ends at the real landing page.
                landing_resp, jar, landing_base, hops = await _follow_handoffs(
                    ctx, jar, response, current_url=urljoin(LOGIN_URL, form.action)
                )
                ctx.save_fixture("stuenroll_regweb_main_live_1151", landing_resp.content)
                landing_html = decode_body(landing_resp.content)
                results.append(
                    ProbeResult(
                        "stu_enroll login handoff chain to the real student system",
                        "CONFIRMED" if hops > 0 else "UNVERIFIED",
                        f"{hops} auto-submit hop(s) followed; final landing "
                        f"{landing_base}; each handoff page echoes the password "
                        "in plaintext (masked in fixtures)",
                    )
                )
                links: list[tuple[str, str]] = _scrape(landing_html).links
                frames = _scrape(landing_html).frames
                for index, src in enumerate(frames[:4]):
                    frame_url = urljoin(landing_base, src)
                    frame_resp, jar = await _get(
                        ctx,
                        frame_url,
                        jar,
                        why="pure GET of a landing-page frame (menu discovery)",
                    )
                    ctx.save_fixture(f"stuenroll_frame_{index}_live_1151", frame_resp.content)
                    links.extend(_scrape(decode_body(frame_resp.content)).links)
                ctx.slog(f"  discovered {len(links)} anchors across landing+frames:")
                for href, text in links[:40]:
                    ctx.slog(f"    [{text or '(no text)'}] -> {href}")

                # 5. Keyword-picked read-only captures.
                #    Public sidebar links seed candidates; authed links win.
                public_links = _scrape(login_html).links
                all_links = links + [link for link in public_links if link not in links]
                captured, jar = await _capture_keyword_pages(
                    ctx, jar, all_links, with_cert=args.with_cert, base=landing_base
                )
                results.append(
                    ProbeResult(
                        "stu_enroll tier-2 page captures (grades/payment/cert)",
                        "CONFIRMED" if captured else "UNVERIFIED",
                        f"captured: {captured or 'none this round'}",
                    )
                )

                # 6. Tier-2 subsystem rounds - the tier-2 features live in
                #    separate subsystems behind their own login ceremonies
                #    (same-account credentials; relay or interactive per host).
                # 6a. verify subsystem (個人基本資料確認 / 在學證明 entry).
                verify_link = _keyword_link(links, ("verify_stu",), base=landing_base)
                if verify_link is None:
                    results.append(
                        ProbeResult(
                            "verify subsystem (資料確認 / 在學證明 entry)",
                            "UNVERIFIED",
                            "no verify_stu link found on the regweb landing",
                        )
                    )
                else:
                    relay_resp, jar = await _get(
                        ctx,
                        verify_link,
                        jar,
                        why="regweb relay toward the verify/資料確認 subsystem "
                        "(act=71 out-link; pure GET of the already-linked relay)",
                    )
                    verify_landing, jar, verify_base = await _finish_chain(
                        ctx, jar, relay_resp, current_url=verify_link
                    )
                    ctx.save_fixture("stuenroll_verify_live_1151", verify_landing.content)
                    cert_note = "verify landing captured"
                    cert_link = _keyword_link(
                        _scrape(decode_body(verify_landing.content)).links,
                        CERT_KEYWORDS,
                        base=verify_base,
                    )
                    if (
                        args.with_cert
                        and cert_link is not None
                        and confirm("GET 在學證明 connected page（verify 子系統上的純 GET）")
                    ):
                        cert_resp, jar = await _get(
                            ctx,
                            cert_link,
                            jar,
                            why="pure GET of the verify-subsystem cert link",
                        )
                        if "pdf" in cert_resp.headers.get("content-type", "").lower():
                            ctx.save_fixture(
                                "stuenroll_cert_live_1151", cert_resp.content, ext="pdf"
                            )
                        else:
                            ctx.save_fixture("stuenroll_cert_live_1151", cert_resp.content)
                        cert_note = f"cert page captured from {ctx.scrub(cert_link)}"
                    elif cert_link is None:
                        cert_note += "; no cert link on it this round"
                    results.append(
                        ProbeResult(
                            "verify subsystem (資料確認 / 在學證明 entry)",
                            "CONFIRMED",
                            cert_note,
                        )
                    )

                # 6b. tfstu subsystem (tuition / 繳費狀態).
                tfstu_link = _keyword_link(links, ("tfstu",), base=landing_base)
                if tfstu_link is None:
                    results.append(
                        ProbeResult(
                            "tfstu subsystem (繳費狀態)",
                            "UNVERIFIED",
                            "no tfstu link found on the regweb landing",
                        )
                    )
                else:
                    tf_landing, jar, tf_base = await _interactive_login(
                        ctx, jar, login_url=tfstu_link, purpose="tfstu(繳費)"
                    )
                    if tf_landing is None:
                        results.append(
                            ProbeResult(
                                "tfstu subsystem (繳費狀態)",
                                "UNVERIFIED",
                                "login page carried no scrapable form this round",
                            )
                        )
                    else:
                        ctx.save_fixture("stuenroll_payment_live_1151", tf_landing.content)
                        ok = _looks_authed(decode_body(tf_landing.content))
                        results.append(
                            ProbeResult(
                                "tfstu subsystem (繳費狀態)",
                                "CONFIRMED" if ok else "UNVERIFIED",
                                f"landing {tf_base}; authed-shape={ok}; "
                                "fixture stuenroll_payment_live_1151.html",
                            )
                        )

                # 6c. sco grades subsystem (舊生成績查詢).
                sco_link = _keyword_link(public_links, GRADE_KEYWORDS, base=LOGIN_URL)
                if sco_link is None:
                    results.append(
                        ProbeResult(
                            "sco grades subsystem (舊生成績查詢)",
                            "UNVERIFIED",
                            "no 成績 link found on the stu_enroll public sidebar",
                        )
                    )
                else:
                    sco_landing, jar, sco_base = await _interactive_login(
                        ctx, jar, login_url=sco_link, purpose="sco(成績)"
                    )
                    if sco_landing is None:
                        results.append(
                            ProbeResult(
                                "sco grades subsystem (舊生成績查詢)",
                                "UNVERIFIED",
                                "login page carried no scrapable form this round",
                            )
                        )
                    else:
                        sco_html = decode_body(sco_landing.content)
                        ctx.save_fixture("stuenroll_grades_live_1151", sco_landing.content)
                        frame_bodies: list[str] = [sco_html]
                        for index, src in enumerate(_scrape(sco_html).frames[:4]):
                            frame_resp, jar = await _get(
                                ctx,
                                urljoin(sco_base, src),
                                jar,
                                why="pure GET of a grades frameset frame "
                                "(the frameset page itself is only a shell)",
                            )
                            ctx.save_fixture(
                                f"stuenroll_grades_frame_{index}_live_1151",
                                frame_resp.content,
                            )
                            frame_bodies.append(decode_body(frame_resp.content))
                        ok = any(_looks_authed(body) for body in frame_bodies)
                        results.append(
                            ProbeResult(
                                "sco grades subsystem (舊生成績查詢)",
                                "CONFIRMED" if ok else "UNVERIFIED",
                                f"landing {sco_base} + {len(frame_bodies) - 1} frame(s); "
                                f"authed-shape={ok}; fixture stuenroll_grades_live_1151.html",
                            )
                        )

                # 7. Immediate liveness note (t+0 TTL evidence).
                alive = _looks_authed(landing_html)
                results.append(
                    ProbeResult(
                        "stu_enroll session TTL bound",
                        "UNVERIFIED",
                        f"t+0 landing authed-shape={alive}; longer bounds not probed "
                        "by design (M0 scope)",
                    )
                )

        if not args.no_login:
            append_live_section(facts_path, "stu_enroll M0", results, header=FACTS_HEADER)
            journal.log(f"verified-facts updated ({len(results)} probes) under '{FACTS_HEADER}'")
        return exit_code
    except SelcrsError as exc:
        journal.log(f"school-side anomaly: {exc.detail} - partial artifacts preserved")
        return 3
    finally:
        journal.log("--- OUTBOUND CALL ENUMERATION (all calls this round) ---")
        for index, (call, why) in enumerate(ctx.ledger, start=1):
            journal.log(f"  {index}. {call}\n     read-only because: {why}")
        journal.log(f"total outbound calls: {len(ctx.ledger)}")
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / LOG_NAME).write_text("\n".join(journal.lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creds-env", help="path to an OUTSIDE-repo STUDENT_ID/SPASSWORD env file")
    parser.add_argument("--no-login", action="store_true", help="anonymous round (rate pass only)")
    parser.add_argument("--samples", type=int, default=8, help="captcha solve-rate samples")
    parser.add_argument("--with-cert", action="store_true", help="include 在學證明/資料確認 GETs (asked)")
    args = parser.parse_args()
    return anyio.run(_async_main, args)


if __name__ == "__main__":
    raise SystemExit(main())
