"""Loop contract tests (plan todo 5): a scripted in-memory school drives
CaptchaLoop through its four contract behaviors. Adapter-level mechanics
(semaphore=1 captcha lane nested in the global cap of 2, fresh jar per
adapter-level run) are already locked in tests/test_selcrs_throttle.py - this
file pins the LOOP-level contract (QA: qa/05-loop.log, qa/05-jariso.log)."""

import sys
from collections.abc import Callable

import anyio
import httpx
import pytest

from app.selcrs.endpoints import CatalogQuery, ValidcodeResult
from app.solver.errors import CaptchaUnsolvable
from app.solver.loop import (
    MAX_SOLVE_ATTEMPTS,
    CaptchaLoop,
    CaptchaPageResult,
    is_wrong_code_response,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


WRONG_ALERT = "<script language='javascript'>alert('Wrong Validation Code');history.back();</script>"
WRONG_BIG5 = "<html><body><b>驗證碼錯誤</b>，請重新輸入</body></html>"
CATALOG_OK = "<html><body>1151 學期開課一覽　第 1 / 12 頁<table><tr><td>微積分(一)</td></tr></table></body></html>"


class _FakeSolver:
    """Injectable OCR stand-in: records every image, hands out scripted codes."""

    def __init__(self, codes: tuple[str, ...] = ("4242",)) -> None:
        self._codes = codes
        self.calls: list[bytes] = []

    def __call__(self, image_bytes: bytes) -> str:
        self.calls.append(image_bytes)
        return self._codes[(len(self.calls) - 1) % len(self._codes)]


class _FakeSchool:
    """Scripted school with the adapter's jar semantics.

    A captcha fetch with NO jar mints a FRESH jar carrying a globally unique
    ASPSESSION value (like the real school); a fetch WITH a jar returns an
    evolved copy of the same lineage (httpx copies the constructor jar, so
    endpoints hand back a new object, never the input). ``catalog_rule``
    decides from (lineage, validcode, submission_index_of_lineage) whether
    the school rejects the code.
    """

    def __init__(
        self,
        *,
        catalog_rule: Callable[[str, str, int], str],
        fetch_dwell: float = 0.0,
    ) -> None:
        self._catalog_rule = catalog_rule
        self._fetch_dwell = fetch_dwell
        self._session_serial = 0
        self.validcode_calls = 0
        self.catalog_calls = 0
        self.submits: list[tuple[str, str]] = []  # (lineage, validcode)
        self._submit_index: dict[str, int] = {}

    async def fetch_validcode(
        self,
        *,
        cookies: httpx.Cookies | None = None,
        transport: object | None = None,
    ) -> ValidcodeResult:
        self.validcode_calls += 1
        if self._fetch_dwell:
            await anyio.sleep(self._fetch_dwell)
        if cookies is None:
            self._session_serial += 1
            lineage = f"sess-{self._session_serial}"
        else:
            lineage = cookies.get("ASPSESSION") or ""
        jar = httpx.Cookies()  # evolved copy, same lineage
        jar.set("ASPSESSION", lineage)
        return ValidcodeResult(image_bytes=b"BM-fake-bitmap", cookies=jar)

    async def fetch_catalog_page(
        self,
        query: CatalogQuery,
        *,
        validcode: str,
        cookies: httpx.Cookies,
        transport: object | None = None,
    ) -> str:
        self.catalog_calls += 1
        lineage = cookies.get("ASPSESSION") or ""
        index = self._submit_index.get(lineage, 0) + 1
        self._submit_index[lineage] = index
        self.submits.append((lineage, validcode))
        return self._catalog_rule(lineage, validcode, index)


@pytest.mark.anyio
async def test_five_wrong_codes_raise_after_exactly_five_attempts() -> None:
    # Given a school that rejects every solved code (both marker languages)
    markers = [WRONG_ALERT, WRONG_BIG5, WRONG_ALERT, WRONG_BIG5, WRONG_ALERT]
    school = _FakeSchool(catalog_rule=lambda lineage, code, index: markers[index - 1])
    solver = _FakeSolver()
    loop = CaptchaLoop(solve=solver, validcode_fetcher=school.fetch_validcode,
                       catalog_page_fetcher=school.fetch_catalog_page)

    # When one page run exhausts the retry budget
    with pytest.raises(CaptchaUnsolvable) as excinfo:
        await loop.run_page(CatalogQuery(year_sem="1151"))

    # Then it raised with attempts=5, and the school NEVER saw a 6th fetch,
    # a 6th solve, or a 6th submission
    assert excinfo.value.attempts == MAX_SOLVE_ATTEMPTS == 5
    assert school.validcode_calls == 5
    assert school.catalog_calls == 5
    assert len(solver.calls) == 5
    # And the whole run stayed on ONE jar lineage (fresh BMPs fetched into it)
    lineages = {lineage for lineage, _ in school.submits}
    assert len(lineages) == 1


@pytest.mark.anyio
async def test_success_on_third_attempt_returns_the_accepted_page() -> None:
    # Given a school rejecting the lineage's first two codes, accepting the 3rd
    script = [WRONG_BIG5, WRONG_ALERT, CATALOG_OK]
    school = _FakeSchool(catalog_rule=lambda lineage, code, index: script[index - 1])
    solver = _FakeSolver(codes=("1111", "2222", "3333"))
    loop = CaptchaLoop(solve=solver, validcode_fetcher=school.fetch_validcode,
                       catalog_page_fetcher=school.fetch_catalog_page)

    # When the page runs
    result = await loop.run_page(CatalogQuery(year_sem="1151"))

    # Then it returned after attempt 3 with the accepted page and its artifact
    assert result.attempts == 3
    assert result.html == CATALOG_OK
    assert school.validcode_calls == 3
    assert school.catalog_calls == 3
    assert len(solver.calls) == 3
    # The accepted attempt's validcode artifact carries the run's jar, and it
    # is the jar every submission of this run rode on
    accepted_lineage = result.validcode.cookies.get("ASPSESSION")
    assert accepted_lineage
    assert {lineage for lineage, _ in school.submits} == {accepted_lineage}
    # The third submission spent the third solved code
    assert school.submits[-1] == (accepted_lineage, "3333")


@pytest.mark.anyio
async def test_injected_fake_solver_never_imports_ddddocr() -> None:
    # Given a loop with a fake solver injected (provider seam)
    sys.modules.pop("ddddocr", None)
    school = _FakeSchool(catalog_rule=lambda lineage, code, index: CATALOG_OK)
    solver = _FakeSolver()
    loop = CaptchaLoop(solve=solver, validcode_fetcher=school.fetch_validcode,
                       catalog_page_fetcher=school.fetch_catalog_page)

    # When a page runs
    result = await loop.run_page(CatalogQuery(year_sem="1151"))

    # Then the injected fake did the work and ddddocr was never booted
    assert result.attempts == 1
    assert len(solver.calls) == 1
    assert "ddddocr" not in sys.modules


@pytest.mark.anyio
async def test_two_overlapping_runs_never_share_a_jar() -> None:
    # Given ONE shared school (unique session per fresh jar) that rejects each
    # lineage's FIRST code and accepts its second - both runs overlap in the
    # captcha lane, so any jar bleed would cross the runs' lineages
    school = _FakeSchool(
        catalog_rule=lambda lineage, code, index: WRONG_ALERT if index == 1 else CATALOG_OK,
        fetch_dwell=0.01,  # widen the overlap window in fresh-jar minting
    )
    solver_a = _FakeSolver(codes=("aaaa", "bbbb"))
    solver_b = _FakeSolver(codes=("cccc", "dddd"))

    def make_loop(solver: _FakeSolver) -> CaptchaLoop:
        return CaptchaLoop(solve=solver, validcode_fetcher=school.fetch_validcode,
                           catalog_page_fetcher=school.fetch_catalog_page)

    # When two runs race through the same fetcher instances concurrently
    async with anyio.create_task_group() as tasks:
        boxes: dict[str, CaptchaPageResult] = {}
        for name, solver in (("A", solver_a), ("B", solver_b)):

            async def run(key: str, loop: CaptchaLoop) -> None:
                boxes[key] = await loop.run_page(CatalogQuery(year_sem="1151", wkday=key))

            tasks.start_soon(run, name, make_loop(solver))

    # Then each run needed its 2 attempts and got its own lineage end to end
    result_a, result_b = boxes["A"], boxes["B"]
    assert result_a.attempts == 2 and result_b.attempts == 2
    lineage_a = result_a.validcode.cookies.get("ASPSESSION")
    lineage_b = result_b.validcode.cookies.get("ASPSESSION")
    assert lineage_a and lineage_b and lineage_a != lineage_b
    per_run: dict[str, set[str]] = {"A": set(), "B": set()}
    for lineage, code in school.submits:
        if code in ("aaaa", "bbbb"):
            per_run["A"].add(lineage)
        else:
            per_run["B"].add(lineage)
    assert per_run["A"] == {lineage_a}
    assert per_run["B"] == {lineage_b}
    assert result_a.validcode.cookies is not result_b.validcode.cookies


@pytest.mark.parametrize(
    "html",
    (
        "Wrong Validation Code",
        WRONG_ALERT,  # alert() wrapper
        WRONG_BIG5,  # the Big5 marker language
        "驗證碼　錯誤",  # full-width space INSIDE the marker
        "Ｗｒｏｎｇ　Ｖａｌｉｄａｔｉｏｎ　Ｃｏｄｅ",  # fully full-width ASCII
    ),
)
def test_wrong_code_markers_survive_wrappers_and_width_variants(html: str) -> None:
    assert is_wrong_code_response(html)


@pytest.mark.parametrize("html", (CATALOG_OK, "", "驗證碼欄位", "Wrong Credentials"))
def test_normal_pages_or_near_misses_are_not_wrong_code_responses(html: str) -> None:
    assert not is_wrong_code_response(html)
