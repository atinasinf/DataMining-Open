"""
Các hàm dùng chung cho crawler tuyển dụng.

Giữ văn bản thô từ nguồn, dấu thời gian ISO 8601 theo giờ Việt Nam và URL tin.
Đường dẫn schema tương đối được giải quyết theo thư mục của module này.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schema.json"
RAW_COLUMNS = [
    "job_id", "site", "URL_Goc", "Timestamp", "title", "company", "location",
    "salary_raw", "experience_raw", "description", "requirements", "benefits",
    "skills_raw", "work_model_raw", "employment_type_raw", "posted_at_raw",
    "keyword_search",
]
REQUIRED_FIELDS = [
    "job_id", "site", "URL_Goc", "Timestamp", "title", "company", "location",
    "salary_raw", "experience_raw", "description", "requirements", "benefits",
]
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def current_timestamp() -> str:
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def canonicalize_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def make_job_id(site: str, source_id: str | None = None, url: str | None = None) -> str:
    if source_id is not None and str(source_id).strip():
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(source_id).strip())
        return f"{site.lower()}_{safe_id}"
    canonical_url = canonicalize_url(url or "")
    if not canonical_url:
        raise ValueError("Cần source_id hoặc URL hợp lệ để tạo job_id ổn định.")
    digest = hashlib.sha256(f"{site.lower()}|{canonical_url}".encode()).hexdigest()[:20]
    return f"{site.lower()}_{digest}"


def resolve_schema_path(schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> Path:
    path = Path(schema_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_schema(schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> dict:
    with resolve_schema_path(schema_path).open("r", encoding="utf-8") as file:
        return json.load(file)


def make_raw_record(*, site: str, url: str, title: str = "", company: str = "",
                    location: str = "", salary_raw: str = "", experience_raw: str = "",
                    description: str = "", requirements: str = "", benefits: str = "",
                    source_id: str | None = None, timestamp: str | None = None,
                    skills_raw: str = "", work_model_raw: str = "",
                    employment_type_raw: str = "", posted_at_raw: str = "",
                    keyword_search: str | list[str] | None = None) -> dict[str, Any]:
    if not url or not str(url).strip():
        raise ValueError("Bản ghi hợp lệ phải có URL_Goc.")
    return {
        "job_id": make_job_id(site, source_id, url), "site": str(site or ""),
        "URL_Goc": canonicalize_url(url), "Timestamp": timestamp or current_timestamp(),
        "title": title or "", "company": company or "", "location": location or "",
        "salary_raw": salary_raw or "", "experience_raw": experience_raw or "",
        "description": description or "", "requirements": requirements or "",
        "benefits": benefits or "", "skills_raw": skills_raw or "",
        "work_model_raw": work_model_raw or "", "employment_type_raw": employment_type_raw or "",
        "posted_at_raw": posted_at_raw or "", "keyword_search": keyword_search or "",
    }


def validate_record(record: dict, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> list[str]:
    schema = load_schema(schema_path)
    errors: list[str] = []
    for field in schema.get("required", REQUIRED_FIELDS):
        if field not in record:
            errors.append(f"Thiếu trường bắt buộc: {field}")
        elif not isinstance(record[field], str):
            errors.append(f"Trường {field} phải là string.")
    allowed = set(schema.get("properties", {}))
    extra = set(record) - allowed
    if extra:
        errors.append(f"Có trường ngoài schema: {', '.join(sorted(extra))}")
    for field, value in record.items():
        if field not in allowed:
            continue
        expected_type = schema["properties"][field].get("type")
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Trường {field} phải là string.")
        elif field == "keyword_search" and not (
            isinstance(value, str) or (isinstance(value, list) and all(isinstance(x, str) for x in value))
        ):
            errors.append("keyword_search phải là string hoặc list[string].")
    timestamp = record.get("Timestamp")
    if isinstance(timestamp, str) and timestamp:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                errors.append("Timestamp phải có thông tin múi giờ.")
        except ValueError:
            errors.append("Timestamp không đúng định dạng ISO 8601.")
    return errors


def deduplicate_records(records: Iterable[dict], *, merge_keywords: bool = True) -> list[dict]:
    collected: dict[str, dict] = {}
    for original in records:
        row = dict(original)
        key = canonicalize_url(row.get("URL_Goc", ""))
        if not key:
            continue
        if key not in collected:
            row["URL_Goc"] = key
            collected[key] = row
            continue
        if merge_keywords:
            values: list[str] = []
            for value in (collected[key].get("keyword_search", ""), row.get("keyword_search", "")):
                values.extend(value if isinstance(value, list) else ([value] if isinstance(value, str) and value else []))
            unique = list(dict.fromkeys(values))
            if unique:
                collected[key]["keyword_search"] = unique[0] if len(unique) == 1 else unique
    return list(collected.values())


def write_raw_csv(records: Iterable[dict], output_path: str | Path, *,
                  schema_path: str | Path = DEFAULT_SCHEMA_PATH, append: bool = False) -> int:
    """Ghi CSV có kiểm tra schema; append cho phép lưu checkpoint không lặp header."""
    rows = list(records)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, 1):
        errors = validate_record(row, schema_path)
        if errors:
            raise ValueError(f"Bản ghi thứ {index} không hợp lệ: " + "; ".join(errors))
    has_content = output.exists() and output.stat().st_size > 0
    mode = "a" if append else "w"
    encoding = "utf-8" if append and has_content else "utf-8-sig"
    with output.open(mode, newline="", encoding=encoding) as file:
        writer = csv.DictWriter(file, fieldnames=RAW_COLUMNS, extrasaction="raise")
        if not (append and has_content):
            writer.writeheader()
        for row in rows:
            csv_row = {}
            for column in RAW_COLUMNS:
                value = row.get(column, "")
                csv_row[column] = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else ("" if value is None else value)
            writer.writerow(csv_row)
    return len(rows)


def read_raw_csv(input_path: str | Path) -> list[dict]:
    with Path(input_path).open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))
