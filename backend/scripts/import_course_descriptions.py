"""학과별 "교과목개요" 원문(과목명+설명)을 파싱해 courses.description·source_document에
직접 채워넣는다.

입력 형식(마크다운/텍스트, `--source` 인자): 표제 마커 뒤에 `국문과목명(영문과목명)`
형식의 표제가 오고, 다음 줄부터 설명 문단이 이어지는 블록의 반복. 표제 마커는 다음 셋:
- `* ` (기존 불릿) — 표제 어떤 내용이든 허용
- `1. `/`12. ` (숫자 + 점) — 표제에 `(...)` 있어야 인정(설명 안의 번호 목록과 구분)
- `1-1. `/`3-2. ` (하이픈 숫자) — 동일 조건

`raw_data/manual_staging/02_course_descriptions/by_department/{단과대}/{학과코드}__{학과명}/course_descriptions_source.md`
컨벤션 파일을 그대로 넣으면 된다.

**설계 결정 (2026-08-04)**: 이전엔 `course_descriptions` 별도 테이블에 원문을 저장하고
`sync_course_descriptions_to_courses.py`로 옮겼으나 실용상 이득이 없어 폐기. 이 스크립트가
파싱과 매칭·적재를 한 번에 처리한다. 매칭 안 되는 항목(개편으로 이름이 바뀐 과목 등)은
count만 리포트하고 스킵 — 억지로 붙이지 않는다(잘못된 매칭보다 안전 실패가 낫다). 원문이
필요하면 raw md 파일이 gitignored raw_data/에 그대로 있으므로 재실행이 답.

department_id/major_id는 이미 courses에 적재된 학과/전공 이름으로 조회한다
(get-or-create 아님 — 오타로 엉뚱한 학과가 새로 생기는 걸 막기 위해, 없으면 에러).

실행: python -m scripts.import_course_descriptions \
    --source ../raw_data/manual_staging/02_course_descriptions/by_department/정보의생명공학대학/U04080300126__정보컴퓨터공학부/course_descriptions_source.md \
    --department 정보컴퓨터공학부 --source-document "정보컴퓨터공학부 교과목개요(사용자 제공, 연도 미상)" \
    [--major 컴퓨터공학전공] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major
from app.domains.courses.course_description_matching import normalize_course_name, strip_korean_name
from app.domains.courses.models import Course


_STAR_MARKER = re.compile(r"^\*\s*(.*)$")
_NUM_MARKER = re.compile(r"^\d+(?:-\d+)?\.\s*(.*)$")


def _match_marker(line: str) -> tuple[bool, str | None]:
    """(is_marker, title_on_marker). title_on_marker=None은 다음 줄에서 표제 대기."""
    star = _STAR_MARKER.match(line)
    if star:
        content = star.group(1).strip()
        return True, content or None
    num = _NUM_MARKER.match(line)
    if num:
        content = num.group(1).strip()
        # 설명 안의 번호 목록("1. 개념, 2. 응용")과 진짜 표제("1. 교육철학(Educational Philosophy)")를
        # 구분: 진짜 표제는 국문(영문) 병기 규약이므로 반드시 괄호 쌍을 포함한다.
        if "(" in content and ")" in content:
            return True, content
    return False, None


def parse_entries(text: str) -> list[tuple[str, str]]:
    """(원문 표제, 설명) 쌍의 리스트. 표제 다음 줄부터 다음 마커 전까지를 설명으로 취급.

    표제가 마커 줄 자체에 없고(빈 "* ") 바로 다음 줄에 오는 경우도 처리한다(별표 마커에만 적용).
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
        is_marker, title_on_marker = _match_marker(line)
        if is_marker:
            flush()
            current_title = title_on_marker
            current_body = []
            awaiting_title = title_on_marker is None
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

        major_id_filter: int | None = None
        if major_name:
            major = db.scalars(
                select(Major).where(Major.department_id == department.id, Major.name == major_name)
            ).first()
            if major is None:
                raise SystemExit(f"전공을 찾을 수 없음: {major_name!r} (department={department_name!r})")
            major_id_filter = major.id

        # 학과(선택적으로 전공)에 속한 courses 전부 로드 후, normalized_name 기준 인덱스.
        # 같은 학과에 이름이 같은 과목이 여러 major 단위 courses 행으로 중복 존재하는 게
        # 정상이라, 매칭되는 courses 행이 여러 개면 전부 채운다.
        course_query = select(Course).where(Course.department_id == department.id)
        if major_id_filter is not None:
            course_query = course_query.where(Course.major_id == major_id_filter)
        courses = db.scalars(course_query).all()
        courses_by_norm: dict[str, list[Course]] = {}
        for c in courses:
            norm = normalize_course_name(c.course_name)
            if norm:
                courses_by_norm.setdefault(norm, []).append(c)

        skipped_empty_name = 0
        skipped_dup_in_run = 0
        matched_entries = 0
        matched_courses = 0
        updated_courses = 0
        unmatched_entries: list[str] = []
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

            matching_courses = courses_by_norm.get(normalized)
            if not matching_courses:
                unmatched_entries.append(korean_name)
                continue

            matched_entries += 1
            matched_courses += len(matching_courses)
            for course in matching_courses:
                changed = course.description != description or course.source_document != source_document
                if changed:
                    course.description = description
                    course.source_document = source_document
                    updated_courses += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(
        f"파싱 {len(entries)}건 → 매칭 {matched_entries}건 (courses 행 {matched_courses}개 대응, "
        f"이번 실행에서 실제 갱신 {updated_courses}건) / "
        f"매칭 실패 {len(unmatched_entries)} / 과목명 비어 스킵 {skipped_empty_name} / "
        f"실행 내 중복 스킵 {skipped_dup_in_run}"
        + (" [dry-run, 롤백됨]" if dry_run else "")
    )
    if unmatched_entries:
        preview = ", ".join(unmatched_entries[:5])
        more = f" 외 {len(unmatched_entries) - 5}건" if len(unmatched_entries) > 5 else ""
        print(f"  매칭 실패 예시: {preview}{more}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--department", required=True)
    parser.add_argument("--major", default=None)
    parser.add_argument(
        "--source-document",
        required=True,
        help="courses.source_document에 그대로 저장될 원문 출처 설명(URL·파일명·수집시점 등).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_descriptions(
        args.source, args.department, args.major, args.source_document, dry_run=args.dry_run
    )
