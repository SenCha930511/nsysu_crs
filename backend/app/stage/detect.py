"""Studfun.asp stage detection + 必修課程確認 pre-step gate (plan todo 13).

Detection ladder on the decoded Studfun page (first hit wins):

1. **Open** — an ``<a>`` whose href path ends with ``ssform.asp``
   (variant ``ssform``, 加退選, 15-row form) or ``stage5/saddstage5.asp``
   (variant ``stage5``, 初選, 10-row form). The link's query params
   (X1/X2/EDU/DEG_COD/college/dept/grade/SCH_COD/USE_YR) are the *assembly
   starting point* only — todo 14/15 own the real same-session form replay
   and re-scrape every hidden input themselves; these values are never
   trusted past parse-time reporting.
2. **Closed** — the literal heading 選課關閉 in the page's *visible text*
   (live-verified 2026-08-27, docs/verified-facts.md (b), fixture
   studfun_closed_live_1151.html).
3. **Closed** — every link on the page sits inside the read-only
   closed-page families (querys.asp / query/* / tools/* / sys_prs
   pass-through / exit_sys) seen on the real closed page.
4. **Unknown (未知)** — anything else. Shape drift is a VALUE here, never
   an exception (``drift_no_marker``), and must NEVER be mis-reported as
   open: the ONLY path that yields an open stage is a matched write-form
   anchor. The parser raises solely for a dead school session (login-page
   bounce → ``SelcrsSessionExpired``), mirroring the slt_result parser.

need_confirmation (必修課程確認 pre-step): the school can front the real form
with a pre-confirmation page whose submit button is labelled 送出 (NOT the
normal 提交) and whose onclick injects ``<input type=hidden name=step value=2>``
into ``#step_id`` before re-clicking ``send``. The two verbatim anchors below
are pinned byte-for-byte from the edwinchu detector (it is the only place its
``SelectionState.needConfirmation`` is set):

Adapted from NsysuApp_OpenSource (MIT License, Copyright (c) 2026 Edwin Chu):
https://raw.githubusercontent.com/edwinchu0711/NsysuApp_OpenSource/fe64ddb64df76614fc406a7ec2b6694af26c75d6/lib/services/course_selection_service.dart
(lib/services/course_selection_service.dart L197-L207, Dart original):

    if (selectionBody.contains('value="送出"') &&
        selectionBody.contains(
          '''onclick="document.getElementById('step_id').innerHTML='&lt;input type=hidden name=step value=2 &gt;';document.all['send'].click();"''',
        )) {
      return {'state': SelectionState.needConfirmation, ...};
    }
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict

from app.selcrs.errors import SelcrsSessionExpired

#: Stage labels (the API's closed enum).
STAGE_ADD_DROP: Final = "加退選"
STAGE_FIRST_ROUND: Final = "初選"
STAGE_CLOSED: Final = "關閉"
STAGE_UNKNOWN: Final = "未知"

#: Form variants (ssform = 15 rows, stage5 = 10 rows; plan todo 13).
VARIANT_SSFORM: Final = "ssform"
VARIANT_STAGE5: Final = "stage5"

#: Machine reasons (drift forensics; always present in the API response).
REASON_SSFORM_LINK: Final = "ssform_link"
REASON_STAGE5_LINK: Final = "stage5_link"
REASON_CLOSED_HEADING: Final = "closed_heading"
REASON_CLOSED_READONLY_LINKS: Final = "closed_readonly_links"
REASON_DRIFT_NO_MARKER: Final = "drift_no_marker"

#: Live-verified closed-state heading (studfun_closed_live_1151.html).
CLOSED_HEADING: Final = "選課關閉"

#: Dead-session bounce markers (same policy as selections/parse.py).
_EXPIRED_MARKERS: Final = ("請先登錄", "請先登入", "SPassword", "Studcheck_sso2")

#: Link families the real closed page exposes (all read-only).
_READONLY_LINK_HINTS: Final = ("querys.asp", "query/", "tools/", "sys_prs", "exit_sys")

_VARIANT_REASON: Final = {VARIANT_SSFORM: REASON_SSFORM_LINK, VARIANT_STAGE5: REASON_STAGE5_LINK}
_VARIANT_STAGE: Final = {VARIANT_SSFORM: STAGE_ADD_DROP, VARIANT_STAGE5: STAGE_FIRST_ROUND}

# Verbatim edwinchu needConfirmation anchors (see module docstring).
PRESTEP_BUTTON_ANCHOR: Final = 'value="送出"'
PRESTEP_ONCLICK_ANCHOR: Final = (
    "onclick=\"document.getElementById('step_id').innerHTML="
    "'&lt;input type=hidden name=step value=2 &gt;';"
    "document.all['send'].click();\""
)


class StageParams(BaseModel):
    """Query params of the Studfun write-form link (assembly starting point)."""

    model_config = ConfigDict(frozen=True)

    X1: str | None = None
    X2: str | None = None
    EDU: str | None = None
    DEG_COD: str | None = None
    college: str | None = None
    dept: str | None = None
    grade: str | None = None
    SCH_COD: str | None = None
    USE_YR: str | None = None


@dataclass(frozen=True, slots=True)
class StudfunDetection:
    """Parse result of one Studfun page. Never writable on closed/unknown."""

    stage: str  # STAGE_ADD_DROP | STAGE_FIRST_ROUND | STAGE_CLOSED | STAGE_UNKNOWN
    variant: str | None  # VARIANT_SSFORM | VARIANT_STAGE5 | None
    form_href: str | None  # raw href (root-relative path + query) when open
    params: StageParams | None
    reason: str


def _href(tag: Tag) -> str | None:
    """The tag's href, case-insensitive on the attribute name."""
    value = tag.get("href")
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _write_variant(href: str) -> str | None:
    """Classify one href as a write-form link; None when it is not one.

    The path is compared on its END so both bare (``ssform.asp?...``) and
    nested (``addcourse/ssform.asp?...`` / absolute) href shapes match;
    ``ssprs.asp``/``saddstage5prs.asp`` submit endpoints cannot collide.
    """
    path = urlsplit(href).path.lower()
    if path.endswith("ssform.asp"):
        return VARIANT_SSFORM
    if path.endswith("stage5/saddstage5.asp"):
        return VARIANT_STAGE5
    return None


def _params_from(href: str) -> StageParams:
    query = parse_qs(urlsplit(href).query, keep_blank_values=True)
    values = {name: query[name][0] for name in StageParams.model_fields if name in query}
    return StageParams(**values)


def _is_readonly_family(href: str) -> bool:
    return any(hint in href for hint in _READONLY_LINK_HINTS)


def parse_studfun(html: str) -> StudfunDetection:
    """Detect the selection stage from one decoded Studfun page.

    Raises:
        SelcrsSessionExpired: the school bounced the session back to its
            login page (dead jar) -> API maps to 401 SELCRS_EXPIRED.

    Everything else — including total shape drift — returns a detection:
    unknown pages yield ``stage=未知, reason=drift_no_marker`` and are never
    mistaken for an open window.
    """
    if any(marker in html for marker in _EXPIRED_MARKERS):
        raise SelcrsSessionExpired("Studfun bounced to the school login page")
    soup = BeautifulSoup(html, "html.parser")
    hrefs = [href for tag in soup.find_all("a") if (href := _href(tag))]
    for href in hrefs:
        variant = _write_variant(href)
        if variant is not None:
            return StudfunDetection(
                stage=_VARIANT_STAGE[variant],
                variant=variant,
                form_href=href,
                params=_params_from(href),
                reason=_VARIANT_REASON[variant],
            )
    # The heading is matched on VISIBLE text: HTML comments/boilerplate that
    # mention the words (e.g. this repo's own fixture notes) must not count.
    if CLOSED_HEADING in soup.get_text():
        return StudfunDetection(
            stage=STAGE_CLOSED,
            variant=None,
            form_href=None,
            params=None,
            reason=REASON_CLOSED_HEADING,
        )
    if hrefs and all(_is_readonly_family(href) for href in hrefs):
        return StudfunDetection(
            stage=STAGE_CLOSED,
            variant=None,
            form_href=None,
            params=None,
            reason=REASON_CLOSED_READONLY_LINKS,
        )
    return StudfunDetection(
        stage=STAGE_UNKNOWN,
        variant=None,
        form_href=None,
        params=None,
        reason=REASON_DRIFT_NO_MARKER,
    )


def detect_need_confirmation(form_html: str) -> bool:
    """True when the form page is the 必修課程確認 pre-step gate.

    Both edwinchu anchors must be present (the 送出 button alone is not
    enough — the step-2 DOM-injection onclick is what makes the page the
    pre-step). When True the user must complete the required-course
    confirmation on the school site itself before any write can proceed.
    """
    return PRESTEP_BUTTON_ANCHOR in form_html and PRESTEP_ONCLICK_ANCHOR in form_html
