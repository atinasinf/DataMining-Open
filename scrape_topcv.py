"""
scrape_topcv.py - Crawler TopCV cho phân khúc Data Science / Data Analytics.

Luồng chạy:
  1. Với mỗi từ khóa -> duyệt các trang kết quả tìm kiếm (pagination + cuộn trang để
     kích hoạt lazy-load) và thu thập thẻ tin (card).
  2. Với mỗi URL tin MỚI -> mở trang chi tiết, lấy nguyên văn Mô tả / Yêu cầu / Quyền lợi.
  3. Gộp trùng theo URL (một tin xuất hiện ở nhiều từ khóa -> keyword_search là list).
  4. Ghi raw_topcv.csv qua base_scraper.write_raw_csv (kiểm tra schema.json),
     mỗi bản ghi có Timestamp ISO 8601 (giờ Việt Nam) tại thời điểm thu thập.

Chạy thử nhanh (kiểm chứng trước hội đồng):
    python scrape_topcv.py --pages 1 --max-jobs 10
Chạy đầy đủ:
    python scrape_topcv.py --pages 40 --out raw_topcv.csv
Tiếp tục sau khi bị ngắt:
    python scrape_topcv.py --resume

Lưu ý đạo đức: có delay ngẫu nhiên giữa các request; không dùng dịch vụ cào trả phí.
Nếu TopCV hiện Cloudflare/captcha, chạy chế độ có giao diện (mặc định) và tự giải tay
khi script tạm dừng chờ bạn.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from base_scraper import (
    canonicalize_url,
    current_timestamp,
    make_raw_record,
    read_raw_csv,
    write_raw_csv,
)

SITE = "topcv"
BASE = "https://www.topcv.vn"
SEARCH_URL = BASE + "/tim-viec-lam-{slug}?type_keyword=1&page={page}&sba=1"

# từ khóa: vị trí + kỹ năng cốt lõi, mảng Data Science / Data Analytics
KEYWORDS = [
    "Data Analyst",
    "Data Scientist",
    "Machine Learning",
    "Data Engineer",
    "AI Engineer",
    "Deep Learning Engineer",
    "Database",
    "Business Analyst"
]

SECTION_MAP = {  # từ khóa trong tiêu đề mục -> trường schema
    "mô tả công việc": "description",
    "yêu cầu": "requirements",
    "quyền lợi": "benefits",
}
BLOCK_MARKERS = ("just a moment", "attention required", "cloudflare", "access denied")


# ----------------------------------------------------------------------------- tiện ích
def log(msg: str) -> None:
    print(msg, flush=True)


def soup_of(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # lxml chưa cài
        return BeautifulSoup(html, "html.parser")


def text_of(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def block_text(node) -> str:
    """Giữ xuống dòng của JD gốc."""
    if not node:
        return ""
    return "\n".join(line.strip() for line in node.get_text("\n").splitlines() if line.strip())


def source_id_from_url(url: str) -> str | None:
    m = re.search(r"-?j?(\d+)\.html", url) or re.search(r"/(\d+)(?:/|$)", url)
    return m.group(1) if m else None


def pause(page, lo: float, hi: float) -> None:
    page.wait_for_timeout(int(random.uniform(lo, hi) * 1000))


class StopCrawl(Exception):
    """Dừng sớm nhưng vẫn lưu dữ liệu đã thu thập."""


def is_blocked(page) -> bool:
    try:
        title = (page.title() or "").lower()
        if any(m in title for m in BLOCK_MARKERS):
            return True
        return page.locator("iframe[src*='challenges.cloudflare.com'], #challenge-form").count() > 0
    except PWError:
        return False


def wait_if_blocked(page, headless: bool, timeout_s: int = 300) -> bool:
    """Nếu gặp trang xác minh: chờ người dùng giải tay, tự tiếp tục khi trang đã qua."""
    if not is_blocked(page):
        return False
    if headless:
        raise StopCrawl("Bị chặn bởi xác minh; hãy chạy lại KHÔNG dùng --headless.")
    log("[!] Trang yêu cầu xác minh. Hãy giải trong cửa sổ trình duyệt - script tự tiếp tục khi xong...")
    waited = 0
    while is_blocked(page):
        page.wait_for_timeout(2000)
        waited += 2
        if waited >= timeout_s:
            raise StopCrawl("Chờ xác minh quá 5 phút.")
    page.wait_for_timeout(2500)
    return True


def goto_clear(page, url: str, args) -> None:
    """Mở lại URL đích sau khi người dùng giải xong trang xác minh."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if wait_if_blocked(page, args.headless):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        wait_if_blocked(page, args.headless)


def scroll_page(page, steps: int = 4) -> None:
    """Cuộn dần để kích hoạt lazy-load/AJAX."""
    for _ in range(steps):
        page.mouse.wheel(0, random.randint(900, 1500))
        page.wait_for_timeout(random.randint(400, 900))


def check_robots(url: str) -> None:
    try:
        rp = RobotFileParser(BASE + "/robots.txt")
        rp.read()
        if not rp.can_fetch("*", url):
            log("[!] robots.txt có thể không cho phép URL tìm kiếm này - hãy cân nhắc và ghi chú trong báo cáo.")
    except Exception:
        pass


# ----------------------------------------------------------------------------- parse danh sách
def parse_cards(soup: BeautifulSoup) -> list[dict]:
    rows, seen = [], set()
    cards = soup.select("div.job-item-search-result") or soup.select("div.job-item-default")
    for card in cards:
        a = card.select_one("h3.title a") or card.select_one("a[href*='/viec-lam/']")
        if not a or not a.get("href"):
            continue
        url = a["href"]
        if not url.startswith("http"):
            url = BASE + url
        url = canonicalize_url(url)
        if url in seen:
            continue
        seen.add(url)
        loc = card.select_one("a.address") or card.select_one("span.city-text")
        rows.append({
            "url": url,
            "title": text_of(a),
            "company": text_of(card.select_one("a.company")),
            "location": text_of(loc),
            "salary_raw": text_of(card.select_one("label.salary")),
            "experience_raw": text_of(card.select_one("label.exp")),
            "posted_at_raw": text_of(card.select_one("label.label-update")),
        })
    return rows


# ----------------------------------------------------------------------------- parse chi tiết
def parse_detail(soup: BeautifulSoup) -> dict:
    out = {"description": "", "requirements": "", "benefits": "", "skills_raw": "",
           "employment_type_raw": "", "work_model_raw": "", "title": "", "company": "",
           "salary_raw": "", "location": "", "experience_raw": ""}

    # Tiêu đề / công ty
    out["title"] = text_of(soup.select_one("h1.job-detail__info--title, h1.title, h1"))
    out["company"] = text_of(soup.select_one(
        "a.company-name-label, .company-name-label, h2.company-name-label, .job-detail__company--information-item.company-name a"))

    # Lương / địa điểm / kinh nghiệm ở khối thông tin đầu trang
    for sec in soup.select("div.job-detail__info--section"):
        label = text_of(sec.select_one(".job-detail__info--section-content-title")).lower()
        value = text_of(sec.select_one(".job-detail__info--section-content-value"))
        if "lương" in label:
            out["salary_raw"] = value
        elif "địa điểm" in label:
            out["location"] = value
        elif "kinh nghiệm" in label:
            out["experience_raw"] = value

    # Thông tin chung (hình thức làm việc, ...)
    for item in soup.select("div.box-general-group-info"):
        label = text_of(item.select_one(".box-general-group-info-title")).lower()
        value = text_of(item.select_one(".box-general-group-info-value"))
        if "hình thức" in label:
            out["employment_type_raw"] = value
        elif "kinh nghiệm" in label and not out["experience_raw"]:
            out["experience_raw"] = value

    # Kỹ năng (tag)
    tags = soup.select(".box-category-tag, .job-tags a, .item-tag")
    out["skills_raw"] = ", ".join(dict.fromkeys(text_of(t) for t in tags if text_of(t)))

    # Các mục JD
    for item in soup.select("div.job-description__item"):
        head = text_of(item.select_one("h3, h2")).lower()
        body = block_text(item.select_one("div.job-description__item--content") or item)
        for key, field in SECTION_MAP.items():
            if key in head and not out[field]:
                out[field] = body

    # TopCV layout mới dùng tiêu đề tiếng Anh và vùng nội dung riêng.
    # Ví dụ: Job Description / Candidate Requirements / Benefits.
    english_sections = {
        "job description": "description",
        "candidate requirements": "requirements",
        "requirements": "requirements",
        "benefits": "benefits",
    }
    for item in soup.select(".box-job-information-detail-item"):
        heading = text_of(item.select_one(
            ".box-job-information-detail-item__title--title"
        )).strip().lower().rstrip(":")
        field = english_sections.get(heading)
        if not field or out[field]:
            continue
        content = item.select_one(".box-job-information-detail-item__text")
        if content:
            out[field] = block_text(content)

    # Fallback (vd. trang brand/tuyen-dung có bố cục khác): tìm tiêu đề ngắn rồi lấy các khối kế tiếp
    if not (out["description"] or out["requirements"] or out["benefits"]):
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"]):
            head = text_of(h).lower()
            if len(head) > 60:
                continue
            for key, field in SECTION_MAP.items():
                if head.startswith(key) and not out[field]:
                    out[field] = _collect_after(h)
    return out


def _collect_after(h) -> str:
    node = h if h.find_next_sibling() else h.parent
    parts, size = [], 0
    for sib in node.find_next_siblings():
        t = text_of(sib).lower()
        if len(t) < 60 and any(k in t for k in SECTION_MAP):
            break
        b = block_text(sib)
        parts.append(b)
        size += len(b)
        if size > 8000:
            break
    return "\n".join(x for x in parts if x)


def fetch_detail(page, url: str, args) -> dict | None:
    for attempt in (1, 2):
        try:
            goto_clear(page, url, args)
            page.wait_for_timeout(1500)
            html = page.content()
            d = parse_detail(soup_of(html))
            if d["description"] or d["requirements"] or d["benefits"]:
                return d
            dump = Path("debug_topcv") / f"{source_id_from_url(url) or 'unknown'}.html"
            dump.parent.mkdir(exist_ok=True)
            dump.write_text(html, encoding="utf-8")
            log(f"    (lần {attempt}) không thấy nội dung JD, đã lưu HTML vào {dump}")
        except PWTimeout:
            log(f"    (lần {attempt}) timeout")
        pause(page, 2, 4)
    return None


# ----------------------------------------------------------------------------- lưu trữ
def as_list(value) -> list[str]:
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, str) and value else []


def add_keyword(rec: dict, keyword: str) -> None:
    merged = list(dict.fromkeys(as_list(rec.get("keyword_search")) + [keyword]))
    rec["keyword_search"] = merged[0] if len(merged) == 1 else merged


def load_existing(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not path.exists() or path.stat().st_size == 0:
        return records
    for row in read_raw_csv(path):
        kw = row.get("keyword_search", "")
        if isinstance(kw, str) and kw.startswith("["):
            try:
                row["keyword_search"] = json.loads(kw)
            except json.JSONDecodeError:
                pass
        records[canonicalize_url(row["URL_Goc"])] = row
    return records


# ----------------------------------------------------------------------------- main crawl
def crawl(args) -> None:
    out = Path(args.out)
    if not args.resume and out.exists():
        out.unlink()
    records = load_existing(out) if args.resume else {}
    log(f"Bắt đầu. Đã có sẵn {len(records)} bản ghi. Timestamp bắt đầu: {current_timestamp()}")
    check_robots(SEARCH_URL.format(slug="data-analyst", page=1))

    pending: list[dict] = []
    failed = 0

    with sync_playwright() as pw:
        opts = dict(headless=args.headless, locale="vi-VN", viewport={"width": 1366, "height": 900})
        try:  # Chrome thật + profile lưu cookie: giải xác minh một lần, các lần sau đỡ bị hỏi lại
            ctx = pw.chromium.launch_persistent_context(args.profile, channel="chrome", **opts)
        except PWError:
            log("Không tìm thấy Google Chrome, dùng Chromium của Playwright.")
            ctx = pw.chromium.launch_persistent_context(args.profile, **opts)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        consecutive_fail = 0

        try:
            for keyword in args.keywords:
                slug = quote_plus(keyword.lower().strip()).replace("+", "-")
                log(f"\n=== Từ khóa: {keyword} ===")
                empty_streak = 0
                for page_num in range(args.start_page, args.start_page + args.pages):
                    if args.max_jobs and len(records) >= args.max_jobs:
                        break
                    url = SEARCH_URL.format(slug=slug, page=page_num)
                    cards = []
                    for attempt in range(1, 4):
                        try:
                            goto_clear(page, url, args)
                            try:
                                page.wait_for_selector(
                                    "div.job-item-search-result, div.job-item-default",
                                    timeout=12000,
                                )
                            except PWTimeout:
                                pass
                            page.wait_for_timeout(1500)
                            scroll_page(page)
                            cards = parse_cards(soup_of(page.content()))
                        except PWTimeout:
                            log(f"  trang {page_num}: timeout lần {attempt}/3")
                            cards = []
                        if cards:
                            break
                        if attempt < 3:
                            log(f"  trang {page_num}: chưa thấy thẻ tin, tải lại ({attempt}/3)")
                            pause(page, 3, 6)
                    if not cards:
                        log(f"  trang {page_num}: vẫn 0 thẻ sau 3 lần tải; kiểm tra xác minh/HTML trước khi kết luận hết kết quả")
                    new_cards = [c for c in cards if c["url"] not in records]
                    log(f"  trang {page_num}: {len(cards)} thẻ, {len(new_cards)} tin mới")

                    # tin đã có -> chỉ gộp keyword
                    for c in cards:
                        if c["url"] in records:
                            add_keyword(records[c["url"]], keyword)

                    if not cards:
                        # Ba lượt tải rỗng không đủ bằng chứng rằng đã hết kết quả.
                        # Sang keyword tiếp để tránh bỏ toàn bộ phần còn lại do challenge/layout.
                        log("  Không xác nhận được trang kết quả; tạm bỏ trang này và tiếp tục trang kế tiếp")
                        continue
                    empty_streak = empty_streak + 1 if not new_cards else 0
                    if empty_streak >= 2:
                        log("  2 trang liên tiếp không có tin mới -> sang từ khóa tiếp")
                        break

                    for c in new_cards:
                        if args.max_jobs and len(records) >= args.max_jobs:
                            break
                        pause(page, args.min_delay, args.max_delay)
                        d = fetch_detail(page, c["url"], args)
                        if d is None:
                            failed += 1
                            consecutive_fail += 1
                            if consecutive_fail >= 5:
                                raise StopCrawl("5 tin liên tiếp lỗi - kiểm tra thư mục debug_topcv/ rồi chạy lại với --resume.")
                            log(f"    [x] bỏ qua (không lấy được JD): {c['url']}")
                            continue
                        consecutive_fail = 0
                        rec = make_raw_record(
                            site=SITE, url=c["url"], source_id=source_id_from_url(c["url"]),
                            title=d["title"] or c["title"],
                            company=d["company"] or c["company"],
                            location=d["location"] or c["location"],
                            salary_raw=d["salary_raw"] or c["salary_raw"],
                            experience_raw=d["experience_raw"] or c["experience_raw"],
                            description=d["description"], requirements=d["requirements"],
                            benefits=d["benefits"], skills_raw=d["skills_raw"],
                            employment_type_raw=d["employment_type_raw"],
                            work_model_raw=d["work_model_raw"],
                            posted_at_raw=c["posted_at_raw"],
                            keyword_search=keyword,
                        )  # Timestamp = thời điểm thu thập tin này
                        records[rec["URL_Goc"]] = rec
                        pending.append(rec)
                        log(f"    [+] {len(records):>4} | {rec['title'][:60]}")
                        if len(pending) >= args.checkpoint:
                            write_raw_csv(pending, out, append=True)
                            pending.clear()
                    pause(page, args.min_delay, args.max_delay)
        except (KeyboardInterrupt, StopCrawl, PWError) as e:
            log(f"\nDừng: {e or type(e).__name__} - đang lưu dữ liệu đã thu thập...")
        finally:
            try:
                ctx.close()
            except PWError:
                pass

    # Ghi lại toàn bộ file một lần để keyword_search đã được gộp đúng
    final = list(records.values())
    write_raw_csv(final, out, append=False)
    log(f"\nHoàn tất: {len(final)} bản ghi -> {out} (bỏ qua {failed} tin lỗi)")
    log(f"Timestamp kết thúc: {current_timestamp()}")


def main() -> None:
    p = argparse.ArgumentParser(description="Crawl TopCV - Data Science / Data Analytics")
    p.add_argument("--keywords", nargs="+", default=KEYWORDS, help="Danh sách từ khóa")
    p.add_argument("--pages", type=int, default=40, help="Số trang tối đa mỗi từ khóa")
    p.add_argument("--start-page", type=int, default=1)
    p.add_argument("--max-jobs", type=int, default=0, help="Dừng khi đủ N tin (0 = không giới hạn)")
    p.add_argument("--out", default="raw_topcv.csv")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--profile", default=".topcv_profile", help="Thư mục profile trình duyệt (giữ cookie giữa các lần chạy)")
    p.add_argument("--min-delay", type=float, default=3.0)
    p.add_argument("--max-delay", type=float, default=7.0)
    p.add_argument("--checkpoint", type=int, default=20, help="Lưu tạm sau mỗi N tin")
    p.add_argument("--resume", action="store_true", help="Tiếp tục từ file --out đã có")
    args = p.parse_args()
    if args.min_delay < 0 or args.max_delay < 0 or args.min_delay > args.max_delay:
        sys.exit("--min-delay và --max-delay phải không âm, đồng thời min <= max")
    if args.pages < 1 or args.start_page < 1 or args.checkpoint < 1:
        sys.exit("--pages, --start-page và --checkpoint phải >= 1")
    if args.max_jobs < 0:
        sys.exit("--max-jobs phải >= 0")
    crawl(args)


if __name__ == "__main__":
    main()
