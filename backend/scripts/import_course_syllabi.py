"""One-Stop 교수계획표(강의계획서)를 크롤링·파싱해서 `course_syllabi`에 upsert한다.

강의계획서 RAG 반영 파일럿(2026-08-24, `docs/progress/`에 아직 설계 문서는 없음 —
`local.md` 참고) 실행 스크립트. 전공(major) 하나를 대상으로, 그 전공 소속
`courses`의 이름들로 One-Stop을 검색하고, `course_offerings`(같은 year/semester)에
매칭되는 분반만 `CourseSyllabus`로 저장한다.

전공 대신 학과(department) 전체를 대상으로 하려면 `--department`만 주고
`--major`는 생략 — 그 학과 소속 전공 미지정 과목까지 포함해서 이름을 모은다.

실행 (파일럿 대상 컴퓨터공학전공, 2026-2학기):
    python -m scripts.import_course_syllabi \
        --major 컴퓨터공학전공 --year 2026 --semester-code 0020 \
        --output-dir raw_data/crawled_data/onestop_syllabus/2026_2 \
        [--dry-run]

**Supabase 팀 공유 DB에 바로 실행하지 말 것** — CLAUDE.md 원칙대로 로컬 Postgres에서
먼저 결과 품질을 확인한다(`DATABASE_URL`을 로컬로 넘겨서 실행).
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major
from app.domains.courses.models import Course, CourseOffering, CourseSyllabus
from app.ingestion.crawlers.onestop_syllabus import crawl_syllabi_for_course_names
from app.ingestion.parsers.onestop_syllabus import parse_syllabus_pdf

# 크롤러가 받는 raw term code(One-Stop selectAtlectManual_v2025 기준) →
# course_offerings.semester 표기. 지금 크롤러는 정규학기만 지원한다(계절학기는
# 학기 전환 UI 자체를 아직 안 만들었다 — 크롤러 모듈 docstring 참고), 그래서
# 이 매핑도 정규학기 2개만 있으면 된다.
_SEMESTER_LABELS = {"0010": "1학기", "0020": "2학기"}


def resolve_semester_label(semester_code: str) -> str:
    if semester_code not in _SEMESTER_LABELS:
        raise ValueError(
            f"semester_code={semester_code!r}는 아직 지원 안 함(정규학기 0010/0020만) — "
            "계절학기는 크롤러가 학기 전환을 지원하지 않아 course_offerings 매칭 표기를 정할 수 없다."
        )
    return _SEMESTER_LABELS[semester_code]


def _resolve_course_names(db, department: str | None, major: str | None) -> list[str]:
    """department/major 이름으로 `courses.course_name` 목록을 조회한다(get-or-create
    아님 — 오타로 조회 0건이면 그대로 빈 목록을 돌려주고 호출자가 알아채게 한다)."""
    query = select(Course.course_name).distinct()
    if major:
        major_ids = list(
            db.scalars(
                select(Major.id).where(
                    Major.name == major,
                    *([Major.department_id == db.scalar(
                        select(Department.id).where(Department.name == department)
                    )] if department else []),
                )
            )
        )
        query = query.where(Course.major_id.in_(major_ids))
    elif department:
        dept_id = db.scalar(select(Department.id).where(Department.name == department))
        query = query.where(Course.department_id == dept_id)
    else:
        raise ValueError("--department 또는 --major 중 하나는 있어야 한다")
    return sorted(name for name in db.scalars(query) if name)


def upsert_syllabus_row(db, result, year: int, semester: str) -> str:
    """크롤 결과 하나를 `course_offerings`와 매칭해 `CourseSyllabus`로 upsert한다.

    `db`를 인자로 받는 순수 함수로 분리해서 SQLite 인메모리로 단위 테스트할 수 있게
    했다(`SessionLocal()`을 직접 여는 `import_course_syllabi`는 실 DB에 묶여 있어
    테스트하기 어렵다 — `tests/test_import_course_syllabi.py` 참고).

    `semester`는 `course_offerings.semester` 표기 그대로("2학기" 등, `resolve_semester_label`
    참고) — **연도만으로 매칭하면 안 된다.** 같은 과목코드+분반 번호가 같은 연도
    1학기/2학기 양쪽에 있을 수 있어서(분반 번호가 학기마다 재시작), 학기까지 같이
    걸지 않으면 `db.scalar()`가 어느 학기 offering을 집을지 결정적이지 않다
    (독립 리뷰 2026-08-24 지적, 실제로 놓쳤던 정확도 버그).

    돌려주는 문자열은 "created"/"updated"/"no_offering"/"no_pdf"/"failed" 중 하나다.
    """
    if result.pdf_path is None:
        return "failed" if result.error else "no_pdf"

    offering_id = db.scalar(
        select(CourseOffering.id)
        .join(Course, Course.id == CourseOffering.course_id)
        .where(
            Course.course_code == result.offering.subj_no,
            CourseOffering.section == result.offering.class_no,
            CourseOffering.year == str(year),
            CourseOffering.semester == semester,
        )
    )
    if offering_id is None:
        return "no_offering"

    parsed = parse_syllabus_pdf(result.pdf_path)
    existing = db.scalar(select(CourseSyllabus).where(CourseSyllabus.offering_id == offering_id))
    row = existing or CourseSyllabus(offering_id=offering_id)
    # office/office_hours(연구실/상담시간)는 실측 샘플 전부 빈 셀이라 파서가 아직
    # 안 뽑는다(파서 모듈 docstring 참고) — 모델 컬럼은 남겨두되 여기선 안 채운다.
    row.phone = parsed.phone
    row.email = parsed.email
    row.teaching_mode = parsed.teaching_mode
    row.evaluation_method = parsed.evaluation_method
    row.prerequisites_text = parsed.prerequisites_text
    row.course_objectives = parsed.course_objectives
    row.course_overview = parsed.course_overview
    row.textbooks = parsed.textbooks
    row.core_competencies = parsed.core_competencies
    row.weekly_plan = parsed.weekly_plan
    row.raw_text = parsed.raw_text
    row.source_pdf_path = str(result.pdf_path)
    if existing is None:
        db.add(row)
        return "created"
    return "updated"


def import_course_syllabi(
    department: str | None,
    major: str | None,
    year: int,
    semester_code: str,
    output_dir_str: str,
    dry_run: bool = False,
) -> None:
    from pathlib import Path

    output_dir = Path(output_dir_str)
    semester = resolve_semester_label(semester_code)
    db = SessionLocal()
    try:
        course_names = _resolve_course_names(db, department, major)
        print(f"대상 과목명 {len(course_names)}개: {course_names[:10]}{'...' if len(course_names) > 10 else ''}")
        if not course_names:
            print("대상이 0건이다 — department/major 이름을 확인할 것.")
            return

        results = crawl_syllabi_for_course_names(course_names, year, semester_code, output_dir)

        counts = {"created": 0, "updated": 0, "no_offering": 0, "no_pdf": 0, "failed": 0}
        for result in results:
            status = upsert_syllabus_row(db, result, year, semester)
            counts[status] += 1
            if status == "no_offering":
                print(
                    f"  [매칭 실패] {result.offering.subj_no}/{result.offering.class_no} — "
                    "course_offerings에서 못 찾음(course_code/section 표기 차이일 수 있음)"
                )
            elif status == "failed":
                print(f"  [실패] {result.offering.subj_no}/{result.offering.class_no}: {result.error}")

        if dry_run:
            db.rollback()
        else:
            db.commit()

        print(
            f"생성 {counts['created']} / 갱신 {counts['updated']} / "
            f"offering 매칭 실패 {counts['no_offering']} / "
            f"교수계획표 없음(정상) {counts['no_pdf']} / 크롤링·저장 실패 {counts['failed']}"
            + (" [dry-run, 롤백됨]" if dry_run else "")
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--department", default=None)
    parser.add_argument("--major", default=None)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--semester-code", required=True, help="0010=1학기, 0020=2학기")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_course_syllabi(
        args.department, args.major, args.year, args.semester_code,
        args.output_dir, dry_run=args.dry_run,
    )
