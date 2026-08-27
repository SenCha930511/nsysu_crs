"""Shared runtime state for the live capture kit: journal, session ctx, IO.

Everything here is side-effect-light and shared by ``kit`` (orchestration) and
``protocol`` (supervised write mini-protocol + probes). Hard rules: no
credentials or cookie VALUES ever touch the journal; the journal is the only
place run narrative is collected, and it lands in qa/04-capture.log.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from app.selcrs.decode import decode_body
from app.selcrs.endpoints import SELCRS_BASE_URL
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from app.selcrs.sso2 import Sso2Outcome, classify_sso2_response
from app.selcrs.transform import base64md5
from scripts.capture.formparse import looks_like_login_page
from scripts.capture.windows import TAIPEI, SelectionWindow

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
FIXTURES_DIR = BACKEND_ROOT / "tests" / "fixtures"
QA_DIR = REPO_ROOT / "qa"
FACTS_PATH = REPO_ROOT / "docs" / "verified-facts.md"

SEMESTER = "1151"
SSO2_URL = f"{SELCRS_BASE_URL}/menu4/Studcheck_sso2.asp"
STUDFUN_URL = f"{SELCRS_BASE_URL}/menu4/Studfun.asp"
SLT_RESULT_URL = f"{SELCRS_BASE_URL}/menu4/query/slt_result.asp"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


@dataclass(slots=True)
class Journal:
    """Timestamped run narrative, echoed to the terminal, dumped to qa/."""

    lines: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.lines.append(f"[{datetime.now(TAIPEI):%H:%M:%S}] {message}")
        print(message)


@dataclass(slots=True)
class LiveCtx:
    """Mutable run state shared by the protocol steps."""

    window: SelectionWindow
    fixtures_dir: Path
    journal: Journal
    jar: httpx.Cookies | None = None
    form_url: str = ""
    submit_url: str = ""
    t0: float = 0.0
    liveness: list[tuple[float, bool]] = field(default_factory=list)

    def elapsed_min(self) -> float:
        return round((time.monotonic() - self.t0) / 60.0, 1)

    def mark_liveness(self, raw: bytes) -> bool:
        alive = not looks_like_login_page(decode_body(raw))
        self.liveness.append((self.elapsed_min(), alive))
        self.journal.log(f"liveness t+{self.elapsed_min()}min: {'alive' if alive else 'DEAD'}")
        return alive

    def save(self, stem: str, raw: bytes) -> None:
        (self.fixtures_dir / f"{stem}.html").write_bytes(raw)
        (self.fixtures_dir / f"{stem}.txt").write_text(decode_body(raw), encoding="utf-8")
        self.journal.log(f"saved {stem}.html (+.txt), {len(raw)} bytes")

    async def get_page(self, url: str) -> bytes:
        assert self.jar is not None
        async with build_client(cookies=self.jar) as client:
            response = await request_school(client, "GET", url)
        if response.status_code != 200:
            raise SelcrsUnavailable(f"GET {url.rsplit('/', 1)[-1]} -> HTTP {response.status_code}")
        return response.content

    async def post_form(self, body: str, *, referer: str | None) -> bytes:
        assert self.jar is not None
        headers = dict(FORM_HEADERS)
        if referer is not None:
            headers["Referer"] = referer
        async with build_client(cookies=self.jar) as client:
            response = await request_school(
                client, "POST", self.submit_url, content=body, headers=headers
            )
        return response.content


async def sso2_attempt(student_no: str, password: str) -> tuple[Sso2Outcome, bytes, httpx.Cookies]:
    """One raw SSO2 attempt. UNKNOWN shapes raise SelcrsUnavailable (breaker's diet)."""
    jar = httpx.Cookies()
    async with build_client(cookies=jar) as client:
        response = await request_school(
            client, "POST", SSO2_URL,
            data={"stuid": student_no, "SPassword": base64md5(password)},
        )
        session = client.cookies
    names = [cookie.name for cookie in session.jar]
    outcome = classify_sso2_response(response)
    print(f"  SSO2 HTTP {response.status_code}, "
          f"Location={response.headers.get('location', '-')}, cookie-names={names}")
    return outcome, response.content, session


def confirm(step: str) -> bool:
    """Real writes gate here: nothing happens without a literal typed 'yes'."""
    return input(f'\n請確認執行【{step}】（輸入 yes 才會執行）: ').strip() == "yes"
