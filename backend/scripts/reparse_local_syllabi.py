"""로컬에 이미 다운로드된 강의계획서 PDF를 (재)크롤링 없이 다시 파싱해서
`course_syllabi`/`courses.description`을 갱신한다.

강의계획서 파서 버그 수정(PR #245, 2026-08-25 — 장애학생 안내문/표 셀 레이블
단어가 교수가 쓴 실제 내용인 것처럼 저장되던 문제) 이후, 이미 Supabase에
반영된 437건은 옛 파서 결과라 이 수정을 못 받는다. `raw_data/`에 이미 저장된
PDF로 재파싱·재upsert만 하면 되므로 재크롤링(브라우저 자동화, PNU 서버 부하)이
필요 없다.

파일명 패턴은 크롤러(`app.ingestion.crawlers.onestop_syllabus`)가 저장할 때
쓰는 `{course_code}_{section}_{lang}.pdf`를 그대로 역파싱한다 — 검색 단계 없이
바로 offering을 찾을 수 있는 건 이 형식 덕분이다. `upsert_syllabus_row`는
`course_code`+`section`+`year`+`semester`로만 매칭하므로 교수명(prof_nm)은
매칭에 안 쓰이고 source_document 표시용이다 — 어차피 이미 course_offerings에
있는 값을 그대로 가져온다.

실행:
    python -m scripts.reparse_local_syllabi \
        --pdf-dir raw_data/crawled_data/onestop_syllabus/2026_2 \
        --year 2026 --semester-code 0020 \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.courses.models import Course, CourseOffering
from app.ingestion.crawlers.onestop_syllabus import SyllabusCrawlResult, SyllabusOffering
from scripts.import_course_syllabi import resolve_semester_label, upsert_syllabus_row

_FILENAME_RE = re.compile(r"^(?P<subj_no>[A-Za-z0-9]+)_(?P<class_no>\d+)_(?P<lang>[A-Za-z]+)\.pdf$")


def reparse_local_syllabi(pdf_dir_str: str, year: int, semester_code: str, dry_run: bool = False) -> None:
    pdf_dir = Path(pdf_dir_str)
    semester = resolve_semester_label(semester_code)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    print(f"대상 PDF {len(pdfs)}개")

    db = SessionLocal()
    try:
        counts = {"created": 0, "updated": 0, "no_offering": 0, "no_pdf": 0, "failed": 0}
        skipped_filename = 0
        for pdf_path in pdfs:
            m = _FILENAME_RE.match(pdf_path.name)
            if not m:
                skipped_filename += 1
                print(f"  [파일명 패턴 불일치, 건너뜀] {pdf_path.name}")
                continue
            subj_no = m.group("subj_no")
            class_no = m.group("class_no")

            prof_nm = db.scalar(
                select(CourseOffering.professor)
                .join(Course, Course.id == CourseOffering.course_id)
                .where(
                    Course.course_code == subj_no,
                    CourseOffering.section == class_no,
                    CourseOffering.year == str(year),
                    CourseOffering.semester == semester,
                )
            )

            offering = SyllabusOffering(
                subj_no=subj_no, class_no=class_no, subj_nm="",
                prof_no="", prof_nm=prof_nm, dept_nm=None, has_kor=True,
            )
            result = SyllabusCrawlResult(offering=offering, pdf_path=pdf_path)
            status = upsert_syllabus_row(db, result, year=year, semester=semester)
            counts[status] += 1
            if status == "no_offering":
                print(f"  [매칭 실패] {subj_no}/{class_no}")
            elif status == "failed":
                print(f"  [파싱 실패] {subj_no}/{class_no}: {result.error}")

        if dry_run:
            db.rollback()
        else:
            db.commit()

        print(
            f"생성 {counts['created']} / 갱신 {counts['updated']} / "
            f"offering 매칭 실패 {counts['no_offering']} / "
            f"교수계획표 없음 {counts['no_pdf']} / 파싱 실패 {counts['failed']} / "
            f"파일명 패턴 불일치 {skipped_filename}"
            + (" [dry-run, 롤백됨]" if dry_run else "")
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--semester-code", required=True, help="0010=1학기, 0020=2학기")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reparse_local_syllabi(args.pdf_dir, args.year, args.semester_code, dry_run=args.dry_run)
