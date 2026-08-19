"""One-Stop 졸업예정정보(menuCD 000000000000089)의 **학교 공식 판정**을 DB로 upsert.

`portal_sync`는 이 페이지의 표 7개 중 표 0(학적신청 정보)과 균형교양 세부영역만 쓰고
**나머지를 통째로 버리고 있었다.** 그래서 "졸업요건이랑 토익 등 자격증을 못 가져온다"는
문제로 보였는데, 실제로는 크롤링은 되고 저장만 안 하던 상태였다(2026-08-16 실측 확인).

여기서 담는 것:
  - 표 1 `subject_category_completion`  → `student_graduation_categories`
  - 표 6 `graduation_requirement_completion` → `student_graduation_requirements`

담지 않는 것(의도적):
  - 표 2 `required_course_completion`(필수 교과목별 이수여부) — 값어치는 있지만 별건.
  - 표 3 `general_education_area_completion` — 이미 `portal_sync._refine_liberal_area_categories`
    가 `student_course_records.category` 세부화에 쓰고 있다.

**이건 우리 판정이 아니라 학교 판정이다.** `graduation_requirements`(학과 기준학점 원문)나
`/me/graduation`(우리 엔진 추정)과 섞지 않는다 — 어긋나면 이쪽이 맞다.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.academics.models import (
    StudentGraduationCategory,
    StudentGraduationRequirement,
)

_logger = logging.getLogger(__name__)

_CATEGORY_TABLE = "subject_category_completion"
_REQUIREMENT_TABLE = "graduation_requirement_completion"


def _to_bool(value: str | None) -> bool | None:
    """이수여부 Y/N → bool. 그 외 값은 판단하지 않고 None.

    조용히 False로 떨어뜨리면 "학교가 미충족이라고 했다"와 "우리가 못 읽었다"가
    구분되지 않는다.
    """
    text = (value or "").strip().upper()
    if text == "Y":
        return True
    if text == "N":
        return False
    return None


def _clean(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def upsert_official_graduation_status(
    db: Session,
    user_id: int,
    normalized: dict[str, Any],
    *,
    synced_at: datetime.datetime | None = None,
) -> dict[str, int]:
    """정규화된 졸업예정정보를 학생별 스냅샷 두 테이블에 반영한다.

    **스냅샷이므로 upsert 후 이번 크롤에 없던 행은 지운다.** 학적신청이 바뀌거나(복수전공
    포기 등) 요건이 개편되면 옛 행이 남아 "충족 못 한 요건"으로 계속 보이기 때문이다.

    반환: 각 테이블의 created/updated/deleted 카운트.
    """
    stamp = synced_at or datetime.datetime.now(datetime.UTC)
    stats = {
        "categories_created": 0, "categories_updated": 0, "categories_deleted": 0,
        "requirements_created": 0, "requirements_updated": 0, "requirements_deleted": 0,
    }

    seen_categories: set[tuple[str, str]] = set()
    for row in normalized.get("category_statuses", []):
        program_type = _clean(row.get("program_type"), 30)
        category = _clean(row.get("category"), 50)
        if not program_type or not category:
            continue
        key = (program_type, category)
        if key in seen_categories:
            # 같은 (학적신청구분, 사정구분)이 두 번 오면 원문이 이상한 것이다.
            # 조용히 덮어쓰면 어느 쪽이 남는지 알 수 없으므로 첫 행만 쓰고 남긴다.
            _logger.warning(
                "졸업예정정보 이수구분 중복 행 (user_id=%s, %s/%s) — 첫 행만 반영한다.",
                user_id, program_type, category,
            )
            continue
        seen_categories.add(key)

        values = {
            "required_credits": row.get("required_credits"),
            "earned_credits": row.get("earned_credits"),
            "registered_credits": row.get("registered_credits"),
            "expected_credits": row.get("expected_credits"),
            "satisfied": _to_bool(row.get("completed_status")),
            "failure_reason": _clean(row.get("failure_reason"), 200),
            "synced_at": stamp,
        }
        existing = db.scalars(
            select(StudentGraduationCategory).where(
                StudentGraduationCategory.user_id == user_id,
                StudentGraduationCategory.program_type == program_type,
                StudentGraduationCategory.category == category,
            )
        ).first()
        if existing is None:
            db.add(StudentGraduationCategory(
                user_id=user_id, program_type=program_type, category=category, **values,
            ))
            db.flush()   # SessionLocal이 autoflush=False — 같은 루프 안 재조회에 안 보인다
            stats["categories_created"] += 1
        else:
            for field, value in values.items():
                setattr(existing, field, value)
            stats["categories_updated"] += 1

    seen_requirements: set[tuple[str, str, str]] = set()
    # "조회내역이 없습니다." 행은 요건이 아니지만, **학교가 "요건 없음"이라고 답한 유일한
    # 신호**다. 그냥 버리면 `seen_requirements`가 비고 아래 빈 결과 가드가 걸려 삭제를
    # 안 해서, 학교가 요건을 지워도 옛 행이 영원히 "미충족"으로 남는다(독립 리뷰 지적).
    requirement_table_answered = False
    for row in normalized.get("requirement_items", []):
        if row.get("source_table_name") != _REQUIREMENT_TABLE:
            continue
        if row.get("completed_status") == "no_records":
            # **여기서만** 플래그를 세운다. 표 6 행이 "있기만" 하면 세우도록 두면,
            # 표는 정상적으로 왔는데 컬럼명이 바뀌어 파싱만 실패한 경우에도 플래그가
            # 서서 **요건 스냅샷을 통째로 지운다** — 원래 가드가 막으려던 바로 그
            # 케이스다(독립 2차 리뷰가 실측으로 재현). 하필 이 변경에서 컬럼명 접두어를
            # 틀렸던 전례가 있어 현실성도 충분하다.
            requirement_table_answered = True
            continue
        # ⚠️ 위 `source_table_name` 검사는 **중복 방어가 아니라 이 경로의 유일한 방어**다.
        # 지우면 안 된다.
        #
        # 다른 표에서 온 `no_records` 행은 아래 `program_type` 가드에 **도달하지 못한다** —
        # 그 앞의 `no_records` 분기가 먼저 `continue`하기 때문이다. 그리고 표 4·5
        # (`general_required_course_completion`, `major_course_completion`)는 **매 크롤마다
        # `no_records`로 온다**(실크롤 샘플로 확인). 즉 이 검사를 빼면 표 6 컬럼명만 바뀌어도
        # 표 4·5의 no_records가 플래그를 세워 **요건 스냅샷 전체가 삭제된다.**
        #
        # 2·3차 리뷰에서 이 줄의 성격을 두 번 잘못 적었다("중복 방어라 안 잡히는 게 맞다").
        # `test_rows_from_other_tables_do_not_clear_requirements`가 이제 실제로 고정한다.
        raw = row.get("raw_record", {})
        program_type = _clean(raw.get("졸업기준_학적신청구분"), 30)
        requirement_name = _clean(row.get("required_category"), 100)
        if not program_type or not requirement_name:
            continue
        detail_name = _clean(row.get("required_course_name"), 200) or ""
        key = (program_type, requirement_name, detail_name)
        if key in seen_requirements:
            _logger.warning(
                "졸업예정정보 요건 중복 행 (user_id=%s, %s/%s/%s) — 첫 행만 반영한다.",
                user_id, program_type, requirement_name, detail_name,
            )
            continue
        seen_requirements.add(key)

        values = {
            # ⚠️ 접두어가 `졸업기준_`이 아니라 `학생이수정보_`다. 처음엔 학적신청구분과
            # 같은 접두어일 거라 짐작하고 `졸업기준_합격구분`/`졸업기준_취득일자`를 읽었는데,
            # 원문엔 그런 키가 없어서 **요건을 이미 통과한 학생의 합격구분·취득일자가
            # 조용히 버려졌다** — 이 변경이 고치겠다던 "가져와놓고 버린다"를 컬럼 2개에서
            # 그대로 반복한 것이다(독립 리뷰 지적). 실제 키:
            #   ['No', '졸업기준_상세졸업요건명', '졸업기준_졸업요건명', '졸업기준_학적신청구분',
            #    '학생이수정보_비고_예외사항_상세내역_점수', '학생이수정보_이수여부',
            #    '학생이수정보_취득일자', '학생이수정보_합격구분']
            "pass_type": _clean(raw.get("학생이수정보_합격구분"), 50),
            "acquired_date": _clean(raw.get("학생이수정보_취득일자"), 30),
            "satisfied": _to_bool(row.get("completed_status")),
            "note": _clean(row.get("note"), 500),
            "synced_at": stamp,
        }
        existing = db.scalars(
            select(StudentGraduationRequirement).where(
                StudentGraduationRequirement.user_id == user_id,
                StudentGraduationRequirement.program_type == program_type,
                StudentGraduationRequirement.requirement_name == requirement_name,
                StudentGraduationRequirement.detail_name == detail_name,
            )
        ).first()
        if existing is None:
            db.add(StudentGraduationRequirement(
                user_id=user_id, program_type=program_type,
                requirement_name=requirement_name, detail_name=detail_name, **values,
            ))
            db.flush()
            stats["requirements_created"] += 1
        else:
            for field, value in values.items():
                setattr(existing, field, value)
            stats["requirements_updated"] += 1

    # 이번 스냅샷에 없는 옛 행 제거 (위 docstring 참고).
    #
    # **파싱 실패와 "학교가 비었다고 답함"을 구분한다.** 그냥 "결과가 비면 안 지운다"로
    # 두면 학교가 요건을 지워도 옛 행이 영원히 남는다. 요건 쪽은 원문에 "조회내역이
    # 없습니다." 행이 오므로(`requirement_table_answered`) 그걸 근거로 삭제한다.
    # 카테고리 표에는 그런 신호가 없어서 보수적으로 "비면 안 지움"을 유지한다.
    if seen_categories:
        for row_obj in db.scalars(
            select(StudentGraduationCategory).where(StudentGraduationCategory.user_id == user_id)
        ).all():
            if (row_obj.program_type, row_obj.category) not in seen_categories:
                db.delete(row_obj)
                stats["categories_deleted"] += 1
    if seen_requirements or requirement_table_answered:
        for row_obj in db.scalars(
            select(StudentGraduationRequirement).where(
                StudentGraduationRequirement.user_id == user_id
            )
        ).all():
            key = (row_obj.program_type, row_obj.requirement_name, row_obj.detail_name)
            if key not in seen_requirements:
                db.delete(row_obj)
                stats["requirements_deleted"] += 1

    return stats
