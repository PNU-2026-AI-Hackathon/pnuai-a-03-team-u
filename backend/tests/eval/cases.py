"""Phase 3.1 골든 데이터셋.

각 케이스는 실제 관찰된 버그/설계 결정을 회귀 방지하는 assertion을 갖는다:

- 로드맵 챗 8개: 정컴 신입/3학년, 부전공, 엇학기, 편입, AI융합트랙, 복수전공, 진로-전공 mismatch
- 시간표 챗 3개: 정컴 3학년 기본, 시간 제약, 못 찾음(부재 검증)

원래 매트릭스(총 20+)에서 우선순위 높은 것만 추린 첫 배치.
"""

from __future__ import annotations

from .case_spec import (
    CourseSpec, DepartmentSpec, EvalCase, ExpectedBehavior, MajorSpec,
    OfferingSpec, PersonaSpec, ProgramSpec, RecordSpec, RequirementSpec,
    RoadmapItemSpec,
)


# 학과·전공 id는 실제 DB의 것을 흉내낸 상수. 사이드 이펙트 없음.
DEPT_CS = 10           # 정보컴퓨터공학부
MAJOR_CS = 20          # 컴퓨터공학전공
DEPT_BIZ = 30          # 경영학과
DEPT_EE = 40           # 전기전자공학부
MAJOR_EE = 41          # 전자공학전공
DEPT_PSY = 18          # 심리학과 (test_tracks_api와 정합)
MAJOR_PSY_TRACK = 66   # 심리데이터사이언스(SW융합트랙)
DEPT_MATH = 50         # 수학과
DEPT_KOR = 60          # 국어국문학과


# --- 공통 학과 셋 -----------------------------------------------------------

def _cs_hierarchy() -> tuple[list[DepartmentSpec], list[MajorSpec]]:
    return (
        [DepartmentSpec(id=DEPT_CS, name="정보컴퓨터공학부", college_name="정보의생명공학대학")],
        [MajorSpec(id=MAJOR_CS, department_id=DEPT_CS, name="컴퓨터공학전공")],
    )


def _cs_catalog() -> list[CourseSpec]:
    """정컴 커리큘럼 일부. LLM search_courses가 결과를 실제로 뽑을 수 있게 최소 12과목."""
    return [
        # 1학년
        CourseSpec(id=1001, course_name="컴퓨터프로그래밍(I)", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공기초", credits=3, year="1", semester="1"),
        CourseSpec(id=1002, course_name="컴퓨터프로그래밍(II)", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공기초", credits=3, year="1", semester="2"),
        CourseSpec(id=1003, course_name="이산수학", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공기초", credits=3, year="1", semester="2"),
        # 2학년
        CourseSpec(id=1010, course_name="자료구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공필수", credits=3, year="2", semester="1"),
        CourseSpec(id=1011, course_name="알고리즘", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공필수", credits=3, year="2", semester="2"),
        CourseSpec(id=1012, course_name="컴퓨터구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공필수", credits=3, year="2", semester="2"),
        # 3학년
        CourseSpec(id=1020, course_name="운영체제", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="1"),
        CourseSpec(id=1021, course_name="시스템프로그래밍", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="1"),
        CourseSpec(id=1022, course_name="데이터베이스", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="2"),
        CourseSpec(id=1023, course_name="컴퓨터네트워크", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="2"),
        CourseSpec(id=1024, course_name="인공지능", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="1"),
        CourseSpec(id=1025, course_name="머신러닝", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="2"),
    ]


# --- 케이스 정의 -----------------------------------------------------------


def case_freshman_backend() -> EvalCase:
    """1: 정컴 신입 1학년, 진로=백엔드. '1학년 2학기 뭐 들어야 해?' """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="cs-freshman-backend", label="정컴 신입 1학년 / 백엔드",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2026")],
        requirements=[RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                                       program_type="primary", curriculum_year="2026",
                                       required_total_credits=133,
                                       required_major_foundation=15,
                                       required_major_required=30,
                                       required_major_elective=27)],
        courses=_cs_catalog(),
    )
    return EvalCase(
        slug="01-cs-freshman-backend", persona=persona, agent="roadmap",
        prompt="안녕하세요. 저 정컴 신입 1학년인데 다음 학기(1학년 2학기) 뭐 들어야 할까요? 진로는 백엔드 개발자예요.",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses",
                             reason="후보 확정 없이 과목명 지어내는 것 방지 (finish_response 전 필수)"),
            ExpectedBehavior("tool_called", "finish_response",
                             reason="tool_choice=any라 유일한 답변 경로"),
            ExpectedBehavior("response_mentions", "1학년",
                             reason="다음 학기 배치 = 1학년 2학기라는 걸 인지"),
        ],
    )


def case_cs_junior_ai() -> EvalCase:
    """2: 정컴 3학년 완료, 진로=AI. '4학년 뭐 들으면 좋아요?' """
    depts, majors = _cs_hierarchy()
    completed = [
        RecordSpec(raw_course_name=name, category=cat, year="2025", semester=sem)
        for (name, cat, sem) in [
            ("컴퓨터프로그래밍(I)", "전공기초", "1학기"),
            ("컴퓨터프로그래밍(II)", "전공기초", "2학기"),
            ("이산수학", "전공기초", "2학기"),
            ("자료구조", "전공필수", "1학기"),
            ("알고리즘", "전공필수", "2학기"),
            ("컴퓨터구조", "전공필수", "2학기"),
            ("운영체제", "전공선택", "1학기"),
            ("시스템프로그래밍", "전공선택", "1학기"),
            ("데이터베이스", "전공선택", "2학기"),
        ]
    ]
    persona = PersonaSpec(
        id="cs-junior-ai", label="정컴 3학년 완료 / AI",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="AI 엔지니어",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                                       program_type="primary", curriculum_year="2024",
                                       required_total_credits=133)],
        courses=_cs_catalog(),
        records=completed,
        roadmap_items=[
            # 이미 3학년까지 다 이수했다고 표시 (편입생 폴백 방지용 completed 있음)
            RoadmapItemSpec(course_name=r.raw_course_name, planned_grade=int(2 if "이산" in r.raw_course_name
                                                                             or "프로그래밍" in r.raw_course_name else 3),
                            status="completed")
            for r in completed
        ],
    )
    return EvalCase(
        slug="02-cs-junior-ai", persona=persona, agent="roadmap",
        prompt="3학년까지 다 들었어요. 4학년 1학기 뭐 들으면 AI 진로에 도움이 될까요?",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses",
                             reason="AI 진로 관련 과목을 실제 카탈로그에서 찾아야 함 (지어내면 안 됨)"),
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="이미 이수한 과목 재추천 방지에 반드시 필요"),
            # 이수한 과목을 재추천하지 않는지는 도구 단(propose_change의
            # CompletedCoursesGuard, test_roadmap_chat 참고)에서 이미 검증됨. LLM은
            # "이미 이수했다"고 언급하며 제외 사실을 말할 수 있어(그게 오히려 친절함)
            # response_absent 문자열 매칭은 오탐이라 뺐다.
        ],
    )


def case_minor_biz_ee() -> EvalCase:
    """8: 경영 primary + 전자공학전공 minor. '부전공 몇 학점 남았어?' """
    persona = PersonaSpec(
        id="minor-biz-ee", label="경영 primary + 전자공 minor",
        departments=[
            DepartmentSpec(id=DEPT_BIZ, name="경영학과", college_name="경영대학"),
            DepartmentSpec(id=DEPT_EE, name="전기전자공학부", college_name="정보의생명공학대학"),
        ],
        majors=[MajorSpec(id=MAJOR_EE, department_id=DEPT_EE, name="전자공학전공")],
        department_id=DEPT_BIZ,
        career_goal="반도체 마케팅",
        programs=[
            ProgramSpec(department_id=DEPT_BIZ, program_type="primary", curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_BIZ, program_type="primary",
                            curriculum_year="2024", required_total_credits=130),
            # 부전공 21학점 + 필수과목 규칙. 부전공 필수과목 미확인 방지가 핵심.
            RequirementSpec(
                department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                curriculum_year="2024", required_total_credits=21,
                special_rules={
                    "total_credits": 21,
                    "groups": [
                        {"label": "부전공 필수과목", "rule_type": "all",
                         "courses": ["회로이론", "전자회로"]},
                        {"label": "부전공 선택과목", "rule_type": "min_credits",
                         "required_credits": 15,
                         "courses": ["디지털논리회로", "반도체소자", "신호및시스템"]},
                    ],
                },
            ),
        ],
        courses=[
            CourseSpec(id=2001, course_name="회로이론", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=2002, course_name="전자회로", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=2003, course_name="디지털논리회로", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공선택", credits=3, year="2", semester="1"),
        ],
    )
    return EvalCase(
        slug="08-minor-biz-ee", persona=persona, agent="roadmap",
        prompt="저 경영학과인데 전자공학전공 부전공 하고 있어요. 지금까지 아무것도 안 들었는데 뭐부터 들어야 해요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_program_evaluations",
                             reason="부전공 필수과목 확인은 이 도구가 유일. 21학점만 채우고 필수 미확인은 사고 (2026-08-03)"),
            ExpectedBehavior("response_mentions", "회로이론",
                             reason="부전공 필수과목 중 하나가 답변에 나와야 함"),
        ],
    )


def case_staggered_semester() -> EvalCase:
    """10: 2022 신입, 2024-2 휴학. 커리큘럼 학기 ≠ 달력 학기 (PR #121 fix). """
    depts, majors = _cs_hierarchy()
    # 2022-1 ~ 2024-1 = 5학기 이수 후 휴학. 커리큘럼상 3학년 1학기까지.
    completed = [
        RecordSpec(raw_course_name="컴퓨터프로그래밍(I)", category="전공기초",
                   year="2022", semester="1학기"),
        RecordSpec(raw_course_name="컴퓨터프로그래밍(II)", category="전공기초",
                   year="2022", semester="2학기"),
        RecordSpec(raw_course_name="이산수학", category="전공기초",
                   year="2022", semester="2학기"),
        RecordSpec(raw_course_name="자료구조", category="전공필수",
                   year="2023", semester="1학기"),
        RecordSpec(raw_course_name="알고리즘", category="전공필수",
                   year="2023", semester="2학기"),
        RecordSpec(raw_course_name="컴퓨터구조", category="전공필수",
                   year="2023", semester="2학기"),
        RecordSpec(raw_course_name="운영체제", category="전공선택",
                   year="2024", semester="1학기"),
    ]
    persona = PersonaSpec(
        id="staggered", label="엇학기 (2022 신입, 2024-2 휴학)",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="시스템 프로그래밍",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2022")],
        requirements=[RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                                       program_type="primary", curriculum_year="2022",
                                       required_total_credits=133)],
        courses=_cs_catalog(),
        records=completed,
        roadmap_items=[
            RoadmapItemSpec(course_name=r.raw_course_name, planned_grade=int(r.year) - 2021,
                            status="completed")
            for r in completed
        ],
    )
    return EvalCase(
        slug="10-staggered-semester", persona=persona, agent="roadmap",
        prompt="저 2024년 2학기부터 휴학했고 곧 복학해요. 다음 학기 뭐 들어야 해요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="next_plannable_term(커리큘럼 학기)과 current_academic_term(달력 학기) 차이를 이 도구에서 얻음"),
            # 엇학기 학생의 다음 학기는 3-2 (2024-1까지 이수, 다음이 3-2).
            # LLM이 정확한 년도까진 못 맞춰도 '3학년 2학기' 언급은 해야 정상.
            ExpectedBehavior("response_mentions", "3학년",
                             reason="커리큘럼상 다음 학기 = 3-2. 달력 학기(2026-2)로 답하면 회귀"),
        ],
    )


def case_transfer_student() -> EvalCase:
    """11: 편입생 (admission_type=transfer). 1·2학년 과목 새로 추천 금지. """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="transfer-cs", label="편입생 정컴",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        admission_type="transfer",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2026")],
        requirements=[RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                                       program_type="primary", curriculum_year="2026",
                                       required_total_credits=133)],
        courses=_cs_catalog(),
    )
    return EvalCase(
        slug="11-transfer-student", persona=persona, agent="roadmap",
        prompt="저 이번에 정컴으로 편입했어요. 뭐부터 들어야 할까요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="편입 폴백 학년 확인은 이 도구 응답의 earliest_recorded_grade/min_completed_grade에 있음"),
            ExpectedBehavior("response_mentions", "3학년",
                             reason="편입생 최저 학년 = 3학년. 1·2학년 과목 언급하면 회귀 (test_transfer 참고)"),
            # propose_change가 있었다면 planned_grade가 3 이상이어야 하지만 dry-run에선 검증 X.
        ],
    )


def case_ai_track() -> EvalCase:
    """16: 심리학과 3학년, AI융합트랙 등록 후 진도 문의 (PR #124)."""
    persona = PersonaSpec(
        id="ai-track-psy", label="심리학과 3학년 / AI융합트랙 등록",
        departments=[DepartmentSpec(id=DEPT_PSY, name="심리학과", college_name="사회과학대학")],
        majors=[MajorSpec(id=MAJOR_PSY_TRACK, department_id=DEPT_PSY,
                          name="심리데이터사이언스(SW융합트랙)")],
        department_id=DEPT_PSY,
        career_goal="AI 심리 데이터 분석",
        programs=[
            ProgramSpec(department_id=DEPT_PSY, program_type="primary", curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_PSY, major_id=MAJOR_PSY_TRACK,
                        program_type="interdisciplinary", curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_PSY, program_type="primary",
                            curriculum_year="2024", required_total_credits=130),
            RequirementSpec(
                department_id=DEPT_PSY, major_id=MAJOR_PSY_TRACK,
                program_type="interdisciplinary", curriculum_year="2024",
                required_total_credits=21,
                special_rules={
                    "certification_type": "AI융합트랙",
                    "not_graduation_requirement": True,
                    "total_credits": 21,
                    "groups": [
                        {"label": "학과 전공과목", "rule_type": "min_credits",
                         "required_credits": 12,
                         "courses": ["심리통계", "인지심리학"]},
                        {"label": "AI융합 공통교과목", "rule_type": "min_credits",
                         "required_credits": 9,
                         "courses": ["인공지능개론", "머신러닝기초"]},
                    ],
                },
            ),
        ],
        courses=[
            CourseSpec(id=3001, course_name="심리통계", department_id=DEPT_PSY,
                       category="전공선택", credits=3, year="2", semester="1"),
            CourseSpec(id=3002, course_name="인지심리학", department_id=DEPT_PSY,
                       category="전공선택", credits=3, year="3", semester="1"),
            CourseSpec(id=3003, course_name="인공지능개론", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공선택", credits=3, year="3", semester="1"),
        ],
    )
    return EvalCase(
        slug="16-ai-track", persona=persona, agent="roadmap",
        prompt="AI융합트랙 등록했어요. 지금 진도 얼마나 됐고 뭐 더 들어야 해요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_program_evaluations",
                             reason="AI융합트랙 그룹별 규칙 판정은 이 도구가 유일"),
            ExpectedBehavior("response_mentions", "21학점",
                             reason="트랙 총요건 21학점 안내가 컨텍스트 블록에 이미 노출됨"),
            ExpectedBehavior("response_mentions", "AI융합트랙",
                             reason="트랙 이름을 사용자에게 그대로 다시 언급"),
        ],
    )


def case_timetable_cs_junior() -> EvalCase:
    """17: 정컴 3학년, 이번 학기 시간표. 시간표 챗 기본 케이스."""
    depts, majors = _cs_hierarchy()
    # 정컴 3학년 2학기 개설 (offerings) — 시간 겹치지 않도록 짜둠.
    offerings = [
        OfferingSpec(id=5001, course_id=1022, year="2026", semester="2학기",  # 데이터베이스
                     times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
        OfferingSpec(id=5002, course_id=1023, year="2026", semester="2학기",  # 컴퓨터네트워크
                     times=[("화", "13:00", "14:30"), ("목", "13:00", "14:30")]),
        OfferingSpec(id=5003, course_id=1025, year="2026", semester="2학기",  # 머신러닝
                     times=[("월", "13:00", "14:30"), ("수", "13:00", "14:30")]),
    ]
    persona = PersonaSpec(
        id="tt-cs-junior", label="시간표: 정컴 3학년",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="AI 엔지니어",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        # per-category까지 채워야 timetable_chat의 get_student_context가
        # remaining_by_category를 노출한다. 없으면 LLM이 "훑을 카테고리 없음"으로 판단해
        # list_offered_courses 자체를 안 부른다 (실제 관찰 2026-08-11).
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS,
            program_type="primary", curriculum_year="2024",
            required_total_credits=133,
            required_major_foundation=15,
            required_major_required=30,
            required_major_elective=27,
            required_general_required=15,
            required_general_elective=17,
            required_free_elective=6,
        )],
        courses=_cs_catalog(),
        # 3-1까지 이수한 척 — 그래야 3-2 시간표 짜기 시나리오가 자연스럽다.
        records=[
            RecordSpec(raw_course_name=name, category=cat, year=y, semester=sem)
            for (name, cat, y, sem) in [
                ("컴퓨터프로그래밍(I)", "전공기초", "2024", "1학기"),
                ("컴퓨터프로그래밍(II)", "전공기초", "2024", "2학기"),
                ("이산수학", "전공기초", "2024", "2학기"),
                ("자료구조", "전공필수", "2025", "1학기"),
                ("알고리즘", "전공필수", "2025", "2학기"),
                ("컴퓨터구조", "전공필수", "2025", "2학기"),
                ("운영체제", "전공선택", "2026", "1학기"),
                ("시스템프로그래밍", "전공선택", "2026", "1학기"),
                ("인공지능", "전공선택", "2026", "1학기"),
            ]
        ],
        offerings=offerings,
    )
    return EvalCase(
        slug="17-tt-cs-junior", persona=persona, agent="timetable",
        prompt="정컴 3학년이에요. 이번 학기 시간표 후보 짜주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "get_student_context",
                             reason="시간표 챗의 모든 흐름은 이 도구로 시작"),
            ExpectedBehavior("tool_called", "list_offered_courses",
                             reason="offerings에서 실제 후보 뽑는 유일 경로"),
            ExpectedBehavior("schedules_count", (">=", 1),
                             reason="validate_timetable로 검증된 조합이 최소 1개 나와야 함"),
        ],
    )


def case_dual_cs_math() -> EvalCase:
    """9: 복수전공 (정컴 primary + 수학과 dual). 두 프로그램 동시 진도 요약."""
    depts, majors = _cs_hierarchy()
    depts = depts + [DepartmentSpec(id=DEPT_MATH, name="수학과", college_name="자연과학대학")]
    persona = PersonaSpec(
        id="dual-cs-math", label="정컴 + 수학과 dual",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="데이터 사이언티스트",
        programs=[
            ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                        program_type="primary", curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_MATH, program_type="dual",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                            program_type="primary", curriculum_year="2024",
                            required_total_credits=133),
            # 복수전공은 별도 이수학점 규정 — 최소 36학점 요구가 일반적.
            RequirementSpec(department_id=DEPT_MATH, program_type="dual",
                            curriculum_year="2024", required_total_credits=36,
                            required_major_required=18, required_major_elective=18),
        ],
        courses=_cs_catalog() + [
            CourseSpec(id=4001, course_name="해석학", department_id=DEPT_MATH,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=4002, course_name="선형대수학", department_id=DEPT_MATH,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=4003, course_name="확률론", department_id=DEPT_MATH,
                       category="전공선택", credits=3, year="3", semester="1"),
        ],
    )
    return EvalCase(
        slug="09-dual-cs-math", persona=persona, agent="roadmap",
        prompt="복수전공으로 수학과 하고 있어요. 지금 뭐부터 시작해야 해요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress",
                             reason="dual 프로그램 진도도 이 도구가 반환 (program_types에 'dual' 포함)"),
            ExpectedBehavior("response_mentions", "수학",
                             reason="복수전공 학과를 답변에 언급해야 사용자 요청 이해"),
        ],
    )


def case_career_mismatch() -> EvalCase:
    """14: 국문 + 백엔드 진로 mismatch → 복수/부전공 컴공 추천 유도."""
    persona = PersonaSpec(
        id="mismatch-kor-backend", label="국문 + 백엔드 진로",
        departments=[
            DepartmentSpec(id=DEPT_KOR, name="국어국문학과", college_name="인문대학"),
            DepartmentSpec(id=DEPT_CS, name="정보컴퓨터공학부", college_name="정보의생명공학대학"),
        ],
        majors=[MajorSpec(id=MAJOR_CS, department_id=DEPT_CS, name="컴퓨터공학전공")],
        department_id=DEPT_KOR,
        career_goal="백엔드 개발자",
        programs=[
            ProgramSpec(department_id=DEPT_KOR, program_type="primary",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_KOR, program_type="primary",
                            curriculum_year="2024", required_total_credits=130,
                            required_major_required=30, required_major_elective=27),
            # 정컴 부전공 가능하다는 걸 LLM이 알 수 있도록 GR 시드
            RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                            program_type="minor", curriculum_year="2024",
                            required_total_credits=21),
        ],
        # 국문학과 카탈로그도 최소한 있어야 LLM이 상담 흐름을 잡음
        courses=_cs_catalog() + [
            CourseSpec(id=8001, course_name="현대문학의이해", department_id=DEPT_KOR,
                       category="전공필수", credits=3, year="1", semester="1"),
            CourseSpec(id=8002, course_name="국어학개론", department_id=DEPT_KOR,
                       category="전공필수", credits=3, year="1", semester="2"),
        ],
    )
    return EvalCase(
        slug="14-career-mismatch", persona=persona, agent="roadmap",
        prompt="저는 국문학과인데 백엔드 개발자가 되고 싶어요. 어떻게 해야 할까요?",
        expectations=[
            # 문자열 매칭("부전공")은 오탐 가능 — "부·복수전공" 처럼 조합해 쓰거나
            # "이중전공" 이라 쓰면 fail. 의미 기반 판정으로 교체.
            ExpectedBehavior(
                "llm_judge",
                "학생의 진로(백엔드 개발자)와 주전공(국문학과)이 mismatch일 때, "
                "부전공/복수전공/이중전공 중 하나 이상을 명시적으로 옵션으로 제안했는가? "
                "단순히 국문 전공 과목만 나열하고 mismatch 자체를 언급 안 했으면 fail.",
                reason="진로-전공 mismatch면 부·복수전공 옵션 제시가 정답 — 의미 기반 판정",
            ),
        ],
    )


def case_tt_time_constraint() -> EvalCase:
    """18: 시간표에 시간 제약 ('월수금 오전만'). 사용자 제약 반영."""
    # 정컴 3학년 시나리오 재사용하되 offering을 시간대별로 다양화.
    depts, majors = _cs_hierarchy()
    offerings = [
        # 오전 후보 (제약 부합)
        OfferingSpec(id=6001, course_id=1022, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
        OfferingSpec(id=6002, course_id=1024, year="2026", semester="2학기",
                     times=[("월", "10:30", "12:00"), ("수", "10:30", "12:00")]),
        # 오후 후보 (제약 위반 — 걸러야 함)
        OfferingSpec(id=6003, course_id=1025, year="2026", semester="2학기",
                     times=[("화", "14:00", "15:30"), ("목", "14:00", "15:30")]),
    ]
    persona = PersonaSpec(
        id="tt-time-constraint", label="시간표: 월수금 오전만",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="AI 엔지니어",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS,
            program_type="primary", curriculum_year="2024",
            required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=_cs_catalog(), offerings=offerings,
    )
    def _no_tuesday_offering(r):
        """LLM이 화요일 offering(6003)을 스케줄에 포함했으면 fail.
        답변 텍스트에 '화'가 등장하는 건 제외 이유 설명일 수 있으니 반응 텍스트가 아닌
        실제 반환된 스케줄 offering_ids로만 판정."""
        for sched in r.schedules:
            if 6003 in (sched.get("offering_ids") or []):
                return "schedule에 화/목 offering(6003) 포함됨 — 사용자 '월수 오전만' 제약 위반"
        return None

    return EvalCase(
        slug="18-tt-time-constraint", persona=persona, agent="timetable",
        prompt="이번 학기 시간표 짜주세요. 조건 있어요 — 월수 오전에만 수업 넣어주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "validate_timetable",
                             reason="후보 조합 검증 없이 답변하면 안 됨"),
            ExpectedBehavior("custom", _no_tuesday_offering,
                             reason="반환된 스케줄의 offering_ids에 화요일 6003이 있는지 확인"),
        ],
    )


def case_tt_course_not_found() -> EvalCase:
    """21: 사용자가 특정 과목명 요청('공학작문')하지만 이번 학기 개설 없음.
    LLM이 없음을 정직하게 안내해야 함 (지어내기 방지)."""
    depts, majors = _cs_hierarchy()
    # 카탈로그에는 공학작문이 있지만 offerings에는 없음 → 이번 학기 미개설.
    catalog = _cs_catalog() + [
        CourseSpec(id=9001, course_name="공학작문", department_id=DEPT_CS,
                   major_id=MAJOR_CS, category="교양필수", credits=2,
                   year="2", semester="1"),
    ]
    # 다른 과목은 정상 개설 (아무것도 없으면 LLM이 조기 폴백으로 빠짐).
    offerings = [
        OfferingSpec(id=7001, course_id=1022, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
        OfferingSpec(id=7002, course_id=1023, year="2026", semester="2학기",
                     times=[("화", "13:00", "14:30"), ("목", "13:00", "14:30")]),
    ]
    persona = PersonaSpec(
        id="tt-not-found", label="시간표: 못 찾음 케이스",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS,
            program_type="primary", curriculum_year="2024",
            required_total_credits=133,
            required_major_required=30, required_major_elective=27,
            required_general_required=15,
        )],
        courses=catalog, offerings=offerings,
    )
    return EvalCase(
        slug="21-tt-not-found", persona=persona, agent="timetable",
        prompt="이번 학기에 공학작문 넣어서 시간표 짜주세요.",
        expectations=[
            ExpectedBehavior("tool_called", "list_offered_courses",
                             reason="'공학작문' 검색을 실제로 시도해야 함"),
            # 이전 문자열 매칭 assertion은 LLM이 "공학작문 포함하여 시간표를 짰습니다"
            # 라고 거짓말해도 PASS 처리하는 오탐이 있었다 (실제 관찰). 의미 기반으로 교체.
            ExpectedBehavior(
                "llm_judge",
                "다음 두 조건을 **모두** 만족하면 pass, 하나라도 어기면 fail:\n"
                "(a) 이번 학기에 '공학작문'이 개설되지 않았음(못 찾음)을 명시적으로 알렸다.\n"
                "(b) '공학작문을 포함해서 시간표를 만들었다'거나 실제로 공학작문이 스케줄에 "
                "들어가 있는 것처럼 거짓 주장을 하지 않았다.\n"
                "**참고**: 대안 과목명 제안(예: '공학글쓰기 아니세요?')이나 사용자 확인 요청은 "
                "도움되는 문의이므로 fail 사유가 아니다 — (a)를 만족한다면 pass.",
                reason="LLM이 '없음'을 인정하고 없는 과목을 있는 척 안 하는지 확인",
            ),
        ],
    )


ALL_CASES: list[EvalCase] = [
    case_freshman_backend(),
    case_cs_junior_ai(),
    case_minor_biz_ee(),
    case_dual_cs_math(),
    case_staggered_semester(),
    case_transfer_student(),
    case_career_mismatch(),
    case_ai_track(),
    case_timetable_cs_junior(),
    case_tt_time_constraint(),
    case_tt_course_not_found(),
]
