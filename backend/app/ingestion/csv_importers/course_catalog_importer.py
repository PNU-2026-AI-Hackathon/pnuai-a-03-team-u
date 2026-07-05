"""onestop 수강편람 원본(`raw_data/crawled_data/onestop_course_catalog/*/​*_course_catalog.csv`)을
`courses` 테이블용 과목 마스터로 정리해 upsert한다.

이 임포터는 학기별 개설(분반/시간표/교수/정원) 정보는 다루지 않는다 — 그건 나중에
시간표 추천 기능을 만들 때 같은 원본 CSV에서 별도로 다시 뽑는다. 실제로 학기마다
바뀌는 건 교수/분반/시간표뿐이고 과목명·학점은 course_code 기준으로 완전히
안정적이라는 걸 전수 확인했다(2023_1~2026_winter, 17개 학기, 6,617개 고유
course_code 중 과목명/학점이 학기마다 다른 경우 0건). 그래서 지금은 course_code당
한 행으로 합친 과목 마스터만 만든다.

이수구분(category)과 개설학과(offering_department)는 드물게 학기마다 다르게
찍힌다(커리큘럼 개정, 학과 개편 등 246/6,617건). 이런 경우 가장 최근 학기 값을
대표값으로 쓰고, 달라졌던 이력은 review CSV에 남긴다 — 조용히 덮어쓰지 않는다.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domains.academics.models import Department
from app.domains.courses.models import Course

_SEMESTER_RANK = {"1": 0, "summer": 1, "2": 2, "winter": 3}

# "도시공학과" vs "도시공학전공"처럼 같은 학과가 학과/전공/학부 표기만 다르게 찍히는
# 경우가 흔하다(공과대학 다수 학과가 트랙제로 개편되며 표기가 섞였다). 접미사를 뗀
# 이름이 department 하나에만 유일하게 걸릴 때만 fallback으로 매칭한다.
_DEPARTMENT_SUFFIX_PATTERN = re.compile(r"(공학과|공학부|공학전공|학과|학부|전공)$")


def _normalize_department_name(value: str) -> str:
    """학과명 매칭용 1차 정규화(공백/기호 제거). 정확 일치가 안 될 때만 fallback으로 쓴다."""
    return re.sub(r"[\s()（）·ㆍ・.]", "", value or "")


def _stem_department_name(value: str) -> str:
    """학과/학부/전공 접미사를 뗀 2차 fallback 키. 접미사 표기 차이만 있는 동일 학과를 잡는다."""
    return _DEPARTMENT_SUFFIX_PATTERN.sub("", _normalize_department_name(value))


@dataclass
class _CatalogRow:
    year: str
    semester: str
    school: str | None
    course_code: str
    course_name: str
    credits: float | None
    category: str | None
    offering_department: str | None

    def term_sort_key(self) -> tuple[int, int]:
        try:
            year = int(self.year)
        except (TypeError, ValueError):
            year = 0
        return (year, _SEMESTER_RANK.get(self.semester, -1))


@dataclass
class CanonicalCourse:
    """course_code 하나당 대표 행. 학기별 department/category가 갈렸으면 drift=True."""

    course_code: str
    course_name: str
    credits: float | None
    school: str | None
    offering_department: str | None
    category: str | None
    department_drift: bool
    category_drift: bool
    departments_seen: list[str] = field(default_factory=list)
    categories_seen: list[str] = field(default_factory=list)


def _to_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_course_catalog_csv_dir(catalog_dir: Path) -> list[_CatalogRow]:
    """`{catalog_dir}/{term}/{term}_course_catalog.csv` 전부를 읽는다."""
    rows: list[_CatalogRow] = []
    for csv_path in sorted(catalog_dir.glob("*/*_course_catalog.csv")):
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                course_code = (raw.get("course_code") or "").strip()
                if not course_code:
                    continue
                rows.append(
                    _CatalogRow(
                        year=(raw.get("year") or "").strip(),
                        semester=(raw.get("semester") or "").strip(),
                        school=(raw.get("school") or "").strip() or None,
                        course_code=course_code,
                        course_name=(raw.get("course_name") or "").strip(),
                        credits=_to_float(raw.get("credits")),
                        category=(raw.get("category") or "").strip() or None,
                        offering_department=(raw.get("offering_department") or "").strip()
                        or None,
                    )
                )
    return rows


def build_canonical_courses(rows: Iterable[_CatalogRow]) -> list[CanonicalCourse]:
    """course_code로 묶어서 최신 학기 값을 대표값으로 쓰는 과목 마스터 행을 만든다."""
    by_code: dict[str, list[_CatalogRow]] = defaultdict(list)
    for row in rows:
        by_code[row.course_code].append(row)

    canonical: list[CanonicalCourse] = []
    for code, code_rows in sorted(by_code.items()):
        latest = max(code_rows, key=_CatalogRow.term_sort_key)
        departments = sorted({r.offering_department for r in code_rows if r.offering_department})
        categories = sorted({r.category for r in code_rows if r.category})
        names = {r.course_name for r in code_rows if r.course_name}
        credits_seen = {r.credits for r in code_rows if r.credits is not None}
        # 전수 확인상 과목명/학점은 안정적이지만, 혹시 어긋나면 조용히 넘어가지 않고
        # 최신 학기 값을 쓰되 drift 플래그로 남긴다 (department/category와 동일 취급).
        canonical.append(
            CanonicalCourse(
                course_code=code,
                course_name=latest.course_name or (names.pop() if names else ""),
                credits=latest.credits if latest.credits is not None else (
                    next(iter(credits_seen), None)
                ),
                school=latest.school,
                offering_department=latest.offering_department,
                category=latest.category,
                department_drift=len(departments) > 1,
                category_drift=len(categories) > 1,
                departments_seen=departments,
                categories_seen=categories,
            )
        )
    return canonical


def _build_unambiguous_stem_map(department_rows: list[tuple[int, str]]) -> dict[str, int]:
    """접미사 뗀 이름이 department 하나에만 대응할 때만 stem -> id로 등록한다."""
    stem_to_ids: dict[str, set[int]] = defaultdict(set)
    for dept_id, name in department_rows:
        stem_to_ids[_stem_department_name(name)].add(dept_id)
    return {stem: next(iter(ids)) for stem, ids in stem_to_ids.items() if len(ids) == 1}


def _resolve_department_ids(db: Session, courses: list[CanonicalCourse]) -> dict[str, int]:
    """offering_department 이름 -> departments.id.

    1순위 정확 일치, 2순위 공백/기호 제거 정규화, 3순위 학과/전공 접미사를 뗀
    stem 매칭(단, 그 stem이 department 하나에만 대응할 때만 — "경제학부"/"경영학과"처럼
    서로 다른 학과가 우연히 같은 stem이 되는 경우를 피하기 위함).
    """
    department_rows = db.execute(select(Department.id, Department.name)).all()
    by_exact_name = {name: dept_id for dept_id, name in department_rows}
    by_normalized_name = {
        _normalize_department_name(name): dept_id for dept_id, name in department_rows
    }
    by_unambiguous_stem = _build_unambiguous_stem_map(department_rows)

    resolved: dict[str, int] = {}
    for course in courses:
        name = course.offering_department
        if not name:
            continue
        dept_id = (
            by_exact_name.get(name)
            or by_normalized_name.get(_normalize_department_name(name))
            or by_unambiguous_stem.get(_stem_department_name(name))
        )
        if dept_id is not None:
            resolved[name] = dept_id
    return resolved


def write_review_report(courses: list[CanonicalCourse], unmatched_departments: set[str], output_path: Path) -> int:
    """drift/미매칭 학과가 있는 행만 review CSV로 남긴다. 반환값은 기록한 행 수."""
    review_rows = [
        course
        for course in courses
        if course.department_drift
        or course.category_drift
        or (course.offering_department and course.offering_department in unmatched_departments)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "issue",
                "latest_offering_department",
                "departments_seen",
                "latest_category",
                "categories_seen",
            ]
        )
        for course in review_rows:
            issues = []
            if course.department_drift:
                issues.append("department_drift")
            if course.category_drift:
                issues.append("category_drift")
            if course.offering_department in unmatched_departments:
                issues.append("department_unmatched")
            writer.writerow(
                [
                    course.course_code,
                    course.course_name,
                    ";".join(issues),
                    course.offering_department or "",
                    ";".join(course.departments_seen),
                    course.category or "",
                    ";".join(course.categories_seen),
                ]
            )
    return len(review_rows)


def import_course_catalog(
    db: Session,
    catalog_dir: Path,
    review_output_path: Path | None = None,
) -> dict[str, int]:
    """course_catalog_dir을 읽어 courses 테이블에 upsert하고 요약 dict를 반환한다."""
    rows = read_course_catalog_csv_dir(catalog_dir)
    courses = build_canonical_courses(rows)
    department_ids = _resolve_department_ids(db, courses)
    unmatched_departments = {
        c.offering_department
        for c in courses
        if c.offering_department and c.offering_department not in department_ids
    }

    values = [
        {
            "school": course.school,
            "course_code": course.course_code,
            "course_name": course.course_name,
            "department": course.offering_department,
            "department_id": department_ids.get(course.offering_department or ""),
            "major": None,
            "default_category": course.category,
            "credits": course.credits,
        }
        for course in courses
    ]

    upsert_columns = [
        "school",
        "course_name",
        "department",
        "department_id",
        "default_category",
        "credits",
    ]
    chunk_size = 1000
    for start in range(0, len(values), chunk_size):
        chunk = values[start : start + chunk_size]
        stmt = insert(Course).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["course_code"],
            set_={column: getattr(stmt.excluded, column) for column in upsert_columns},
        )
        db.execute(stmt)
    db.commit()

    review_row_count = 0
    if review_output_path is not None:
        review_row_count = write_review_report(courses, unmatched_departments, review_output_path)

    return {
        "source_rows": len(rows),
        "distinct_courses": len(courses),
        "matched_department": sum(1 for c in courses if c.offering_department in department_ids),
        "unmatched_department": sum(
            1 for c in courses if c.offering_department and c.offering_department not in department_ids
        ),
        "department_drift": sum(1 for c in courses if c.department_drift),
        "category_drift": sum(1 for c in courses if c.category_drift),
        "review_rows_written": review_row_count,
    }
