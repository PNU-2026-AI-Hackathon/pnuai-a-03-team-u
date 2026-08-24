"""One-Stop 교수계획표(강의계획서)를 크롤링·파싱해서 `course_syllabi`에 upsert하고,
`courses.description`을 그 내용으로 덮어써서 실제 RAG 검색에 반영한다.

강의계획서 RAG 반영 파일럿(2026-08-24, `docs/progress/`에 아직 설계 문서는 없음 —
`local.md` 참고) 실행 스크립트. 전공(major) 하나를 대상으로, 그 전공 소속
`courses`의 이름들로 One-Stop을 검색하고, `course_offerings`(같은 year/semester)에
매칭되는 분반만 `CourseSyllabus`로 저장한다.

**`courses.description` 오버라이딩(사용자 판단, 2026-08-24)**: `CurriculumRetriever.
search()`의 기본 검색 경로(`use_vector=False`, 실제 서비스가 쓰는 경로 — `RagChunk`
임베딩이 아니다)가 진로 키워드 매칭에 직접 읽는 필드가 `courses.description`이다.
그래서 강의계획서에서 강의개요(없으면 교수목표)를 뽑아 이 필드를 **무조건 덮어쓴다**
— 학과 "교과목개요" 원문이든 예전 값이든, 수강편람에서 방금 받아온 게 가장 현재
상황을 반영한다는 판단. 같은 과목에 분반(교수)이 여럿이면 마지막으로 처리된 분반의
내용이 남는다(분반 간 우선순위를 정할 근거가 없어 임의 — 처리 순서는 One-Stop 검색
결과 순서를 따른다). `upsert_syllabus_row`의 docstring 참고.

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
# course_offerings.semester 표기. 크롤러 자체는 학기 전환(select_option)을 지원하지만
# (2026-08-25, 크롤러 모듈 docstring 참고), `course_offerings.semester`에 계절학기
# 표기("여름계절수업" 등)가 뭔지 정해진 바가 없어 이 매핑은 정규학기 2개만 둔다 —
# 계절학기까지 지원하려면 course_offerings 쪽 표기 컨벤션부터 확인해야 한다.
_SEMESTER_LABELS = {"0010": "1학기", "0020": "2학기"}


def resolve_semester_label(semester_code: str) -> str:
    if semester_code not in _SEMESTER_LABELS:
        raise ValueError(
            f"semester_code={semester_code!r}는 아직 지원 안 함(정규학기 0010/0020만) — "
            "계절학기는 course_offerings.semester 표기 컨벤션이 안 정해져 있어 매칭 표기를 정할 수 없다."
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

    offering = db.scalars(
        select(CourseOffering)
        .join(Course, Course.id == CourseOffering.course_id)
        .where(
            Course.course_code == result.offering.subj_no,
            CourseOffering.section == result.offering.class_no,
            CourseOffering.year == str(year),
            CourseOffering.semester == semester,
        )
    ).first()
    if offering is None:
        return "no_offering"

    parsed = parse_syllabus_pdf(result.pdf_path)
    # `SessionLocal`은 `autoflush=False`다(`core/db.py`) — 이 SELECT가 세션 안에
    # 아직 flush 안 된 이전 `db.add()`를 못 본다. 같은 offering이 이번 실행 중
    # 두 번 이상 나타나면(검색 결과 중복, 같은 offering이 여러 course_name 검색에
    # 걸리는 경우 등 — 실제 파일럿 규모에서 실측됨, 2026-08-24) 둘 다 "없음"으로
    # 잘못 판단해 CREATE를 두 번 시도하다가 최종 커밋 시점에 unique 제약 위반으로
    # **트랜잭션 전체가 롤백**됐다(197건 다운로드해놓고 0건 저장되는 사고). 아래
    # `db.flush()`로 매번 즉시 반영해서 다음 호출의 existing 체크가 항상 최신
    # 상태를 보게 한다.
    existing = db.scalar(select(CourseSyllabus).where(CourseSyllabus.offering_id == offering.id))
    row = existing or CourseSyllabus(offering_id=offering.id)
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
        status = "created"
    else:
        status = "updated"
    db.flush()

    # RAG 검색(`CurriculumRetriever.search`, use_vector=False 기본 경로)이 실제로
    # 읽는 건 courses.description이다(RagChunk 임베딩이 아니라 — 확인 완료). 강의
    # 계획서가 있으면 **무조건 그걸로 덮어쓴다**: 학과 "교과목개요" 원문이든 예전
    # description이든, 지금 수강편람에서 직접 받아온 게 제일 현재 상황을 반영한다
    # (사용자 판단, 2026-08-24). 개요가 비어있는 드문 경우엔 교수목표로 대체 —
    # 둘 다 없으면 description을 건드리지 않는다(빈 값으로 덮어써서 잃지 않는다).
    description_text = parsed.course_overview or parsed.course_objectives
    if description_text:
        course = db.get(Course, offering.course_id)
        if course is not None:
            course.description = description_text
            course.source_document = (
                f"One-Stop 수강편람 교수계획표(강의계획서) — "
                f"{result.offering.prof_nm or '교수 미상'} 교수, "
                f"{result.offering.subj_no}/{result.offering.class_no}분반, {year}년 {semester}"
            )
    return status


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

    # DB 세션과 크롤링(브라우저 자동화, 분반 수십~수백 개면 수십 분 걸림)을 세션
    # 하나로 묶지 않는다 — 실제로 묶어서 돌렸다가 크롤링하는 내내 DB 커넥션이
    # 아무 것도 안 하며 열려만 있어서 Supabase가 유휴 커넥션을 끊어버린 사고가
    # 났다("server closed the connection unexpectedly", 2026-08-24 사회학과
    # 실행에서 실측). course_names 조회용 세션을 먼저 닫고, 크롤링은 DB 세션
    # 없이 하고, 저장할 때 새 세션을 연다.
    with SessionLocal() as name_db:
        course_names = _resolve_course_names(name_db, department, major)
    print(f"대상 과목명 {len(course_names)}개: {course_names[:10]}{'...' if len(course_names) > 10 else ''}")
    if not course_names:
        print("대상이 0건이다 — department/major 이름을 확인할 것.")
        return

    results = crawl_syllabi_for_course_names(course_names, year, semester_code, output_dir)

    db = SessionLocal()
    try:
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
