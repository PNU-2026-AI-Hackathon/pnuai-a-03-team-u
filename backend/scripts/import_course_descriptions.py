""""교과목개요" 원문(과목명+설명) 텍스트를 course_descriptions에 적재한다.

입력 형식(마크다운/텍스트, `--source` 인자): `* 국문과목명(영문과목명)` 줄 다음에
설명 문단이 이어지는 블록의 반복. `raw_data/manual_staging/02_course_descriptions/
by_department/{단과대}/{학과코드}__{학과명}/course_descriptions_source.md` 컨벤션을
따르는 파일을 그대로 넣으면 된다.

department_id/major_id는 이미 courses에 적재된 학과/전공 이름으로 조회한다
(get-or-create 아님 — 오타로 엉뚱한 학과가 새로 생기는 걸 막기 위해, 없으면 에러).

과목명 매칭은 여기서 하지 않는다. department_id/major_id + normalized_name만 저장해둔다.
실제 courses.description에 반영하려면 이 스크립트로 적재한 뒤
`python -m scripts.sync_course_descriptions_to_courses`를 이어서 돌려야 한다 — 이름이
정확히 일치하는 courses 행에만 복사되고(app/domains/courses/course_description_matching.py),
CurriculumRetriever/course_roadmap_agent.py는 courses.description을 그대로 읽는다.

실행: python -m scripts.import_course_descriptions \
    --source ../raw_data/manual_staging/02_course_descriptions/by_department/정보의생명공학대학/U04080300126__정보컴퓨터공학부/course_descriptions_source.md \
    --department 정보컴퓨터공학부 --source-document "정보컴퓨터공학부 교과목개요(사용자 제공, 연도 미상)" \
    [--major 컴퓨터공학전공] [--dry-run]
그 다음: python -m scripts.sync_course_descriptions_to_courses [--department 정보컴퓨터공학부]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major
from app.domains.courses.course_description_matching import normalize_course_name, strip_korean_name
from app.domains.courses.models import CourseDescription

_ENTRY_MARKER = re.compile(r"^\*\s*(.*)$")


def parse_entries(text: str) -> list[tuple[str, str]]:
    """(원문 표제, 설명) 쌍의 리스트. 표제 다음 줄부터 다음 '* ' 전까지를 설명으로 취급.

    표제가 마커 줄 자체에 없고(빈 "* ") 바로 다음 줄에 오는 경우도 처리한다.
    설명이 비어 있는 항목(원문에 개요가 없는 과목)은 제외한다.
    """
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []
    awaiting_title = False

    def flush() -> None:
        if current_title:
            blocks.append((current_title, current_body))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        marker = _ENTRY_MARKER.match(line)
        if marker is not None:
            flush()
            title_on_marker = marker.group(1).strip()
            current_title = title_on_marker or None
            current_body = []
            awaiting_title = not title_on_marker
            continue
        if not line:
            continue
        if awaiting_title:
            current_title = line
            awaiting_title = False
            continue
        if current_title is not None:
            current_body.append(line)
    flush()

    entries: list[tuple[str, str]] = []
    for title, body_lines in blocks:
        description = " ".join(body_lines).strip()
        if not description:
            continue
        entries.append((title, description))
    return entries


def import_descriptions(
    source: Path,
    department_name: str,
    major_name: str | None,
    source_document: str,
    dry_run: bool = False,
) -> None:
    text = source.read_text(encoding="utf-8")
    entries = parse_entries(text)

    db = SessionLocal()
    try:
        department = db.scalars(select(Department).where(Department.name == department_name)).first()
        if department is None:
            raise SystemExit(f"학과를 찾을 수 없음: {department_name!r} (courses/departments 시드가 먼저 되어 있어야 함)")

        major_id = None
        if major_name:
            major = db.scalars(
                select(Major).where(Major.department_id == department.id, Major.name == major_name)
            ).first()
            if major is None:
                raise SystemExit(f"전공을 찾을 수 없음: {major_name!r} (department={department_name!r})")
            major_id = major.id

        created = updated = skipped_empty_name = skipped_dup_in_run = 0
        # SessionLocal이 autoflush=False라 같은 실행 안의 add가 이후 select에 안 보인다
        # (import_courses_from_ais.py와 동일한 이유) — 실행 내 중복은 여기서 직접 걸러낸다.
        seen_in_run: set[str] = set()
        for raw_title, description in entries:
            korean_name = strip_korean_name(raw_title)
            normalized = normalize_course_name(korean_name)
            if not normalized:
                skipped_empty_name += 1
                continue
            if normalized in seen_in_run:
                skipped_dup_in_run += 1
                continue
            seen_in_run.add(normalized)

            row = db.scalars(
                select(CourseDescription).where(
                    CourseDescription.department_id == department.id,
                    CourseDescription.major_id == major_id,
                    CourseDescription.normalized_name == normalized,
                )
            ).first()
            if row is None:
                db.add(
                    CourseDescription(
                        department_id=department.id,
                        major_id=major_id,
                        source_course_name=korean_name,
                        normalized_name=normalized,
                        description=description,
                        source_document=source_document,
                    )
                )
                created += 1
            else:
                changed = row.description != description or row.source_course_name != korean_name
                row.description = description
                row.source_course_name = korean_name
                row.source_document = source_document
                updated += int(changed)

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(
        f"파싱 {len(entries)}건 → 신규 {created} / 갱신 {updated} / "
        f"과목명 비어 스킵 {skipped_empty_name} / 실행 내 중복 스킵 {skipped_dup_in_run}"
        + (" [dry-run, 롤백됨]" if dry_run else "")
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--department", required=True, help="departments.name과 정확히 일치해야 함")
    parser.add_argument("--major", default=None, help="majors.name (department 범위 내). 생략 시 학과 공통(major_id=NULL)")
    parser.add_argument("--source-document", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_descriptions(args.source, args.department, args.major, args.source_document, dry_run=args.dry_run)
