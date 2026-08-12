"""챗 골든 데이터셋 — 21 케이스 (Phase 3.1 계획 매트릭스 완성).

각 케이스는 실제 관찰된 버그/설계 결정을 회귀 방지하는 assertion을 갖는다.

**로드맵 챗 (16)**:
- 01 정컴 신입 · 02 정컴 3학년(AI) · 03 경영 4학년(재무)
- 04 전자공학 3학년(반도체) · 05 기계 2학년(자동차)
- 06 SW연계전공 임베디드 (48학점) · 07 핀테크 융합전공 (42학점)
- 08 부전공 · 09 복수전공 · 15 부·복수 동시
- 10 엇학기 · 11 편입 · 12 전공기초 부족 · 13 1학기 전용 미수강
- 14 진로-전공 mismatch · 16 AI융합트랙

**시간표 챗 (5)**:
- 17 정컴 3학년 · 18 시간 제약 · 19 엇학기 · 20 부전공 · 21 못 찾음
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
DEPT_MECH = 70         # 기계공학부
DEPT_FINTECH = 80      # 핀테크 융합전공 (dept-level program, major_id None)
DEPT_IE = 90           # 산업공학과
MAJOR_EMBED = 25       # 임베디드SW SW연계전공 (정컴 학과 소속)


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
    return EvalCase(
        slug="18-tt-time-constraint", persona=persona, agent="timetable",
        prompt="이번 학기 시간표 짜주세요. 조건 있어요 — 월수 오전에만 수업 넣어주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "validate_timetable",
                             reason="후보 조합 검증 없이 답변하면 안 됨"),
            ExpectedBehavior("response_absent", "화",
                             reason="화요일 오후 offering(6003)이 답변에 나오면 사용자 제약 무시"),
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


# --- 2차 배치 케이스 (매트릭스 완성) --------------------------------------


def case_biz_senior_finance() -> EvalCase:
    """3: 경영학과 4학년, 진로=재무분석. 마지막 학기 남은 학점 우선순위 검증."""
    persona = PersonaSpec(
        id="biz-senior-finance", label="경영 4학년 / 재무분석",
        departments=[DepartmentSpec(id=DEPT_BIZ, name="경영학과", college_name="경영대학")],
        majors=[],
        department_id=DEPT_BIZ,
        career_goal="재무분석가",
        programs=[ProgramSpec(department_id=DEPT_BIZ, program_type="primary",
                              curriculum_year="2023")],
        requirements=[RequirementSpec(
            department_id=DEPT_BIZ, program_type="primary", curriculum_year="2023",
            required_total_credits=130, required_major_required=30,
            required_major_elective=30, required_general_required=15,
            required_general_elective=15,
        )],
        courses=[
            CourseSpec(id=3101, course_name="재무관리", department_id=DEPT_BIZ,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=3102, course_name="회계원리", department_id=DEPT_BIZ,
                       category="전공필수", credits=3, year="1", semester="1"),
            CourseSpec(id=3103, course_name="투자론", department_id=DEPT_BIZ,
                       category="전공선택", credits=3, year="3", semester="2"),
            CourseSpec(id=3104, course_name="파생상품", department_id=DEPT_BIZ,
                       category="전공선택", credits=3, year="4", semester="1"),
            CourseSpec(id=3105, course_name="기업재무", department_id=DEPT_BIZ,
                       category="전공선택", credits=3, year="4", semester="1"),
        ],
        # 3학년까지 이수한 척
        records=[
            RecordSpec(raw_course_name="회계원리", category="전공필수", year="2023"),
            RecordSpec(raw_course_name="재무관리", category="전공필수", year="2024"),
            RecordSpec(raw_course_name="투자론", category="전공선택", year="2025"),
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name=n, planned_grade=g, status="completed")
            for n, g in [("회계원리", 1), ("재무관리", 2), ("투자론", 3)]
        ],
    )
    return EvalCase(
        slug="03-biz-senior-finance", persona=persona, agent="roadmap",
        prompt="경영학과 4학년 1학기 뭐 들어야 해요? 재무분석 쪽으로 가려고요.",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses",
                             reason="4학년 남은 과목 후보를 실제 카탈로그에서 뽑아야 함"),
            ExpectedBehavior(
                "llm_judge",
                "재무분석 진로에 부합하는 과목(예: 파생상품, 기업재무, 투자론 계열)을 "
                "우선순위로 추천했는가? 진로와 무관한 과목만 나열했으면 fail.",
                reason="진로 기반 우선순위 반영 검증",
            ),
        ],
    )


def case_ee_junior_semiconductor() -> EvalCase:
    """4: 전기전자 전자공학전공 3학년, 진로=반도체 설계."""
    persona = PersonaSpec(
        id="ee-junior-semi", label="전자공 3학년 / 반도체",
        departments=[DepartmentSpec(id=DEPT_EE, name="전기전자공학부",
                                     college_name="정보의생명공학대학")],
        majors=[MajorSpec(id=MAJOR_EE, department_id=DEPT_EE, name="전자공학전공")],
        department_id=DEPT_EE, major_id=MAJOR_EE,
        career_goal="반도체 회로 설계",
        programs=[ProgramSpec(department_id=DEPT_EE, major_id=MAJOR_EE,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_EE, major_id=MAJOR_EE, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=[
            CourseSpec(id=2001, course_name="회로이론", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=2002, course_name="전자회로", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=2011, course_name="반도체소자", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공선택", credits=3, year="3", semester="1"),
            CourseSpec(id=2012, course_name="집적회로설계", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공선택", credits=3, year="3", semester="2"),
            CourseSpec(id=2013, course_name="VLSI설계", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공선택", credits=3, year="4", semester="1"),
        ],
        records=[
            RecordSpec(raw_course_name="회로이론", category="전공필수", year="2024"),
            RecordSpec(raw_course_name="전자회로", category="전공필수", year="2025"),
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name="회로이론", planned_grade=2, status="completed"),
            RoadmapItemSpec(course_name="전자회로", planned_grade=2, status="completed"),
        ],
    )
    return EvalCase(
        slug="04-ee-junior-semi", persona=persona, agent="roadmap",
        prompt="전자공학전공 3학년인데 반도체 설계 쪽에 관심 있어요. 다음 학기 뭐 들으면 좋아요?",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses"),
            ExpectedBehavior(
                "llm_judge",
                "반도체 진로에 맞는 과목(반도체소자·집적회로설계·VLSI 계열)을 우선순위로 "
                "추천했는가?",
                reason="전자공 진로 반영",
            ),
        ],
    )


def case_mech_sophomore_auto() -> EvalCase:
    """5: 기계공학부 2학년, 진로=자동차 엔지니어."""
    persona = PersonaSpec(
        id="mech-soph-auto", label="기계 2학년 / 자동차",
        departments=[DepartmentSpec(id=DEPT_MECH, name="기계공학부",
                                     college_name="공과대학")],
        majors=[],
        department_id=DEPT_MECH,
        career_goal="자동차 엔지니어",
        programs=[ProgramSpec(department_id=DEPT_MECH, program_type="primary",
                              curriculum_year="2025")],
        requirements=[RequirementSpec(
            department_id=DEPT_MECH, program_type="primary",
            curriculum_year="2025", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
            required_general_required=15,
        )],
        courses=[
            CourseSpec(id=5001, course_name="공학수학", department_id=DEPT_MECH,
                       category="전공기초", credits=3, year="1", semester="1"),
            CourseSpec(id=5002, course_name="정역학", department_id=DEPT_MECH,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=5003, course_name="열역학", department_id=DEPT_MECH,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=5011, course_name="자동차공학", department_id=DEPT_MECH,
                       category="전공선택", credits=3, year="3", semester="1"),
            CourseSpec(id=5012, course_name="내연기관", department_id=DEPT_MECH,
                       category="전공선택", credits=3, year="3", semester="2"),
        ],
        records=[
            RecordSpec(raw_course_name="공학수학", category="전공기초", year="2025"),
            RecordSpec(raw_course_name="정역학", category="전공필수", year="2026"),
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name="공학수학", planned_grade=1, status="completed"),
            RoadmapItemSpec(course_name="정역학", planned_grade=2, status="completed"),
        ],
    )
    return EvalCase(
        slug="05-mech-soph-auto", persona=persona, agent="roadmap",
        prompt="기계공학부 2학년 2학기 뭐 들어야 해요? 나중에 자동차 관련 일 하고 싶어요.",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses"),
            ExpectedBehavior(
                "llm_judge",
                "다음 학기(2-2)에 이수할 만한 과목으로 열역학(전공필수) 같은 필수를 "
                "우선순위로 챙기고, 자동차 진로 관련 과목(내연기관·자동차공학 등)은 "
                "장기 계획으로 언급했는가? 필수 무시하고 진로 과목만 추천했으면 fail.",
                reason="필수 우선 + 진로 반영 균형",
            ),
        ],
    )


def case_sw_convergence_embedded() -> EvalCase:
    """6: 정컴 primary + SW연계전공 임베디드SW (48학점, 정식 다전공)."""
    depts, majors = _cs_hierarchy()
    majors = majors + [MajorSpec(id=MAJOR_EMBED, department_id=DEPT_CS,
                                  name="임베디드SW(SW연계전공)")]
    persona = PersonaSpec(
        id="sw-embed", label="정컴 + SW연계전공 임베디드 (48학점)",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="임베디드 시스템 개발",
        programs=[
            ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                        program_type="primary", curriculum_year="2024"),
            # 트랙(21학점)이 아니라 정식 다전공(48학점) — special_rules로 구분
            ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_EMBED,
                        program_type="interdisciplinary", curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                            program_type="primary", curriculum_year="2024",
                            required_total_credits=133),
            RequirementSpec(
                department_id=DEPT_CS, major_id=MAJOR_EMBED,
                program_type="interdisciplinary", curriculum_year="2024",
                required_total_credits=48,
                special_rules={"total_credits": 48},  # 트랙과 다르게 not_graduation_requirement 없음
            ),
        ],
        courses=_cs_catalog(),
    )
    return EvalCase(
        slug="06-sw-embed", persona=persona, agent="roadmap",
        prompt="SW연계전공 임베디드 하고 있어요. 지금까지 뭐 들었고 뭐가 남았어요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress",
                             reason="주전공 + 연계전공 진도 둘 다 필요"),
            ExpectedBehavior(
                "llm_judge",
                "48학점 요구 조건이 있는 연계전공에 대해 남은 학점/진도를 사용자에게 "
                "명확히 안내했는가? 21학점 SW융합트랙으로 오인하지 않았는가?",
                reason="트랙(21학점) vs 정식 연계전공(48학점) 구분",
            ),
        ],
    )


def case_fintech_convergence() -> EvalCase:
    """7: 핀테크 융합전공 (42학점, dept-level 프로그램)."""
    persona = PersonaSpec(
        id="fintech", label="핀테크 융합전공 (42학점)",
        departments=[
            DepartmentSpec(id=DEPT_BIZ, name="경영학과", college_name="경영대학"),
            DepartmentSpec(id=DEPT_FINTECH, name="핀테크융합전공",
                           college_name="융합대학"),
        ],
        majors=[],
        department_id=DEPT_BIZ,
        career_goal="핀테크 스타트업",
        programs=[
            ProgramSpec(department_id=DEPT_BIZ, program_type="primary",
                        curriculum_year="2024"),
            # major_id=None — 학과 자체가 프로그램 단위
            ProgramSpec(department_id=DEPT_FINTECH, program_type="interdisciplinary",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_BIZ, program_type="primary",
                            curriculum_year="2024", required_total_credits=130),
            RequirementSpec(
                department_id=DEPT_FINTECH, program_type="interdisciplinary",
                curriculum_year="2024", required_total_credits=42,
                special_rules={"total_credits": 42},
            ),
        ],
        courses=[
            CourseSpec(id=8101, course_name="블록체인개론", department_id=DEPT_FINTECH,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=8102, course_name="금융공학", department_id=DEPT_FINTECH,
                       category="전공필수", credits=3, year="2", semester="2"),
        ],
    )
    return EvalCase(
        slug="07-fintech", persona=persona, agent="roadmap",
        prompt="핀테크 융합전공 하고 있어요. 필요한 학점 뭐 뭐 있어요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress"),
            ExpectedBehavior(
                "llm_judge",
                "핀테크 융합전공 42학점 요건을 사용자에게 안내했는가? "
                "(정확한 숫자든 '42학점 이상' 표현이든 무방)",
                reason="42학점 융합전공 규정 정확 반영",
            ),
        ],
    )


def case_missing_foundation() -> EvalCase:
    """12: 3학년인데 이산수학(전공기초) 안 들음 — 다음 학기 필수 우선."""
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="missing-foundation", label="정컴 3학년 · 이산수학 미이수",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_foundation=15, required_major_required=30,
            required_major_elective=27,
        )],
        # _cs_catalog의 이산수학은 semester="2" (2학기 전용) 이라 next term=1학기와 어긋난다.
        # 이 시나리오("전공기초 우선 배치")를 정합하려면 이산수학이 next term에 개설돼야
        # 하므로 catalog에서 이산수학만 semester="1,2"로 override한다 (실제로도 여러 학기
        # 개설되는 경우 흔함).
        courses=[c for c in _cs_catalog() if c.course_name != "이산수학"] + [
            CourseSpec(id=1003, course_name="이산수학", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공기초", credits=3, year="1", semester="1,2"),
        ],
        # 이산수학은 없고 나머지 전공기초·필수는 완료. 3학년까지 진행.
        records=[
            RecordSpec(raw_course_name="컴퓨터프로그래밍(I)", category="전공기초", year="2024"),
            RecordSpec(raw_course_name="컴퓨터프로그래밍(II)", category="전공기초", year="2024"),
            RecordSpec(raw_course_name="자료구조", category="전공필수", year="2025"),
            RecordSpec(raw_course_name="알고리즘", category="전공필수", year="2025"),
            RecordSpec(raw_course_name="운영체제", category="전공선택", year="2026"),
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name=n, planned_grade=g, status="completed")
            for n, g in [("컴퓨터프로그래밍(I)", 1), ("컴퓨터프로그래밍(II)", 1),
                          ("자료구조", 2), ("알고리즘", 2), ("운영체제", 3)]
        ],
    )
    return EvalCase(
        slug="12-missing-foundation", persona=persona, agent="roadmap",
        prompt="다음 학기 뭐 들으면 좋아요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress"),
            ExpectedBehavior(
                "llm_judge",
                "학생이 아직 이수 안 한 전공기초 과목(이산수학)을 놓치지 않고 다음 학기 "
                "우선순위로 추천했는가? 진로 관련 전공선택만 나열하고 미이수 전공기초를 "
                "무시했으면 fail.",
                reason="미이수 전공기초 우선순위 검증",
            ),
        ],
    )


def case_last_semester_1st_only_gap() -> EvalCase:
    """13: 4학년 학생이 컴퓨터구조(2학기 전용) 미이수. 다음 배치 학기가 1학기라
    개설 안 됨 — 도구가 critical_missing_required로 자동 감지 → LLM이 위험 안내.

    _current_academic_term 패치는 (2026, 2) → 다음 학기 = 2027-1학기 (1학기).
    컴퓨터구조.semester='2'(2학기 전용) → 다음 학기에 개설 X → critical.
    """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="last-sem-gap", label="4학년 · 2학기 전용 필수 미이수",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2023")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2023", required_total_credits=133,
        )],
        courses=[
            # 컴퓨터구조: 2학기 전용 필수. 학생이 미이수인데 다음 학기(1학기) 개설 X.
            CourseSpec(id=1010, course_name="자료구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=1011, course_name="알고리즘", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=1012, course_name="컴퓨터구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=1013, course_name="운영체제", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공선택", credits=3, year="3", semester="1"),
        ],
        # 컴퓨터구조 빼고 다 이수함
        records=[
            RecordSpec(raw_course_name="컴퓨터프로그래밍(I)", category="전공기초", year="2023"),
            RecordSpec(raw_course_name="자료구조", category="전공필수", year="2024"),
            RecordSpec(raw_course_name="알고리즘", category="전공필수", year="2024"),
            RecordSpec(raw_course_name="운영체제", category="전공선택", year="2025"),
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name=n, planned_grade=g, status="completed")
            for n, g in [("컴퓨터프로그래밍(I)", 1), ("자료구조", 2),
                          ("알고리즘", 2), ("운영체제", 3)]
        ],
    )
    return EvalCase(
        slug="13-last-sem-gap", persona=persona, agent="roadmap",
        prompt="4학년 2학기예요. 다음 학기 뭐 들어야 졸업할 수 있어요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="critical_missing_required는 이 도구로만 확인"),
            ExpectedBehavior(
                "llm_judge",
                "학생이 이수 안 한 컴퓨터구조(2학기 전용 전공필수)를 "
                "'다음 학기(1학기)에는 개설 안 된다'는 사실과 함께 명시적으로 위험 안내"
                "하거나 대안(같은 학기의 다음 연도)을 제시했는가? 그냥 다른 과목만 "
                "나열하고 이 필수 미이수를 언급 안 했으면 fail.",
                reason="critical_missing_required 활용 검증",
            ),
        ],
    )


def case_minor_and_dual() -> EvalCase:
    """15: 부·복수 동시 (경영 primary + 전자 minor + 산업 dual)."""
    persona = PersonaSpec(
        id="minor-and-dual", label="경영 + 전자minor + 산업dual",
        departments=[
            DepartmentSpec(id=DEPT_BIZ, name="경영학과", college_name="경영대학"),
            DepartmentSpec(id=DEPT_EE, name="전기전자공학부",
                           college_name="정보의생명공학대학"),
            DepartmentSpec(id=DEPT_IE, name="산업공학과", college_name="공과대학"),
        ],
        majors=[MajorSpec(id=MAJOR_EE, department_id=DEPT_EE, name="전자공학전공")],
        department_id=DEPT_BIZ,
        career_goal="스타트업 창업",
        programs=[
            ProgramSpec(department_id=DEPT_BIZ, program_type="primary",
                        curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                        curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_IE, program_type="dual",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_BIZ, program_type="primary",
                            curriculum_year="2024", required_total_credits=130),
            RequirementSpec(
                department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                curriculum_year="2024", required_total_credits=21,
                special_rules={"total_credits": 21, "groups": [
                    {"label": "필수", "rule_type": "all", "courses": ["회로이론"]},
                ]},
            ),
            RequirementSpec(department_id=DEPT_IE, program_type="dual",
                            curriculum_year="2024", required_total_credits=36,
                            required_major_required=18, required_major_elective=18),
        ],
        courses=[
            CourseSpec(id=2001, course_name="회로이론", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=7001, course_name="생산공학", department_id=DEPT_IE,
                       category="전공필수", credits=3, year="2", semester="1"),
        ],
    )
    return EvalCase(
        slug="15-minor-and-dual", persona=persona, agent="roadmap",
        prompt="지금 부전공(전자) + 복수전공(산업) 하고 있어요. 세 개 다 정리해서 뭐 남았는지 알려주세요.",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress",
                             reason="세 프로그램 진도 동시 조회"),
            ExpectedBehavior("tool_called", "get_program_evaluations",
                             reason="부전공 필수과목 규칙 확인"),
            ExpectedBehavior(
                "llm_judge",
                "주전공(경영) + 부전공(전자) + 복수전공(산업) 세 프로그램 각각에 대해 "
                "남은 상태를 사용자에게 구분해서 안내했는가? 하나만 챙기고 나머지를 "
                "빠뜨렸으면 fail.",
                reason="세 program_type 동시 처리",
            ),
        ],
    )


def case_tt_staggered() -> EvalCase:
    """19: 엇학기 학생 시간표. 커리큘럼 학기 vs 달력 학기 반영."""
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="tt-staggered", label="시간표: 엇학기",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="시스템 프로그래밍",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2022")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2022", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=_cs_catalog(),
        records=[
            RecordSpec(raw_course_name=n, category=c, year=y, semester=sem)
            for (n, c, y, sem) in [
                ("컴퓨터프로그래밍(I)", "전공기초", "2022", "1학기"),
                ("컴퓨터프로그래밍(II)", "전공기초", "2022", "2학기"),
                ("자료구조", "전공필수", "2023", "1학기"),
                ("알고리즘", "전공필수", "2023", "2학기"),
                ("컴퓨터구조", "전공필수", "2023", "2학기"),
                ("운영체제", "전공선택", "2024", "1학기"),
            ]
        ],
        offerings=[
            OfferingSpec(id=5501, course_id=1022, year="2026", semester="2학기",  # 데이터베이스
                         times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
            OfferingSpec(id=5502, course_id=1023, year="2026", semester="2학기",  # 컴퓨터네트워크
                         times=[("화", "13:00", "14:30"), ("목", "13:00", "14:30")]),
        ],
    )
    return EvalCase(
        slug="19-tt-staggered", persona=persona, agent="timetable",
        prompt="복학하는데 이번 학기 시간표 짜주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "list_offered_courses"),
            ExpectedBehavior("schedules_count", (">=", 1),
                             reason="휴학 후 복학 학생도 유효 조합 제안 가능해야 함"),
        ],
    )


def case_tt_minor_student() -> EvalCase:
    """20: 부전공(전자) 학생 시간표. 부전공 필수과목 우선 검증."""
    persona = PersonaSpec(
        id="tt-minor", label="시간표: 경영+전자minor",
        departments=[
            DepartmentSpec(id=DEPT_BIZ, name="경영학과", college_name="경영대학"),
            DepartmentSpec(id=DEPT_EE, name="전기전자공학부",
                           college_name="정보의생명공학대학"),
        ],
        majors=[MajorSpec(id=MAJOR_EE, department_id=DEPT_EE, name="전자공학전공")],
        department_id=DEPT_BIZ,
        career_goal="반도체 마케팅",
        programs=[
            ProgramSpec(department_id=DEPT_BIZ, program_type="primary",
                        curriculum_year="2024"),
            ProgramSpec(department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                        curriculum_year="2024"),
        ],
        requirements=[
            RequirementSpec(department_id=DEPT_BIZ, program_type="primary",
                            curriculum_year="2024", required_total_credits=130,
                            required_major_required=30),
            RequirementSpec(
                department_id=DEPT_EE, major_id=MAJOR_EE, program_type="minor",
                curriculum_year="2024", required_total_credits=21,
                special_rules={"total_credits": 21, "groups": [
                    {"label": "필수", "rule_type": "all", "courses": ["회로이론"]},
                ]},
            ),
        ],
        courses=[
            CourseSpec(id=3401, course_name="마케팅원론", department_id=DEPT_BIZ,
                       category="전공필수", credits=3, year="2", semester="2"),
            CourseSpec(id=2001, course_name="회로이론", department_id=DEPT_EE, major_id=MAJOR_EE,
                       category="전공필수", credits=3, year="2", semester="2"),
        ],
        offerings=[
            OfferingSpec(id=6501, course_id=3401, year="2026", semester="2학기",
                         times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
            OfferingSpec(id=6502, course_id=2001, year="2026", semester="2학기",
                         times=[("화", "13:00", "14:30"), ("목", "13:00", "14:30")]),
        ],
    )
    return EvalCase(
        slug="20-tt-minor", persona=persona, agent="timetable",
        prompt="경영학과인데 전자 부전공도 하고 있어요. 이번 학기 시간표 짜주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "list_offered_courses"),
            ExpectedBehavior("schedules_count", (">=", 1)),
        ],
    )


ALL_CASES: list[EvalCase] = [
    # 로드맵 챗
    case_freshman_backend(),          # 01
    case_cs_junior_ai(),              # 02
    case_biz_senior_finance(),        # 03
    case_ee_junior_semiconductor(),   # 04
    case_mech_sophomore_auto(),       # 05
    case_sw_convergence_embedded(),   # 06
    case_fintech_convergence(),       # 07
    case_minor_biz_ee(),              # 08
    case_dual_cs_math(),              # 09
    case_staggered_semester(),        # 10
    case_transfer_student(),          # 11
    case_missing_foundation(),        # 12
    case_last_semester_1st_only_gap(),  # 13
    case_career_mismatch(),           # 14
    case_minor_and_dual(),            # 15
    case_ai_track(),                  # 16
    # 시간표 챗
    case_timetable_cs_junior(),       # 17
    case_tt_time_constraint(),        # 18
    case_tt_staggered(),              # 19
    case_tt_minor_student(),          # 20
    case_tt_course_not_found(),       # 21
]
