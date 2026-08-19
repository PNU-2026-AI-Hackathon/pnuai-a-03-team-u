"""AI융합트랙(SW융합트랙) 조회 — 학과 기준 이수 가능 트랙.

**졸업요건이 아니다.** AI융합교육원(소프트웨어융합교육원)이 운영하는 인증 프로그램으로,
학과 전공과목 12~15학점 + AI융합 공통교과목 6~9학점 = 총 21학점을 이수하면 졸업증명서에
과정명이 표기된다. 미이수해도 졸업에는 영향이 없다.

`graduation_requirements`에 `program_type='interdisciplinary'`로 저장돼 있는데, 그 유형에는
정식 연계전공(42·48학점)과 복수전공(36학점)도 섞여 들어온다. 그래서 총학점 21과
`special_rules.certification_type` 두 조건을 함께 봐야 트랙만 골라진다.

이 판별을 API 라우터(`api/tracks.py`)와 로드맵 챗이 각각 들고 있으면 한쪽만 고쳤을 때
화면과 AI가 서로 다른 말을 한다. 여기로 모은다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.academics.models import GraduationRequirement
from app.domains.courses.models import Course

# 트랙 인증 유형 표기. special_rules에 이 값이 있어야 AI융합트랙으로 본다.
TRACK_CERTIFICATION_TYPE = "AI융합트랙"

# 트랙 총 이수학점. 연계전공(42·48)·복수전공(36)과 구분하는 1차 조건이다.
TRACK_TOTAL_CREDITS = 21

# AI융합 공통교과목의 이수구분. 전부 일반선택으로 개설된다.
AI_COMMON_CATEGORY = "일반선택"


def is_ai_track(requirement: GraduationRequirement) -> bool:
    """이 요건 행이 AI융합트랙 인증 프로그램인가."""
    rules = requirement.special_rules or {}
    return rules.get("certification_type") == TRACK_CERTIFICATION_TYPE


# AI융합 공통교과목 — AI융합교육원이 AI중심대학사업으로 개설하는 AI 관련 교과목.
# 이수구분은 **일반선택**이고, 트랙의 "AI융합 공통교과목 6~9학점"을 이 목록에서 채운다.
#
# 왜 상수로 두는가: 학과 커리큘럼(`courses`)과 달리 이 목록은 AI융합교육원이 지정하는
# 고정 목록이고, `courses`에는 이 과목들이 "일반선택"으로만 들어 있어 **트랙 공통과목인지
# 구분할 표시가 없다.** 이름으로 이어 붙여야 한다.
#
# `aliases`는 개편 전 명칭이다 — `courses`에는 아직 구명칭으로 들어 있는 것이 있다
# (AI활용디지털전환 ← 창의적 프로그래밍). 이름 매칭은 공백을 제거하고 비교한다.
#
# 출처: https://ai.pusan.ac.kr (2026-08-19 기준 사용자 확인)
AI_COMMON_COURSES: tuple[dict, ...] = (
    {"name": "AI리터러시의이해", "module": 1, "aliases": (),
     "summary": "AI 기본 개념·데이터과학·최신 정보기술을 활용사례로 학습."},
    {"name": "AI이해를위한파이썬기초", "module": 1, "aliases": (),
     "summary": "코딩입문자 대상 파이썬 기초와 AI·디지털 전환의 기본 이해."},
    {"name": "데이터리터러시의이해", "module": 1, "aliases": (),
     "summary": "노코딩 도구(오렌지3)로 데이터 분석 기초부터 머신러닝 개념까지."},
    {"name": "데이터분석 입문", "module": 1, "aliases": (),
     "summary": "파이썬·판다스로 데이터 전처리와 시각화."},
    {"name": "데이터 마이닝", "module": 2, "aliases": (),
     "summary": "웹크롤링 수집부터 처리·분석·인사이트 도출까지 전 과정."},
    {"name": "AI활용디지털전환", "module": 2, "aliases": ("창의적 프로그래밍",),
     "summary": "파이썬 기계학습으로 디지털전환(DX) 실전 프로젝트.",
     "online_only": True},
    {"name": "메타버스활용프로젝트", "module": 2, "aliases": (),
     "summary": "VR·AR·메타버스 개념을 프로젝트로 구현."},
    {"name": "인공지능기초수학", "module": 2, "aliases": (),
     "summary": "머신러닝/딥러닝의 기본 용어와 연산 과정, 알고리즘 이해.",
     "online_only": True},
    {"name": "인공지능기반창업", "module": 2, "aliases": (),
     "summary": "AI를 활용한 창업 과정과 프로젝트 수행."},
    {"name": "SW문제해결프로젝트", "module": 2, "aliases": (),
     "summary": "공공데이터·전공 기반 데이터로 실전 프로젝트."},
)

# 이수 편의 안내. 트랙 이수생이 전공 수업과 충돌하지 않게 운영되는 방식이라,
# 로드맵·시간표를 짤 때 "금요일/계절학기에 몰아넣을 수 있다"는 판단 근거가 된다.
AI_COMMON_SCHEDULING_NOTE = (
    "AI융합 공통교과목은 전공수업 배치가 적은 금요일 수업과 계절학기로 적극 개설된다. "
    "'AI활용디지털전환'과 '인공지능기초수학'은 2025학년도 2학기부터 100% 온라인으로 개설된다."
)


def _normalize_course_name(name: str | None) -> str:
    return (name or "").replace(" ", "").strip()


def list_ai_common_courses(db: Session) -> list[dict]:
    """AI융합 공통교과목 목록에 `courses`의 개설 정보(학점·이수구분)를 붙여서 돌려준다.

    `courses`에 없는 과목은 `offered=False`로 남긴다 — 목록에서 빼지 않는다.
    우리 수강편람 적재가 불완전한 것과 학교가 폐강한 것을 구분할 수 없는데, 빼버리면
    학생이 "그 과목은 없다"고 오해한다.
    """
    rows = db.execute(
        select(Course.id, Course.course_name, Course.category, Course.credits)
    ).all()
    # **이수구분이 일반선택인 것만 후보로 본다.** 이름만 맞추면 학과 개설 동명 과목을
    # 집는다 — 실제로 전공선택 "데이터마이닝"이 공통교과목 "데이터 마이닝"으로 잘못
    # 매칭됐다(2026-08-19). AI융합 공통교과목은 전부 일반선택이다.
    by_name: dict[str, tuple] = {}
    for row in rows:
        if row.category != AI_COMMON_CATEGORY:
            continue
        by_name.setdefault(_normalize_course_name(row.course_name), row)

    out: list[dict] = []
    for spec in AI_COMMON_COURSES:
        matched = None
        matched_as = None
        for candidate in (spec["name"], *spec["aliases"]):
            hit = by_name.get(_normalize_course_name(candidate))
            if hit is not None:
                matched, matched_as = hit, candidate
                break
        entry = {
            "course_name": spec["name"],
            "module": spec["module"],
            "summary": spec["summary"],
            "offered": matched is not None,
        }
        if spec.get("online_only"):
            entry["online_only"] = True
        if matched is not None:
            entry["course_id"] = matched.id
            entry["credits"] = float(matched.credits) if matched.credits is not None else None
            entry["category"] = matched.category
            if matched_as != spec["name"]:
                # 구명칭으로 적재돼 있다. 학생에게 안내할 때 헷갈리지 않게 알려준다.
                entry["listed_as"] = matched_as
        out.append(entry)
    return out


def find_ai_tracks_for_department(
    db: Session, department_id: int | None
) -> list[GraduationRequirement]:
    """이 학과 학생이 이수 가능한 AI융합트랙 요건 행 목록.

    대상 학과가 아니면 빈 목록. 2026-08-19 기준 14개 학과에 등록돼 있고,
    정보컴퓨터공학부처럼 SW 학과는 대상이 아니다(트랙 취지가 비SW 전공자의
    AI·SW 역량 인증이다).
    """
    if department_id is None:
        return []
    candidates = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == department_id,
            GraduationRequirement.program_type == "interdisciplinary",
            GraduationRequirement.required_total_credits == TRACK_TOTAL_CREDITS,
        )
    ).all()
    return [gr for gr in candidates if is_ai_track(gr)]
