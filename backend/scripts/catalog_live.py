"""One-shot LIVE catalog ingest + evidence capture (plan todo 6, QA 06-live).

Two modes:

- ``--probe``: fetch page 1 ONLY through the solver loop (no DB writes, no
  ledger row, no fixture), print the layout facts needed before committing to
  a full run: discovered D0, pagination marker, <th> header texts, per-column
  8-char-code match counts, detected charset, and one fully-indexed sample
  row. Read-only reconnaissance.
- default: run the REAL full current-D0 ingest through ``run_ingest`` (open
  ledger -> discover -> every page through the captcha loop -> atomic
  snapshot -> close ledger), holding the plan's own Redis singleton lock for
  the duration so the compose worker's scheduled tick COALESCES instead of
  running a second concurrent crawl. Writes to ``--out``: the page-1 fixture
  (raw bytes ``.html`` + big5hkscs-decoded ``.txt``, capture-kit convention),
  ``stats.json`` (all telemetry), and a human-readable evidence block
  (``06-live.log`` body; the host appends the peak-gate verdict).

Adapter discipline: every school call rides ``build_client`` +
``request_school`` (TLS SECLEVEL=1, global cap 2, captcha lane 1, backoff
1/2/4/8/16) and the ddddocr ``CaptchaLoop`` - the capture fetcher merely
re-composes the SAME primitives ``endpoints.fetch_catalog_page`` uses, adding
a raw-bytes sink that the public endpoint deliberately does not expose.
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import anyio
import redis.asyncio as aioredis
from bs4 import BeautifulSoup

from app.catalog.discover import discover_current_d0
from app.catalog.ingest import run_ingest
from app.catalog.parse import MIN_CELLS, extract_page_link, parse_catalog_page
from app.catalog.schedule import CronPolicy, IngestLock
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.selcrs.decode import decode_body, resolve_charset
from app.selcrs.endpoints import (
    SELCRS_BASE_URL,
    CatalogQuery,
    _catalog_form,
)
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from app.solver.loop import CaptchaLoop

TAIPEI: Final = ZoneInfo("Asia/Taipei")
CODE_8_RE: Final = re.compile(r"^[A-Za-z0-9]{8}$")


@dataclass(frozen=True, slots=True)
class PageCapture:
    """Raw page bytes + transport header, kept per page for charset evidence."""

    content: bytes
    content_type: str | None

    @property
    def charset(self) -> str:
        return resolve_charset(self.content, self.content_type)


class CaptureSink:
    """Page-number -> raw capture + code-column scanner over decoded HTML."""

    def __init__(self) -> None:
        self.pages: dict[int, PageCapture] = {}
        self.code_col_hits: dict[int, int] = {}
        self.headers: list[str] = []
        self.sample_row: list[str] = []
        self.candidates: int = 0

    def record(self, page: int, content: bytes, content_type: str | None, html: str) -> None:
        self.pages[page] = PageCapture(content, content_type)
        soup = BeautifulSoup(html, "html.parser")
        if not self.headers:
            for tr in soup.find_all("tr"):
                ths = [th.get_text(strip=True) for th in tr.find_all("th")]
                if ths:
                    self.headers = ths
                    break
        candidate_index = 0
        for tr in soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td", recursive=False)]
            if len(cells) < MIN_CELLS:
                continue
            candidate_index += 1
            if not self.sample_row:
                self.sample_row = cells
            for index, text in enumerate(cells):
                if CODE_8_RE.match(text):
                    self.code_col_hits[index] = self.code_col_hits.get(index, 0) + 1
        self.candidates += candidate_index


def capture_fetcher_factory(sink: CaptureSink):
    """Page-1 fetcher identical to the production default, plus a raw sink:
    POST dplycourse via build_client/request_school/_catalog_form with the
    caller's per-run jar, on the captcha lane."""

    def factory(page: int):
        async def _fetch(query: CatalogQuery, *, validcode: str, cookies, transport=None) -> str:
            async with build_client(cookies=cookies, transport=transport) as client:
                response = await request_school(
                    client,
                    "POST",
                    f"{SELCRS_BASE_URL}/menu1/dplycourse.asp",
                    params={"page": 1},  # see fetch_catalog_page docstring (a-token contract)
                    data=_catalog_form(query, validcode),
                    captcha_parented=True,
                )
            if response.status_code != 200:
                raise SelcrsUnavailable(
                    f"dplycourse.asp responded HTTP {response.status_code}"
                )
            html = decode_body(response.content, response.headers.get("content-type"))
            sink.record(page, response.content, response.headers.get("content-type"), html)
            return html

        return _fetch

    return factory


def capture_get_fetcher(sink: CaptureSink):
    """Paging GET fetcher (pages 2..N) mirroring fetch_catalog_page_get, plus
    the same raw sink - per-page charset evidence needs the GETs' bytes."""

    async def _get(cookies, path: str, *, transport=None) -> str:
        match = re.search(r"[?&]page=(\d+)", path)
        page = int(match.group(1)) if match is not None else 0
        async with build_client(cookies=cookies, transport=transport) as client:
            response = await request_school(client, "GET", f"{SELCRS_BASE_URL}{path}")
        if response.status_code != 200:
            raise SelcrsUnavailable(f"dplycourse.asp?page responded HTTP {response.status_code}")
        html = decode_body(response.content, response.headers.get("content-type"))
        sink.record(page, response.content, response.headers.get("content-type"), html)
        return html

    return _get


async def probe(out_lines: list[str]) -> int:
    """Page 1 through the loop + page-2 GET check; facts out, zero DB writes."""
    d0 = await discover_current_d0()
    sink = CaptureSink()
    loop = CaptchaLoop(catalog_page_fetcher=capture_fetcher_factory(sink)(1))
    started = time.monotonic()
    result = await loop.run_page(CatalogQuery(year_sem=d0, deg_cod="*"))
    seconds = time.monotonic() - started
    page = parse_catalog_page(result.html, year_sem=d0)
    capture = sink.pages[1]
    out_lines.append(f"discovered current D0 (qrycourse YRSM): {d0}")
    out_lines.append(f"page 1: {result.attempts} attempts, {seconds:.1f}s")
    out_lines.append(f"detected charset: {capture.charset} (content-type: {capture.content_type!r})")
    pagination = page.pagination
    out_lines.append(
        "pagination: "
        + (f"page {pagination.current} of {pagination.total} ({pagination.variant})" if pagination else "NONE")
    )
    out_lines.append(f"header cells ({len(sink.headers)}): {sink.headers}")
    out_lines.append(f"candidate rows: {page.candidate_rows}, accepted: {len(page.rows)}, skipped: {page.skipped_rows}")
    out_lines.append(f"code-like (^[A-Za-z0-9]{{8}}$) column hits on page 1: {sink.code_col_hits or '{}'}")
    out_lines.append("sample accepted row (indexed):")
    for index, text in enumerate(sink.sample_row):
        out_lines.append(f"  [{index:2d}] {text!r}")
    if pagination is None or pagination.total < 2:
        out_lines.append("page-2 GET check: skipped (single page)")
        return 0
    link = extract_page_link(result.html, 2)
    out_lines.append(f"page-2 link extracted: {link!r}")
    if link is None:
        out_lines.append("page-2 GET check: FAIL (no link; POST URL query contract broken?)")
        return 4
    getter = capture_get_fetcher(sink)
    get_started = time.monotonic()
    html2 = await getter(result.validcode.cookies, link)
    page2 = parse_catalog_page(html2, year_sem=d0)
    pagination2 = page2.pagination
    out_lines.append(
        f"page-2 GET check: {time.monotonic() - get_started:.1f}s, "
        f"{len(page2.rows)} accepted rows, skipped {page2.skipped_rows}, marker "
        + (f"page {pagination2.current} of {pagination2.total}" if pagination2 else "NONE")
    )
    return 0 if page.rows and page2.rows else 4


async def full_ingest(out_dir: Path, out_lines: list[str]) -> int:
    """The real run: run_ingest under the plan's Redis singleton lock."""
    settings = Settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    redis = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    ttl = 2 * 3600  # EX = 2x off-peak interval (the manual run's own TTL rule)
    lock = IngestLock(redis)
    sink = CaptureSink()
    started_at = datetime.now(TAIPEI)
    token = await lock.acquire(ttl)
    if token is None:
        out_lines.append("ABORT: ingest:lock already held (a scheduled tick is mid-run) - retry later")
        return 5
    try:
        report = await run_ingest(
            session_factory,
            fetcher_factory=capture_fetcher_factory(sink),
            get_fetcher=capture_get_fetcher(sink),
        )
    finally:
        released = await lock.release(token)
        await redis.aclose()
        await engine.dispose()
    finished_at = datetime.now(TAIPEI)
    out_lines.append(f"lock released (compare-and-del): {released}")

    peak_interval = CronPolicy(settings.catalog_cron_peak).interval_seconds(finished_at)
    stats = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "ok": report.ok,
        "error": report.error,
        "year_sem": report.year_sem,
        "pages_announced": report.pages_announced,
        "pages_fetched": report.pages_fetched,
        "rows_stored": report.rows_stored,
        "rows_skipped": report.rows_skipped,
        "persist": None
        if report.persist is None
        else {
            "stored": report.persist.rows_stored,
            "updated": report.persist.rows_updated,
            "inserted": report.persist.rows_inserted,
            "deleted": report.persist.rows_deleted,
            "dedup_skipped": report.persist.dedup_skipped,
        },
        "wall_seconds": round(report.wall_seconds, 1),
        "captcha_attempts": report.captcha_attempts,
        "captcha_attempt_rate": None
        if report.captcha_attempt_rate is None
        else round(report.captcha_attempt_rate, 3),
        "page_records": [
            {
                "page": record.page,
                "attempts": record.attempts,
                "seconds": round(record.seconds, 1),
                "rows": record.rows,
                "skipped": record.skipped,
                "charset": sink.pages[record.page].charset if record.page in sink.pages else None,
            }
            for record in report.page_records
        ],
        "code_col_hits": sink.code_col_hits,
        "headers": sink.headers,
        "candidate_rows_seen": sink.candidates,
        "peak_cron": settings.catalog_cron_peak,
        "peak_interval_seconds": peak_interval,
        "paging_contract": (
            "page 1 = captcha-spending POST; pages 2..N = captcha-free GETs on "
            "the embedded ?a=<token>&page=N links with the page-1 jar "
            "(live-verified 2026-08-28)"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Fixture: page-1 raw bytes + big5hkscs decode (capture-kit convention).
    page1 = sink.pages.get(1)
    if page1 is not None:
        (out_dir / "dply_page_live_1151.html").write_bytes(page1.content)
        (out_dir / "dply_page_live_1151.txt").write_text(
            page1.content.decode("big5hkscs", errors="replace"), encoding="utf-8"
        )
    return 0 if report.ok else 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scripts.catalog_live")
    parser.add_argument("--out", type=Path, default=Path("/app/live-out"))
    parser.add_argument("--probe", action="store_true", help="page-1 reconnaissance only (no DB)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_lines: list[str] = [
        (
            f"catalog live {'PROBE' if args.probe else 'FULL INGEST'} | "
            f"started {datetime.now(TAIPEI):%Y-%m-%d %H:%M:%S} Asia/Taipei"
        ),
    ]
    if args.probe:
        code = anyio.run(probe, out_lines)
    else:
        code = anyio.run(full_ingest, args.out, out_lines)
    text = "\n".join(out_lines) + "\n"
    sys.stdout.write(text)
    if not args.probe:
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "run.log").open("a", encoding="utf-8") as handle:
            handle.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
