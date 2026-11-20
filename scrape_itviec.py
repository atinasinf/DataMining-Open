"""ITviec scraper - Phase 1 (raw data collection).

Flow, per keyword:
  1. open the search-result pages (with pagination) and parse each job card
  2. open every new job's detail page and extract salary / experience / skills /
     employment type / description / requirements / benefits
Jobs found by several keywords are stored once; `keyword_search` lists all of them.

Output (one folder per run, so raw data is kept separately per crawl):
  data/raw/<YYYYmmdd_HHMMSS>/raw_itviec.csv   (columns follow schema.json)
  data/raw/<YYYYmmdd_HHMMSS>/meta.json

Run:
  python scrape_itviec.py                          # 5 default Data Science / Analytics keywords
  python scrape_itviec.py --limit 20               # quick test
  python scrape_itviec.py --login                  # sign in once to see salaries (see below)
  python scrape_itviec.py --refill old.csv --login # fill the empty columns of an existing CSV
  python scrape_itviec.py --limit 3 --save-html 3  # also save 3 detail pages (to tune selectors)

About salary: ITviec shows "Sign in to view salary" to visitors who are not signed in.
With --login the script opens a browser window with its own profile folder (.itviec_profile);
sign in to ITviec yourself in that window, then press Enter in the terminal. The sign-in is
remembered for the next runs. The script never stores or types your password.
"""

import argparse
import csv
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
    read_csv_ids,
    robots_allowed,
    write_csv,
    write_meta,
)

SITE = "itviec"
BASE = "https://itviec.com"
LIST_URL = "https://itviec.com/it-jobs"
SIGN_IN_URL = "https://itviec.com/sign_in"
PROFILE_DIR = ".itviec_profile"

# 5 keywords for Data Science / Data Analytics (role names + core skills)
DEFAULT_KEYWORDS = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning",
    "Power BI",
]

# Columns that the detail page is expected to fill
DETAIL_FIELDS = (
    "salary_raw", "experience_raw", "skills_raw", "employment_type_raw",
    "description", "requirements", "benefits",
)

# Section titles on the detail page (English + Vietnamese) -> schema column
SECTION_MAP = {
    "description": ("job description", "mô tả công việc"),
    "requirements": ("your skills and experience", "yêu cầu", "kỹ năng và kinh nghiệm"),
    "benefits": ("why you'll love working here", "why you’ll love working here", "phúc lợi", "quyền lợi"),
}

SIGN_IN_TEXT = "sign in to view salary"
SALARY_WORDS = (SIGN_IN_TEXT, "đăng nhập để xem", "negotiable", "thỏa thuận", "thoả thuận", "you'll love it", "you’ll love it")
CURRENCY_RE = re.compile(r"usd|vnd|\$|triệu|million|vnđ|đ\b", re.I)
EXP_LABELS = ("experience", "years of experience", "kinh nghiệm", "yêu cầu kinh nghiệm", "level", "cấp bậc")
TYPE_LABELS = ("job type", "employment type", "loại hình", "loại hình công việc", "hình thức hợp đồng")
TYPE_VALUE_RE = re.compile(
    r"^(full[- ]?time|part[- ]?time|intern(ship)?|contract|freelance|temporary|"
    r"toàn thời gian|bán thời gian|thực tập|hợp đồng|thời vụ)$", re.I)
EXP_LINE_RE = re.compile(r"\d+\s*\+?\s*(?:[-–]\s*\d+\s*\+?\s*)?(?:năm|years?|yrs?)", re.I)


@contextmanager
def browser(headless: bool = False, login: bool = False):
    """Playwright browser context.

    login=True  -> persistent profile (.itviec_profile) so an ITviec sign-in is kept;
                   the user signs in by hand and presses Enter.
    login=False -> crawlers.browser if the project has it, else a plain Chromium.
    """
    if login:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False, locale="en-US")
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(SIGN_IN_URL, wait_until="domcontentloaded", timeout=60000)
                print("\nA browser window is open on the ITviec sign-in page.")
                print("Sign in there yourself (skip if you are already signed in),")
                input("then come back here and press Enter to start... ")
                yield ctx
            finally:
                ctx.close()
        return

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
def _clean(s: str) -> str:
    return " ".join(str(s).split())


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


def _top_strings(soup: BeautifulSoup, limit: int = 120) -> list:
    """Text pieces that follow the job title (h1): the header block with salary, tags, etc."""
    h1 = soup.find("h1")
    if not h1:
        return []
    out = []
    for s in h1.find_all_next(string=True, limit=limit):
        if s.find_parent("h1") or s.find_parent(["script", "style"]):
            continue
        t = _clean(s)
        if t:
            out.append(t)
    return out


def extract_salary(soup: BeautifulSoup) -> str:
    """Salary text shown under the job title, exactly as displayed (may be the sign-in prompt)."""
    for t in _top_strings(soup, 80):
        if len(t) > 60:
            continue
        low = t.lower()
        if any(w in low for w in SALARY_WORDS):
            return t
        if re.search(r"\d", t) and CURRENCY_RE.search(low):
            return t
    return ""


def _label_value(soup: BeautifulSoup, labels) -> str:
    """Value that sits next to a label such as 'Experience' (label element, then its value)."""
    for s in soup.find_all(string=True):
        if _clean(s).lower().rstrip(":") not in labels:
            continue
        if s.find_parent(["h1", "h2", "h3", "script", "style"]):
            continue
        parent = s.parent
        sib = parent.find_next_sibling() if parent is not None else None
        if sib is not None:
            val = _clean(sib.get_text(" ", strip=True))
            if val and len(val) < 80:
                return val
        nxt = s.find_next(string=lambda x: x and _clean(x) and _clean(x).lower().rstrip(":") not in labels)
        if nxt is not None and len(_clean(nxt)) < 80:
            return _clean(nxt)
    return ""


def extract_experience(soup: BeautifulSoup, requirements: str) -> str:
    """1) a labelled field if the page has one; 2) otherwise the first line of the
    requirements text that states a number of years (copied word for word)."""
    val = _label_value(soup, EXP_LABELS)
    if val:
        return val
    for line in (requirements or "").splitlines():
        line = line.strip()
        if line and EXP_LINE_RE.search(line):
            return line[:300]
    return ""


def extract_employment_type(soup: BeautifulSoup) -> str:
    """Contract type if the page states it: a labelled field, or a header tag whose whole
    text is exactly Full-time / Part-time / Intern / Contract ... (nothing is guessed)."""
    val = _label_value(soup, TYPE_LABELS)
    if val:
        return val
    for t in _top_strings(soup, 100):
        if TYPE_VALUE_RE.match(t):
            return t
    return ""


def extract_skills(soup: BeautifulSoup) -> str:
    """Skill tags of the job: the same tag component as the cards, else header links /it-jobs/<skill>."""
    skills = [a.get_text(strip=True) for a in soup.select("a[data-responsive-tag-list-target='tag']")]
    if not skills:
        h1 = soup.find("h1")
        if h1:
            for a in h1.find_all_next("a", limit=60):
                href = (a.get("href") or "").split("?")[0]
                text = a.get_text(strip=True)
                if (re.fullmatch(r"(?:https://itviec\.com)?/it-jobs/[a-z0-9\-]+", href)
                        and not re.search(r"-\d+$", href)
                        and not a.get("title") and text and len(text) <= 30):
                    skills.append(text)
    return ", ".join(dict.fromkeys(skills))


def parse_detail(soup: BeautifulSoup) -> dict:
    """Extract the detail-page fields. Nothing is invented: a field that cannot be found
    stays empty. If no known section title is found, the whole main text is kept as
    `description` (original text block, not split)."""
    out = {col: "" for col in DETAIL_FIELDS}

    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(" ", strip=True).lower()
        for col, names in SECTION_MAP.items():
            if not out[col] and any(n in title for n in names):
                out[col] = _section_text(h)

    if not (out["description"] or out["requirements"] or out["benefits"]):
        main = soup.select_one("main") or soup.body
        if main:
            out["description"] = main.get_text("\n", strip=True)

    out["salary_raw"] = extract_salary(soup)
    out["skills_raw"] = extract_skills(soup)
    out["employment_type_raw"] = extract_employment_type(soup)
    out["experience_raw"] = extract_experience(soup, out["requirements"])
    return out


def is_empty(value) -> bool:
    return not str(value or "").strip()


def needs_salary(value) -> bool:
    return is_empty(value) or SIGN_IN_TEXT in str(value).lower()


def merge_detail(row: dict, detail: dict) -> list:
    """Fill the row from the detail dict without overwriting existing values
    (except a 'Sign in to view salary' prompt, which a real salary replaces).
    Returns the list of columns that were filled."""
    filled = []
    for col in DETAIL_FIELDS:
        new = detail.get(col, "")
        if is_empty(new):
            continue
        old = row.get(col)
        if col == "salary_raw":
            if needs_salary(old) and SIGN_IN_TEXT not in str(new).lower():
                row[col] = new
                filled.append(col)
            elif is_empty(old):
                row[col] = new
        elif is_empty(old):
            row[col] = new
            filled.append(col)
    return filled


def fetch_detail(page, job_url: str, retries: int = 2, save_html: Path | None = None) -> dict | None:
    for attempt in range(retries + 1):
        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("h1", timeout=30000)
            html = page.content()
            if save_html is not None:
                save_html.parent.mkdir(parents=True, exist_ok=True)
                save_html.write_text(html, encoding="utf-8")
            return parse_detail(BeautifulSoup(html, "lxml"))
        except Exception as exc:  # noqa: BLE001
            print(f"  detail retry {attempt + 1}/{retries + 1} {job_url}: {str(exc)[:60]}", flush=True)
            polite_sleep(3, 6)
    return None


def load_csv_rows(path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape ITviec jobs (Phase 1, raw data)")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS)
    parser.add_argument("--pages", type=int, default=34, help="max listing pages per keyword")
    parser.add_argument("--limit", type=int, default=0, help="stop after N unique jobs (0 = no limit)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--login", action="store_true", help="use a browser profile you sign in to by hand (to see salaries)")
    parser.add_argument("--refill", type=str, default="", help="existing raw CSV: only visit detail pages of rows with empty columns and fill them")
    parser.add_argument("--skip-from", nargs="+", default=[], help="CSV file(s) from earlier runs: jobs already in them are skipped")
    parser.add_argument("--save-html", type=int, default=0, help="save the first N detail pages as .html in the run folder (to tune selectors)")
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
    known = read_csv_ids(args.skip_from)
    if known:
        print(f"skipping {len(known)} jobs already collected in earlier runs", flush=True)
    filled_count = {col: 0 for col in DETAIL_FIELDS}
    html_saved = 0

    def done() -> bool:
        return bool(args.limit) and len(jobs) >= args.limit

    def fill_details(page, todo: list) -> None:
        nonlocal html_saved
        for i, row in enumerate(todo, 1):
            polite_sleep(args.min_delay, args.max_delay)
            html_path = None
            if html_saved < args.save_html:
                html_path = run_dir / "html_samples" / f"{row['job_id']}.html"
                html_saved += 1
            detail = fetch_detail(page, row["URL_Goc"], save_html=html_path)
            row["Timestamp"] = now_iso()
            if detail:
                for col in merge_detail(row, detail):
                    filled_count[col] += 1
            print(f"detail {i}/{len(todo)}: {str(row.get('title'))[:60]}", flush=True)

    try:
        with browser(headless=args.headless, login=args.login) as b:
            page = b.new_page()

            if args.refill:
                # Only revisit detail pages; keep the listing data as it is
                for r in load_csv_rows(args.refill):
                    jobs[r["job_id"]] = r
                todo = [
                    r for r in jobs.values()
                    if needs_salary(r.get("salary_raw")) or any(is_empty(r.get(c)) for c in DETAIL_FIELDS if c != "salary_raw")
                ]
                if args.limit:
                    todo = todo[: args.limit]
                print(f"refill: {len(jobs)} rows read, {len(todo)} rows have empty columns", flush=True)
                fill_details(page, todo)
            else:
                for kw in args.keywords:
                    kw_seen: set[str] = set()  # job_ids already seen on earlier pages of this keyword
                    for page_num in range(1, args.pages + 1):
                        cards = fetch_listing_page(page, kw, page_num)
                        if not cards:
                            break
                        # ITviec repeats old results past the last page instead of returning an empty page
                        page_ids = {r["job_id"] for r in cards}
                        if page_ids <= kw_seen:
                            print(f"[{kw}] page {page_num}: no new results for this keyword, stop.", flush=True)
                            break
                        kw_seen |= page_ids

                        new = 0
                        for row in cards:
                            jid = row["job_id"]
                            if jid in known:
                                continue
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

                fill_details(page, [r for r in jobs.values() if "Timestamp" not in r])
    except KeyboardInterrupt:
        print("Interrupted - saving what has been collected.", flush=True)
    finally:
        # rows without a detail fetch still get a Timestamp (time of collection)
        for row in jobs.values():
            if is_empty(row.get("Timestamp")):
                row["Timestamp"] = now_iso()
        rows = [normalize_row(r, schema) for r in jobs.values()]
        write_csv(out_csv, rows, schema)
        still_signin = sum(1 for r in rows if SIGN_IN_TEXT in str(r.get("salary_raw", "")).lower())
        write_meta(
            run_dir, site=SITE, keywords=args.keywords, started_at=started,
            finished_at=now_iso(), total_jobs=len(rows), empty_required=empty_report(rows, schema),
            empty_optional={c: sum(1 for r in rows if is_empty(r.get(c))) for c in ("skills_raw", "employment_type_raw")},
            salary_sign_in_prompt=still_signin, filled_columns=filled_count, args=vars(args),
        )
        print(f"saved {len(rows)} unique jobs to {out_csv}")
        print("filled from detail pages:", filled_count)
        if still_signin:
            print(f"NOTE: {still_signin} rows still show 'Sign in to view salary' - run again with --login.")


if __name__ == "__main__":
    main()
