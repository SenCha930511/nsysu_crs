"""Form-replay payload builders (plan todo 14, consumed by todo 15's worker).

Replay model (patch-over-scraped-form, plan todo 14 References): instead of
synthesizing a POST body from scratch, the write path GETs the real form
page in the SAME school session, parses every hidden input, replays those
values VERBATIM, and overwrites only the D/C/T row slots:

- ``D1..Dn``  = ``+`` / ``-`` / ``N`` (add / drop / rest),
- ``C1..Cn``  = the 8-char school course code (empty on rest rows; the
  fixture's client-side ``check(f)`` rejects ``D!=N`` with empty ``C``),
- ``T1..Tn``  = priority zero-padded to 2 chars for ``+`` rows; EMPTY for
  ``-`` rows and rest rows ("'-' rows cleared").

Everything else is preserved from the scraped form: ``MAX_ADD`` (which also
sets the row count: 15 for ssform, 10 for stage5), ``step`` (2 = 加退選 at
ssform; per-stage at stage5 - the provisional stage5 form carries 1),
``send=提交`` (the form's submit-button value), and the identity params
``X1/X2/DEG_COD/college/dept/grade/SCH_COD/USE_YR/EDU`` - all taken from the
FORM itself; Studfun link params are only a fallback the CALLER merges in
when the form lacks a key (the builders never reach past ``hidden``).

志願/點數 semantics: T today carries 志願 1-20 (志願制: 初選2 +
加退選1/2 - checked as int 1-20 at the preview boundary). 初選1's 點數
0-100 (points-system, bachelor general-education only) has NO archaeological
form evidence (``.omo/drafts`` key_facts; plan pins it behind
FEATURE_FIRST_ROUND_WRITE) - it stays out of reach here; the zero-pad rule
of this module is locked for the 1-20 surface only.

``ops`` must arrive in CANONICAL order (``app.write.canonical``): ``-``
before ``+`` - the same deterministic row layout the worker will re-derive
at submit time, so the previewed payload is byte-identical to the one being
confirmed.
"""

from collections.abc import Sequence
from typing import Final

from bs4 import BeautifulSoup

from app.write.canonical import CanonicalOp

#: Row counts per variant (plan: ssform 15 rows / stage5 10 rows, mirrored
#: by the fixtures' MAX_ADD hidden inputs). Fallback only when the scraped
#: form itself lacks MAX_ADD.
SSPRS_ROWS: Final = 15
STAGE5_ROWS: Final = 10

#: The submission button name/value pinned by the archaeological key_facts;
#: the scraped form's own <input type=submit name=send> value wins when
#: present (they are the same 提交 on both provisional fixtures).
SEND_NAME: Final = "send"
SEND_DEFAULT: Final = "提交"


def parse_form_hidden_inputs(html: str) -> dict[str, str]:
    """Every ``<input type="hidden">`` as name -> value, first-wins.

    This is THE replay source: only hidden inputs (never selects/text fields,
    whose D/C/T slots the builders own). A duplicated name keeps its first
    occurrence (classic ASP forms here never duplicate hidden names).
    """
    soup = BeautifulSoup(html, "html.parser")
    hidden: dict[str, str] = {}
    for tag in soup.find_all("input"):
        input_type = str(tag.get("type", "")).lower()
        if input_type != "hidden":
            continue
        name = tag.get("name")
        if not isinstance(name, str) or not name or name in hidden:
            continue
        value = tag.get("value", "")
        hidden[name] = value if isinstance(value, str) else " ".join(str(v) for v in value)
    return hidden


def parse_form_action(html: str) -> str | None:
    """The submit URL (``action``) of the write form, verbatim as scraped.

    The replay model posts where the FORM says to post (ssprs.asp /
    saddstage5prs.asp, resolved against the same-session form URL by the
    caller with ``urljoin``) - the endpoint is school state, never a constant
    this codebase asserts (plan todo 14: patch-over-scraped-form).
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("form"):
        action = tag.get("action")
        if isinstance(action, str) and action.strip():
            return action.strip()
        if isinstance(action, list) and action:
            candidate = str(action[0]).strip()
            return candidate or None
    return None


def parse_send_value(html: str) -> str | None:
    """Value of the form's ``<input type="submit" name="send">`` (提交), if any."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("input"):
        if str(tag.get("type", "")).lower() != "submit":
            continue
        if tag.get("name") != SEND_NAME:
            continue
        value = tag.get("value")
        return value if isinstance(value, str) else None
    return None


def _rows_total(hidden: dict[str, str], default_rows: int) -> int:
    raw = hidden.get("MAX_ADD")
    if raw is not None and raw.isdigit():
        return int(raw)
    return default_rows


def _build(ops: Sequence[CanonicalOp], hidden: dict[str, str], default_rows: int) -> dict[str, str]:
    rows = _rows_total(hidden, default_rows)
    if len(ops) > rows:
        raise ValueError(f"{len(ops)} ops exceed the form's {rows} rows")
    # VERBATIM replay of every non-D/C/T hidden field first...
    payload = dict(hidden)
    # ...then the D/C/T slots are owned by the ops (rest rows: N + cleared).
    for row in range(1, rows + 1):
        op = ops[row - 1] if row <= len(ops) else None
        payload[f"D{row}"] = op.action if op is not None else "N"
        payload[f"C{row}"] = op.code if op is not None else ""
        if op is not None and op.action == "+":
            payload[f"T{row}"] = f"{op.priority:02d}" if op.priority is not None else ""
        else:
            payload[f"T{row}"] = ""  # '-' rows and rest rows: T cleared
    payload[SEND_NAME] = hidden.get(SEND_NAME, SEND_DEFAULT)
    return payload


def build_payload_ssprs(ops: Sequence[CanonicalOp], hidden: dict[str, str]) -> dict[str, str]:
    """加退選 payload for ssprs.asp (ssform.asp replay, 15 rows by default)."""
    return _build(ops, hidden, SSPRS_ROWS)


def build_payload_stage5(ops: Sequence[CanonicalOp], hidden: dict[str, str]) -> dict[str, str]:
    """初選志願 payload for stage5/saddstage5prs.asp (10 rows by default)."""
    return _build(ops, hidden, STAGE5_ROWS)
