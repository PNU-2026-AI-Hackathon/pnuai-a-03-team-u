from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


STATUS_COLUMNS = [
    "validation_level",
    "college_name",
    "academic_program_code",
    "program_name",
    "homepage_url",
    "source_status",
    "candidate_count",
    "downloaded_file_count",
    "unsupported_source_count",
    "course_rows",
    "matched_course_rows",
    "unmatched_course_rows",
    "course_rows_needing_review",
    "minor_status",
    "dual_major_status",
    "validation_tasks",
    "source_inventory_path",
    "rule_candidates_path",
]

TASK_COLUMNS = [
    "validation_level",
    "college_name",
    "academic_program_code",
    "program_name",
    "task_type",
    "task",
    "evidence",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize per-department parsed review data for curriculum validation."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--discovery-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_source_discovery"),
    )
    parser.add_argument(
        "--curriculum-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_courses"),
    )
    parser.add_argument(
        "--problem-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_problem_report"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_review_pack"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = read_csv(args.targets.resolve())
    reviews = index_by_code(read_csv((args.discovery_dir / "departments_needing_review.csv").resolve()))
    candidates_by_code = group_by_code(
        read_csv((args.discovery_dir / "department_curriculum_source_candidates.csv").resolve()),
        "academic_program_code",
    )
    downloads_by_code = group_by_code(
        read_csv((args.discovery_dir / "downloaded_curriculum_sources.csv").resolve()),
        "academic_program_code",
    )
    match_summary = index_by_code(
        read_csv((args.curriculum_dir / "department_curriculum_match_summary.csv").resolve()),
        "department_code",
    )
    courses_by_code = group_by_code(
        read_csv((args.curriculum_dir / "department_curriculum_courses.csv").resolve()),
        "department_code",
    )
    unsupported_by_code = group_by_code(
        read_csv((args.curriculum_dir / "unsupported_sources.csv").resolve()),
        "department_code",
    )
    program_sources_by_code = group_by_code(
        read_csv((args.problem_dir / "minor_dual_major_source_candidates.csv").resolve()),
        "academic_program_code",
    )
    missing_programs_by_code = group_by_code(
        read_csv((args.problem_dir / "missing_minor_dual_major_data.csv").resolve()),
        "academic_program_code",
    )

    status_rows: list[dict[str, str]] = []
    task_rows: list[dict[str, str]] = []
    source_status_counts: Counter[str] = Counter()
    validation_level_counts: Counter[str] = Counter()

    for target in targets:
        code = target["academic_program_code"]
        review = reviews.get(code, {})
        candidates = candidates_by_code.get(code, [])
        downloads = downloads_by_code.get(code, [])
        downloaded = [row for row in downloads if row.get("download_status") == "downloaded"]
        failed_downloads = [row for row in downloads if row.get("download_status") != "downloaded"]
        match = match_summary.get(code, {})
        courses = courses_by_code.get(code, [])
        unsupported = unsupported_by_code.get(code, [])
        program_sources = program_sources_by_code.get(code, [])
        missing_programs = missing_programs_by_code.get(code, [])

        source_status = detect_source_status(review, candidates, downloaded, unsupported, match)
        tasks = validation_tasks(
            review=review,
            candidates=candidates,
            downloaded=downloaded,
            failed_downloads=failed_downloads,
            unsupported=unsupported,
            match=match,
            program_sources=program_sources,
            missing_programs=missing_programs,
        )
        level = validation_level(tasks)
        minor_status = program_type_status("minor", program_sources, missing_programs)
        dual_status = program_type_status("dual_major", program_sources, missing_programs)

        display_folder = Path(target["folder_path"])
        folder = Path("..") / display_folder
        extracted_dir = folder / "01_extracted_text"
        rule_dir = folder / "02_rule_candidates"
        display_extracted_dir = display_folder / "01_extracted_text"
        display_rule_dir = display_folder / "02_rule_candidates"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        rule_dir.mkdir(parents=True, exist_ok=True)

        inventory_path = extracted_dir / "curriculum_source_inventory.json"
        html_extract_path = extracted_dir / "discovered_html_pages.json"
        rule_path = rule_dir / "curriculum_rule_candidates.json"
        html_extracts = extract_downloaded_html_pages(downloads)
        write_json(
            html_extract_path,
            {
                "department": department_payload(target, review),
                "html_pages": html_extracts,
            },
        )
        write_json(
            inventory_path,
            {
                "department": department_payload(target, review),
                "source_status": source_status,
                "homepage": review.get("homepage_url", ""),
                "candidates": candidates,
                "downloads": downloads,
                "downloaded_source_type_counts": dict(Counter(source_type(row) for row in downloaded)),
                "html_extracts_path": str(display_extracted_dir / "discovered_html_pages.json"),
                "html_extract_count": len(html_extracts),
                "unsupported_sources": unsupported,
                "course_parse_summary": match,
                "course_rows": compact_course_rows(courses),
            },
        )
        write_json(
            rule_path,
            {
                "department": department_payload(target, review),
                "parse_status": {
                    "validation_level": level,
                    "source_status": source_status,
                    "major_status": major_status(match, unsupported, candidates),
                    "minor_status": minor_status,
                    "dual_major_status": dual_status,
                },
                "program_source_candidates": program_sources,
                "missing_minor_dual_major_data": missing_programs,
                "validation_tasks": tasks,
                "rule_candidates": build_rule_candidates(
                    match,
                    courses,
                    program_sources,
                    missing_programs,
                    major_status(match, unsupported, candidates),
                ),
            },
        )

        status_row = {
            "validation_level": level,
            "college_name": target["college_name"],
            "academic_program_code": code,
            "program_name": target["program_name"],
            "homepage_url": review.get("homepage_url", ""),
            "source_status": source_status,
            "candidate_count": str(len(candidates)),
            "downloaded_file_count": str(len(downloaded)),
            "unsupported_source_count": str(len(unsupported)),
            "course_rows": match.get("course_rows", "0"),
            "matched_course_rows": match.get("matched", "0"),
            "unmatched_course_rows": match.get("unmatched", "0"),
            "course_rows_needing_review": match.get("needs_review", "0"),
            "minor_status": minor_status,
            "dual_major_status": dual_status,
            "validation_tasks": "; ".join(task["task_type"] for task in tasks),
            "source_inventory_path": str(display_extracted_dir / "curriculum_source_inventory.json"),
            "rule_candidates_path": str(display_rule_dir / "curriculum_rule_candidates.json"),
        }
        status_rows.append(status_row)
        source_status_counts[source_status] += 1
        validation_level_counts[level] += 1
        for task in tasks:
            task_rows.append(
                {
                    "validation_level": level,
                    "college_name": target["college_name"],
                    "academic_program_code": code,
                    "program_name": target["program_name"],
                    "task_type": task["task_type"],
                    "task": task["task"],
                    "evidence": task.get("evidence", ""),
                }
            )

    status_rows.sort(key=status_sort_key)
    task_rows.sort(key=lambda row: (level_order(row["validation_level"]), row["college_name"], row["program_name"]))

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "department_parse_status.csv", STATUS_COLUMNS, status_rows)
    write_csv(output_dir / "validation_tasks.csv", TASK_COLUMNS, task_rows)
    per_department_outputs = [
        "01_extracted_text/curriculum_source_inventory.json",
        "01_extracted_text/discovered_html_pages.json",
        "02_rule_candidates/curriculum_rule_candidates.json",
    ]
    summary = {
        "targets": len(targets),
        "per_department_files_written": len(targets) * len(per_department_outputs),
        "validation_levels": dict(validation_level_counts),
        "source_statuses": dict(source_status_counts),
        "validation_tasks": len(task_rows),
        "outputs": {
            "department_parse_status": str(output_dir / "department_parse_status.csv"),
            "validation_tasks": str(output_dir / "validation_tasks.csv"),
            "readme": str(output_dir / "README.md"),
        },
        "per_department_outputs": per_department_outputs,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(build_readme(summary), encoding="utf-8")
    print(output_dir)


def detect_source_status(
    review: dict[str, str],
    candidates: list[dict[str, str]],
    downloaded: list[dict[str, str]],
    unsupported: list[dict[str, str]],
    match: dict[str, str],
) -> str:
    if review.get("homepage_match_status") == "unmatched":
        return "homepage_unmatched"
    if not candidates:
        return "no_candidate"
    if as_int(match.get("course_rows")) > 0:
        return "course_rows_parsed"
    if unsupported:
        return "source_files_need_parser"
    if parser_blocking_downloads(downloaded):
        return "downloaded_files_need_parser"
    if any(source_type(row) == "html" for row in downloaded):
        return "html_pages_extracted"
    if downloaded:
        return "downloaded_sources_need_review"
    return "candidates_found"


def validation_tasks(
    *,
    review: dict[str, str],
    candidates: list[dict[str, str]],
    downloaded: list[dict[str, str]],
    failed_downloads: list[dict[str, str]],
    unsupported: list[dict[str, str]],
    match: dict[str, str],
    program_sources: list[dict[str, str]],
    missing_programs: list[dict[str, str]],
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    if review.get("homepage_match_status") == "unmatched":
        tasks.append(task("homepage", "공식 학과 홈페이지를 수동 매칭한다.", review.get("review_reason", "")))
    if not candidates:
        tasks.append(task("source_discovery", "교육과정/졸업요건 원문 후보를 수동 수집한다.", "candidate_count=0"))
    if failed_downloads:
        tasks.append(task("download", "다운로드 실패 URL을 브라우저로 확인해 원문을 저장한다.", str(len(failed_downloads))))
    if unsupported:
        suffixes = sorted({row.get("suffix", "") for row in unsupported})
        tasks.append(task("file_parser", "PDF/HWP/XLS/XLSX/이미지 파서 또는 변환본을 추가한다.", ", ".join(suffixes)))
    blocking_downloads = parser_blocking_downloads(downloaded)
    if blocking_downloads and as_int(match.get("course_rows")) == 0:
        types = sorted({source_type(row) for row in blocking_downloads})
        tasks.append(
            task(
                "file_parser",
                "다운로드된 PDF/HWP/XLS/이미지 원문을 변환/OCR/파싱해 과목표와 졸업요건 후보를 추출한다.",
                ", ".join(types),
            )
        )
    if any(source_type(row) == "html" for row in downloaded) and as_int(match.get("course_rows")) == 0:
        tasks.append(
            task(
                "html_rule_parse",
                "저장된 HTML 본문/표에서 교육과정, 졸업요건, 부전공/복수전공 규칙 후보를 구조화한다.",
                "html",
            )
        )
    if as_int(match.get("unmatched")) > 0 or as_int(match.get("needs_review")) > 0:
        tasks.append(
            task(
                "course_match",
                "과목명/과목번호를 수강편람과 대조하고 별칭 또는 폐지 과목 처리를 추가한다.",
                f"unmatched={match.get('unmatched', '0')}, needs_review={match.get('needs_review', '0')}",
            )
        )
    if missing_programs:
        missing_types = sorted({row.get("missing_program_type", "") for row in missing_programs})
        tasks.append(
            task(
                "minor_dual_major",
                "부전공/복수전공 원문을 확인하고 없으면 명시적 없음으로 표시한다.",
                ", ".join(missing_types),
            )
        )
    if program_sources:
        tasks.append(
            task(
                "minor_dual_major_parse",
                "부전공/복수전공 후보 페이지를 파싱해 신청조건, 적용 교육과정, 제출서류를 구조화한다.",
                str(len(program_sources)),
            )
        )
    return tasks


def validation_level(tasks: list[dict[str, str]]) -> str:
    high = {"homepage", "source_discovery", "download", "file_parser"}
    medium = {"course_match", "html_rule_parse", "minor_dual_major_parse"}
    task_types = {task["task_type"] for task in tasks}
    if task_types & high:
        return "high"
    if task_types & medium:
        return "medium"
    if task_types:
        return "low"
    return "ready"


def parser_blocking_downloads(downloaded: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in downloaded if source_type(row) not in {"html"}]


def source_type(row: dict[str, str]) -> str:
    path = row.get("downloaded_path", "").lower()
    ext = (row.get("file_ext", "") or Path(path).suffix).lower()
    if ext in {".html", ".htm"} or path.endswith((".html", ".htm")):
        return "html"
    if ext == ".pdf":
        return "pdf"
    if ext in {".hwp", ".hwpx"}:
        return "hwp"
    if ext in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
        return "image"
    if ext in {".doc", ".docx", ".ppt", ".pptx"}:
        return "office"
    if ext == ".zip":
        return "archive"
    return "unknown"


def program_type_status(
    program_type: str,
    program_sources: list[dict[str, str]],
    missing_programs: list[dict[str, str]],
) -> str:
    if any(row.get("program_type") == program_type for row in program_sources):
        return "candidate_found_needs_parse"
    for row in missing_programs:
        if row.get("missing_program_type") == program_type:
            return row.get("status", "not_found_in_current_auto_result")
    return "not_checked"


def major_status(
    match: dict[str, str],
    unsupported: list[dict[str, str]],
    candidates: list[dict[str, str]],
) -> str:
    if as_int(match.get("course_rows")) > 0:
        return "course_rows_parsed_needs_validation"
    if unsupported:
        return "source_file_found_needs_file_parse"
    if candidates:
        return "source_candidate_found_needs_parse"
    return "source_not_found"


def build_rule_candidates(
    match: dict[str, str],
    courses: list[dict[str, str]],
    program_sources: list[dict[str, str]],
    missing_programs: list[dict[str, str]],
    major_status_value: str,
) -> dict[str, Any]:
    return {
        "major": {
            "status": major_status_value,
            "course_rows_count": as_int(match.get("course_rows")),
            "matched_course_rows": as_int(match.get("matched")),
            "unmatched_course_rows": as_int(match.get("unmatched")),
            "needs_review_rows": as_int(match.get("needs_review")),
            "sample_course_rows": compact_course_rows(courses[:20]),
        },
        "minor": {
            "status": program_type_status("minor", program_sources, missing_programs),
            "source_candidates": [row for row in program_sources if row.get("program_type") == "minor"],
            "missing_rows": [row for row in missing_programs if row.get("missing_program_type") == "minor"],
        },
        "dual_major": {
            "status": program_type_status("dual_major", program_sources, missing_programs),
            "source_candidates": [row for row in program_sources if row.get("program_type") == "dual_major"],
            "missing_rows": [row for row in missing_programs if row.get("missing_program_type") == "dual_major"],
        },
    }


def compact_course_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    columns = [
        "department_code",
        "department_name",
        "document_title",
        "curriculum_year",
        "recommended_year",
        "recommended_semester",
        "category",
        "raw_course_name",
        "raw_credit",
        "matched_course_code",
        "matched_course_name",
        "match_status",
        "needs_review",
        "review_reason",
    ]
    return [{column: row.get(column, "") for column in columns} for row in rows]


def extract_downloaded_html_pages(downloads: list[dict[str, str]]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for row in downloads:
        path_text = row.get("downloaded_path", "")
        if row.get("candidate_kind") != "page" and not path_text.lower().endswith((".html", ".htm")):
            continue
        path = Path(path_text)
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else row.get("candidate_title", "")
        body_text = clean_text(soup.get_text(" ", strip=True))
        pages.append(
            {
                "candidate_title": row.get("candidate_title", ""),
                "candidate_url": row.get("candidate_url", ""),
                "downloaded_path": path_text,
                "title": title,
                "text": body_text[:20000],
                "tables": extract_html_tables(soup),
            }
        )
    return pages


def extract_html_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows = []
        for tr in table.find_all("tr"):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append({"table_index": table_index, "rows": rows[:200]})
    return tables


def clean_text(value: str) -> str:
    return " ".join((value or "").split())


def department_payload(target: dict[str, str], review: dict[str, str]) -> dict[str, str]:
    return {
        "college_name": target["college_name"],
        "academic_program_code": target["academic_program_code"],
        "program_name": target["program_name"],
        "status_name": target.get("status_name", ""),
        "first_admission_year": target.get("first_admission_year", ""),
        "program_feature_name": target.get("program_feature_name", ""),
        "duration_name": target.get("duration_name", ""),
        "folder_path": target.get("folder_path", ""),
        "homepage_url": review.get("homepage_url", ""),
    }


def task(task_type: str, text: str, evidence: str = "") -> dict[str, str]:
    return {"task_type": task_type, "task": text, "evidence": evidence}


def status_sort_key(row: dict[str, str]) -> tuple[int, str, str]:
    return (level_order(row["validation_level"]), row["college_name"], row["program_name"])


def level_order(level: str) -> int:
    return {"high": 0, "medium": 1, "low": 2, "ready": 3}.get(level, 9)


def build_readme(summary: dict[str, Any]) -> str:
    return f"""# 학과별 교육과정 파싱/검증 패키지

이 폴더는 각 학과 폴더에 저장된 파싱 결과를 검증하기 위한 집계 산출물이다.

## 현재 요약

- 대상 학과/전공: {summary["targets"]}개
- 학과별 저장 파일: {summary["per_department_files_written"]}개
- 검증 작업 행: {summary["validation_tasks"]}건

## 학과별 저장 파일

각 학과 폴더 아래에 다음 파일을 저장한다.

- `01_extracted_text/curriculum_source_inventory.json`: 홈페이지, 후보 URL, 다운로드 파일, 파싱된 과목 행 등 원문 인벤토리.
- `01_extracted_text/discovered_html_pages.json`: 저장된 HTML 후보 페이지의 본문 텍스트와 HTML 표 추출 결과.
- `02_rule_candidates/curriculum_rule_candidates.json`: 주전공/부전공/복수전공별 규칙 후보와 검증 작업.

## 집계 파일

- `department_parse_status.csv`: 학과별 파싱 상태와 검증 우선순위.
- `validation_tasks.csv`: 사람이 확인해야 할 작업 목록.
- `summary.json`: 집계 통계.

## 검증 레벨

- `high`: 홈페이지 미매칭, 후보 없음, 다운로드 실패, HWP/PDF/XLS/이미지 등 파서/OCR 필요.
- `medium`: HTML 본문/표 규칙화, 과목 매칭 검토 또는 부전공/복수전공 후보 페이지 파싱 필요.
- `low`: 부전공/복수전공 후보가 현재 결과에 없어 원문 확인 필요.
- `ready`: 현재 자동 산출물 기준으로 즉시 검증 가능한 상태.

## 재생성

backend 디렉터리에서 실행한다.

```bash
python scripts/materialize_department_curriculum_review_data.py
```

상위 데이터가 바뀌면 먼저 discovery/download/course/problem report 스크립트를 다시 실행한 뒤 이 스크립트를 실행한다.
"""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def index_by_code(rows: list[dict[str, str]], code_key: str = "academic_program_code") -> dict[str, dict[str, str]]:
    return {row[code_key]: row for row in rows if row.get(code_key)}


def group_by_code(rows: list[dict[str, str]], code_key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get(code_key):
            grouped[row[code_key]].append(row)
    return grouped


def as_int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


if __name__ == "__main__":
    main()
