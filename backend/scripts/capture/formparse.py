"""Form scraping + byte-exact submit-body building for the capture kit.

Stdlib ``html.parser`` only: the kit must stay dependency-free beyond what the
backend already pins, and classic-ASP form pages are structurally simple.

Encoding contract: classic ASP expects Big5 percent-encoding for non-ASCII
form values (in particular the ``send`` submit button, whose value is the
Chinese label 提交). ``build_submit_body`` therefore URL-encodes with
``encoding="big5"`` so the captured request body is byte-identical to what a
browser on a Big5 page would send - that byte identity is the whole point of
the carry-over probe (replaying body #1 verbatim must actually be verbatim).
"""

from html.parser import HTMLParser
from urllib.parse import urlencode

FORM_TEXT_ENCODING = "big5"


class FormScrape(HTMLParser):
    """Collect anchor hrefs, form actions and hidden inputs (in document order)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.form_actions: list[str] = []
        self.hidden: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value if value is not None else "") for name, value in attrs}
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "form" and values.get("action"):
            self.form_actions.append(values["action"])
        elif tag == "input" and values.get("type", "").lower() == "hidden":
            if values.get("name"):
                self.hidden.append((values["name"], values.get("value", "")))


def scrape_form(html: str) -> FormScrape:
    parser = FormScrape()
    parser.feed(html)
    parser.close()
    return parser


def find_write_link(scrape: FormScrape) -> str | None:
    """First ssform/stage5 add-drop form link on a Studfun-style page."""
    for href in scrape.links:
        if "ssform.asp" in href or "saddstage5.asp" in href:
            return href
    return None


def build_submit_body(hidden: list[tuple[str, str]], overrides: list[tuple[str, str]]) -> str:
    """Form-replay submit body: hidden inputs verbatim, plus D/C/T overrides.

    Any hidden input whose name collides with an override is replaced (the
    override wins), matching browser submit semantics of "the value the user
    set". Ordering is deterministic: surviving hidden inputs in document
    order, then the overrides in the order given, so two runs building the
    same logical submission produce byte-identical bodies.
    """
    override_names = {name for name, _ in overrides}
    pairs = [pair for pair in hidden if pair[0] not in override_names]
    pairs.extend(overrides)
    return urlencode(pairs, encoding=FORM_TEXT_ENCODING)


def looks_like_login_page(html: str) -> bool:
    """Heuristic liveness check: was our session bounced back to a login form?"""
    return "SPassword" in html or "stuid" in html or "Studcheck" in html
