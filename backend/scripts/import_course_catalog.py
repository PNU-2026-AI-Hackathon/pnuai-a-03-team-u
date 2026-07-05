"""raw_data/crawled_data/onestop_course_catalog의 학기별 수강편람 CSV를 읽어
course_code 기준으로 합친 과목 마스터를 courses 테이블에 upsert한다.

시간표/분반/교수 같은 학기별 개설 정보는 다루지 않는다 (나중에 시간표 추천
기능을 만들 때 같은 원본에서 별도로 다룬다). 실행 전에 `alembic upgrade head`로
courses.course_code unique 제약(revision a1c47e0f9d52)이 적용돼 있어야 한다.

실행: python -m scripts.import_course_catalog
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.db import SessionLocal
from app.ingestion.csv_importers.course_catalog_importer import import_course_catalog

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_DIR = REPO_ROOT / "raw_data/crawled_data/onestop_course_catalog"
DEFAULT_REVIEW_OUTPUT = REPO_ROOT / "raw_data/reports/course_catalog_import_review.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW_OUTPUT)
    parser.add_argument(
        "--no-review-output",
        action="store_true",
        help="review CSV를 안 쓰고 콘솔 요약만 출력",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = import_course_catalog(
            db,
            catalog_dir=args.catalog_dir,
            review_output_path=None if args.no_review_output else args.review_output,
        )
    finally:
        db.close()

    print("과목 마스터 적재 완료")
    print(f"  원본 행: {summary['source_rows']}")
    print(f"  고유 course_code: {summary['distinct_courses']}")
    print(f"  학과 매칭: {summary['matched_department']}")
    print(f"  학과 미매칭: {summary['unmatched_department']}")
    print(f"  학과 drift(학기별로 다르게 찍힘): {summary['department_drift']}")
    print(f"  이수구분 drift: {summary['category_drift']}")
    if not args.no_review_output:
        print(f"  review CSV: {args.review_output} ({summary['review_rows_written']}행)")


if __name__ == "__main__":
    main()
