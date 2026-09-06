"""Feature parsers for the stu_enroll family (M1) - fixture-driven, drift-safe.

Shapes below come from the 2026-09-04 live captures
(tests/fixtures/stuenroll_*_live_1151); a page that loses its anchors raises
SelcrsUnavailable (breaker path) rather than answering with invented data.
"""

import re
from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup

from app.selcrs.errors import SelcrsUnavailable


@dataclass(frozen=True, slots=True)
class PaymentBill:
    """One TWD bill row from tfstudata's 繳費單 table."""

    item: str
    amount: str
    status: str
    pay_date: str
    receipt_href: str | None


@dataclass(frozen=True, slots=True)
class PaymentPage:
    dept: str
    bills: tuple[PaymentBill, ...]


_BILL_HEADER_MARKERS: Final = ("單據名稱", "應繳金額", "繳費狀態")
_ONCLICK_HREF_RE: Final = re.compile(r"location\.href='([^']+)'")


def parse_payment_bills(html: str) -> PaymentPage:
    """Parse tfstudata.asp?act=11 (繳費單管理): dept + TWD bill rows."""
    soup = BeautifulSoup(html, "html.parser")
    header_row = next(
        (
            row
            for row in soup.find_all("tr")
            if all(marker in row.get_text() for marker in _BILL_HEADER_MARKERS)
        ),
        None,
    )
    if header_row is None:
        raise SelcrsUnavailable("tfstudata carries no bill-table header row")
    dept = ""
    dept_td = soup.find(lambda tag: tag.name == "td" and "系所" in tag.get_text())
    if dept_td is not None and dept_td.parent is not None:
        values = [
            td.get_text(" ", strip=True)
            for td in dept_td.parent.find_all("td")
            if "系所" not in td.get_text() and td.get_text(strip=True) not in ("", "：")
        ]
        dept = values[0].split("(INSTITUTE")[0].strip() if values else ""

    bills: list[PaymentBill] = []
    for row in header_row.find_all_next("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        texts_row = [cell.get_text(" ", strip=True) for cell in cells]
        receipt_href: str | None = None
        for anchor in row.find_all("a"):
            onclick = anchor.get("onclick")
            match = _ONCLICK_HREF_RE.search(onclick) if isinstance(onclick, str) else None
            href_value = anchor.get("href")
            if match:
                receipt_href = match.group(1)
            elif isinstance(href_value, str) and href_value != "#":
                receipt_href = href_value
        item_parts = texts_row[0].split()
        status_parts = texts_row[2].split()
        bills.append(
            PaymentBill(
                item=item_parts[0] if item_parts else "",
                amount=texts_row[1].replace("\xa0", " ").strip(),
                status=status_parts[0] if status_parts else "",
                pay_date=texts_row[3],
                receipt_href=receipt_href,
            )
        )
    return PaymentPage(dept=dept, bills=tuple(bills))


@dataclass(frozen=True, slots=True)
class ScoMenuLink:
    """One menu entry from the sco grades menu frame."""

    title: str
    url: str
    action: str | None
    kind: str | None


def parse_sco_menu(html: str) -> tuple[ScoMenuLink, ...]:
    """Parse the sco_query.asp?action=1 menu frame into feature links."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[ScoMenuLink] = []
    for anchor in soup.find_all("a", href=True):
        href_value = anchor.get("href")
        if not isinstance(href_value, str):
            continue
        href = href_value
        if "sco_query.asp?" not in href or "action=" not in href:
            continue
        action = kind = None
        for part in href.split("?", 1)[1].split("&"):
            name, _, value = part.partition("=")
            if name == "action":
                action = value
            elif name == "KIND":
                kind = value
        title = anchor.get_text(" ", strip=True)
        if title:
            links.append(ScoMenuLink(title=title, url=href, action=action, kind=kind))
    if not links:
        raise SelcrsUnavailable("sco menu frame carries no sco_query action links")
    return tuple(links)


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """One regweb registration-checklist row."""

    title: str
    period: str
    status_text: str
    out_url: str | None


@dataclass(frozen=True, slots=True)
class RegwebChecklist:
    items: tuple[ChecklistItem, ...]
    enrollcert_present: bool


_RELAY_HREF_MARK: Final = "WRegMain3.asp?act=71&out="
_ENROLLCERT_MARK: Final = "print/enrollcert.asp"


def parse_regweb_checklist(html: str) -> RegwebChecklist:
    """Parse WRegMain3.asp?act=11: checklist rows + the enrollcert button flag."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[ChecklistItem] = []
    for anchor in soup.find_all("a", href=True):
        href_value = anchor.get("href")
        if not isinstance(href_value, str):
            continue
        href = href_value
        if _RELAY_HREF_MARK not in href:
            continue
        row = anchor.find_parent("tr")
        cells = row.find_all("td", recursive=False) if row is not None else []
        if len(cells) < 2:
            continue
        title = anchor.get_text(" ", strip=True)
        period = cells[1].get_text(" ", strip=True)
        status_text = ""
        for cell in cells[2:]:
            text = cell.get_text(" ", strip=True).replace(" ", " ")
            if "完成" in text or "未完成" in text:
                status_text = text.split("(")[0].strip()
                break
        items.append(
            ChecklistItem(title=title, period=period, status_text=status_text, out_url=href)
        )
    if not items:
        raise SelcrsUnavailable("regweb main carries no act=71 checklist relays")
    return RegwebChecklist(
        items=tuple(items), enrollcert_present=_ENROLLCERT_MARK in html
    )


@dataclass(frozen=True, slots=True)
class GradesPage:
    """sco rpt-page rows as VERBATIM cell-text tuples (no column semantics are
    assumed yet: with-rows fixtures ship in a later capture round, then this
    parser grows field extraction). Empty for a legitimate zero-rows account -
    the 115-1 shell (title 成績查詢 + sco_qry_rpt.css, empty <center>) is a
    page shape, not drift.
    """

    rows: tuple[tuple[str, ...], ...]


_GRADES_SHELL_TITLE_MARK: Final = "成績查詢"
_GRADES_SHELL_CSS_MARK: Final = "sco_qry_rpt.css"


def parse_grades_history(html: str) -> GradesPage:
    """Parse sco_query.asp?action=811&KIND=3: shell markers gate recognition,
    any present table's rows come out verbatim (header row included, if any)."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text() if soup.title is not None else ""
    if _GRADES_SHELL_TITLE_MARK not in title or _GRADES_SHELL_CSS_MARK not in html:
        raise SelcrsUnavailable("sco history page lost its rpt-shell markers")
    rows: list[tuple[str, ...]] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if cells:
                rows.append(tuple(cells))
    return GradesPage(rows=tuple(rows))
