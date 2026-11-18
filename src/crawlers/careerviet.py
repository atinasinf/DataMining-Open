"""CareerViet public job pages, inspected on 2026-11-18.

Run from the project root with python -m src.crawlers.careerviet --max-jobs 3.
Search routes serve initial HTML; the site's pagination UI also uses fetch.
This crawler visits those routes and waits for result/empty-state DOM signals.
Description and requirements retain source HTML for downstream text cleaning.
"""

import argparse
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeout

from .base import BaseCrawler, JobLink, RAW_DIR


KEYWORDS = (
    "Data Science", "Data Analytics", "AI", "Machine Learning", "DevOps / Cloud",
    "Python", "SQL", "PyTorch",
)
ORIGIN = "https://careerviet.vn"
JOB_PATH = re.compile(r"/vi/tim-viec-lam/[^/]+\.([0-9a-f]{8})\.html", re.I)
RESULT_LINKS = "#jobs-side-list-content .job-item .title a.job_link"
EMPTY_RESULTS = ".job-list-no-result__message"
ERROR_HEADING = 'h2:has-text("Rất tiếc, không tìm thấy trang")'
log = logging.getLogger(__name__)


def job_link(href: str, origin: str = ORIGIN) -> JobLink:
    """The URL token is corroborated by data-id and JobPosting.identifier.value."""
    url = urljoin(origin, href)
    parts = urlsplit(url)
    match = JOB_PATH.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc != "careerviet.vn" or match is None:
        raise ValueError(f"Unexpected CareerViet job URL: {url}")
    return JobLink(ORIGIN + parts.path, match[1].upper())


def _text(locator: Locator) -> str | None:
    if locator.count() == 0:
        return None
    # inner_text preserves line boundaries and the source's spelling and units.
    return locator.inner_text().strip() or None


class CareerVietCrawler(BaseCrawler):
    site = "careerviet"

    def configure_context(self, context: BrowserContext) -> None:
        # Main-host robots disallows /api/*; internal-api is a separate host.
        context.route("https://careerviet.vn/api/**", lambda route: route.abort())

    def _wait_content(self, page: Page, selector: str, *, state="visible") -> None:
        try:
            page.locator(f"{selector}, {ERROR_HEADING}").first.wait_for(state=state, timeout=self.timeout_ms)
        except PlaywrightTimeout as exc:
            raise RuntimeError(f"CareerViet content did not load or layout changed: {page.url}") from exc
        if page.locator(ERROR_HEADING).count():
            # This same error screen also appears when a background request fails.
            raise RuntimeError(f"CareerViet returned an error page: {page.url}")

    def iter_job_links(self, page: Page, keyword: str) -> Iterator[JobLink]:
        # CareerViet's own search form maps 'DevOps / Cloud' to 'devops--cloud'.
        slug = quote(keyword.lower().replace("/", "").replace(" ", "-"), safe="-")
        search = f"{ORIGIN}/viec-lam/{slug}-k"
        number = 1
        signatures = set()
        while True:
            suffix = "-vi.html" if number == 1 else f"-trang-{number}-vi.html"
            expected = search + suffix
            self.visit(page, expected)
            if page.url.split("?")[0] != expected:
                raise RuntimeError(f"Search redirected unexpectedly: {expected} -> {page.url}")
            self._wait_content(page, f"{RESULT_LINKS}, {EMPTY_RESULTS}")
            if page.locator(EMPTY_RESULTS).count():
                log.info("CareerViet [%s] page %s has no results", keyword, number)
                return

            links = []
            for anchor in page.locator(RESULT_LINKS).all():
                href = anchor.get_attribute("href")
                if not href:
                    raise ValueError(f"Job link has no href: {page.url}")
                link = job_link(href, page.url)
                native_id = anchor.get_attribute("data-id")
                if native_id and native_id.upper() != link.source_id:
                    raise ValueError(f"Listing data-id disagrees with URL: {link.url}")
                links.append(link)
            signature = frozenset(link.source_id for link in links)
            if not signature or signature in signatures:
                raise RuntimeError(f"Empty or repeated result page: {page.url}")
            signatures.add(signature)
            log.info("CareerViet [%s] page %s: %s listings", keyword, number, len(links))
            yield from links

            self._wait_content(page, ".pagination", state="attached")
            if page.locator(".pagination .next-page").count() == 0:
                return
            active = _text(page.locator(".pagination .active"))
            if active != str(number):
                raise RuntimeError(f"Pagination state changed at {page.url}: active={active!r}")
            number += 1

    def parse_job(self, page: Page) -> dict[str, str | None]:
        link = job_link(page.url)
        self._wait_content(page, ".job-desc-main h1.title")
        try:
            posting_node = page.locator('script#job-posting-schema[type="application/ld+json"]')
            posting_node.wait_for(state="attached", timeout=self.timeout_ms)
            posting = json.loads(posting_node.text_content())
            if posting.get("@type") != "JobPosting":
                raise ValueError("Expected JobPosting structured data")
            source_id = posting.get("identifier", {}).get("value")
            if source_id is not None and str(source_id).upper() != link.source_id:
                raise ValueError("JobPosting ID disagrees with detail URL")
            if posting.get("url") and job_link(posting["url"]).source_id != link.source_id:
                raise ValueError("JobPosting URL refers to a different job")

            content = page.locator("section.job-detail-content")
            content.wait_for(timeout=self.timeout_ms)
            sections = {}
            for row in content.locator(":scope > .detail-row").all():
                heading = _text(row.locator(":scope > .detail-title"))
                if heading:
                    sections[heading.casefold()] = row

            fields = {
                "source_id": link.source_id,
                "title": _text(page.locator(".job-desc-main h1.title")),
                "company": _text(page.locator(".job-desc-main .job-company-name")),
                "salary_raw": _text(page.locator(".job-desc-main .meta-salary")),
                "location": None,
                "experience_raw": None,
                "description": None,
                "requirements": None,
                "benefits": None,
                "skills_raw": posting.get("skills") or None,
                "employment_type_raw": None,
                "work_model_raw": None,
                # datePosted is explicitly published in JSON-LD; 'Ngày cập nhật' is separate.
                "posted_at_raw": posting.get("datePosted") or None,
            }
            if not fields["title"] or not fields["company"]:
                raise ValueError("Missing job title/company; detail layout cannot be confirmed")
            for label, field in (("mô tả công việc", "description"), ("yêu cầu công việc", "requirements")):
                if label in sections:
                    body = sections[label].locator(":scope > div")
                    if body.count() != 1:
                        raise ValueError(f"Cannot read {label} content")
                    fields[field] = body.inner_html() if _text(body) else None
            if not fields["description"] and not fields["requirements"]:
                raise ValueError("No readable JD/requirements; detail layout cannot be confirmed")
            if "phúc lợi" in sections:
                welfare = sections["phúc lợi"].locator(".welfare-list")
                if welfare.count() != 1:
                    raise ValueError("Cannot read benefits content")
                fields["benefits"] = _text(welfare)

            places = content.locator(".info-place-detail .place-name")
            if places.count():
                fields["location"] = "\n".join(places.all_inner_texts()).strip() or None
            else:
                fields["location"] = _text(page.locator(".job-desc-main .meta-location-text"))
            for item in page.locator(".job-overview-item").all():
                label = _text(item.locator(".overview-label"))
                if label and label.casefold() in ("kinh nghiệm", "hình thức"):
                    value = item.locator(".overview-value")
                    if value.count() != 1:
                        raise ValueError(f"Missing value element for {label}")
                    field = "experience_raw" if label.casefold() == "kinh nghiệm" else "employment_type_raw"
                    fields[field] = _text(value)
            return fields
        except Exception as exc:
            raise RuntimeError(f"CareerViet detail parser failed at {page.url}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", action="append", choices=KEYWORDS, help="Repeat to select keywords; default is all eight")
    parser.add_argument("--max-jobs", type=int, help="Total successfully saved unique jobs for this run")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = CareerVietCrawler(args.raw_dir, headless=not args.headed).run(args.keyword or KEYWORDS, args.max_jobs)
    print(f"{result.path}\nSaved={result.saved}, duplicates={result.duplicates}, failed={result.failed}")


if __name__ == "__main__":
    main()
