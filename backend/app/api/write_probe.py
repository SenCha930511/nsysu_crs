"""Fresh school probe behind POST /api/write/preview (plan todo 14).

One call = one GET Studfun (+ same-session form GET when a write-form link
exists), never cached: failure routing is 401 on a login bounce, 503 on
unrecognized school behaviour; everything else comes back as a StageProbe
the route maps to 409 / proceeds with.
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin

from fastapi import status
from fastapi.exceptions import HTTPException

from app.selcrs.endpoints import SELCRS_BASE_URL, get_studfun, get_write_form
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.jar import SelcrsJar
from app.stage.detect import StudfunDetection, detect_need_confirmation, parse_studfun

ERR_EXPIRED: Final = "SELCRS_EXPIRED"
ERR_SCHOOL: Final = "school_unavailable"

_STUDFUN_URL: Final = f"{SELCRS_BASE_URL}/menu4/Studfun.asp"


@dataclass(frozen=True, slots=True)
class StageProbe:
    """A live probe outcome: detection + the form page (None when closed)."""

    detection: StudfunDetection
    form_html: str | None
    form_url: str | None
    need_confirmation: bool


async def probe_stage(cookies: SelcrsJar) -> StageProbe:
    """Fresh Studfun + form fetch (seams follow the repo's monkeypatch style:
    adapters imported INTO this module's namespace)."""
    try:
        detection = parse_studfun(await get_studfun(cookies))
        form_html: str | None = None
        form_url: str | None = None
        need_confirmation = False
        if detection.form_href is not None:
            form_url = urljoin(_STUDFUN_URL, detection.form_href)
            form_html = await get_write_form(cookies, form_url)
            need_confirmation = detect_need_confirmation(form_html)
        return StageProbe(detection, form_html, form_url, need_confirmation)
    except SelcrsSessionExpired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
