"""Collect original job listings, one CSV per site and run."""

import csv
import logging
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from random import uniform
from time import sleep
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import BrowserContext, Page, sync_playwright


REQUIRED_FIELDS = (
    "title", "company", "location", "salary_raw", "experience_raw",
    "description", "requirements", "benefits",
)
OPTIONAL_FIELDS = ("skills_raw", "work_model_raw", "employment_type_raw", "posted_at_raw")
CONTENT_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
RAW_COLUMNS = ("job_id", "site", "URL_Goc", "Timestamp", *CONTENT_FIELDS, "keyword_search")
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
VN_TIME = timezone(timedelta(hours=7))
log = logging.getLogger(__name__)


class _CSVHTMLText(HTMLParser):
    line_break_tags = {
        "blockquote", "br", "dd", "div", "dt", "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "li", "ol", "p", "pre", "table", "tr", "ul",
    }

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.has_tags = False
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        self.has_tags = True
        if tag in {"script", "style"}:
            self.hidden = True
        elif tag in self.line_break_tags:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = False
        elif tag in self.line_break_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _csv_text(value: str | None) -> str | None:
    if not value or "<" not in value:
        return value
    parser = _CSVHTMLText()
    parser.feed(value)
    parser.close()
    if not parser.has_tags:
        return value
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def csv_display_row(row: dict[str, str | None]) -> dict[str, str | None]:
    """Format job text for CSV without changing the fields returned by the site parser."""
    return {**row, **{name: _csv_text(row[name]) for name in ("description", "requirements")}}


class JobUnavailable(Exception):
    """One detail could not be fetched or the site explicitly marks it as expired."""


@dataclass(frozen=True)
class JobLink:
    url: str
    source_id: str | None = None


@dataclass
class CrawlResult:
    path: Path
    saved: int = 0
    duplicates: int = 0
    failed: int = 0
    missing: Counter[str] = field(default_factory=Counter)


def _web_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError(f"Expected an absolute job or listing URL, got {url!r}")
    return url


class BaseCrawler(ABC):
    """Subclass with a site slug, a listing iterator and a detail parser."""

    site: str
    timeout_ms = 30_000
    delay_range = (1.0, 3.0)

    def __init__(self, raw_dir: Path = RAW_DIR, *, headless: bool = True):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.site):
            raise ValueError(f"Invalid site slug: {self.site!r}")
        self.raw_dir = Path(raw_dir)
        self.headless = headless

    @abstractmethod
    def iter_job_links(self, page: Page, keyword: str) -> Iterator[JobLink]:
        """Yield direct links. Use visit for navigation, pause before loading more.

        Wait for new results or the site's end signal. Raise on a broken listing.
        """

    @abstractmethod
    def parse_job(self, page: Page) -> dict[str, str | None]:
        """Verify the detail page, then return original fields (None if unpublished).

        Supply source_id here if unavailable on the listing. A site with no native
        ID may use its verified stable permalink as source_id. Keep combined JD
        sections in description. Raise JobUnavailable for a confirmed expired ad,
        and raise a parser error if the expected detail layout cannot be read.
        """

    def pause(self) -> None:
        """Pace site accesses. Each site waits separately for its content to load."""
        sleep(uniform(*self.delay_range))

    def configure_context(self, context: BrowserContext) -> None:
        """Apply site-specific browser settings before opening either tab."""

    def visit(self, page: Page, url: str) -> None:
        """Retry a temporary navigation failure once; stop on access restrictions."""
        _web_url(url)
        for attempt in range(2):
            self.pause()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except PlaywrightError as exc:
                if page.is_closed():
                    raise RuntimeError(f"Browser page closed while visiting {url}") from exc
                if attempt == 0:
                    continue
                raise JobUnavailable(f"Navigation failed for {url}: {exc}") from exc
            if response is None:
                raise JobUnavailable(f"No HTTP response for {url}")
            status = response.status
            if 200 <= status < 300:
                return
            if status in (401, 403, 429):
                raise RuntimeError(f"Access restricted: HTTP {status} for {url}")
            if status in (408, 500, 502, 503, 504) and attempt == 0:
                continue
            raise JobUnavailable(f"HTTP {status} for {url}")

    def _read_row(self, page: Page, link: JobLink, keyword: str) -> dict[str, str | None]:
        self.visit(page, link.url)
        try:
            fields = self.parse_job(page).copy()
            source_id = fields.pop("source_id", None)
            if source_id is not None and link.source_id is not None and source_id != link.source_id:
                raise ValueError(f"Conflicting listing/detail IDs: {link.source_id!r}, {source_id!r}")
            source_id = link.source_id if source_id is None else source_id
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("Missing stable source_id on both listing and detail")
            missing = set(REQUIRED_FIELDS).difference(fields)
            extra = fields.keys() - CONTENT_FIELDS
            if missing or extra:
                raise ValueError(f"Raw schema mismatch: missing={sorted(missing)}, unexpected={sorted(extra)}")
            for name, value in fields.items():
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{name} must contain raw text or None")
            if not any((fields[name] or "").strip() for name in REQUIRED_FIELDS):
                raise ValueError("All required content fields are empty")
            return {
                **fields, "job_id": f"{self.site}:{source_id}", "site": self.site,
                "URL_Goc": _web_url(page.url), "Timestamp": datetime.now(VN_TIME).isoformat(),
                "keyword_search": keyword,
            }
        except JobUnavailable:
            raise
        except Exception as exc:
            raise RuntimeError(f"Detail parser failed at {link.url}: {exc}") from exc

    def _collect(self, listing, detail, keywords, max_jobs, stream, result):
        writer = csv.DictWriter(stream, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        seen_ids, seen_urls = set(), set()
        for keyword in keywords:
            try:
                for link in self.iter_job_links(listing, keyword):
                    if link.url in seen_urls or (
                        link.source_id is not None and f"{self.site}:{link.source_id}" in seen_ids
                    ):
                        result.duplicates += 1
                        continue
                    try:
                        row = self._read_row(detail, link, keyword)
                    except JobUnavailable as exc:
                        result.failed += 1
                        log.warning("%s [%s] skipping %s: %s", self.site, keyword, link.url, exc)
                        continue
                    if row["job_id"] in seen_ids:
                        seen_urls.add(link.url)
                        result.duplicates += 1
                        continue
                    writer.writerow(csv_display_row(row))
                    stream.flush()
                    seen_ids.add(row["job_id"])
                    seen_urls.update((link.url, row["URL_Goc"]))
                    result.saved += 1
                    result.missing.update(k for k in CONTENT_FIELDS if not (row.get(k) or "").strip())
                    if result.saved == max_jobs:
                        return
            except Exception as exc:
                raise RuntimeError(f"{self.site} [{keyword}], listing {listing.url}: {exc}") from exc
        if result.failed and not result.saved:
            raise RuntimeError(f"{self.site}: all {result.failed} detail attempts failed; see warnings")

    def run(self, keywords: Iterable[str], max_jobs: int | None = None) -> CrawlResult:
        """Write one snapshot. max_jobs counts saved unique jobs across all keywords."""
        if max_jobs is not None and (type(max_jobs) is not int or max_jobs < 1):
            raise ValueError("max_jobs must be a positive integer or None")
        if isinstance(keywords, str):
            raise ValueError("Pass a collection of keywords, e.g. ['SQL']")
        keywords = tuple(keywords)
        if not keywords or any(not isinstance(k, str) or not k.strip() for k in keywords):
            raise ValueError("Provide at least one keyword; each must be non-empty text")

        directory = self.raw_dir / self.site
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(VN_TIME).strftime("%Y%m%dT%H%M%S")
        path = directory / f"{self.site}_{stamp}_{uuid4().hex}.csv"
        partial = path.with_suffix(".csv.part")
        result = CrawlResult(path)
        with partial.open("x", encoding="utf-8-sig", newline="") as stream:
            try:
                with sync_playwright() as pw, ExitStack() as cleanup:
                    browser = pw.chromium.launch(headless=self.headless)
                    cleanup.callback(browser.close)
                    context = browser.new_context()
                    cleanup.callback(context.close)
                    context.set_default_timeout(self.timeout_ms)
                    self.configure_context(context)
                    self._collect(context.new_page(), context.new_page(), keywords, max_jobs, stream, result)
            except Exception as exc:
                raise RuntimeError(f"Crawl interrupted; partial output {partial}: {exc}") from exc
        partial.rename(path)
        return result
