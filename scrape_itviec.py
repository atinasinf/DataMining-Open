"""ITviec scraper - Phase 1 (raw data collection).

Flow, per keyword:
  1. open the search-result pages (with pagination) and parse each job card
  2. open every new job's detail page and extract description / requirements / benefits
Jobs found by several keywords are stored once; `keyword_search` lists all of them.

Output (one folder per run, so raw data is kept separately per crawl):
  data/raw/<YYYYmmdd_HHMMSS>/raw_itviec.csv   (columns follow schema.json)
  data/raw/<YYYYmmdd_HHMMSS>/meta.json

Run:
  python scrape_itviec.py                    # 5 default Data Science / Analytics keywords
  python scrape_itviec.py --limit 20         # quick test
  python scrape_itviec.py --headless --keywords "Data Analyst" "SQL"
"""

import argparse
import hashlib
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from base_scraper import (
    empty_report,
    load_schema,
    make_run_dir,
    normalize_row,
    now_iso,
    polite_sleep,
    robots_allowed,
    write_csv,
    write_meta,
)

@contextmanager
def browser(headless: bool = False):
    """Playwright browser context. Uses crawlers.browser if the project has it,
    otherwise falls back to a plain Playwright Chromium."""
    try:
        from crawlers.browser import browser as project_browser
    except ImportError:
        project_browser = None

    if project_browser is not None:
        with project_browser(headless=headless) as b:
            yield b
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        br = p.chromium.launch(headless=headless)
        ctx = br.new_context(locale="en-US")
        try:
            yield ctx
        finally:
            br.close()


SITE = "itviec"
BASE = "https://itviec.com"
LIST_URL = "https://itviec.com/it-jobs"

# 5 keywords for Data Science / Data Analytics (role names + core skills)
DEFAULT_KEYWORDS = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning",
    "Power BI",
]

# Section titles on the detail page (English + Vietnamese) -> schema column
SECTION_MAP = {
    "description": ("job description", "mô tả công việc"),
    "requirements": ("your skills and experience", "yêu cầu", "kỹ năng và kinh nghiệm"),
    "benefits": ("why you'll love working here", "why you’ll love working here", "phúc lợi", "quyền lợi"),
}


# --------------------------------------------------------------------------- listing
def make_job_id(job_url: str) -> str:
    """Stable id: trailing number of the URL slug if present, else a hash of the slug."""
    slug = job_url.rstrip("/").rsplit("/", 1)[-1]
    m = re.search(r"-(\d+)$", slug)
    if m:
        return m.group(1)
    return "h" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:12]


def parse_card(card: BeautifulSoup) -> dict | None:
    """Parse one `div.job-card` into a raw listing record."""
    title_a = card.select_one("h3 a")
    if not title_a:
        return None

    job_url = urljoin(BASE, title_a.get("href", "").split("?")[0])
    title = title_a.get_text(strip=True)

    company = None
    company_a = card.select_one("span.ims-2 a.text-rich-grey")
    if company_a:
        company = company_a.get_text(strip=True)

    posted = None
    posted_span = card.select_one("span.small-text.text-dark-grey")
    if posted_span:
        posted = " ".join(posted_span.get_text(" ", strip=True).split())
        posted = posted.removeprefix("Posted ")

    salary = None
    salary_a = card.select_one("div.salary a")
    if salary_a:
        salary = salary_a.get_text(strip=True)

    location = None
    loc_div = card.select_one("div.text-rich-grey.text-truncate.text-nowrap")
    if loc_div:
        location = loc_div.get("title")

    work_model = None
    wm_div = card.select_one("div.text-rich-grey.flex-shrink-0")
    if wm_div:
        work_model = wm_div.get_text(strip=True)

    skills = [
        a.get_text(strip=True)
        for a in card.select("a[data-responsive-tag-list-target='tag']")
    ]

    return {
        "job_id": make_job_id(job_url),
        "site": SITE,
        "URL_Goc": job_url,
        "title": title,
        "company": company,
        "location": location,
        "salary_raw": salary,
        "skills_raw": ", ".join(skills),
        "work_model_raw": work_model,
        "posted_at_raw": posted,
    }


def fetch_listing_page(page, keyword: str, page_num: int) -> list[dict]:
    url = f"{LIST_URL}?query={quote_plus(keyword)}"
    if page_num > 1:
        url += f"&page={page_num}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("div.job-card", timeout=30000)
    except Exception:  # noqa: BLE001 - no cards => past the last page
        return []
    soup = BeautifulSoup(page.content(), "lxml")
    return [row for c in soup.select("div.job-card") if (row := parse_card(c))]


# --------------------------------------------------------------------------- detail
def _section_text(heading) -> str:
    """Text that belongs to a heading: following siblings until the next heading;
    if there are none, the rest of the parent block."""
    parts = []
    for sib in heading.next_siblings:
        name = getattr(sib, "name", None)
        if name in ("h1", "h2", "h3") or (name and sib.find(["h2"])):
            break
        text = sib.get_text("\n", strip=True) if name else str(sib).strip()
        if text:
            parts.append(text)
    if not parts and heading.parent is not None:
        full = heading.parent.get_text("\n", strip=True)
        parts.append(full.removeprefix(heading.get_text(strip=True)).strip())
    return "\n".join(p for p in parts if p).strip()


def parse_detail(soup: BeautifulSoup) -> dict:
    """Extract description / requirements / benefits / experience from a detail page.

    Nothing is invented: a section that cannot be found stays empty. If no known
    section title is found, the whole main text is kept as `description`
    (original text block, not split).
    """
    out = {"description": "", "requirements": "", "benefits": "", "experience_raw": "", "employment_type_raw": ""}

    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(" ", strip=True).lower()
        for col, names in SECTION_MAP.items():
            if not out[col] and any(n in title for n in names):
                out[col] = _section_text(h)

    if not (out["description"] or out["requirements"] or out["benefits"]):
        main = soup.select_one("main") or soup.body
        if main:
            out["description"] = main.get_text("\n", strip=True)
    return out


def fetch_detail(page, job_url: str, retries: int = 2) -> dict | None:
    for attempt in range(retries + 1):
        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("h1", timeout=30000)
            return parse_detail(BeautifulSoup(page.content(), "lxml"))
        except Exception as exc:  # noqa: BLE001
            print(f"  detail retry {attempt + 1}/{retries + 1} {job_url}: {str(exc)[:60]}", flush=True)
            polite_sleep(3, 6)
    return None


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape ITviec jobs (Phase 1, raw data)")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS)
    parser.add_argument("--pages", type=int, default=34, help="max listing pages per keyword")
    parser.add_argument("--limit", type=int, default=0, help="stop after N unique jobs (0 = no limit)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--out-root", type=str, default="data/raw")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=5.0)
    args = parser.parse_args()

    schema = load_schema()
    run_dir = make_run_dir(args.out_root)
    out_csv = run_dir / "raw_itviec.csv"
    started = now_iso()
    write_meta(run_dir, site=SITE, keywords=args.keywords, started_at=started, args=vars(args))

    if not robots_allowed(LIST_URL):
        print("WARNING: robots.txt disallows the listing URL - check before continuing.", flush=True)

    jobs: dict[str, dict] = {}  # job_id -> row (dedup across keywords)

    def done() -> bool:
        return bool(args.limit) and len(jobs) >= args.limit

    try:
        with browser(headless=args.headless) as b:
            page = b.new_page()
            for kw in args.keywords:
                for page_num in range(1, args.pages + 1):
                    cards = fetch_listing_page(page, kw, page_num)
                    if not cards:
                        break

                    new = 0
                    for row in cards:
                        jid = row["job_id"]
                        if jid in jobs:  # same job via another keyword/page: only add the keyword
                            kws = jobs[jid]["keyword_search"]
                            if kw not in kws:
                                kws.append(kw)
                            continue
                        row["keyword_search"] = [kw]
                        jobs[jid] = row
                        new += 1
                        if done():
                            break
                    print(f"[{kw}] page {page_num}: {len(cards)} cards, {new} new (total {len(jobs)})", flush=True)
                    if done():
                        break
                    polite_sleep(args.min_delay, args.max_delay)
                if done():
                    break

            # detail pages
            todo = [r for r in jobs.values() if "Timestamp" not in r]
            for i, row in enumerate(todo, 1):
                polite_sleep(args.min_delay, args.max_delay)
                detail = fetch_detail(page, row["URL_Goc"])
                row["Timestamp"] = now_iso()
                if detail:
                    row.update(detail)
                print(f"detail {i}/{len(todo)}: {row['title'][:60]}", flush=True)
    except KeyboardInterrupt:
        print("Interrupted - saving what has been collected.", flush=True)
    finally:
        # rows without a detail fetch still get a Timestamp (time of collection)
        for row in jobs.values():
            row.setdefault("Timestamp", now_iso())
        rows = [normalize_row(r, schema) for r in jobs.values()]
        write_csv(out_csv, rows, schema)
        write_meta(
            run_dir, site=SITE, keywords=args.keywords, started_at=started,
            finished_at=now_iso(), total_jobs=len(rows), empty_required=empty_report(rows, schema),
            args=vars(args),
        )
        print(f"saved {len(rows)} unique jobs to {out_csv}")


if __name__ == "__main__":
    main()
