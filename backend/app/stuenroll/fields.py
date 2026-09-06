"""Login-form scraping for the stu_enroll family (M1).

Same discipline as scripts/capture/formparse: stdlib ``html.parser`` only.
Collected per page: all inputs in document order, the form action, and captcha
``<img>`` srcs - the captcha answer binds to the session that ISSUED the image,
so the login flow must fetch the BMP on the same jar lineage it posts with.
"""

from html.parser import HTMLParser


class FormScrape(HTMLParser):
    """Inputs (name, type, value), first form action, and captcha img srcs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[tuple[str, str, str]] = []
        self.action: str | None = None
        self.captcha_srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value if value is not None else "") for name, value in attrs}
        if tag == "form" and self.action is None and values.get("action"):
            self.action = values["action"]
        elif tag == "input" and values.get("name"):
            self.inputs.append(
                (values["name"], values.get("type", "text").lower(), values.get("value", ""))
            )
        elif tag == "img" and values.get("src") and "validcode" in values["src"].lower():
            self.captcha_srcs.append(values["src"])


def scrape_page(html_text: str) -> FormScrape:
    parser = FormScrape()
    parser.feed(html_text)
    parser.close()
    return parser
