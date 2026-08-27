"""ssprs / saddstage5prs submit-response parser (plan todo 15).

*** PROVISIONAL *** — every response fixture in the repo is synthetic and
marked ``provisional`` until the todo-4 capture window records a real ssprs
reply; the marker vocabularies below are the archaeological expectation
(shape: a classic-ASP confirmation page listing a per-course verdict row
containing the 8-char course code), NOT live-verified. The parser is written
so that a vocabulary miss degrades to ``parse_failed`` with the raw excerpt
stored — the engine NEVER guesses an outcome the page did not state plainly
(plan: "parse failure -> outcome 'parse_failed' + raw excerpt stored, never
guessed").

Per-op mapping is KEYED BY COURSE CODE, never by row position: each batch
code is located in the decoded HTML, the enclosing ``<tr>`` (or enclosing
text segment when the page is not tabular) is isolated, and only that
fragment is classified. Marker matching follows the repo's Big5-tolerance
policy: NFKC fold + whitespace strip, then substring search.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from app.selcrs.errors import SelcrsSessionExpired
from app.write.outcomes import (
    OUTCOME_FAILED,
    OUTCOME_PARSE_FAILED,
    OUTCOME_SUCCESS,
)

#: School-message excerpt cap stored on write_audit.school_msg (原文摘錄).
EXCERPT_LIMIT: Final = 160

#: Dead-session bounce (same markers as the Studfun/slt_result parsers).
SESSION_BOUNCE_MARKERS: Final = ("請先登錄", "請先登入", "SPassword", "Studcheck_sso2")

#: PROVISIONAL success vocabulary (a marker inside the op's own fragment).
_SUCCESS_MARKERS: Final = ("加選成功", "退選成功", "登記成功", "選課成功", "成功")

#: PROVISIONAL business-failure vocabulary (checked before success: an
#: 「加選失敗」 fragment must never read as a success).
_FAILURE_MARKERS: Final = (
    "失敗",
    "不成功",
    "額滿",
    "已額滿",
    "已滿",
    "衝堂",
    "不符",
    "錯誤",
    "超過",
    "未開放",
    "無此課程",
    "查無",
    "不可",
)

#: PROVISIONAL duplicate-like subset of the failure vocabulary. When a
#: transport-retried op lands here, the FIRST post may actually have gone
#: through: the engine marks the op ``unknown-reconciled`` and reconciles it
#: against slt_result at the end of the job (plan todo 15 retry discipline).
_DUPLICATE_LIKE_MARKERS: Final = ("重複", "重覆", "已選", "已加選", "已登記", "已退")

_ROW_RE: Final = re.compile(r"<tr[^>]*>(?P<body>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE: Final = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class ParsedOp:
    """One op's classified verdict from the school response."""

    outcome: str  # success | failed | parse_failed
    school_msg: str | None
    duplicate_like: bool = False


def _fold(text: str) -> str:
    """NFKC fold + whitespace strip (the repo's Big5-variant tolerance)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _clean_cell_text(fragment_html: str) -> str:
    """Fragment -> readable text (tags flattened, entities collapsed)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", fragment_html)).strip()


def is_session_bounce(text: str) -> bool:
    """True when the school served its login page / 請先登錄 bounce."""
    return any(marker in text for marker in SESSION_BOUNCE_MARKERS)


_BLOCK_BOUNDARY_RE: Final = re.compile(r"</?(p|div|br|li|section|article|h\d)[^>]*>", re.IGNORECASE)


def _fragment_for_code(html: str, code: str) -> str | None:
    """The page fragment to classify for ``code``: the enclosing table row
    when the code sits inside one, else the enclosing block-level LINE (a
    flat window would bleed verdicts across ops on non-tabular pages). None
    when the code is absent from the page (never classify a missing op)."""
    for match in _ROW_RE.finditer(html):
        if code in match.group("body"):
            return match.group("body")
    if code not in html:
        return None
    lines = _BLOCK_BOUNDARY_RE.sub("\n", html).split("\n")
    for line in lines:
        if code in line:
            return line
    return None


def _excerpt(text: str) -> str:
    return text[:EXCERPT_LIMIT] if len(text) > EXCERPT_LIMIT else text


def classify_fragment(fragment_html: str) -> ParsedOp:
    """Classify one op's fragment. Ambiguity is ALWAYS parse_failed."""
    plain = _clean_cell_text(fragment_html)
    folded = _fold(plain)
    has_success = any(marker in folded for marker in _SUCCESS_MARKERS)
    has_failure = any(marker in folded for marker in _FAILURE_MARKERS)
    excerpt = _excerpt(plain)
    if has_success and has_failure:
        # A fragment stating both cannot be attributed without guessing.
        return ParsedOp(OUTCOME_PARSE_FAILED, excerpt)
    if has_failure:
        duplicate_like = any(marker in folded for marker in _DUPLICATE_LIKE_MARKERS)
        return ParsedOp(OUTCOME_FAILED, excerpt, duplicate_like)
    if has_success:
        return ParsedOp(OUTCOME_SUCCESS, excerpt)
    return ParsedOp(OUTCOME_PARSE_FAILED, excerpt)


def parse_submit_response(html: str, batch_codes: list[str]) -> dict[str, ParsedOp]:
    """Classify every batch op against one decoded submit response.

    Raises:
        SelcrsSessionExpired: the response is a login bounce (the session
            died between the dequeue-time liveness check and the POST) - the
            engine maps every still-open op to 階段逾時.
    """
    if is_session_bounce(html):
        raise SelcrsSessionExpired("submit response bounced to the school login page")
    page_excerpt = _excerpt(_clean_cell_text(html))
    outcomes: dict[str, ParsedOp] = {}
    for code in batch_codes:
        fragment = _fragment_for_code(html, code)
        if fragment is None:
            outcomes[code] = ParsedOp(OUTCOME_PARSE_FAILED, page_excerpt)
            continue
        outcomes[code] = classify_fragment(fragment)
    return outcomes
