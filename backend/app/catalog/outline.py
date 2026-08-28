"""Course-outline (教學大綱) page parser — showoutline.asp (menu5, public).

LIVE-PROBED 2026-08-28 against the real CSE515 outline page: the page is
served UTF-8, labels appear as flat label lines (zh + zh/en combined), fields
follow on the next non-label line, and long free-text sections run until the
next known label. HTML comments and script/style islands are stripped BEFORE
flattening, and every text chunk passes html.unescape (the school encodes
most CJK as numeric entities, e.g. &#35611;).

The parser never guesses: unknown layouts yield whatever identity fields are
recognizable plus ``parsed=False`` classification upstream (sparse), so the UI
can fall back to the school's original page link instead of showing garbage.
"""

import html
import re
from dataclasses import dataclass

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_WS_RE = re.compile(r"[ \t]+")

_IDENTITY_LABELS: tuple[tuple[str, str], ...] = (
    ("中文名稱", "name_zh"),
    ("課號", "code"),
    ("英文名稱", "name_en"),
    ("課程類別", "course_type"),
    ("必選修", "requirement"),
    ("系所", "dept"),
    ("授課教師", "instructor"),
    ("學分", "credit"),
)

# Section labels appear exactly like this on one flat line (verified on the
# real page). Order matters: scanning stops a section at the next label hit.
_SECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("課程大綱 Course syllabus", "syllabus"),
    ("課程目標 Objectives", "objectives"),
    ("授課方式 Teaching methods", "teaching_methods"),
    ("評分方式﹝評分標準及比例﹞Evaluation (Criteria and ratio)", "evaluation"),
    ("參考書/教科書/閱讀文獻 Reference book/ textbook/ documents", "references"),
)

# Lines that terminate section accumulation (sub-headers stamped INSIDE a
# section, e.g. the letter-grade reference table header embedded under 評分).
_TERMINATORS: frozenset[str] = frozenset(
    {
        "等第制單科成績對照表 letter grading reference",
        "請先登錄",
        "請先登入",
    }
)

# English companion lines that follow a zh identity label on their own line;
# skipped so they never pollute the section stream.
_EN_COMPANIONS: frozenset[str] = frozenset(
    {
        "Course name(Chinese)",
        "Course name(English)",
        "Course Code",
        "Type of the course",
        "Required/Selected",
        "Dept./faculty",
        "Instructor",
        "Credit",
    }
)


@dataclass(frozen=True, slots=True)
class OutlineData:
    name_zh: str | None = None
    code: str | None = None
    name_en: str | None = None
    course_type: str | None = None
    requirement: str | None = None
    dept: str | None = None
    instructor: str | None = None
    credit: str | None = None
    semester_title: str | None = None
    syllabus: str | None = None
    objectives: str | None = None
    teaching_methods: str | None = None
    evaluation: str | None = None
    references: str | None = None


def _flatten(page_html: str) -> list[str]:
    """HTML -> clean non-empty text lines (comments stripped, entities decoded)."""
    text = _COMMENT_RE.sub(" ", page_html)
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ")
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = _TAG_RE.sub("\n", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = _MULTI_WS_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return lines


def parse_outline(page_html: str) -> OutlineData:
    """Structured outline from one showoutline.asp body (never raises)."""
    lines = _flatten(page_html)
    fields: dict[str, str] = {}
    identity_keys = {key for _label, key in _IDENTITY_LABELS}
    section_keys = {key for _label, key in _SECTION_LABELS}

    semester_title: str | None = None
    for line in lines:
        if "學年度" in line and "課程大綱" in line:
            semester_title = line
            break

    active: str | None = None
    buffer: dict[str, list[str]] = {}
    for index, line in enumerate(lines):
        identity_hit = next((key for label, key in _IDENTITY_LABELS if line == label), None)
        section_hit = next((key for label, key in _SECTION_LABELS if line == label), None)
        if identity_hit is not None:
            active = None
            # identity value = first following line that is not a label/en companion
            for follower in lines[index + 1 :]:
                if follower in _EN_COMPANIONS or follower in (l for l, _k in _IDENTITY_LABELS):
                    continue
                if next((True for l, _k in _SECTION_LABELS if follower == l), False):
                    break
                fields.setdefault(identity_hit, follower)
                break
            continue
        if section_hit is not None:
            active = section_hit
            continue
        if line in _TERMINATORS:
            active = None
            continue
        if active is not None:
            buffer.setdefault(active, []).append(line)

    for key in section_keys:
        if key in buffer:
            fields[key] = "\n".join(buffer[key])

    return OutlineData(
        semester_title=semester_title,
        **{key: fields.get(key) for key in identity_keys | section_keys},
    )
