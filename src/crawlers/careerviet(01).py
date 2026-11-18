"""CareerViet public job pages, inspected on 2026-11-18.

Run from the project root: python -m "src.crawlers.careerviet(01)" --max-jobs 20.
Search routes serve initial HTML; the site's pagination UI also uses fetch.
This crawler visits those routes and waits for result/empty-state DOM signals.
Description and requirements retain source HTML for downstream text cleaning.
"""

import argparse
import json
import logging
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeout

from .base import BaseCrawler, JobLink, JobUnavailable, RAW_DIR, VN_TIME


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
POSTING = 'script#job-posting-schema[type="application/ld+json"]'
TRACKERS = ('google-analytics.com', 'googletagmanager.com', 'doubleclick.net',
            'connect.facebook.net', 'criteo.com', 'creativecdn.com', 'netcoresmartech.com')


class DetailParseError(JobUnavailable, RuntimeError):
    """Unreadable individual ad; logged and skipped with a consecutive-error cap."""


class ContentTimeout(RuntimeError):
    """Content still absent after one paced reload."""


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
    if locator.count() != 1:
        raise ValueError('Ambiguous raw field: multiple matching elements')
    # inner_text preserves line boundaries and the source's spelling and units.
    return locator.inner_text().strip() or None


class CareerVietCrawler(BaseCrawler):
    site = "careerviet"
    max_consecutive_failures = 10

    def configure_context(self, context: BrowserContext) -> None:
        def route_request(route):
            request = route.request
            parts = urlsplit(request.url)
            host = parts.hostname or ''
            # Keep scripts/XHR needed by the site; robots applies per host.
            blocked = (host == 'careerviet.vn' and parts.path.startswith('/api/'))
            blocked |= request.resource_type in {'image', 'media', 'font'}
            blocked |= any(host == domain or host.endswith('.' + domain) for domain in TRACKERS)
            route.abort() if blocked else route.fallback()
        context.route('**/*', route_request)

    def _check_access(self, page):
        if page.is_closed():
            raise RuntimeError('Browser page closed')
        headings = ' '.join(page.locator('h1, h2').all_inner_texts()).casefold()
        title = page.title().casefold()
        challenge = page.locator('#challenge-running, #challenge-stage, iframe[src*="captcha"]:visible')
        if challenge.count() or any(text in title + ' ' + headings for text in (
            'access denied', 'verify you are human', 'just a moment', 'xác minh bạn là con người',
        )):
            raise RuntimeError(f'Access challenge detected: {page.url}')

    def visit(self, page, url):
        super().visit(page, url)
        self._check_access(page)
        if urlsplit(url).path.startswith('/viec-lam/') and page.url.split('?')[0] != url.split('?')[0]:
            raise RuntimeError(f'Search redirected unexpectedly: {url} -> {page.url}')
        if JOB_PATH.fullmatch(urlsplit(url).path):
            try:
                same_job = job_link(page.url).source_id == job_link(url).source_id
            except ValueError:
                same_job = False
            if not same_job:
                raise RuntimeError(f'Detail redirected unexpectedly: {url} -> {page.url}')

    def _wait_content(self, page: Page, selector: str, *, state="visible") -> None:
        for attempt in range(2):
            self._check_access(page)
            try:
                page.locator(f"{selector}, {ERROR_HEADING}").first.wait_for(state=state, timeout=self.timeout_ms)
                break
            except PlaywrightTimeout as exc:
                self._check_access(page)
                if attempt:
                    raise ContentTimeout(f"CareerViet content did not load or layout changed: {page.url}") from exc
                log.warning('Content timeout; retrying once: %s', page.url)
                self.visit(page, page.url)
        self._check_access(page)
        if page.locator(ERROR_HEADING).count():
            # This same error screen also appears when a background request fails.
            raise DetailParseError(f"CareerViet returned an error page: {page.url}")

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
        try:
            self._wait_content(page, POSTING, state="attached")
            posting_node = page.locator(POSTING)
            if posting_node.count() != 1:
                raise ValueError('Expected exactly one JobPosting block')
            posting = json.loads(posting_node.text_content())
            if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
                raise ValueError("Expected JobPosting structured data")
            source_id = posting.get("identifier", {}).get("value")
            if source_id is not None and str(source_id).upper() != link.source_id:
                raise ValueError("JobPosting ID disagrees with detail URL")
            if posting.get("url") and job_link(posting["url"]).source_id != link.source_id:
                raise ValueError("JobPosting URL refers to a different job")

            standard = page.locator(".job-desc-main h1.title").count() > 0
            if standard or page.locator('section.template .caption .title h2').count():
                self._wait_content(page, 'section.job-detail-content .detail-title, section.template .detail-row .detail-title')
            content = page.locator("section.job-detail-content" if standard else "section.template")
            sections = {}
            for row in content.locator(".detail-row").all():
                heading = _text(row.locator(":scope > .detail-title"))
                if heading:
                    key = heading.casefold()
                    if key in sections:
                        raise ValueError(f"Ambiguous detail section: {heading}")
                    sections[key] = row

            def published_text(value):
                if value is not None and not isinstance(value, str):
                    raise ValueError('Expected published text in JobPosting')
                return value if value and value.strip() else None

            fields = {
                "source_id": link.source_id,
                "title": _text(page.locator(".job-desc-main h1.title" if standard else "section.template .caption .title h2")) or published_text(posting.get('title')),
                "company": _text(page.locator(".job-desc-main .job-company-name" if standard else "section.template .caption a.company")) or published_text(posting.get('hiringOrganization', {}).get('name')),
                "salary_raw": _text(page.locator(".job-desc-main .meta-salary")),
                "location": None,
                "experience_raw": None,
                "description": None,
                "requirements": None,
                "benefits": None,
                # SEO skills includes suggested job titles; it is not a skills section.
                "skills_raw": None,
                "employment_type_raw": None,
                "work_model_raw": None,
                # datePosted is explicitly published in JSON-LD; 'Ngày cập nhật' is separate.
                "posted_at_raw": published_text(posting.get("datePosted")),
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
                if content.count():
                    raise ValueError("No readable JD/requirements; detail layout cannot be confirmed")
                # Unknown templates may publish a combined JD. Preserve it unsplit.
                if source_id is None:
                    raise ValueError('Cannot confirm JSON-LD fallback identity')
                fields['description'] = published_text(posting.get('description'))
                if not fields['description'] or not page.evaluate('(html) => { const d = new DOMParser().parseFromString(html, "text/html"); return !!d.body.textContent.trim(); }', fields['description']):
                    raise ValueError('No readable JD/requirements in JSON-LD fallback')
                log.warning('JSON-LD combined JD fallback; separate raw fields may be missing: %s', page.url)
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
            for row in content.locator('table tr').all():
                label = _text(row.locator('td.name'))
                field = {'lương': 'salary_raw', 'kinh nghiệm': 'experience_raw',
                         'hình thức': 'employment_type_raw', 'địa điểm': 'location'}.get((label or '').casefold())
                if field and not fields[field]:
                    value = row.locator('td.content')
                    if value.count() != 1:
                        raise ValueError(f'Missing value element for {label}')
                    fields[field] = _text(value)
            return fields
        except (ValueError, TypeError, AttributeError, PlaywrightTimeout, ContentTimeout) as exc:
            raise DetailParseError(f"CareerViet detail parser failed at {page.url}: {exc}") from exc

    def _read_row(self, page, link, keyword):
        try:
            row = super()._read_row(page, link, keyword)
        except JobUnavailable as exc:
            self._consecutive_failures += 1
            failure = {'URL_Goc': link.url, 'source_id': link.source_id,
                       'keyword_search': keyword, 'Timestamp': datetime.now(VN_TIME).isoformat(),
                       'error': str(exc)}
            self._failure_stream.write(json.dumps(failure, ensure_ascii=False) + '\n')
            self._failure_stream.flush()
            if self._consecutive_failures >= self.max_consecutive_failures:
                raise RuntimeError(f'Stopping after {self._consecutive_failures} consecutive detail failures; last URL: {link.url}') from exc
            raise
        self._consecutive_failures = 0
        log.info('Read %s [%s]: %s', row['job_id'], keyword, row['title'])
        return row

    def _collect(self, listing, detail, keywords, max_jobs, stream, result):
        self._consecutive_failures = 0
        failures = result.path.with_suffix('.failures.jsonl')
        with failures.open('x', encoding='utf-8') as self._failure_stream:
            try:
                super()._collect(listing, detail, keywords, max_jobs, stream, result)
            except KeyboardInterrupt:
                log.warning('Stopped by Ctrl+C; saved=%s, partial CSV: %s; failure log: %s',
                            result.saved, result.path.with_suffix('.csv.part'), failures)
                raise
            finally:
                if self._failure_stream.tell():
                    log.warning('Failed detail URLs recorded in %s', failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", action="append", choices=KEYWORDS, help="Repeat to select keywords; default is all eight")
    parser.add_argument("--max-jobs", type=int, help="Total successfully saved unique jobs for this run")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--log-file", type=Path, help="Write a UTF-8 log as well as console output")
    args = parser.parse_args()
    stdout = logging.StreamHandler(sys.stdout)
    stdout.addFilter(lambda record: record.levelno < logging.WARNING)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(logging.WARNING)
    handlers = [stdout, stderr]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding='utf-8'))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=handlers)
    try:
        result = CareerVietCrawler(args.raw_dir, headless=not args.headed).run(args.keyword or KEYWORDS, args.max_jobs)
    except KeyboardInterrupt:
        raise SystemExit(130)
    print(f"{result.path}\nSaved={result.saved}, duplicates={result.duplicates}, failed={result.failed}")


if __name__ == "__main__":
    main()
