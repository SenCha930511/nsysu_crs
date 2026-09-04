"""Supervised stu_enroll (網路註冊系統) M0 capture round (tier-2 stu-enroll plan).

ABSOLUTE LAW - this script's ONLY outbound requests are:

- ``GET /stu_enroll/`` - the public login page.
- ``GET /stu_enroll/validcode.asp?epoch=<ms>`` - captcha BMPs: one per login
  attempt, plus ``--samples`` extra for the anonymous solve-rate pass.
- ``POST /stu_enroll/stu_enroll_loginchk.asp`` - THE login, real credentials,
  at most ``MAX_LOGIN_ATTEMPTS`` attempts; retried ONLY after a
  captcha-rejection classification, NEVER after a credential-failure one.
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

MAX_LOGIN_ATTEMPTS: Final = 3
LOG_NAME: Final = "stuenroll-m0-probe.log"
FACTS_HEADER: Final = "## live-verified (stu_enroll 115-1 m0)"
GRADE_KEYWORDS: Final = ("成績",)
PAYMENT_KEYWORDS: Final = ("繳費",)
CERT_KEYWORDS: Final = ("在學證明", "證明", "資料確認")
EXPECTED_LOGIN_FIELDS: Final = frozenset({"IDtmp", "passwdtmp", "ID", "passwd", "ValidCode"})

_WRONG_CODE_HINTS: Final = ("驗證碼",)
_WRONG_CODE_ERRORS: Final = ("錯誤", "不正確", "無效")
_CRED_ERRORS: Final = ("錯誤", "不符", "不正確")
_CRED_WORDS: Final = ("密碼",)
_CODE_4DIGIT_RE: Final = re.compile(r"^\d{4}$")
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
        return text.replace(self.creds.student_id, self.masked_id)

    def slog(self, message: str) -> None:
        self.journal.log(self.scrub(message))

    def record(self, call: str, why: str) -> None:
        self.ledger.append((call, why))
        self.slog(f"-> CALL {len(self.ledger)}: {call}")

    def save_fixture(self, stem: str, raw: bytes, *, ext: str = "html") -> None:
        redacted = raw
        text_note = ""
        if self.creds is not None:
            sid = self.creds.student_id.encode("ascii", errors="ignore")
            if sid:
                redacted = raw.replace(sid, self.masked_id.encode("ascii"))
        path = self.fixtures_dir / f"{stem}.{ext}"
        path.write_bytes(redacted)
        if ext == "html":
            text = decode_body(redacted)
            if self.creds is not None:
                text = text.replace(self.creds.student_id, self.masked_id)
            (self.fixtures_dir / f"{stem}.txt").write_text(text, encoding="utf-8")
            text_note = " (+.txt)"
        if redacted != raw:
            text_note += " (student id masked in-place)"
        self.slog(f"saved {stem}.{ext}{text_note}, {len(redacted)} bytes")


async def _get(ctx: ProbeCtx, url: str, jar: httpx.Cookies, *, why: str) -> httpx.Response:
    ctx.record(f"GET {url}", why)
    async with build_client(cookies=jar) as client:
        return await request_school(client, "GET", url)


async def _fetch_captcha(ctx: ProbeCtx, jar: httpx.Cookies) -> bytes:
    """One fresh captcha BMP on the evolving jar lineage (answer binds to it)."""
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
    return response.content


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
) -> tuple[httpx.Response, Literal["success", "aborted"]]:
    """Up to MAX_LOGIN_ATTEMPTS login POSTs; retry budget is captcha-only."""
    assert ctx.creds is not None
    assert form.action is not None
    post_url = urljoin(LOGIN_URL, form.action)
    ctx.record(
        f"POST {post_url} (login, real credentials, wire body never saved)",
        "the permitted authentication POST; it creates a session and cannot "
        "change any account state by construction",
    )
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        bmp = await _fetch_captcha(ctx, jar)
        if attempt == 1:
            ctx.save_fixture("stuenroll_validcode_live_1151", bmp, ext="bmp")
        code = await _solve(bmp)
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
                return response, "aborted"
            ctx.slog("  redirect away from login: SUCCESS shape (manual follow below)")
            return response, "success"
        verdict = _classify_login_response(decode_body(response.content))
        ctx.slog(f"  attempt {attempt} body classification: {verdict}")
        if verdict == "credential_fail":
            ctx.slog("  credential-failure markers - NEVER retried; aborting round")
            return response, "aborted"
        if verdict == "content":
            ctx.slog("  response is not a login form: SUCCESS shape")
            return response, "success"
        # captcha_fail / login_form: spend one more captcha attempt.
    ctx.slog(f"  captcha budget exhausted ({MAX_LOGIN_ATTEMPTS}) - aborting round")
    return response, "aborted"


def _keyword_link(
    links: list[tuple[str, str]], keywords: tuple[str, ...]
) -> str | None:
    """First link whose visible text or href carries any keyword (same-host only)."""
    for href, text in links:
        haystack = f"{text} {href}"
        if any(keyword in haystack for keyword in keywords):
            absolute = urljoin(LOGIN_URL, href)
            if absolute.startswith(BASE_URL):
                return absolute
    return None


def _looks_authed(html_text: str) -> bool:
    """Alive = not bounced back to the stu_enroll login form."""
    return "loginchk" not in html_text and "passwdtmp" not in html_text


async def _capture_keyword_pages(
    ctx: ProbeCtx, jar: httpx.Cookies, links: list[tuple[str, str]], *, with_cert: bool
) -> list[tuple[str, str]]:
    """GET + save the keyword-picked pages. Returns (group, url) notes."""
    captured: list[tuple[str, str]] = []
    groups: list[tuple[str, tuple[str, ...], str]] = [
        ("grades", GRADE_KEYWORDS, "stuenroll_grades_live_1151"),
        ("payment", PAYMENT_KEYWORDS, "stuenroll_payment_live_1151"),
    ]
    if with_cert:
        groups.append(("cert", CERT_KEYWORDS, "stuenroll_cert_live_1151"))
    for group, keywords, stem in groups:
        url = _keyword_link(links, keywords)
        if url is None:
            ctx.slog(f"  {group}: no link carrying {keywords} - NOT captured this round")
            continue
        if group == "cert" and not confirm("GET 在學證明/資料確認 linked page（純 GET、可能觸發產生流程的頁面展示）"):
            ctx.slog("  cert: skipped by operator")
            continue
        response = await _get(
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
    return captured


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
        response = await _get(
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
            bmp = await _fetch_captcha(ctx, jar)
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
            response, outcome = await _login(ctx, jar, form=form)
            if outcome != "success":
                journal.log("login did not reach a success shape - aborting the round")
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
                # 4. Landing page (follow a 302 manually) + frame fan-out.
                landing_html = decode_body(response.content)
                if response.status_code in (301, 302, 303):
                    landing_url = urljoin(LOGIN_URL, response.headers["location"])
                    landing = await _get(
                        ctx, landing_url, jar, why="manual follow of the login redirect"
                    )
                    landing_html = decode_body(landing.content)
                    ctx.save_fixture("stuenroll_landing_live_1151", landing.content)
                else:
                    ctx.save_fixture("stuenroll_landing_live_1151", response.content)
                links: list[tuple[str, str]] = _scrape(landing_html).links
                frames = _scrape(landing_html).frames
                for index, src in enumerate(frames[:4]):
                    frame_url = urljoin(LOGIN_URL, src)
                    frame_resp = await _get(
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
                captured = await _capture_keyword_pages(
                    ctx, jar, all_links, with_cert=args.with_cert
                )
                results.append(
                    ProbeResult(
                        "stu_enroll tier-2 page captures (grades/payment/cert)",
                        "CONFIRMED" if captured else "UNVERIFIED",
                        f"captured: {captured or 'none this round'}",
                    )
                )

                # 6. Immediate liveness note (t+0 TTL evidence).
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
