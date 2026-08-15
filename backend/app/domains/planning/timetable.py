"""시간표 추천 (결정론적, LLM 미사용).

로드맵의 대상 학기 항목들을 실제 `course_offerings`와 대조해:

1. 개설 자체가 없는 항목은 `unavailable_courses`로 분리 → 사용자가 로드맵을
   수정해야 하는 신호.
2. 개설된 항목들의 분반 조합을 요일·시간 충돌 없이 짤 수 있는지 탐색.
   완전한 조합이 있으면 상위 몇 개 반환.
3. 완전 조합이 없으면 "N-2 이상 크기" 또는 "학점 합 ≥ term_credit_cap × 0.5"
   조건을 만족하는 부분 조합을 반환하고, 매번 빠진 과목들을 `problematic_courses`로
   집계.
4. 문제 항목(unavailable + problematic)에 대해서는 학과 교육과정 안에서
   같은 카테고리 · 그 학기 실제 개설 · 미이수 · 로드맵 미포함 조건을 통과한
   대체 후보를 나열 (`replacement_suggestions`). "확정 세트의 어떤 분반과도
   충돌 없는 분반이 하나도 없는" 후보는 조용히 배제 — 뻔한 실패 후보를 걸러
   사용자 재시도 UX를 지킨다. 이후 사용자가 로드맵 수정 후 이 엔드포인트를
   재호출하는 흐름을 상정한다.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.domains.academics.models import (
    GraduationRequirement,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User

# 조합 폭발 상한. 6과목 × 각 5분반 = 15,625, 실전엔 훨씬 작다.
_MAX_FULL_COMBOS = 10_000
_MAX_FEASIBLE_TO_RETURN = 5
_MAX_CANDIDATES_PER_SLOT = 8
_DEFAULT_CURRICULUM_YEAR = 2024


@dataclass(frozen=True)
class _SectionInfo:
    """조합 탐색에서 다루는 단위. CourseOffering + 그 CourseTime들."""
    item_id: int
    course_id: int
    course_code: str | None
    course_name: str
    category: str | None
    credits: float | None
    offering_id: int
    section: str | None
    professor: str | None
    times: tuple[CourseTime, ...]

    @property
    def has_time_info(self) -> bool:
        return any(t.start_time is not None and t.end_time is not None for t in self.times)


def _intervals_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


def _sections_conflict(a: _SectionInfo, b: _SectionInfo) -> bool:
    """두 분반의 시간이 겹치는지. 시간 정보 없는 CourseTime은 판정 불가로 무충돌 취급."""
    for ta in a.times:
        if ta.start_time is None or ta.end_time is None:
            continue
        for tb in b.times:
            if tb.start_time is None or tb.end_time is None:
                continue
            if ta.day_of_week and tb.day_of_week and ta.day_of_week == tb.day_of_week:
                if _intervals_overlap(ta.start_time, ta.end_time, tb.start_time, tb.end_time):
                    return True
    return False


def _combo_is_feasible(combo: tuple[_SectionInfo, ...]) -> bool:
    for a, b in itertools.combinations(combo, 2):
        if _sections_conflict(a, b):
            return False
    return True


def _sections_for_item(
    db: Session,
    item: CourseRoadmapItem,
    year: str,
    semester: str,
    course_code: str | None = None,
) -> list[_SectionInfo]:
    if item.course_id is None:
        return []
    rows = db.scalars(
        select(CourseOffering).where(
            CourseOffering.course_id == item.course_id,
            CourseOffering.year == year,
            CourseOffering.semester == semester,
        )
    ).all()
    if not rows:
        return []
    offering_ids = [r.id for r in rows]
    times_by_offering: dict[int, list[CourseTime]] = {oid: [] for oid in offering_ids}
    for t in db.scalars(
        select(CourseTime).where(CourseTime.offering_id.in_(offering_ids))
    ).all():
        times_by_offering.setdefault(t.offering_id, []).append(t)
    sections = [
        _SectionInfo(
            item_id=item.id,
            course_id=item.course_id,
            course_code=course_code,
            course_name=item.course_name or "",
            category=item.category,
            credits=float(item.credits) if item.credits is not None else None,
            offering_id=r.id,
            section=r.section,
            professor=r.professor,
            times=tuple(times_by_offering.get(r.id, [])),
        )
        for r in rows
    ]
    # 시간 정보가 있는 분반을 앞세운다. 시간이 없는 분반은 어떤 조합과도 충돌하지
    # 않아 조합 탐색에서 먼저 뽑히는데, 그러면 주간 시간표에 블록이 하나도 안 그려진다.
    # (크롤링이 아직 모든 분반의 시간을 채우지 못했다.)
    sections.sort(key=lambda s: 0 if s.times else 1)
    return sections


def _serialize_section(section: _SectionInfo) -> dict:
    return {
        "item_id": section.item_id,
        "course_id": section.course_id,
        "course_code": section.course_code,
        "course_name": section.course_name,
        "category": section.category,
        "credits": section.credits,
        "offering_id": section.offering_id,
        "section": section.section,
        "professor": section.professor,
        "times": [
            {
                "day_of_week": t.day_of_week,
                "start_time": t.start_time.strftime("%H:%M") if t.start_time else None,
                "end_time": t.end_time.strftime("%H:%M") if t.end_time else None,
                "classroom": t.classroom,
            }
            for t in section.times
        ],
    }


def _serialize_schedule(combo: Iterable[_SectionInfo], credit_cap: int | None = None) -> dict:
    combo = list(combo)
    total_credits = sum(s.credits or 0.0 for s in combo)
    days, gap_minutes = _schedule_shape(combo)
    entry: dict[str, Any] = {
        "total_credits": total_credits,
        "distinct_days": len(days),
        "total_gap_minutes": gap_minutes,
        "sections": [_serialize_section(s) for s in combo],
    }
    if credit_cap is not None:
        entry["over_credit_cap"] = total_credits > credit_cap
    return entry


def _schedule_shape(combo: Iterable[_SectionInfo]) -> tuple[set[str], int]:
    """조합의 (통학 요일 수, 같은 요일 강의 사이 공백 시간 합)을 계산한다.

    랭킹 지표: 요일 수가 적을수록·공백이 짧을수록 상단.
    시간 정보가 없는 CourseTime은 공백 계산에서 제외한다.
    """
    day_intervals: dict[str, list[tuple[int, int]]] = {}
    for section in combo:
        for t in section.times:
            if not t.day_of_week or t.start_time is None or t.end_time is None:
                continue
            start_min = t.start_time.hour * 60 + t.start_time.minute
            end_min = t.end_time.hour * 60 + t.end_time.minute
            day_intervals.setdefault(t.day_of_week, []).append((start_min, end_min))
    days = set(day_intervals.keys())
    total_gap = 0
    for intervals in day_intervals.values():
        intervals.sort()
        for prev, curr in zip(intervals, intervals[1:], strict=False):
            gap = curr[0] - prev[1]
            if gap > 0:
                total_gap += gap
    return days, total_gap


def _rank_schedules(combos: list[list[_SectionInfo]]) -> list[list[_SectionInfo]]:
    """요일 수 오름차순, 공백 시간 오름차순, 학점 내림차순."""
    def key(combo: list[_SectionInfo]) -> tuple:
        days, gap = _schedule_shape(combo)
        credits = sum(s.credits or 0.0 for s in combo)
        return (len(days), gap, -credits)
    return sorted(combos, key=key)


def _term_credit_cap(db: Session, user: User) -> int:
    """이 학생의 정규 학기 학점 상한. 로드맵 챗과 같은 규칙을 재구현하지 않도록 통일된 값을 쓴다."""
    program = db.scalars(
        select(UserAcademicProgram).filter_by(user_id=user.id, program_type="primary")
    ).first()
    if program is None or user.department_id is None:
        return 19
    req = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == user.department_id,
            GraduationRequirement.major_id == user.major_id,
            GraduationRequirement.program_type == "primary",
        )
    ).first()
    if req is None and user.major_id is not None:
        req = db.scalars(
            select(GraduationRequirement).where(
                GraduationRequirement.department_id == user.department_id,
                GraduationRequirement.major_id.is_(None),
                GraduationRequirement.program_type == "primary",
            )
        ).first()
    if req is None or req.required_total_credits is None:
        return 19
    return 21 if req.required_total_credits >= 133 else 19


def _completed_course_norms(db: Session, user_id: int) -> set[str]:
    """이수 기록 과목명을 정규화해 셋으로. 대체 후보에서 이수 완료 과목을 제외할 때 쓴다."""
    def _norm(n: str | None) -> str:
        if not n:
            return ""
        roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
        s = "".join(roman.get(ch, ch) for ch in n)
        return s.replace("(", "").replace(")", "").replace(" ", "").strip()

    records = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
    ).all()
    return {n for n in (_norm(r.raw_course_name) for r in records) if n}


def _roadmap_course_ids(db: Session, roadmap_id: int) -> set[int]:
    ids = db.scalars(
        select(CourseRoadmapItem.course_id).where(
            CourseRoadmapItem.roadmap_id == roadmap_id,
            CourseRoadmapItem.course_id.is_not(None),
        )
    ).all()
    return set(ids)


def _find_replacement_candidates(
    db: Session,
    user: User,
    target_year: str,
    target_semester: str,
    replace_category: str | None,
    replace_curriculum_grade: str | int | None,
    committed_set: list[_SectionInfo],
    excluded_course_ids: set[int],
    completed_norms: set[str],
) -> list[dict]:
    """학과 교육과정에서 대체 후보 후보 리스트를 뽑는다.

    - CurriculumRetriever로 (semester=target_semester, category=replace_category) 검색
    - course_offerings에 target_year/target_semester 개설이 있는 것만
    - 이미 이수했거나 이미 로드맵에 있는 course_id는 제외
    - "확정 세트(committed_set)의 어떤 분반과도 시간이 겹치는 분반이 하나도 없는" 후보는 제외
    """
    if user.department_id is None:
        return []
    program = db.scalars(
        select(UserAcademicProgram).filter_by(user_id=user.id, program_type="primary")
    ).first()
    curriculum_year = (
        program.curriculum_year if program and program.curriculum_year else _DEFAULT_CURRICULUM_YEAR
    )
    retriever = CurriculumRetriever(db)
    filters: dict[str, Any] = {"limit": 40, "semester": target_semester}
    if replace_category:
        filters["category"] = replace_category
    search_results = retriever.search(
        query="",
        department_id=user.department_id,
        major_id=user.major_id,
        curriculum_year=curriculum_year,
        filters=filters,
    )
    candidate_course_ids = [
        r["course_id"] for r in search_results
        if r.get("course_id") is not None and r["course_id"] not in excluded_course_ids
    ]
    if not candidate_course_ids:
        return []
    # 실제 개설 여부 + 개설 개수
    offerings_by_course: dict[int, list[CourseOffering]] = {}
    for row in db.scalars(
        select(CourseOffering).where(
            CourseOffering.course_id.in_(candidate_course_ids),
            CourseOffering.year == target_year,
            CourseOffering.semester == target_semester,
        )
    ).all():
        offerings_by_course.setdefault(row.course_id, []).append(row)
    if not offerings_by_course:
        return []
    all_offering_ids = [o.id for offs in offerings_by_course.values() for o in offs]
    times_by_offering: dict[int, list[CourseTime]] = {oid: [] for oid in all_offering_ids}
    if all_offering_ids:
        for t in db.scalars(
            select(CourseTime).where(CourseTime.offering_id.in_(all_offering_ids))
        ).all():
            times_by_offering.setdefault(t.offering_id, []).append(t)

    course_meta = {
        r["course_id"]: r for r in search_results if r.get("course_id") is not None
    }
    committed_by_course = {(s.course_id, s.offering_id): s for s in committed_set}
    committed_sections = list(committed_by_course.values())

    picked: list[dict] = []
    for course_id in candidate_course_ids:
        offs = offerings_by_course.get(course_id)
        if not offs:
            continue
        meta = course_meta.get(course_id) or {}
        if meta.get("course_name") and _normalize_course_name(meta["course_name"]) in completed_norms:
            continue

        # 각 분반이 확정 세트와 얼마나 충돌하는지 계산 — 하나도 안 겹치는 분반이 있어야 후보로 유효.
        has_nonconflicting_section = False
        for off in offs:
            candidate_section = _SectionInfo(
                item_id=-1,
                course_id=course_id,
                course_code=None,
                course_name=meta.get("course_name") or "",
                category=meta.get("category"),
                credits=meta.get("credits"),
                offering_id=off.id,
                section=off.section,
                professor=off.professor,
                times=tuple(times_by_offering.get(off.id, [])),
            )
            if all(not _sections_conflict(candidate_section, c) for c in committed_sections):
                has_nonconflicting_section = True
                break
        if not has_nonconflicting_section:
            continue

        picked.append(
            {
                "course_id": course_id,
                "course_name": meta.get("course_name"),
                "category": meta.get("category"),
                "credits": meta.get("credits"),
                "offerings_count": len(offs),
                "curriculum_grade": meta.get("grade"),
                "curriculum_semester": meta.get("semester"),
                "description": meta.get("description"),
            }
        )

    # 랭킹: 대체 대상의 권장 학년과 가까운 것 우선, 그다음 개설 분반 많은 것 우선.
    # CurriculumRetriever 원래 순서는 마지막 tiebreaker로만 사용.
    target_grade_int = _grade_to_int(replace_curriculum_grade)

    def rank_key(candidate: dict) -> tuple:
        grade_diff = 999
        cg = _grade_to_int(candidate.get("curriculum_grade"))
        if target_grade_int is not None and cg is not None:
            grade_diff = abs(cg - target_grade_int)
        return (grade_diff, -candidate.get("offerings_count", 0))

    picked.sort(key=rank_key)
    return picked[:_MAX_CANDIDATES_PER_SLOT]


def _grade_to_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 6 else None
    s = str(value).strip()
    if not s or s in ("전학년",):
        return None
    try:
        n = int(s.replace("학년", ""))
        return n if 1 <= n <= 6 else None
    except ValueError:
        return None


def _normalize_course_name(name: str) -> str:
    if not name:
        return ""
    roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
    s = "".join(roman.get(ch, ch) for ch in name)
    return s.replace("(", "").replace(")", "").replace(" ", "").strip()


def _enumerate_partial_combos(
    per_item_sections: list[list[_SectionInfo]],
    *,
    total_items: int,
    min_credits: float,
) -> list[tuple[list[_SectionInfo], set[int]]]:
    """완전 조합이 없을 때, 항목 부분집합에 대해 시간표를 짜본다.

    반환: (조합, 빠진 item_id 셋) 리스트. "N-2 이상" 크기의 부분집합만 시도한다.
    크기가 큰 부분집합부터 봐서 실용성이 큰 후보를 앞에 놓는다.
    """
    n = len(per_item_sections)
    min_subset_size = max(1, n - 2)
    partial_results: list[tuple[list[_SectionInfo], set[int]]] = []
    all_item_ids = {group[0].item_id for group in per_item_sections if group}

    for size in range(n - 1, min_subset_size - 1, -1):
        for subset_indices in itertools.combinations(range(n), size):
            groups = [per_item_sections[i] for i in subset_indices]
            estimate = 1
            for g in groups:
                estimate *= max(len(g), 1)
                if estimate > _MAX_FULL_COMBOS:
                    break
            if estimate > _MAX_FULL_COMBOS:
                continue
            for combo in itertools.product(*groups):
                if not _combo_is_feasible(combo):
                    continue
                credit_sum = sum(s.credits or 0.0 for s in combo)
                if credit_sum < min_credits:
                    continue
                included_ids = {s.item_id for s in combo}
                missing = all_item_ids - included_ids
                partial_results.append((list(combo), missing))
                if len(partial_results) >= _MAX_FEASIBLE_TO_RETURN * 3:
                    return partial_results
    return partial_results


def recommend_timetable(
    db: Session,
    user: User,
    roadmap: CourseRoadmap,
    year: str,
    semester: str,
) -> dict:
    """대상 학기의 로드맵 항목으로 시간표를 짜본다.

    분반 개설은 달력 기준이므로 로드맵 항목도 달력 학기(planned_year/
    planned_semester)로 찾는다. 커리큘럼 학기는 별도 컬럼이라 여기 섞이지 않는다.
    """
    items = db.scalars(
        select(CourseRoadmapItem).where(
            CourseRoadmapItem.roadmap_id == roadmap.id,
            CourseRoadmapItem.planned_year == year,
            CourseRoadmapItem.planned_semester == semester,
            CourseRoadmapItem.status != "completed",
        )
    ).all()

    target_term = {"year": year, "semester": semester}
    credit_cap = _term_credit_cap(db, user)

    if not items:
        return {
            "target_term": target_term,
            "term_credit_cap": credit_cap,
            "feasible_schedules": [],
            "partial_schedules": [],
            "unavailable_courses": [],
            "problematic_courses": [],
            "replacement_suggestions": [],
            "note": "이 학기에 계획된 로드맵 항목이 없습니다.",
        }

    # 프론트 표시용 course_code를 한 번에 조회해둔다. Course.year(권장학년)도
    # 대체 후보 랭킹의 기준 학년으로 활용한다.
    course_ids_in_items = {item.course_id for item in items if item.course_id is not None}
    course_meta_map: dict[int, dict[str, Any]] = {}
    if course_ids_in_items:
        for c in db.scalars(
            select(Course).where(Course.id.in_(course_ids_in_items))
        ).all():
            course_meta_map[c.id] = {
                "course_code": c.course_code,
                "curriculum_grade": c.year,
            }

    # 항목별 분반 후보
    unavailable_courses: list[dict] = []
    per_item_sections: list[list[_SectionInfo]] = []
    item_curriculum_grade: dict[int, str | None] = {}
    for item in items:
        meta = course_meta_map.get(item.course_id) if item.course_id is not None else None
        course_code = meta["course_code"] if meta else None
        item_curriculum_grade[item.id] = (meta or {}).get("curriculum_grade")
        sections = _sections_for_item(db, item, year, semester, course_code=course_code)
        if not sections:
            unavailable_courses.append(
                {
                    "item_id": item.id,
                    "course_id": item.course_id,
                    "course_code": course_code,
                    "course_name": item.course_name,
                    "category": item.category,
                    "curriculum_grade": item_curriculum_grade[item.id],
                    "reason": "no_offering_this_term",
                }
            )
            continue
        per_item_sections.append(sections)

    completed_norms = _completed_course_norms(db, user.id)
    excluded_course_ids = _roadmap_course_ids(db, roadmap.id)

    # 완전 조합 탐색 (개설된 항목만 대상). 학점 상한 초과 조합은 실제 수강신청 자체가
    # 안 되므로 제외한다. 후보를 넉넉히 모아둔 뒤 랭킹으로 상위 M개만 반환.
    feasible_full: list[list[_SectionInfo]] = []
    over_cap_schedules: list[list[_SectionInfo]] = []
    if per_item_sections:
        estimate = 1
        for g in per_item_sections:
            estimate *= max(len(g), 1)
        if estimate <= _MAX_FULL_COMBOS:
            for combo in itertools.product(*per_item_sections):
                if not _combo_is_feasible(combo):
                    continue
                credits = sum(s.credits or 0.0 for s in combo)
                if credits > credit_cap:
                    if len(over_cap_schedules) < _MAX_FEASIBLE_TO_RETURN:
                        over_cap_schedules.append(list(combo))
                    continue
                feasible_full.append(list(combo))
    feasible_full = _rank_schedules(feasible_full)[:_MAX_FEASIBLE_TO_RETURN]
    over_cap_schedules = _rank_schedules(over_cap_schedules)[:_MAX_FEASIBLE_TO_RETURN]

    problematic_courses: list[dict] = []
    partial_schedules: list[dict] = []

    if feasible_full:
        # 완전 조합이 있으면 부분 조합 필요 없음. 문제는 unavailable_courses뿐.
        pass
    else:
        # 완전 조합 실패 → 부분 조합 탐색. 학점 상한 초과 케이스도 함께 제외한다.
        min_credits = credit_cap * 0.5
        partials = _enumerate_partial_combos(
            per_item_sections, total_items=len(per_item_sections), min_credits=min_credits
        )
        partials = [pc for pc in partials if sum(s.credits or 0.0 for s in pc[0]) <= credit_cap]
        # 요일 몰빵/공백 짧은 것 우선, 그 다음 크기·학점.
        partials.sort(
            key=lambda pc: (
                *((len(_schedule_shape(pc[0])[0]), _schedule_shape(pc[0])[1]) if pc[0] else (99, 99)),
                -len(pc[0]),
                -sum(s.credits or 0.0 for s in pc[0]),
            )
        )
        for combo, missing in partials[:_MAX_FEASIBLE_TO_RETURN]:
            entry = _serialize_schedule(combo, credit_cap=credit_cap)
            entry["excluded_item_ids"] = sorted(missing)
            partial_schedules.append(entry)
        # 부분 조합에서 자주 빠진 항목 = 문제 과목
        drop_counts: dict[int, int] = {}
        for _, missing in partials:
            for iid in missing:
                drop_counts[iid] = drop_counts.get(iid, 0) + 1
        for item in items:
            if item.id in {u["item_id"] for u in unavailable_courses}:
                continue
            cnt = drop_counts.get(item.id, 0)
            if cnt > 0:
                problematic_courses.append(
                    {
                        "item_id": item.id,
                        "course_id": item.course_id,
                        "course_code": (course_meta_map.get(item.course_id) or {}).get("course_code")
                        if item.course_id is not None else None,
                        "course_name": item.course_name,
                        "category": item.category,
                        "curriculum_grade": item_curriculum_grade.get(item.id),
                        "drop_frequency": cnt,
                    }
                )
        problematic_courses.sort(key=lambda x: x["drop_frequency"], reverse=True)

    # 확정 세트: 완전 조합이 있으면 첫 조합, 없으면 최대 부분 조합의 첫 세트
    committed_set: list[_SectionInfo] = []
    if feasible_full:
        committed_set = feasible_full[0]
    elif partial_schedules:
        # 첫 partial_schedule에 대응하는 combo 재구성 (offering_id로 찾음)
        first_ids = {s["offering_id"] for s in partial_schedules[0]["sections"]}
        for group in per_item_sections:
            for sec in group:
                if sec.offering_id in first_ids:
                    committed_set.append(sec)
                    break

    replacement_suggestions: list[dict] = []
    for entry in unavailable_courses + problematic_courses:
        candidates = _find_replacement_candidates(
            db,
            user=user,
            target_year=year,
            target_semester=semester,
            replace_category=entry.get("category"),
            replace_curriculum_grade=entry.get("curriculum_grade"),
            committed_set=committed_set,
            excluded_course_ids=excluded_course_ids,
            completed_norms=completed_norms,
        )
        if candidates:
            replacement_suggestions.append(
                {
                    "replace_item_id": entry["item_id"],
                    "replace_course_name": entry.get("course_name"),
                    "replace_category": entry.get("category"),
                    "candidates": candidates,
                }
            )

    return {
        "target_term": target_term,
        "term_credit_cap": credit_cap,
        "feasible_schedules": [_serialize_schedule(c, credit_cap=credit_cap) for c in feasible_full],
        "partial_schedules": partial_schedules,
        "over_cap_schedules": [_serialize_schedule(c, credit_cap=credit_cap) for c in over_cap_schedules],
        "unavailable_courses": unavailable_courses,
        "problematic_courses": problematic_courses,
        "replacement_suggestions": replacement_suggestions,
    }
