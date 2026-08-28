"""ssprs / saddstage5prs submit-response parser (plan todo 15).

CANONICAL LIVE SHAPE — recorded 2026-08-28 in the 115-1 加退選一 window
(fixture ``ssprs_resp_addfail_live_1151``, canonical): the real ssprs reply
is a status-SNAPSHOT page, NOT a per-course verdict table. It carries the
student header (姓名/學號), the CURRENT selections table under
【目前選課紀錄】 (post-submit school state), and — when the school rejected
(any of) the batch — an ``<hr>``-separated failure section headed by the
school's own words 【加退選失敗課程清單】. On the bogus-code capture the
section carries NO itemized rows at all (the school never echoes a code it
does not know); whether real validation failures (額滿/衝堂/必修...) are
itemized per course code there is unverified, so per-code rows are
classified when found and everything else falls back to the batch-level
statement.

The older synthetic fixtures (``*_provisional``) keep their marker: their
row-table shape is the archaeological expectation, not live-verified. They
remain parseable so the write-engine regression suite can script them, and
``parse_failed`` stays the honest outcome for shapes no live evidence
covers (never guessed, per plan: "parse failure -> outcome 'parse_failed'
+ raw excerpt stored, never guessed").

Classification contract:

1. Login bounce -> ``SelcrsSessionExpired`` (session died mid-flight).
2. Failure section present: a batch code itemized inside the section is
   classified from its own fragment (unrecognized wording -> parse_failed,
   never guessed). A batch code NOT itemized inherits the school's
   batch-level rejection: outcome ``failed`` with the section text as
   school_msg (the school's only statement about the op; the bogus-code
   live capture proves this is how the school rejects, and duplicate_like
   stays False so the engine never mistakes it for a retry collision).
   Multi-op caveat: if a future live capture shows itemized rows coexisting
   with unlisted ops, this wholesale branch must be revisited - it is the
   honest reading of a page that lists failures without acquitting anyone.
3. No failure section: the PROVISIONAL whole-page fragment search runs
   (keyed by course code, never by row position). Absent codes and
   markerless fragments degrade to parse_failed with the raw excerpt.

Marker matching follows the repo's Big5-tolerance policy: NFKC fold +
whitespace strip, then substring search.
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

#: LIVE-VERIFIED failure-section header (ssprs_resp_addfail_live_1151.html:
#: the school renders exactly this line when it rejects the submission).
FAILURE_SECTION_HEADER: Final = "【加退選失敗課程清單】"

#: PROVISIONAL success vocabulary (a marker inside the op's own fragment).
_SUCCESS_MARKERS: Final = ("加選成功", "退選成功", "登記成功", "選課成功", "成功")

#: Business-failure vocabulary (checked before success: an 「加選失敗」
#: fragment must never read as a success). Covers the plan-pinned message
#: families: 額滿/quota (額滿/已滿), rule violations (不符/不可/未開放),
#: 無此課 (無此課程/查無/不存在), and duplicate-like rejections
#: (重複/已選/已加選 - a bare duplicate wording with no 「失敗」 beside it is
#: still a rejection, and the engine's unknown-reconciled path needs it
#: failed + duplicate_like, not parse_failed).
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
    "不存在",
    "不可",
    "重複",
    "已選",
    "已加選",
)

#: PROVISIONAL duplicate-like subset of the failure vocabulary. When a
#: transport-retried op lands here, the FIRST post may actually have gone
#: through: the engine marks the op ``unknown-reconciled`` and reconciles it
#: against slt_result at the end of the job (plan todo 15 retry discipline).
_DUPLICATE_LIKE_MARKERS: Final = ("重複", "重覆", "已選", "已加選", "已登記", "已退")

_ROW_RE: Final = re.compile(r"<tr[^>]*>(?P<body>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE: Final = re.compile(r"<[^>]+>")
_ANCHOR_RE: Final = re.compile(r"<a\b", re.IGNORECASE)


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


def _failure_section(html: str) -> str | None:
    """The live-verified failure section (header through the first anchor -
    the trailing 回加退選課程 back-link is navigation, not school message),
    or None when the page rejects nothing / is not the canonical shape."""
    idx = html.find(FAILURE_SECTION_HEADER)
    if idx < 0:
        return None
    return _ANCHOR_RE.split(html[idx:], maxsplit=1)[0]


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
    section = _failure_section(html)
    outcomes: dict[str, ParsedOp] = {}
    for code in batch_codes:
        fragment = _fragment_for_code(section, code) if section is not None else None
        if fragment is None and section is None:
            fragment = _fragment_for_code(html, code)
        if fragment is not None:
            outcomes[code] = classify_fragment(fragment)
        elif section is not None:
            # The school's only statement about this op is the batch-level
            # rejection (live-proven for unknown codes; see module docstring
            # for the multi-op caveat). The message is the section HEADER
            # only - itemized rows belong to their own ops, never to an
            # unlisted one. Never duplicate_like: no per-op duplicate
            # wording exists on the page.
            outcomes[code] = ParsedOp(OUTCOME_FAILED, FAILURE_SECTION_HEADER)
        else:
            outcomes[code] = ParsedOp(OUTCOME_PARSE_FAILED, page_excerpt)
    return outcomes
