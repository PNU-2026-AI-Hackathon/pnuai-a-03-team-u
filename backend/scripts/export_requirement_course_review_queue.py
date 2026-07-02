"""사람 검토가 필요한 requirement_courses 후보를 리뷰용 CSV로 뽑아낸다.

`raw_data/parsed_experiments/graduation_requirement_seed_tables/requirement_course_seed_candidates.csv`
(build_graduation_requirement_seed_tables.py의 출력)를 입력으로 받아, needs_review=Y인
행만 대학/학과/카테고리 순으로 정렬해 사람이 훑어보기 쉬운 형태로 내보낸다.

리뷰어는 이 파일을 그대로 고치는 게 아니라, 확인이 끝난 행만 골라
`resolution`/`corrected_*`/`reviewed_by` 열을 채워서
`backend/seeds/requirement_course_corrections.csv`에 옮겨 적는다
(append_to_corrections.py 참고, 또는 직접 CSV 편집).

실행:
    python scripts/export_requirement_course_review_queue.py
"""

from __future__ import annotations

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_TABLES_DIR = REPO_ROOT / "raw_data/parsed_experiments/graduation_requirement_seed_tables"
INPUT_PATH = SEED_TABLES_DIR / "requirement_course_seed_candidates.csv"
OUTPUT_PATH = SEED_TABLES_DIR / "requirement_course_review_queue.csv"

OUTPUT_COLUMNS = [
    "requirement_course_id",
    "college_name",
    "program_name",
    "program_type",
    "curriculum_year",
    "category_code",
    "raw_course_code",
    "raw_course_name",
    "raw_credit",
    "match_status",
    "matched_course_code",
    "matched_course_name",
    "matched_departments",
    "choice_rule_types",
    "review_reason",
    "source_file",
    # 리뷰어가 채우는 열 (비워두면 미검토 상태로 남음)
    "resolution",  # confirm | fix | drop | needs_source
    "corrected_matched_course_code",
    "corrected_matched_course_name",
    "corrected_match_status",
    "reviewed_by",
    "note",
]


def main() -> None:
    with INPUT_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    pending = [row for row in rows if (row.get("needs_review") or "").strip().upper() in {"Y", "TRUE", "1"}]
    pending.sort(
        key=lambda r: (
            r.get("college_name", ""),
            r.get("program_name", ""),
            r.get("category_code", ""),
            r.get("raw_course_name", ""),
        )
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in pending:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})

    print(f"{len(pending)}건 (전체 {len(rows)}건 중) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
