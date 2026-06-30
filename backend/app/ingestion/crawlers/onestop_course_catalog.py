"""Fetch PNU Onestop course catalog data.

This crawler talks to the same JSON endpoint used by the Onestop course catalog
page. The site wraps AJAX payloads in RSA-encrypted `_data`, so the crawler
mirrors the client-side encryption flow instead of relying on a browser.

Raw outputs should be written under ignored folders such as `raw_data/`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://onestop.pusan.ac.kr"
COURSE_CATALOG_PAGE = f"{BASE_URL}/page?menuCD=000000000000335"
COURSE_CATALOG_ENDPOINT = (
    f"{BASE_URL}/ost/cls/atlectmanual/atlectmanual/selectAtlectManual_v2025"
)
COURSE_PRECAUTION_ENDPOINT = (
    f"{BASE_URL}/ost/cls/atlectmanual/atlectmanual/selectAtlectManualPrecaution"
)

COLLEGE_UNDERGRAD_CODE = "0001"
LOCALE_KOREAN = "0001"

TERM_CODES = {
    "1": "0010",
    "2": "0020",
    "summer": "0011",
    "winter": "0021",
}

SUBJECT_CATEGORIES = {
    "1": "전공,교직과목(2,3,4학년)",
    "2": "전공기초 및 기타1학년",
    "3": "효원(균형,창의)교양-교양선택",
    "4": "효원핵심교양(교양필수)",
    "5": "일반선택",
}

CANONICAL_COLUMNS = [
    "school",
    "year",
    "semester",
    "source_type",
    "source_name",
    "source_snapshot_date",
    "crawled_at",
    "offering_status",
    "change_status",
    "subject_category_code",
    "subject_category_name",
    "college",
    "parent_department",
    "offering_department_code",
    "offering_department",
    "display_department_name",
    "target_grade",
    "course_code",
    "section",
    "course_name",
    "category",
    "credits",
    "lecture_hours",
    "practice_hours",
    "total_hours",
    "timetable_raw",
    "timetable_parse_status",
    "professor",
    "capacity",
    "enrolled_count",
    "capacity_raw",
    "general_education_area",
    "foreign_language_lecture",
    "team_teaching",
    "is_remote",
    "class_type",
    "remark",
    "raw_department",
]

PRECAUTION_COLUMNS = [
    "school",
    "year",
    "semester",
    "course_code",
    "section",
    "course_name",
    "offering_department",
    "message",
    "raw_response",
]

SNAPSHOT_COMPARE_COLUMNS = [
    "school",
    "year",
    "semester",
    "subject_category_code",
    "offering_department_code",
    "offering_department",
    "target_grade",
    "course_code",
    "section",
    "course_name",
    "category",
    "credits",
    "total_hours",
    "timetable_raw",
    "professor",
    "capacity",
    "enrolled_count",
    "foreign_language_lecture",
    "is_remote",
    "class_type",
    "remark",
]


@dataclass(frozen=True)
class OnestopSessionInfo:
    rsa_modulus: str
    rsa_exponent: str
    csrf_token: str


def _js_byte_len_char(char: str) -> int:
    code = ord(char)
    upper = char.upper()
    if (upper < "0" or upper > "9") and (upper < "A" or upper > "Z") and (
        code > 255 or code < 0
    ):
        return 3
    return 1


def _rsa_encrypt_one(message: str, modulus_hex: str, exponent_hex: str) -> str:
    modulus = int(modulus_hex, 16)
    exponent = int(exponent_hex, 16)
    key_size = (modulus.bit_length() + 7) // 8
    message_bytes = message.encode("utf-8")
    max_size = key_size - 11
    if len(message_bytes) > max_size:
        raise ValueError(f"RSA chunk too long: {len(message_bytes)} bytes > {max_size}")

    padding_len = key_size - len(message_bytes) - 3
    padding = bytearray()
    while len(padding) < padding_len:
        padding.append(secrets.randbelow(255) + 1)

    block = b"\x00\x02" + bytes(padding) + b"\x00" + message_bytes
    encrypted = pow(int.from_bytes(block, "big"), exponent, modulus)
    return encrypted.to_bytes(key_size, "big").hex()


def _ajax_encrypt_param(text: str, session_info: OnestopSessionInfo) -> str:
    byte_length = sum(_js_byte_len_char(char) for char in text)
    if byte_length <= 245:
        return _rsa_encrypt_one(
            text, session_info.rsa_modulus, session_info.rsa_exponent
        )

    chunks: list[str] = []
    current = ""
    current_len = 0
    for index, char in enumerate(text):
        current += char
        current_len += _js_byte_len_char(char)
        if current_len > 200 or index == len(text) - 1:
            chunks.append(
                _rsa_encrypt_one(
                    current, session_info.rsa_modulus, session_info.rsa_exponent
                )
            )
            current = ""
            current_len = 0
    return ",".join(chunks)


def _extract_session_info(html: str) -> OnestopSessionInfo:
    modulus = re.search(r"RSAModulus = '([^']+)'", html)
    exponent = re.search(r"RSAExponent = '([^']+)'", html)
    token = re.search(r'scwin\.token = "([^"]+)"', html)
    if not modulus or not exponent or not token:
        raise RuntimeError("Could not extract Onestop RSA or CSRF values")
    return OnestopSessionInfo(
        rsa_modulus=modulus.group(1),
        rsa_exponent=exponent.group(1),
        csrf_token=token.group(1),
    )


def _wrap_ajax_payload(payload: dict[str, Any], session_info: OnestopSessionInfo) -> str:
    request_payload = dict(payload)
    request_payload["locale"] = LOCALE_KOREAN
    inner_payload = {"_data": json.dumps(request_payload, ensure_ascii=False)}
    plain_text = json.dumps(inner_payload, ensure_ascii=False, separators=(",", ":"))
    encrypted = _ajax_encrypt_param(plain_text, session_info)
    return json.dumps({"_data": encrypted}, ensure_ascii=False)


def create_session() -> tuple[requests.Session, OnestopSessionInfo]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Referer": COURSE_CATALOG_PAGE,
        }
    )
    response = session.get(COURSE_CATALOG_PAGE, timeout=30)
    response.raise_for_status()
    return session, _extract_session_info(response.text)


def build_search_payload(
    year: int,
    semester_code: str,
    subject_category_code: str,
    page_size: int,
    page_index: int = 0,
) -> dict[str, Any]:
    return {
        "SCH_SYEAR": str(year),
        "SCH_TERM_GCD": semester_code,
        "SCH_COLL_GRAD_GCD": COLLEGE_UNDERGRAD_CODE,
        "SCH_SUBJ_GBN": str(subject_category_code),
        "SEARCH_GBN": "1",
        "SCH_DETAIL": "",
        "SCH_GRAD_GCD": "",
        "SCH_COLL_CD": "",
        "SCH_DEPT_CD": "",
        "SCH_SUBJ_NM": "",
        "SCH_PNU_CAPBLTY_GCD": "",
        "SCH_NATIVE_LANG_LECT_GCD": "",
        "sch_AllOC_CHK": "N",
        "TITLE": "목록",
        "pageSize": page_size,
        "pageIndex": page_index,
    }


def post_course_catalog(
    session: requests.Session,
    session_info: OnestopSessionInfo,
    payload: dict[str, Any],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "AJAX": "true",
        "X-CSRF-TOKEN": session_info.csrf_token,
        "Referer": COURSE_CATALOG_PAGE,
    }
    body = _wrap_ajax_payload(payload, session_info).encode("utf-8")
    response = session.post(
        COURSE_CATALOG_ENDPOINT, data=body, headers=headers, timeout=60
    )
    response.raise_for_status()
    return response.json()


def post_course_precaution(
    session: requests.Session,
    session_info: OnestopSessionInfo,
    raw_row: dict[str, Any],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "AJAX": "true",
        "X-CSRF-TOKEN": session_info.csrf_token,
        "Referer": COURSE_CATALOG_PAGE,
    }
    body = _wrap_ajax_payload(raw_row, session_info).encode("utf-8")
    response = session.post(
        COURSE_PRECAUTION_ENDPOINT, data=body, headers=headers, timeout=60
    )
    response.raise_for_status()
    return response.json()


def fetch_subject_category(
    session: requests.Session,
    session_info: OnestopSessionInfo,
    year: int,
    semester_code: str,
    subject_category_code: str,
    page_size: int,
) -> dict[str, Any]:
    first_payload = build_search_payload(
        year=year,
        semester_code=semester_code,
        subject_category_code=subject_category_code,
        page_size=1,
    )
    first_response = post_course_catalog(session, session_info, first_payload)
    total_count = int(first_response.get("pageInfo", {}).get("totCnt") or 0)

    if total_count == 0:
        return {
            "subject_category_code": subject_category_code,
            "subject_category_name": SUBJECT_CATEGORIES.get(subject_category_code, ""),
            "total_count": 0,
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    page_index = 0
    while len(rows) < total_count:
        payload = build_search_payload(
            year=year,
            semester_code=semester_code,
            subject_category_code=subject_category_code,
            page_size=page_size,
            page_index=page_index,
        )
        response = post_course_catalog(session, session_info, payload)
        data = response.get("data") or []
        rows.extend(data)
        if not data or len(data) < page_size:
            break
        page_index += 1

    return {
        "subject_category_code": subject_category_code,
        "subject_category_name": SUBJECT_CATEGORIES.get(subject_category_code, ""),
        "total_count": total_count,
        "rows": rows[:total_count],
    }


def _clean_html_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_allocated_capacity(raw: Any) -> tuple[str, str, str]:
    text = _clean_html_text(raw)
    if not text:
        return "", "", ""
    match = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", text)
    if match:
        return match.group(1), match.group(2), text
    return "", "", text


def normalize_row(
    row: dict[str, Any],
    year: int,
    semester: str,
    subject_category_code: str,
    subject_category_name: str,
    crawled_at: str,
) -> dict[str, Any]:
    enrolled_count, capacity, capacity_raw = _split_allocated_capacity(
        row.get("ALLOC_RCNT")
    )
    raw_department = _clean_html_text(row.get("MNG_DEPT_NM"))
    offering_department = raw_department.split("(")[0].strip()
    target_grade = _clean_html_text(row.get("STDT_YEAR_NM"))
    timetable_raw = _clean_html_text(row.get("TIMETABLE_SUMMARY_INFO"))

    return {
        "school": "부산대학교",
        "year": str(year),
        "semester": semester,
        "source_type": "onestop_json",
        "source_name": COURSE_CATALOG_PAGE,
        "source_snapshot_date": "",
        "crawled_at": crawled_at,
        "offering_status": "active",
        "change_status": "",
        "subject_category_code": subject_category_code,
        "subject_category_name": subject_category_name,
        "college": "",
        "parent_department": "",
        "offering_department_code": _clean_html_text(row.get("MNG_DEPT_CD")),
        "offering_department": offering_department,
        "display_department_name": offering_department,
        "target_grade": target_grade,
        "course_code": _clean_html_text(row.get("SUBJ_NO")),
        "section": _clean_html_text(row.get("CLASS_NO")),
        "course_name": _clean_html_text(row.get("SUBJ_NM")),
        "category": _clean_html_text(row.get("SUBJ_GCD_NM")),
        "credits": _clean_html_text(row.get("CRDT")),
        "lecture_hours": "",
        "practice_hours": "",
        "total_hours": _clean_html_text(row.get("SIGAN")),
        "timetable_raw": timetable_raw,
        "timetable_parse_status": "needs_review" if timetable_raw else "empty",
        "professor": _clean_html_text(row.get("PROF_NM")),
        "capacity": capacity,
        "enrolled_count": enrolled_count,
        "capacity_raw": capacity_raw,
        "general_education_area": "",
        "foreign_language_lecture": _clean_html_text(row.get("NATIVE_LANG_NM")),
        "team_teaching": "",
        "is_remote": "Y" if _clean_html_text(row.get("ALL_CYBER")) else "N",
        "class_type": _clean_html_text(row.get("CLASS_TYPE_NM_KOR")),
        "remark": _clean_html_text(row.get("REMARK")),
        "raw_department": raw_department,
    }


def deduplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row["school"],
            row["course_code"],
            row["year"],
            row["semester"],
            row["section"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_precaution_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=PRECAUTION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_manifest_path(output_dir: Path, year: int, semester: str) -> Path:
    return output_dir / f"{year}_{semester}_snapshot_manifest.json"


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row.get("school", "")),
        str(row.get("year", "")),
        str(row.get("semester", "")),
        str(row.get("course_code", "")),
        str(row.get("section", "")),
        str(row.get("subject_category_code", "")),
    )


def calculate_snapshot_checksum(rows: list[dict[str, Any]]) -> str:
    comparable_rows = []
    for row in sorted(rows, key=_row_sort_key):
        comparable_rows.append(
            {column: str(row.get(column, "")) for column in SNAPSHOT_COMPARE_COLUMNS}
        )
    payload = json.dumps(comparable_rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_snapshot_manifest(
    output_dir: Path,
    year: int,
    semester: str,
    rows: list[dict[str, Any]],
    counts_by_subject_category: dict[str, int],
    crawled_at: str,
) -> dict[str, Any]:
    manifest_path = _snapshot_manifest_path(output_dir, year, semester)
    previous_manifest = read_json(manifest_path)
    checksum = calculate_snapshot_checksum(rows)
    previous_checksum = (
        previous_manifest.get("snapshot_checksum") if previous_manifest else None
    )
    if previous_checksum is None:
        snapshot_status = "new_snapshot"
    elif previous_checksum == checksum:
        snapshot_status = "unchanged"
    else:
        snapshot_status = "changed"

    return {
        "school": "부산대학교",
        "year": str(year),
        "semester": semester,
        "source_type": "onestop_json",
        "source_name": COURSE_CATALOG_PAGE,
        "crawled_at": crawled_at,
        "row_count": len(rows),
        "counts_by_subject_category": counts_by_subject_category,
        "snapshot_checksum": checksum,
        "previous_snapshot_checksum": previous_checksum or "",
        "snapshot_status": snapshot_status,
        "compare_columns": SNAPSHOT_COMPARE_COLUMNS,
    }


def crawl_course_catalog(
    year: int,
    semester: str,
    subject_categories: list[str],
    output_dir: Path,
    page_size: int,
    include_precautions: bool = False,
    precaution_limit: int | None = None,
    request_delay_seconds: float = 0.0,
    skip_write_if_unchanged: bool = False,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    semester_code = TERM_CODES.get(semester, semester)
    session, session_info = create_session()
    crawled_at = datetime.now(UTC).isoformat()

    raw_category_results: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    precaution_rows: list[dict[str, Any]] = []

    for subject_category_code in subject_categories:
        result = fetch_subject_category(
            session=session,
            session_info=session_info,
            year=year,
            semester_code=semester_code,
            subject_category_code=subject_category_code,
            page_size=page_size,
        )
        raw_category_results.append(result)
        raw_path = output_dir / "raw_json" / (
            f"{year}_{semester}_subject_{subject_category_code}.json"
        )
        write_json(raw_path, result)

        normalized_rows.extend(
            normalize_row(
                row=row,
                year=year,
                semester=semester,
                subject_category_code=subject_category_code,
                subject_category_name=result["subject_category_name"],
                crawled_at=crawled_at,
            )
            for row in result["rows"]
        )

        if include_precautions:
            rows_for_precautions = result["rows"]
            if precaution_limit is not None:
                remaining = max(precaution_limit - len(precaution_rows), 0)
                rows_for_precautions = rows_for_precautions[:remaining]

            for raw_row in rows_for_precautions:
                response = post_course_precaution(session, session_info, raw_row)
                message = ""
                data = response.get("data") or []
                if data and isinstance(data[0], dict):
                    message = _clean_html_text(data[0].get("MSG"))

                normalized = normalize_row(
                    row=raw_row,
                    year=year,
                    semester=semester,
                    subject_category_code=subject_category_code,
                    subject_category_name=result["subject_category_name"],
                    crawled_at=crawled_at,
                )
                precaution_rows.append(
                    {
                        "school": normalized["school"],
                        "year": normalized["year"],
                        "semester": normalized["semester"],
                        "course_code": normalized["course_code"],
                        "section": normalized["section"],
                        "course_name": normalized["course_name"],
                        "offering_department": normalized["offering_department"],
                        "message": message,
                        "raw_response": json.dumps(response, ensure_ascii=False),
                    }
                )
                if request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)

                if precaution_limit is not None and len(precaution_rows) >= precaution_limit:
                    break

        if precaution_limit is not None and len(precaution_rows) >= precaution_limit:
            # Keep crawling remaining course rows disabled only for precautions.
            include_precautions = False

    unique_rows = deduplicate_rows(normalized_rows)
    counts_by_subject_category = {
        result["subject_category_code"]: len(result["rows"])
        for result in raw_category_results
    }
    manifest = build_snapshot_manifest(
        output_dir=output_dir,
        year=year,
        semester=semester,
        rows=unique_rows,
        counts_by_subject_category=counts_by_subject_category,
        crawled_at=crawled_at,
    )

    should_write_csv = not (
        skip_write_if_unchanged and manifest["snapshot_status"] == "unchanged"
    )
    if should_write_csv:
        write_csv(output_dir / f"{year}_{semester}_course_catalog.csv", unique_rows)
    if precaution_rows and should_write_csv:
        write_precaution_csv(
            output_dir / f"{year}_{semester}_course_precautions.csv", precaution_rows
        )
    manifest["csv_written"] = should_write_csv
    write_json(_snapshot_manifest_path(output_dir, year, semester), manifest)
    return raw_category_results, unique_rows, precaution_rows, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl PNU Onestop course catalog")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--semester",
        required=True,
        help="Semester shorthand such as 1, 2, summer, winter or a raw term code",
    )
    parser.add_argument(
        "--subject-categories",
        nargs="+",
        default=list(SUBJECT_CATEGORIES.keys()),
        help="Subject category codes to crawl. Defaults to 1 2 3 4 5.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("raw_data/crawled_data/onestop_course_catalog"),
    )
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument(
        "--include-precautions",
        action="store_true",
        help="Also call the course precaution endpoint for each crawled row.",
    )
    parser.add_argument(
        "--precaution-limit",
        type=int,
        default=None,
        help="Optional max number of precaution requests for experiments.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay between precaution requests.",
    )
    parser.add_argument(
        "--skip-write-if-unchanged",
        action="store_true",
        help=(
            "Compare the current normalized rows with the previous term manifest "
            "and skip rewriting the normalized CSV when the checksum is unchanged."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_results, normalized_rows, precaution_rows, manifest = crawl_course_catalog(
        year=args.year,
        semester=args.semester,
        subject_categories=args.subject_categories,
        output_dir=args.output_dir,
        page_size=args.page_size,
        include_precautions=args.include_precautions,
        precaution_limit=args.precaution_limit,
        request_delay_seconds=args.request_delay_seconds,
        skip_write_if_unchanged=args.skip_write_if_unchanged,
    )
    counts = {
        result["subject_category_code"]: len(result["rows"]) for result in raw_results
    }
    print(
        json.dumps(
            {
                "year": args.year,
                "semester": args.semester,
                "counts_by_subject_category": counts,
                "normalized_count": len(normalized_rows),
                "precaution_count": len(precaution_rows),
                "snapshot_status": manifest["snapshot_status"],
                "snapshot_checksum": manifest["snapshot_checksum"],
                "csv_written": manifest["csv_written"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
