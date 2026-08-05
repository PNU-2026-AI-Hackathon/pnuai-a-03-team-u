"""Onestop 수강편람 CSV → course_offerings + course_times 적재.

크롤러(app/ingestion/crawlers/onestop_course_catalog.py)가 만든
`raw_data/crawled_data/onestop_course_catalog/{year}_{semester}/{year}_{semester}_course_catalog.csv`
를 읽어, Course.course_code 매칭으로 course_offerings 를 upsert 하고
timetable_raw 파싱 결과를 course_times 로 다시 채운다.

사용:
    # dry-run(기본): DB 미기록, 매칭/파싱 통계만 출력
    ./backend/.venv/bin/python -m scripts.import_course_offerings \
        --csv raw_data/crawled_data/onestop_course_catalog/2026_2/2026_2_course_catalog.csv

    # 실제 반영
    ./backend/.venv/bin/python -m scripts.import_course_offerings \
        --csv raw_data/crawled_data/onestop_course_catalog/2026_2/2026_2_course_catalog.csv \
        --commit

멱등성:
- upsert 키는 (course_id, year, semester, section).
- 재실행 시 CourseOffering은 값을 덮어쓰고, 소속 CourseTime은 전량 삭제 후
  재삽입한다(강의실/시간 변경분을 무리 없이 반영하기 위함).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

# `scripts/`에서 실행할 때 프로젝트 루트가 sys.path에 없어 app.* 임포트가 실패한다.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.ingestion.parsers.onestop_course_catalog import parse_timetable_raw


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _iter_csv(csv_path: Path) -> Iterable[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def _semester_display(raw: str) -> str:
    """CSV의 `semester` 값(1/2/summer/winter)을 DB 표기에 맞춘다."""
    mapping = {"1": "1학기", "2": "2학기", "summer": "여름계절수업", "winter": "겨울계절수업"}
    return mapping.get(raw, raw)


def import_csv(csv_path: Path, db: Session, *, commit: bool) -> dict:
    stats = Counter()
    unmatched_codes: list[str] = []

    # course_code → id 매핑을 한 번에 로드해 CSV 순회 중 개별 SELECT를 피한다.
    code_to_id: dict[str, int] = dict(
        db.execute(select(Course.course_code, Course.id).where(Course.course_code.is_not(None))).all()
    )

    # 재삽입할 offering들의 CourseTime을 이번 실행 내에서 한 번씩만 비운다.
    times_cleared_for: set[int] = set()

    for row in _iter_csv(csv_path):
        stats["rows_total"] += 1

        course_code = (row.get("course_code") or "").strip()
        if not course_code:
            stats["skipped_no_course_code"] += 1
            continue

        course_id = code_to_id.get(course_code)
        if course_id is None:
            # 수강편람이 courses 카탈로그보다 넓지만(교양 등 학과 밖 개설 포함) 이 스크립트는
            # courses 테이블을 손대지 않는다. 매칭 실패 offering은 스킵하고 카운트만 리포트.
            # 교양 등 학과 밖 개설분은 별도 트랙(학지시 크롤러 → 유저 이수 데이터)에서 처리.
            stats["skipped_unmatched_course"] += 1
            if len(unmatched_codes) < 20:
                unmatched_codes.append(course_code)
            continue

        year = row["year"].strip()
        semester_display = _semester_display(row["semester"].strip())
        section = (row.get("section") or "").strip() or None

        offering = db.scalars(
            select(CourseOffering).where(
                CourseOffering.course_id == course_id,
                CourseOffering.year == year,
                CourseOffering.semester == semester_display,
                CourseOffering.section == section,
            )
        ).first()

        if offering is None:
            offering = CourseOffering(
                course_id=course_id,
                year=year,
                semester=semester_display,
                section=section,
                school=row.get("school") or None,
            )
            db.add(offering)
            stats["offerings_created"] += 1
        else:
            stats["offerings_updated"] += 1

        offering.school = row.get("school") or offering.school
        offering.professor = (row.get("professor") or None)
        offering.capacity = _to_int(row.get("capacity"))
        offering.enrolled_count = _to_int(row.get("enrolled_count"))

        # DB 왕복 없이 offering.id를 얻어야 course_times 재삽입이 되므로 flush.
        db.flush()

        if offering.id not in times_cleared_for:
            db.query(CourseTime).filter(CourseTime.offering_id == offering.id).delete(
                synchronize_session=False
            )
            times_cleared_for.add(offering.id)

        parsed_sessions = parse_timetable_raw(row.get("timetable_raw"))
        stats["time_sessions_parsed"] += len(parsed_sessions)
        for session in parsed_sessions:
            db.add(
                CourseTime(
                    offering_id=offering.id,
                    day_of_week=session.day_of_week,
                    start_time=session.start_time,
                    end_time=session.end_time,
                    classroom=session.classroom or None,
                )
            )

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "stats": dict(stats),
        "unmatched_course_code_samples": unmatched_codes,
        "committed": commit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Onestop 수강편람 CSV → course_offerings/times 적재")
    parser.add_argument("--csv", type=Path, required=True, help="크롤러가 만든 course_catalog.csv 경로")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="실제 DB 반영. 미지정 시 dry-run(트랜잭션 rollback).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        result = import_csv(args.csv, db, commit=args.commit)
    finally:
        db.close()

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
