"""Shared helpers for the job-board scrapers (Phase 1: raw data collection).

Responsibilities:
- load the raw-data schema (schema.json) and keep CSV columns in schema order
- stamp every record with an ISO 8601 timestamp that carries the +07:00 offset
- keep each crawl run in its own folder (raw data is stored per run)
- polite, randomised delays and a robots.txt check
- JSONL / CSV read-write helpers
"""

import csv
import json
import random
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

VN_TZ = timezone(timedelta(hours=7))
LIST_JOINER = " | "
SCHEMA_PATH = Path(__file__).with_name("schema.json")


# --------------------------------------------------------------------------- time / run folders
def now_iso() -> str:
    """Current time as ISO 8601 with +07:00 offset (e.g. 2026-11-14T09:30:00+07:00)."""
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def make_run_dir(root="data/raw") -> Path:
    """Create a fresh folder for this crawl run: <root>/<YYYYmmdd_HHMMSS>/."""
    run_dir = Path(root) / datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_meta(run_dir: Path, **info) -> None:
    """Save run metadata (keywords, start time, ...) next to the data."""
    path = Path(run_dir) / "meta.json"
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- schema
def load_schema(path=SCHEMA_PATH) -> dict:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def schema_columns(schema: dict) -> list:
    return [c["name"] for c in schema["columns"]]


def required_columns(schema: dict) -> list:
    return [c["name"] for c in schema["columns"] if c.get("required")]


def normalize_row(row: dict, schema: dict) -> dict:
    """Return a row with exactly the schema columns. Missing values stay empty
    (never invented); lists are joined into a single string."""
    out = {}
    for col in schema_columns(schema):
        val = row.get(col)
        if val is None:
            val = ""
        elif isinstance(val, (list, tuple)):
            val = LIST_JOINER.join(str(v) for v in val)
        out[col] = val
    return out


def empty_report(rows: list, schema: dict) -> dict:
    """Count empty values for each required column (for a quick quality check)."""
    report = {}
    for col in required_columns(schema):
        report[col] = sum(1 for r in rows if not str(r.get(col, "")).strip())
    return report


# --------------------------------------------------------------------------- I/O
def write_jsonl(path: Path, rows) -> None:
    """Append rows as JSON lines, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path) -> list:
    """Read all JSON-line records from a file (empty list if missing)."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_csv_ids(paths, id_col: str = "job_id") -> set:
    """Collect the job ids stored in one or more earlier CSV files (missing files are ignored)."""
    ids = set()
    for p in paths:
        p = Path(p)
        if not p.exists():
            print(f"warning: {p} not found, ignored", flush=True)
            continue
        with p.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get(id_col):
                    ids.add(row[id_col])
    return ids


def write_csv(path, rows, schema: dict) -> None:
    """Write rows to CSV in schema column order (UTF-8 with BOM so Excel opens it correctly)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = schema_columns(schema)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_row(row, schema))


# --------------------------------------------------------------------------- politeness
def polite_sleep(low: float = 2.0, high: float = 5.0) -> None:
    """Random delay between requests."""
    time.sleep(random.uniform(low, high))


def robots_allowed(url: str, user_agent: str = "*") -> bool:
    """Check robots.txt for `url`. If robots.txt cannot be read, return True
    (and let the caller decide whether to continue)."""
    parts = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:  # noqa: BLE001
        return True
    return rp.can_fetch(user_agent, url)


# --------------------------------------------------------------------------- interactive mode
def interactive_scrape(page, parse_fn, out_path, *, key="job_id", interval=2.0, label="") -> dict:
    """Continuously scrape a page the user is manually navigating.

    The user logs in / scrolls / clicks "next page" in the visible browser while
    this loop re-reads the DOM every `interval` seconds, dedups by `key`, and
    rewrites `out_path` (JSONL) with everything collected so far. Runs until
    KeyboardInterrupt.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    collected = {}
    if out.exists():
        for row in read_jsonl(out):
            if row.get(key):
                collected[row[key]] = row
    try:
        while True:
            try:
                soup = BeautifulSoup(page.content(), "lxml")
                for row in parse_fn(soup):
                    k = row.get(key)
                    if k and k not in collected:
                        collected[k] = row
                with out.open("w", encoding="utf-8") as fh:
                    for row in collected.values():
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[{label}] {len(collected)} unique jobs", flush=True)
            except Exception as exc:  # noqa: BLE001 - navigation in progress, keep scraping
                print(f"[{label}] scrape err: {str(exc)[:60]}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    print(f"[{label}] done: {len(collected)} jobs -> {out}")
    return collected
