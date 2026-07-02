from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


OUTPUT_COLUMNS = [
    "problem_level",
    "college_name",
    "academic_program_code",
    "program_name",
    "homepage_url",
    "flags",
    "next_action",
    "review_reason",
    "candidate_count",
    "undergraduate_candidate_count",
    "minor_candidate_count",
    "dual_major_candidate_count",
    "minor_data_status",
    "dual_major_data_status",
    "downloadable_candidate_count",
    "download_failed_count",
    "unsupported_source_count",
    "source_dirs_with_files",
    "course_rows",
    "matched_course_rows",
    "ambiguous_course_rows",
    "unmatched_course_rows",
    "course_rows_needing_review",
]

SOURCE_COLUMNS = [
    "issue_type",
    "college_name",
    "academic_program_code",
    "program_name",
    "title_or_file",
    "url_or_path",
    "status_or_reason",
]

PROGRAM_SOURCE_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "program_type",
    "candidate_title",
    "candidate_url",
    "candidate_kind",
    "file_ext",
    "score",
    "source_page_url",
    "parse_status",
    "next_action",
]

MISSING_PROGRAM_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "missing_program_type",
    "status",
    "evidence",
    "next_action",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a department-only problem report from curriculum discovery and parsing outputs."
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
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_problem_report"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = read_csv(args.targets.resolve())
    review_rows = index_by_code(read_csv((args.discovery_dir / "departments_needing_review.csv").resolve()))
    candidate_rows = read_csv((args.discovery_dir / "department_curriculum_source_candidates.csv").resolve())
    download_rows = read_csv((args.discovery_dir / "downloaded_curriculum_sources.csv").resolve())
    match_rows = index_by_code(
        read_csv((args.curriculum_dir / "department_curriculum_match_summary.csv").resolve()),
        code_key="department_code",
    )
    unsupported_rows = read_csv((args.curriculum_dir / "unsupported_sources.csv").resolve())

    failed_downloads = group_by_code(
        [row for row in download_rows if row.get("download_status") != "downloaded"],
        code_key="academic_program_code",
    )
    unsupported_by_code = group_by_code(unsupported_rows, code_key="department_code")

    output_rows: list[dict[str, str]] = []
    source_issue_rows: list[dict[str, str]] = []
    program_source_rows = build_program_source_rows(candidate_rows)
    missing_program_rows: list[dict[str, str]] = []
    level_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()

    for target in targets:
        code = target["academic_program_code"]
        review = review_rows.get(code, {})
        match = match_rows.get(code, {})
        failed = failed_downloads.get(code, [])
        unsupported = unsupported_by_code.get(code, [])

        flags = detect_flags(review, match, failed, unsupported)
        minor_status = program_data_status(review, "minor_candidate_count")
        dual_status = program_data_status(review, "dual_major_candidate_count")
        if not flags:
            continue

        level = problem_level(flags)
        action = next_action(flags)
        level_counts[level] += 1
        flag_counts.update(flags)

        output_rows.append(
            {
                "problem_level": level,
                "college_name": target["college_name"],
                "academic_program_code": code,
                "program_name": target["program_name"],
                "homepage_url": review.get("homepage_url", ""),
                "flags": "; ".join(flags),
                "next_action": action,
                "review_reason": review.get("review_reason", ""),
                "candidate_count": review.get("candidate_count", "0"),
                "undergraduate_candidate_count": review.get("undergraduate_candidate_count", "0"),
                "minor_candidate_count": review.get("minor_candidate_count", "0"),
                "dual_major_candidate_count": review.get("dual_major_candidate_count", "0"),
                "minor_data_status": minor_status,
                "dual_major_data_status": dual_status,
                "downloadable_candidate_count": review.get("downloadable_candidate_count", "0"),
                "download_failed_count": str(len(failed)),
                "unsupported_source_count": str(len(unsupported)),
                "source_dirs_with_files": match.get("source_dirs_with_files", "0"),
                "course_rows": match.get("course_rows", "0"),
                "matched_course_rows": match.get("matched", "0"),
                "ambiguous_course_rows": match.get("ambiguous", "0"),
                "unmatched_course_rows": match.get("unmatched", "0"),
                "course_rows_needing_review": match.get("needs_review", "0"),
            }
        )

        for row in failed:
            source_issue_rows.append(
                {
                    "issue_type": "download_failed",
                    "college_name": target["college_name"],
                    "academic_program_code": code,
                    "program_name": target["program_name"],
                    "title_or_file": row.get("candidate_title", ""),
                    "url_or_path": row.get("candidate_url", ""),
                    "status_or_reason": row.get("error", "") or row.get("download_status", ""),
                }
            )
        for row in unsupported:
            source_issue_rows.append(
                {
                    "issue_type": "unsupported_source_type",
                    "college_name": target["college_name"],
                    "academic_program_code": code,
                    "program_name": target["program_name"],
                    "title_or_file": Path(row.get("source_file", "")).name,
                    "url_or_path": row.get("source_file", ""),
                    "status_or_reason": row.get("reason", ""),
                }
            )
        append_missing_program_row(
            missing_program_rows,
            target,
            "minor",
            minor_status,
            review.get("review_reason", ""),
        )
        append_missing_program_row(
            missing_program_rows,
            target,
            "dual_major",
            dual_status,
            review.get("review_reason", ""),
        )

    output_rows.sort(key=sort_key)
    source_issue_rows.sort(key=lambda row: (row["college_name"], row["program_name"], row["issue_type"]))
    missing_program_rows.sort(
        key=lambda row: (row["college_name"], row["program_name"], row["missing_program_type"])
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "problem_departments.csv", OUTPUT_COLUMNS, output_rows)
    write_csv(output_dir / "problem_department_sources.csv", SOURCE_COLUMNS, source_issue_rows)
    write_csv(output_dir / "minor_dual_major_source_candidates.csv", PROGRAM_SOURCE_COLUMNS, program_source_rows)
    write_csv(output_dir / "missing_minor_dual_major_data.csv", MISSING_PROGRAM_COLUMNS, missing_program_rows)
    summary = {
        "targets": len(targets),
        "problem_departments": len(output_rows),
        "problem_levels": dict(level_counts),
        "flags": dict(flag_counts),
        "source_issue_rows": len(source_issue_rows),
        "minor_dual_major_source_candidates": len(program_source_rows),
        "missing_minor_dual_major_rows": len(missing_program_rows),
        "inputs": {
            "targets": str(args.targets),
            "discovery_dir": str(args.discovery_dir),
            "curriculum_dir": str(args.curriculum_dir),
        },
        "outputs": {
            "problem_departments": str(output_dir / "problem_departments.csv"),
            "problem_department_sources": str(output_dir / "problem_department_sources.csv"),
            "minor_dual_major_source_candidates": str(output_dir / "minor_dual_major_source_candidates.csv"),
            "missing_minor_dual_major_data": str(output_dir / "missing_minor_dual_major_data.csv"),
            "readme": str(output_dir / "README.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(build_readme(summary), encoding="utf-8")
    print(output_dir)


def detect_flags(
    review: dict[str, str],
    match: dict[str, str],
    failed_downloads: list[dict[str, str]],
    unsupported_sources: list[dict[str, str]],
) -> list[str]:
    flags: list[str] = []
    if review.get("homepage_match_status") == "unmatched":
        flags.append("homepage_unmatched")
    if as_int(review.get("candidate_count")) == 0:
        flags.append("no_source_candidate")
    if as_int(review.get("undergraduate_candidate_count")) == 0:
        flags.append("no_undergraduate_candidate")
    if as_int(review.get("minor_candidate_count")) == 0:
        flags.append("no_minor_candidate")
    if as_int(review.get("dual_major_candidate_count")) == 0:
        flags.append("no_dual_major_candidate")
    if failed_downloads:
        flags.append("download_failed")
    if unsupported_sources:
        flags.append("unsupported_source_type")
    if as_int(match.get("source_dirs_with_files")) > 0 and as_int(match.get("course_rows")) == 0:
        flags.append("no_parsed_course_rows")
    if as_int(match.get("unmatched")) > 0:
        flags.append("unmatched_course_rows")
    if as_int(match.get("needs_review")) > 0:
        flags.append("parsed_course_rows_need_review")
    return flags


def program_data_status(review: dict[str, str], count_column: str) -> str:
    count = as_int(review.get(count_column))
    if count > 0:
        return "candidate_found_needs_parse"
    if review.get("homepage_match_status") == "unmatched":
        return "not_checked_homepage_unmatched"
    if as_int(review.get("candidate_count")) == 0:
        return "not_found_in_auto_discovery"
    return "not_found_in_current_auto_result"


def append_missing_program_row(
    rows: list[dict[str, str]],
    target: dict[str, str],
    program_type: str,
    status: str,
    evidence: str,
) -> None:
    if status == "candidate_found_needs_parse":
        return
    rows.append(
        {
            "college_name": target["college_name"],
            "academic_program_code": target["academic_program_code"],
            "program_name": target["program_name"],
            "missing_program_type": program_type,
            "status": status,
            "evidence": evidence,
            "next_action": missing_program_next_action(status),
        }
    )


def missing_program_next_action(status: str) -> str:
    if status == "not_checked_homepage_unmatched":
        return "공식 홈페이지를 먼저 매칭한 뒤 부전공/복수전공 메뉴를 다시 탐지한다."
    if status == "not_found_in_auto_discovery":
        return "학과 홈페이지와 학사요람에서 부전공/복수전공 원문이 별도 존재하는지 수동 확인한다."
    return "현재 후보/파싱 결과에는 없으므로 원문 검토 후 없으면 명시적 없음으로 확정한다."


def build_program_source_rows(candidate_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidate_rows:
        for program_type, marker in (
            ("minor", "has_minor_keyword"),
            ("dual_major", "has_dual_major_keyword"),
        ):
            if candidate.get(marker) != "True":
                continue
            key = (
                candidate.get("academic_program_code", ""),
                program_type,
                candidate.get("candidate_url", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "college_name": candidate.get("college_name", ""),
                    "academic_program_code": candidate.get("academic_program_code", ""),
                    "program_name": candidate.get("program_name", ""),
                    "program_type": program_type,
                    "candidate_title": candidate.get("candidate_title", ""),
                    "candidate_url": candidate.get("candidate_url", ""),
                    "candidate_kind": candidate.get("candidate_kind", ""),
                    "file_ext": candidate.get("file_ext", ""),
                    "score": candidate.get("score", ""),
                    "source_page_url": candidate.get("source_page_url", ""),
                    "parse_status": program_source_parse_status(candidate),
                    "next_action": program_source_next_action(candidate),
                }
            )
    rows.sort(
        key=lambda row: (
            row["college_name"],
            row["program_name"],
            row["program_type"],
            -as_int(row["score"]),
            row["candidate_title"],
        )
    )
    return rows


def program_source_parse_status(candidate: dict[str, str]) -> str:
    if candidate.get("candidate_kind") == "page":
        return "source_page_found_needs_content_parse"
    if candidate.get("file_ext", "").lower() in {".hwp", ".hwpx", ".pdf", ".xls", ".xlsx"}:
        return "source_file_found_needs_file_parse"
    return "source_found_needs_review"


def program_source_next_action(candidate: dict[str, str]) -> str:
    if candidate.get("candidate_kind") == "page":
        return "공지/안내 페이지 본문을 파싱해 신청조건, 적용 교육과정, 제출서류를 구조화한다."
    return "파일을 변환/파싱해 부전공/복수전공 이수학점과 필수과목을 구조화한다."


def problem_level(flags: list[str]) -> str:
    high_flags = {
        "homepage_unmatched",
        "no_source_candidate",
        "download_failed",
        "unsupported_source_type",
        "no_parsed_course_rows",
    }
    medium_flags = {
        "no_undergraduate_candidate",
        "unmatched_course_rows",
        "parsed_course_rows_need_review",
    }
    if any(flag in high_flags for flag in flags):
        return "high"
    if any(flag in medium_flags for flag in flags):
        return "medium"
    return "low"


def next_action(flags: list[str]) -> str:
    if "homepage_unmatched" in flags:
        return "PNU 학과 링크에서 공식 홈페이지를 수동 확인하고 homepage 매칭 규칙을 보강한다."
    if "download_failed" in flags:
        return "실패 URL을 브라우저에서 직접 열어 파일을 수동 저장하거나 referrer/cookie가 필요한지 확인한다."
    if "unsupported_source_type" in flags or "no_parsed_course_rows" in flags:
        return "PDF/HWP/XLSX 파서를 추가하거나 해당 파일을 TXT/HTML로 변환해 00_sources에 넣은 뒤 재파싱한다."
    if "no_source_candidate" in flags or "no_undergraduate_candidate" in flags:
        return "학과 홈페이지의 교육과정/학부교육과정/졸업요건 메뉴를 수동 확인하고 후보 키워드를 보강한다."
    if "unmatched_course_rows" in flags or "parsed_course_rows_need_review" in flags:
        return "과목명과 수강편람 매칭 결과를 확인하고 과목명 별칭 또는 연도별 폐지 과목 처리를 추가한다."
    return "부전공/복수전공 정보가 별도 페이지에 있는지 수동 확인한다."


def sort_key(row: dict[str, str]) -> tuple[int, str, str]:
    level_order = {"high": 0, "medium": 1, "low": 2}
    return (level_order[row["problem_level"]], row["college_name"], row["program_name"])


def build_readme(summary: dict[str, Any]) -> str:
    level_counts = summary["problem_levels"]
    flag_counts = summary["flags"]
    return f"""# 학과별 교육과정 자동 수집 문제 리포트

이 폴더는 전체 학과 목록이 아니라, 자동 수집/다운로드/파싱 결과에서 추가 검토가 필요한 학과만 모은 작업용 산출물이다.

## 현재 요약

- 대상 학과/전공: {summary["targets"]}개
- 문제/검토 대상: {summary["problem_departments"]}개
- high: {level_counts.get("high", 0)}개
- medium: {level_counts.get("medium", 0)}개
- low: {level_counts.get("low", 0)}개
- 파일 단위 문제: {summary["source_issue_rows"]}건
- 부전공/복수전공 후보 소스: {summary["minor_dual_major_source_candidates"]}건
- 부전공/복수전공 현재 결과 누락 행: {summary["missing_minor_dual_major_rows"]}건

## 파일

- `problem_departments.csv`: 학과별 문제 플래그와 다음 작업.
- `problem_department_sources.csv`: 다운로드 실패 파일, 자동 파싱 미지원 파일만 따로 모은 목록.
- `minor_dual_major_source_candidates.csv`: 부전공/복수전공 키워드가 잡힌 공식 후보 페이지/파일 목록.
- `missing_minor_dual_major_data.csv`: 현재 자동 탐지/파싱 결과에서 부전공 또는 복수전공 데이터가 확인되지 않은 학과 목록.
- `summary.json`: 위 통계를 기계가 읽기 쉬운 형태로 저장한 파일.

## 문제 레벨 규칙

- `high`: 공식 홈페이지 미매칭, 후보 없음, 다운로드 실패, PDF/HWP 등 자동 파싱 미지원, 소스 파일은 있으나 과목 행을 만들지 못한 경우.
- `medium`: 학부 교육과정 후보가 불명확하거나, 과목 행은 만들었지만 수강편람 과목 매칭 실패/검토 필요 행이 있는 경우.
- `low`: 부전공/복수전공 후보를 자동 탐지하지 못한 경우만 있는 경우.

`no_minor_candidate`, `no_dual_major_candidate`는 정보가 없다는 뜻이 아니다. 현재 크롤러가 제한된 페이지 안에서 별도 후보를 찾지 못했다는 뜻이다. 이 상태는 `missing_minor_dual_major_data.csv`에 따로 적어두고, 사람이 원문을 확인한 뒤에만 "명시적으로 없음"으로 확정한다.

## 플래그 통계

{format_counter(flag_counts)}

## 재생성 명령

backend 디렉터리에서 실행한다.

```bash
python scripts/build_curriculum_problem_report.py
```

상위 입력 산출물을 새로 만들려면 먼저 다음 순서로 실행한다.

```bash
python scripts/discover_department_curriculum_sources.py --max-pages-per-site 6 --delay-seconds 0
python scripts/download_discovered_curriculum_sources.py --max-files-per-department 4 --min-score 6
python scripts/build_department_curriculum_courses.py
python scripts/build_curriculum_problem_report.py
```

## 다른 AI가 이어받을 때

1. `problem_departments.csv`에서 `problem_level=high`부터 본다.
2. `homepage_unmatched`는 학과 공식 홈페이지 URL을 먼저 고친다.
3. `download_failed`는 `problem_department_sources.csv`의 URL을 브라우저로 확인한다.
4. `unsupported_source_type`은 HWP/PDF/XLSX를 TXT/HTML로 변환하거나 파서를 추가한다.
5. `unmatched_course_rows`는 수강편람 통합 CSV와 과목명/과목번호를 대조한다.
6. 부전공/복수전공을 찾을 때는 먼저 `minor_dual_major_source_candidates.csv`에서 학과명을 검색한다.
7. `missing_minor_dual_major_data.csv`는 부전공/복수전공 데이터가 현재 자동 결과에 없는 학과만 모은 것이다. 원문 검토 후 실제로 없으면 별도 보정 결과에 "없음"을 명시한다.
8. 검증된 원문은 해당 학과 폴더의 `00_sources` 또는 `00_sources_discovered`에 두고, 사람이 보정한 구조화 결과는 `01_normalized` 아래에 둔다.

"""


def format_counter(counter: dict[str, int]) -> str:
    if not counter:
        return "- 없음"
    return "\n".join(f"- `{key}`: {value}" for key, value in sorted(counter.items()))


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
