"""Collect VietnamWorks IT vacancies from the public search and job-info APIs."""

import argparse
import json
import logging
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from .base_tin import (
    CONTENT_FIELDS, RAW_DIR, REQUIRED_FIELDS, VN_TIME, BaseCrawler, JobLink,
    JobUnavailable, _web_url,
)


KEYWORDS = (
    "Business Analyst",
    "AI Engineer",
    "Data Analyst",
    "Data Engineer",
    "Data Scientist",
    "SQL",
    "Python",
    "Power BI",
    "Tableau",
    "Machine Learning",
)
ORIGIN = "https://www.vietnamworks.com"
SEARCH_API = "https://ms.vietnamworks.com/job-search/v1.0/search"
DETAIL_API = "https://ms.vietnamworks.com/api-gateway/v1.0/tracking/job-info"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin": ORIGIN,
    "Referer": ORIGIN + "/",
    "Accept-Language": "vi",
    "Content-Type": "application/json",
}
RETRIEVE_FIELDS = (
    "address benefits jobTitle salaryMax isSalaryVisible jobLevelVI isShowLogo salaryMin "
    "companyLogo userId jobLevel jobLevelId jobId jobUrl companyId approvedOn isAnonymous "
    "alias expiredOn industries industriesV3 workingLocations services companyName salary "
    "onlineOn onlineOnText simpleServices visibilityDisplay isShowLogoInSearch priorityOrder "
    "skills profilePublishedSiteMask jobDescription jobRequirement prettySalary requiredCoverLetter "
    "languageSelectedVI languageSelected languageSelectedId typeWorkingId createdOn isAdrLiteJob "
    "applicantSignal numOfApplications numberOfRecruits exposureStatus isTopPriorityV4 topPriorityType"
).split()
IT_FILTER = [{"field": "jobFunction", "value": '[{"parentId":5,"childrenIds":[-1]}]'}]
log = logging.getLogger(__name__)


def _text(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Expected published text, got {type(value).__name__}")
    return value if value and value.strip() else None


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li", "tr"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li", "tr"):
            self.parts.append(" ")


def _clean_html_text(value: str | None) -> str | None:
    if not _text(value):
        return None
    parser = _HTMLText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split()) or None


def _has_html_text(value: str | None) -> bool:
    return bool(_clean_html_text(value))


def _extract_benefits(search: dict) -> str | None:
    lines = []
    for item in search.get("benefits") or []:
        value = _clean_html_text(item.get("benefitValue"))
        if value:
            name = _text(item.get("benefitNameVI"))
            lines.append(f"{name.strip()}: {value}" if name else value)
    return "\n".join(lines) or None


def _unique_values(items, key, separator) -> str | None:
    values = (_text(item.get(key)) for item in items)
    return separator.join(dict.fromkeys(value.strip() for value in values if value)) or None


def _extract_location(search: dict, detail: dict) -> str | None:
    places = search.get("workingLocations") or []
    return (
        _unique_values(places, "cityNameVI", "\n")
        or _unique_values(places, "address", "\n")
        or _text(search.get("address"))
        or _text(detail.get("job_location_city"))
    )


def _extract_salary(search: dict) -> str | None:
    pretty = _text(search.get("prettySalary"))
    if pretty:
        return pretty
    low, high = search.get("salaryMin"), search.get("salaryMax")
    if (search.get("isSalaryVisible") is True and type(high) in (int, float)
            and high > 0 and type(low) in (int, float)):
        return f"{low}-{high}"
    return None


def _extract_experience(detail: dict) -> str | None:
    years = detail.get("number_of_years_of_experience_required")
    return f"{years} năm" if type(years) is int and years > 0 else None


def _extract_skills(search: dict) -> str | None:
    return _unique_values(search.get("skills") or [], "skillName", ", ")


def _job_url(url: str) -> str:
    parts = urlsplit(_web_url(url))
    # urlsplit checks bracketed IP literals; validate DNS labels and the port as well.
    host = parts.hostname.encode("idna").decode("ascii").removesuffix(".")
    if ":" not in host and not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label, re.I)
        for label in host.split(".")
    ):
        raise ValueError(f"Invalid job hostname: {parts.hostname!r}")
    if any(c.isspace() for c in url) or parts.port == 0:
        raise ValueError(f"Invalid job URL: {url!r}")
    return url


def _content_fields(search: dict, detail: dict) -> dict[str, str | None]:
    description = detail.get("job_description")
    requirements = detail.get("job_requirement")
    return {
        "title": _text(search.get("jobTitle")) or _text(detail.get("job_title")),
        "company": _text(search.get("companyName")) or _text(detail.get("company_name")),
        "location": _extract_location(search, detail),
        "salary_raw": _extract_salary(search),
        "experience_raw": _extract_experience(detail),
        "description": description if _has_html_text(description) else None,
        "requirements": requirements if _has_html_text(requirements) else None,
        "benefits": _extract_benefits(search),
        "skills_raw": _extract_skills(search),
        "employment_type_raw": None,
        "work_model_raw": None,
        "posted_at_raw": _text(search.get("approvedOn")) or _text(search.get("createdOn")),
    }


class VietnamWorksCrawler(BaseCrawler):
    site = "vietnamworks"
    max_consecutive_failures = 10

    def __init__(self, raw_dir: Path = RAW_DIR, *, headless: bool = True, max_pages: int | None = None):
        super().__init__(raw_dir, headless=headless)
        if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
            raise ValueError("max_pages must be a positive integer or None")
        self.max_pages = max_pages
        self._search_cache = {}
        self._failure_stream: TextIO | None = None
        self._consecutive_failures = 0

    def _request_json(self, page: Page, url: str, *, body=None, params=None) -> dict:
        error = JobUnavailable if url == DETAIL_API else RuntimeError
        request = page.context.request
        for attempt in range(2):
            self.pause()
            try:
                if body is None:
                    response = request.get(url, params=params, headers=HEADERS, timeout=self.timeout_ms)
                else:
                    response = request.post(url, data=body, headers=HEADERS, timeout=self.timeout_ms)
            except PlaywrightError as exc:
                if page.is_closed():
                    raise RuntimeError(f"Browser page closed while requesting {url}") from exc
                if attempt:
                    raise error(f"Request failed for {url}: {exc}") from exc
                log.warning("Network error for %s; retrying once: %s", url, exc)
                continue

            try:
                status = response.status
                if status in (401, 403, 429):
                    raise RuntimeError(f"Access restricted: HTTP {status} for {url}")
                if status in (408, 500, 502, 503, 504) and not attempt:
                    log.warning("HTTP %s for %s; retrying once", status, url)
                    continue
                if status != 200:
                    raise error(f"HTTP {status} for {url}")
                try:
                    payload = response.json()
                except (ValueError, PlaywrightError) as exc:
                    raise error(f"Invalid JSON from {url}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise error(f"Expected a JSON object from {url}")
                return payload
            finally:
                response.dispose()

    def iter_job_links(self, page: Page, keyword: str) -> Iterator[JobLink]:
        number = 0
        while self.max_pages is None or number < self.max_pages:
            body = {
                "userId": 0, "query": keyword, "filter": IT_FILTER, "ranges": [], "order": [],
                "hitsPerPage": 50, "page": number, "retrieveFields": RETRIEVE_FIELDS,
                "summaryVersion": "", "variants": "test",
            }
            payload = self._request_json(page, SEARCH_API, body=body)
            meta, jobs = payload.get("meta"), payload.get("data")
            if not isinstance(meta, dict) or not isinstance(jobs, list):
                raise RuntimeError(f"Malformed search response for {keyword!r} page {number}")
            pages = meta.get("nbPages")
            if (meta.get("code") != 200 or meta.get("page") != number
                    or type(pages) is not int or pages < 0):
                raise RuntimeError(f"Unexpected search metadata for {keyword!r} page {number}: {meta}")
            log.info("VietnamWorks [%s] page %s (nbPages=%s): %s listings", keyword, number, pages, len(jobs))
            if not jobs or number >= pages:
                return
            for job in jobs:
                native_id = job.get("jobId")
                if type(native_id) not in (str, int) or not str(native_id).strip():
                    raise ValueError(f"Missing stable jobId on {keyword!r} page {number}")
                source_id = str(native_id).strip()
                url = _text(job.get("jobUrl"))
                if not url:
                    alias = _text(job.get("alias"))
                    if not alias:
                        raise ValueError(f"No jobUrl or alias for {source_id}")
                    url = f"{ORIGIN}/{alias}-{source_id}-jv"
                self._search_cache[source_id] = job
                yield JobLink(url, source_id)
                # BaseCrawler can skip duplicate links without calling _read_row.
                self._search_cache.pop(source_id, None)
            number += 1
            if number >= pages:
                return

    def parse_job(self, page: Page) -> dict[str, str | None]:
        """_read_row reads the search and job-info APIs directly, without a detail DOM."""
        raise NotImplementedError("VietnamWorks API data is parsed in _read_row")

    def _read_row(self, page: Page, link: JobLink, keyword: str) -> dict[str, str | None]:
        try:
            source_id = link.source_id
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("Missing stable source_id")
            url = _job_url(link.url)
            search = self._search_cache.pop(source_id, None)
            if search is None:
                raise ValueError(f"Missing cached listing for {source_id}")
            payload = self._request_json(page, DETAIL_API, params={"jobId": source_id})
            detail = payload.get("data")
            if payload.get("status") != "success" or not isinstance(detail, dict):
                raise JobUnavailable(f"Unreadable job-info: {payload.get('message') or payload.get('status')}")
            if detail.get("job_id") is not None and str(detail["job_id"]) != source_id:
                raise ValueError(f"Conflicting listing/detail IDs: {source_id!r}, {detail['job_id']!r}")

            fields = _content_fields(search, detail)
            missing = set(REQUIRED_FIELDS).difference(fields)
            extra = fields.keys() - CONTENT_FIELDS
            if missing or extra:
                raise ValueError(f"Raw schema mismatch: missing={sorted(missing)}, unexpected={sorted(extra)}")
            for name, value in fields.items():
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{name} must contain raw text or None")
            if not any((fields[name] or "").strip() for name in REQUIRED_FIELDS):
                raise ValueError("All required content fields are empty")
            if not fields["title"] and not fields["company"]:
                raise JobUnavailable("Both title and company are missing")
            if not fields["description"] and not fields["requirements"]:
                raise JobUnavailable("No readable description or requirements in job-info")
            row = {
                **fields, "job_id": f"{self.site}:{source_id}", "site": self.site, "URL_Goc": url,
                "Timestamp": datetime.now(VN_TIME).isoformat(), "keyword_search": keyword,
            }
        except (ValueError, TypeError, AttributeError, JobUnavailable, RuntimeError) as exc:
            self._consecutive_failures += 1
            failure = {
                "URL_Goc": link.url, "source_id": link.source_id, "keyword_search": keyword,
                "Timestamp": datetime.now(VN_TIME).isoformat(), "error": str(exc),
            }
            if self._failure_stream is not None:
                self._failure_stream.write(json.dumps(failure, ensure_ascii=False) + "\n")
                self._failure_stream.flush()
            if isinstance(exc, RuntimeError):
                raise
            if self._consecutive_failures >= self.max_consecutive_failures:
                raise RuntimeError(f"Stopping after {self._consecutive_failures} consecutive detail failures: {link.url}") from exc
            if isinstance(exc, JobUnavailable):
                raise
            raise JobUnavailable(str(exc)) from exc
        self._consecutive_failures = 0
        log.info("Read %s [%s]: %s", row["job_id"], keyword, row["title"])
        return row

    def _collect(self, listing, detail, keywords, max_jobs, stream, result):
        self._consecutive_failures = 0
        failures = result.path.with_suffix(".failures.jsonl")
        with failures.open("x", encoding="utf-8") as self._failure_stream:
            try:
                super()._collect(listing, detail, keywords, max_jobs, stream, result)
            except KeyboardInterrupt:
                log.warning("Stopped by Ctrl+C; saved=%s, partial CSV: %s; failure log: %s",
                            result.saved, result.path.with_suffix(".csv.part"), failures)
                raise
            finally:
                self._search_cache.clear()
                if self._failure_stream.tell():
                    log.warning("Failed detail URLs recorded in %s", failures)
                self._failure_stream = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", action="append", choices=KEYWORDS, help="Repeat to select keywords; default is all")
    parser.add_argument("--max-jobs", type=int, help="Total successfully saved unique jobs across all keywords")
    parser.add_argument("--max-pages", type=int, help="Maximum search pages per keyword; default is all nbPages")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--log-file", type=Path, help="Write a UTF-8 log as well as console output")
    args = parser.parse_args()
    # Windows pipes use the ANSI code page by default even for Vietnamese job titles.
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    stdout = logging.StreamHandler(sys.stdout)
    stdout.addFilter(lambda record: record.levelno < logging.WARNING)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(logging.WARNING)
    handlers = [stdout, stderr]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=handlers)
    try:
        crawler = VietnamWorksCrawler(args.raw_dir, headless=not args.headed, max_pages=args.max_pages)
        result = crawler.run(args.keyword or KEYWORDS, args.max_jobs)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    print(f"{result.path}\nSaved={result.saved}, duplicates={result.duplicates}, failed={result.failed}")


if __name__ == "__main__":
    main()
