"""챗 골든 데이터셋 — 32 케이스.

각 케이스는 실제 관찰된 버그/설계 결정을 회귀 방지하는 assertion을 갖는다.

**로드맵 챗 (22)**:
- 01 정컴 신입 · 02 정컴 3학년(AI) · 03 경영 4학년(재무)
- 04 전자공학 3학년(반도체) · 05 기계 2학년(자동차)
- 06 SW연계전공 임베디드 (48학점) · 07 핀테크 융합전공 (42학점)
- 08 부전공 · 09 복수전공 · 15 부·복수 동시
- 10 엇학기 · 11 편입 · 12 전공기초 부족 · 13 1학기 전용 미수강
- 14 진로-전공 mismatch · 16 AI융합트랙
- 22 재수강 요청 · 23 선수과목 차단 · 24 학점 상한 swap
- 25 계절수업 제외 · 26 요청 범위 준수 · 27 범위 미지정 로드맵 요청

**시간표 챗 (10)**:
- 17 정컴 3학년 · 18 시간 제약 · 19 엇학기 · 20 부전공 · 21 못 찾음
- 28 선수과목 차단(시간표 버전) · 29 정확한 학점(credit_mode=exact)
- 30 복수전공 시간 충돌 회피 · 31 재수강은 조언만(강제 편성 X)
- 32 졸업위험(critical_missing) 재분류 — 카탈로그상 미개설이지만 실제 개설 중

**assertion 고르는 법** (2026-08 실측 기반):
- 데이터로 검증 가능하면 `custom` — 반환된 pending_changes/schedules를 직접 본다.
  문자열 매칭보다 항상 우선.
- 의미 판정이 필요하면 `llm_judge`. 판정 모델은 피검사 모델과 분리한다.
- `response_mentions`/`response_absent`는 **고유명사에만** 쓴다. 흔한 단어를 넣으면
  오탐이 난다 (구 case 18의 "화" → "최적화"·"변화"에 걸림).
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
    # 3학년까지 이수한 학생. 연도를 전부 "2025"로 두면 2학기치 기록밖에 없는 셈이 되고,
    # 마지막 이수가 2025-2라 엇학기로 잘못 잡힌다. 6학기(2024-2 ~ 2026-1)에 분산한다.
    _c2_courses = [
        ("컴퓨터프로그래밍(I)", "전공기초"), ("컴퓨터프로그래밍(II)", "전공기초"),
        ("이산수학", "전공기초"), ("자료구조", "전공필수"),
        ("알고리즘", "전공필수"), ("컴퓨터구조", "전공필수"),
        ("운영체제", "전공선택"), ("시스템프로그래밍", "전공선택"),
        ("데이터베이스", "전공선택"),
    ]
    _c2_terms = _terms_ending_at_last_completed(6)
    # 마지막 과목이 마지막 학기(2026-1)에 오도록 균등 분배한다.
    completed = [
        RecordSpec(raw_course_name=name, category=cat,
                   year=_c2_terms[i * (len(_c2_terms) - 1) // (len(_c2_courses) - 1)][0],
                   semester=_c2_terms[i * (len(_c2_terms) - 1) // (len(_c2_courses) - 1)][1],
                   grade="B+", grade_point=3.5)
        for i, (name, cat) in enumerate(_c2_courses)
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
                             reason="build_timetable(규칙 엔진)이 만든 조합이 최소 1개 나와야 함"),
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


def _no_afternoon_offering_in_schedules(result) -> str | None:
    """case 18 전용: 반환된 조합에 제약 위반 offering(6003, 화·목 14:00)이 있는지 검사."""
    for s in result.schedules:
        if _TT_AFTERNOON_OFFERING_ID in (s.get("offering_ids") or []):
            return (
                f"사용자 제약('월수 오전만') 위반: 화·목 오후 offering "
                f"{_TT_AFTERNOON_OFFERING_ID}가 조합에 포함됨 — {s}"
            )
    return None


# case 18에서 "걸러져야 하는" offering. 검사 함수와 시드가 같은 상수를 보게 묶어둔다.
_TT_AFTERNOON_OFFERING_ID = 6003


def case_tt_time_constraint() -> EvalCase:
    """18: 시간표에 시간 제약 ('월수금 오전만'). 사용자 제약 반영."""
    # 정컴 3학년 시나리오 재사용하되 offering을 시간대별로 다양화.
    depts, majors = _cs_hierarchy()
    offerings = [
        # 오전 후보 2개 (제약 부합, 서로 시간 안 겹침).
        # course_id는 반드시 카탈로그상 이 학기(2학기) 개설 과목이어야 한다 —
        # list_offered_courses가 semester 필터로 먼저 거르기 때문에, 1학기 과목에 2학기
        # offering을 달아두면 후보에 아예 안 잡힌다. 예전엔 6002가 인공지능(1024, 1학기)에
        # 붙어 있어서 오전 후보가 사실상 1개뿐이었다.
        OfferingSpec(id=6001, course_id=1022, year="2026", semester="2학기",  # 데이터베이스(2학기)
                     times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
        OfferingSpec(id=6002, course_id=1023, year="2026", semester="2학기",  # 컴퓨터네트워크(2학기)
                     times=[("월", "10:30", "12:00"), ("수", "10:30", "12:00")]),
        # 오후 후보 (제약 위반 — 걸러야 함)
        OfferingSpec(id=_TT_AFTERNOON_OFFERING_ID, course_id=1025, year="2026", semester="2학기",
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
            ExpectedBehavior("tool_called", "build_timetable",
                             reason="후보 조합 구성·검증 없이 답변하면 안 됨. 조합 구성은 이제 "
                                    "규칙 엔진(build_timetable)이 하고, validate_timetable은 "
                                    "사용자가 특정 조합을 콕 집어 물을 때만 쓴다"),
            ExpectedBehavior("schedules_count", (">=", 1),
                             reason="6001·6002는 시간이 안 겹쳐 제약 안에서 조합이 나와야 정상. "
                                    "이게 없으면 아래 custom이 빈 결과로 공허하게 통과한다"),
            ExpectedBehavior("custom", _no_afternoon_offering_in_schedules,
                             reason="구 assertion은 response_absent '화'였는데 '최적화'·'변화' 같은 "
                                    "평범한 단어에 걸려 정상 응답을 fail 처리하는 오탐이었다. "
                                    "답변 텍스트 대신 반환된 조합 데이터로 제약 위반을 검사한다"),
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
            # 마지막 이수가 2026-1이어야 정상 재학생으로 잡힌다 (엇학기 판정 기준).
            RecordSpec(raw_course_name=n, category=cat, year=y, semester=sem,
                       grade="B+", grade_point=3.5)
            for (n, cat), (y, sem) in zip(
                [("회계원리", "전공필수"), ("재무관리", "전공필수"), ("투자론", "전공선택")],
                _terms_ending_at_last_completed(3),
            )
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
            RecordSpec(raw_course_name=n, category="전공필수", year=y, semester=sem,
                       grade="B+", grade_point=3.5)
            for n, (y, sem) in zip(["회로이론", "전자회로"],
                                    _terms_ending_at_last_completed(2))
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
        # 이수 기록이 하나도 없으면 `critical_missing_required`에 2학기 전용 필수가 줄줄이
        # 잡혀서 그 졸업 위험 경고가 답변을 통째로 차지한다 — 정작 검증하려는 48학점 연계전공
        # 안내까지 못 간다(2026-08-14 실측: 3회 모두 그랬다). 애초에 48학점 다전공을 이수
        # 중인데 아무것도 안 들은 학생은 앞뒤가 안 맞기도 하다.
        records=_cs_lower_year_records(),
        roadmap_items=[
            RoadmapItemSpec(course_name=r.raw_course_name, planned_grade=g, status="completed")
            for r, g in zip(_cs_lower_year_records(), [1, 1, 1, 2, 2, 2])
        ],
    )
    return EvalCase(
        slug="06-sw-embed", persona=persona, agent="roadmap",
        prompt="SW연계전공 임베디드 하고 있어요. 지금까지 뭐 들었고 뭐가 남았어요?",
        expectations=[
            ExpectedBehavior("tool_called", "get_graduation_progress",
                             reason="주전공 + 연계전공 진도 둘 다 필요"),
            ExpectedBehavior(
                "llm_judge",
                "다음 두 조건을 **모두** 만족하면 pass, 하나라도 어기면 fail:\n"
                "(a) 임베디드SW 연계전공의 요구 학점이 **48학점**임을 밝혔다 "
                "(\"48학점 중 N학점 이수\"·\"48학점까지 N학점 남음\" 같은 표현도 인정).\n"
                "(b) 그 프로그램의 요구 학점을 21학점이라고 하거나 'SW융합트랙'이라고 "
                "부르지 않았다.\n"
                "**참고**: 프로그램을 '부전공'·'다전공'처럼 다르게 불렀더라도 48학점을 "
                "정확히 안내했으면 (a)를 만족한 것으로 본다 — 명칭 정확도는 별도 관심사다. "
                "주전공(133학점) 진도를 함께 안내한 것도 감점 사유가 아니다.",
                reason="트랙(21학점) vs 정식 연계전공(48학점) 구분. 기준이 애매하면 "
                       "정당한 답변도 fail 처리된다 — 무엇이 pass/fail인지 명시한다",
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
        # 6개 학기를 이수한 상태여야 다음 학기가 커리큘럼상 4학년 2학기가 된다.
        # 기록이 4학기치면 도구가 "3학년 2학기"라고 알려주는데, 프롬프트의 "4학년"과
        # 어긋나서 LLM이 모순된 컨텍스트를 받는다 (2026-08-14 관측).
        # 컴퓨터구조는 일부러 빼둔다 — 이 케이스가 검증하는 critical_missing 대상이다.
        records=[
            RecordSpec(raw_course_name=n, category=cat, year=y, semester=sem,
                       grade="B+", grade_point=3.5)
            for (n, cat), (y, sem) in zip(
                [("컴퓨터프로그래밍(I)", "전공기초"), ("자료구조", "전공필수"),
                 ("알고리즘", "전공필수"), ("운영체제", "전공선택"),
                 ("고전읽기와토론", "교양필수"), ("과학과기술", "교양선택")],
                _terms_ending_at_last_completed(6),
            )
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name=n, planned_grade=g, status="completed")
            for n, g in [("컴퓨터프로그래밍(I)", 1), ("자료구조", 2),
                          ("알고리즘", 2), ("운영체제", 3)]
        ],
    )
    return EvalCase(
        slug="13-last-sem-gap", persona=persona, agent="roadmap",
        prompt="이제 4학년인데 다음 학기 뭐 들어야 졸업할 수 있어요?",
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
            ExpectedBehavior(
                "custom",
                lambda r: None if 6502 in _schedule_offering_ids(r)
                else f"부전공(전자) 필수과목 회로이론(offering 6502)이 조합에 없음: {r.schedules}",
                reason="tool_called/schedules_count만으로는 '부전공 학과 과목을 넓게 "
                       "검색했다'와 '실제로 부전공 필수과목을 채워 넣었다'를 구분 못 한다 "
                       "— 부전공 필수(special_rules.groups)로 지정한 회로이론이 실제로 "
                       "조합에 들어갔는지까지 확인해야 이 케이스의 이름값(부전공 필수과목 "
                       "우선 검증)에 맞는다.",
            ),
        ],
    )


# --- 3차 배치: 도구 자동 판정 필드 · 가드 커버리지 -------------------------
#
# 기존 21 케이스는 `critical_missing_required`(13)만 검증하고 있었고, 나머지 자동 판정
# 필드 2종(`retake_candidates`, `prereq_blocked`)과 도구 단 가드 2종(학기당 학점 상한,
# 계절수업 제외), 그리고 "요청 범위를 넘는 제안 남발 방지" 규칙은 골든 데이터셋에
# 회귀 방지 장치가 아예 없었다. 프롬프트를 손댈 때 조용히 깨져도 아무도 모르는 상태라
# 여기서 채운다.


def _pending_has_course(result, course_id: int) -> bool:
    return any(c.get("course_id") == course_id for c in result.pending_changes)


# --- 이수 기록 연도 기준 -----------------------------------------------------
#
# 평가 실행은 `_current_academic_term`을 (2026, 2)로 고정한다. 그러면:
#   - 지금 진행 중인 학기 = 2026-2
#   - **정상적으로 다니고 있는 학생이 마지막으로 "이수 완료"한 학기 = 2026-1**
#   - 다음 배치 가능 학기 = 2027-1
#
# 엇학기 판정은 "마지막 이수 학기와 현재 학기 사이에 공백이 있는가"로 한다. 그래서
# 정상 학생 페르소나의 이수 기록이 2025-1에서 끊겨 있으면 **전부 엇학기로 잡힌다.**
# 실제로 그런 상태였다 — 케이스 02·03·04·13·22·23과 `_cs_lower_year_records`가
# 2025-1 또는 2025-2에서 끝나 있었다.
#
# 그래서 정상 학생 페르소나는 이 헬퍼로 **2026-1에서 끝나도록 역순 배치**한다.
# 엇학기를 의도한 케이스(10·19)만 예외로 과거에서 끊어둔다.

_EVAL_CURRENT_TERM = (2026, 2)          # run_live가 패치하는 값
_LAST_COMPLETED_TERM = (2026, 1)        # 정상 학생이 마지막으로 이수 완료한 학기


def _terms_ending_at_last_completed(count: int) -> list[tuple[str, str]]:
    """마지막 이수 학기(2026-1)에서 거꾸로 `count`개 학기를 만든다 (오름차순).

    예: count=3 → [("2025", "1학기"), ("2025", "2학기"), ("2026", "1학기")]
    """
    year, sem = _LAST_COMPLETED_TERM
    terms: list[tuple[str, str]] = []
    for _ in range(count):
        terms.append((str(year), f"{sem}학기"))
        sem -= 1
        if sem == 0:
            sem = 2
            year -= 1
    return list(reversed(terms))


def _cs_lower_year_records() -> list[RecordSpec]:
    """정컴 1·2학년 전공기초·전공필수를 전부 이수한 상태.

    이걸 안 깔면 `critical_missing_required`에 2학기 전용 미이수 과목(컴퓨터프로그래밍(II)·
    이산수학·알고리즘·컴퓨터구조)이 줄줄이 잡혀서, 그 졸업 위험 경고가 답변을 지배한다 —
    정작 검증하려는 행동(학점 상한 대응, 계절수업 제외, 요청 범위 준수)이 노이즈에 묻힌다.
    """
    courses = [
        ("컴퓨터프로그래밍(I)", "전공기초"),
        ("컴퓨터프로그래밍(II)", "전공기초"),
        ("이산수학", "전공기초"),
        ("자료구조", "전공필수"),
        ("알고리즘", "전공필수"),
        ("컴퓨터구조", "전공필수"),
    ]
    # 6과목을 6개 학기에 하나씩 — 2024-2 ~ 2026-1. 마지막이 2026-1이라 엇학기로 안 잡힌다.
    terms = _terms_ending_at_last_completed(len(courses))
    return [
        RecordSpec(raw_course_name=n, category=cat, year=y, semester=sem,
                   grade="B+", grade_point=3.5)
        for (n, cat), (y, sem) in zip(courses, terms)
    ]


def case_retake_request() -> EvalCase:
    """22: C0 받은 과목을 학생이 콕 집어 재수강 요청. is_retake 우회 흐름 검증.

    `retake_candidates`(grade_point ≤ 2.5) 노출 → 명시 요청 → propose_change(is_retake=True).
    is_retake 없이 create하면 completed_courses_guard가 막으므로, pending change가 실제로
    생겼다는 것 자체가 우회 플래그를 제대로 넘겼다는 증거가 된다.
    """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="retake-request", label="정컴 3학년 · 자료구조 C0 재수강 요청",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=_cs_catalog(),
        # 자료구조만 C0(2.0) — 재수강 후보. 나머지는 B0 이상이라 후보 아님.
        # 연도는 2026-1에서 끝나야 정상 재학생으로 잡힌다 (엇학기 판정 기준).
        records=[
            RecordSpec(raw_course_name=n, category=cat, year=y, semester=sem,
                       grade=g, grade_point=gp)
            for (n, cat, g, gp), (y, sem) in zip(
                [("컴퓨터프로그래밍(I)", "전공기초", "B+", 3.5),
                 ("컴퓨터프로그래밍(II)", "전공기초", "A0", 4.0),
                 ("자료구조", "전공필수", "C0", 2.0),
                 ("알고리즘", "전공필수", "B0", 3.0)],
                _terms_ending_at_last_completed(4),
            )
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name=n, planned_grade=g, status="completed")
            for n, g in [("컴퓨터프로그래밍(I)", 1), ("컴퓨터프로그래밍(II)", 1),
                          ("자료구조", 2), ("알고리즘", 2)]
        ],
    )
    return EvalCase(
        slug="22-retake-request", persona=persona, agent="roadmap",
        prompt="자료구조 C0 받아서 다시 듣고 싶어요. 다음 학기에 재수강으로 넣어주세요.",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="retake_candidates는 이 도구로만 확인 — 자격 확인 없이 넣으면 안 됨"),
            ExpectedBehavior("tool_called", "propose_change",
                             reason="명시 요청이므로 안내만 하지 말고 실제 제안까지 가야 함"),
            ExpectedBehavior(
                "custom",
                lambda r: None if _pending_has_course(r, 1010)
                else f"자료구조(1010) 재수강 제안이 없음. pending: {r.pending_changes}",
                reason="is_retake=True를 안 넘기면 도구가 거절해 pending이 비게 된다 — "
                       "제안이 생겼다는 것 자체가 우회 플래그 정상 사용의 증거",
            ),
        ],
    )


def case_prereq_blocked_request() -> EvalCase:
    """23: 선수과목(자료구조) 미이수인데 학생이 운영체제를 담아달라고 요청.

    `prereq_blocked` 목록에 오른 과목은 create하지 말고 선수과목을 먼저 안내해야 한다.
    """
    depts, majors = _cs_hierarchy()
    catalog = [c for c in _cs_catalog() if c.course_name != "운영체제"] + [
        CourseSpec(id=1020, course_name="운영체제", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="1",
                   description="프로세스·메모리 관리를 다룬다. 선수과목: 자료구조"),
    ]
    persona = PersonaSpec(
        id="prereq-blocked", label="정컴 2학년 · 자료구조 미이수 상태로 운영체제 요청",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="시스템 프로그래밍",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2025")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2025", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=catalog,
        # 자료구조는 이수하지 않았다 — 그래서 운영체제가 prereq_blocked에 오른다.
        records=[
            RecordSpec(raw_course_name=n, category="전공기초", year=y, semester=sem,
                       grade=g, grade_point=gp)
            for (n, g, gp), (y, sem) in zip(
                [("컴퓨터프로그래밍(I)", "B0", 3.0), ("컴퓨터프로그래밍(II)", "B+", 3.5)],
                _terms_ending_at_last_completed(2),
            )
        ],
        roadmap_items=[
            RoadmapItemSpec(course_name="컴퓨터프로그래밍(I)", planned_grade=1, status="completed"),
            RoadmapItemSpec(course_name="컴퓨터프로그래밍(II)", planned_grade=1, status="completed"),
        ],
    )
    return EvalCase(
        slug="23-prereq-blocked", persona=persona, agent="roadmap",
        prompt="다음 학기에 운영체제 담고 싶어요. 넣어주세요.",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="prereq_blocked는 이 도구 응답에만 있음"),
            ExpectedBehavior(
                "custom",
                lambda r: (f"선수과목 미이수인 운영체제(1020)를 그대로 create 제안함: "
                           f"{r.pending_changes}") if _pending_has_course(r, 1020) else None,
                reason="prereq_blocked 항목은 create 금지 — 안내로 끝내야 한다",
            ),
            ExpectedBehavior(
                "llm_judge",
                "운영체제를 바로 넣어주는 대신, 선수과목인 '자료구조'가 아직 미이수라는 점을 "
                "근거로 들어 자료구조를 먼저 들으라고 안내했는가? 선수과목 얘기 없이 그냥 "
                "운영체제를 추천했거나, 아무 설명 없이 거절만 했으면 fail.",
                reason="차단 사실뿐 아니라 '무엇을 먼저 들어야 하는지'까지 알려야 실용적",
            ),
        ],
    )


def case_credit_cap_swap() -> EvalCase:
    """24: 다음 학기가 이미 학점 상한(21) 가까이 찬 상태에서 과목 추가 요청.

    도구가 상한 초과 create를 거절하면서 `current_items_in_term`·`hint`를 돌려주는데,
    LLM이 그걸 받아 '무엇을 빼고 무엇을 넣을지' 대체안을 제시해야 한다. 그냥 "안 된다"로
    끝내거나 상한을 무시하고 우겨넣으면 회귀.
    """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="credit-cap-swap", label="정컴 3학년 · 다음 학기 18학점 이미 계획됨",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="AI 엔지니어",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,  # → 상한 21학점
            required_major_required=30, required_major_elective=27,
        )],
        # 추가 요청 대상은 다음 학기(1학기) 개설이면서 아직 계획·이수 안 된 과목이어야
        # 한다 — 안 그러면 LLM이 학점 상한이 아니라 "개설 학기가 안 맞아서" 거절해서
        # 이 케이스가 검증하려는 것과 다른 이유로 통과해버린다.
        courses=_cs_catalog() + [
            CourseSpec(id=1030, course_name="클라우드컴퓨팅", department_id=DEPT_CS,
                       major_id=MAJOR_CS, category="전공선택", credits=3,
                       year="4", semester="1"),
        ],
        records=_cs_lower_year_records(),
        # 다음 배치 학기(2027-1학기)에 이미 21학점 = 상한 정각. 3학점을 더 넣으면 24로
        # 초과라 도구가 거절한다. (구 버전은 18학점이라 +3 = 21 정각이어서 가드가 아예
        # 안 걸렸다 — 상한 초과는 `>` 비교다.)
        roadmap_items=[
            RoadmapItemSpec(course_name=n, course_id=cid, credits=3.0,
                            planned_grade=4, planned_year="2027", planned_semester="1학기",
                            category="전공선택")
            for n, cid in [("운영체제", 1020), ("시스템프로그래밍", 1021),
                            ("데이터베이스", 1022), ("컴퓨터네트워크", 1023),
                            ("인공지능", 1024), ("머신러닝", 1025)]
        ] + [
            # 7번째 항목. 교육과정표에 없는 자유 항목이라 개설 학기 정합성 문제를 안 만들면서
            # 학기 합계만 21로 채운다.
            RoadmapItemSpec(course_name="공학경제", credits=3.0, planned_grade=4,
                            planned_year="2027", planned_semester="1학기",
                            category="전공선택"),
        ],
    )
    return EvalCase(
        slug="24-credit-cap-swap", persona=persona, agent="roadmap",
        prompt="다음 학기에 클라우드컴퓨팅도 추가로 넣어주세요.",
        expectations=[
            ExpectedBehavior("tool_called", "get_roadmap_items",
                             reason="term_credit_cap·planned_credits_by_term 확인 없이 추가하면 안 됨"),
            ExpectedBehavior(
                "llm_judge",
                "다음 학기가 이미 학점 상한(21학점)에 차 있다는 사실을 사용자에게 알리고, "
                "기존 항목 중 무엇을 빼거나 다른 학기로 옮기면 되는지 구체적인 대체안을 "
                "제시했는가? 상한 얘기 없이 그냥 넣었다고 하거나, '불가능하다'로만 끝내고 "
                "대안을 안 준 경우는 fail.",
                reason="상한 초과 에러의 current_items_in_term·hint를 실제로 활용하는지",
            ),
        ],
    )


def case_seasonal_course_excluded() -> EvalCase:
    """25: 카탈로그에 계절수업 전용 과목이 섞여 있을 때 정규 학기 추천에서 빠지는지.

    도구 단 가드(`_is_session_only_course_semester`)는 propose_change를 거절하지만,
    LLM이 finish_response에서 그 과목을 추천하는 것까지는 못 막는다 — 프롬프트 규칙이
    지켜지는지 여기서 본다.
    """
    depts, majors = _cs_hierarchy()
    catalog = _cs_catalog() + [
        CourseSpec(id=1099, course_name="로보틱스AI PBL", department_id=DEPT_CS,
                   major_id=MAJOR_CS, category="전공선택", credits=3,
                   year="3", semester="여름계절수업"),
    ]
    persona = PersonaSpec(
        id="seasonal-excluded", label="정컴 3학년 · 계절수업 전용 과목 혼재",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="AI 로보틱스",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=catalog,
        records=_cs_lower_year_records(),
        roadmap_items=[
            RoadmapItemSpec(course_name=r.raw_course_name, planned_grade=g, status="completed")
            for r, g in zip(_cs_lower_year_records(), [1, 1, 1, 2, 2, 2])
        ],
    )
    return EvalCase(
        slug="25-seasonal-excluded", persona=persona, agent="roadmap",
        prompt="다음 정규 학기에 들을 과목 추천해주세요. 로보틱스 쪽에 관심 있어요.",
        expectations=[
            ExpectedBehavior("tool_called", "search_courses"),
            ExpectedBehavior(
                "custom",
                lambda r: (f"계절수업 전용 과목(1099)을 정규 학기에 제안함: {r.pending_changes}")
                if _pending_has_course(r, 1099) else None,
                reason="도구가 거절하므로 pending에 남으면 안 된다 — 남았다면 가드 회귀",
            ),
            ExpectedBehavior(
                "response_absent", "로보틱스AI PBL",
                reason="정규 학기 추천 요청에 계절수업 전용 과목을 언급하면 사용자가 신청 "
                       "가능한 걸로 오해한다. 과목명이 고유해서 문자열 매칭 오탐 위험이 낮다",
            ),
        ],
    )


def case_scope_discipline() -> EvalCase:
    """26: 항목 하나만 옮겨달라는 좁은 요청에 제안을 남발하지 않는지.

    관측된 실패: 범위 좁은 요청인데 묻지도 않은 과목을 추가로 제안하느라 턴을 다 써서
    finish_response를 못 부르고 폴백 요약으로 끝난 사례.
    """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="scope-discipline", label="정컴 3학년 · 항목 1개 이동 요청",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=_cs_catalog(),
        records=_cs_lower_year_records(),
        roadmap_items=[
            RoadmapItemSpec(course_name="데이터베이스", course_id=1022, credits=3.0,
                            planned_grade=4, planned_year="2027", planned_semester="1학기",
                            category="전공선택"),
            RoadmapItemSpec(course_name="컴퓨터네트워크", course_id=1023, credits=3.0,
                            planned_grade=4, planned_year="2027", planned_semester="1학기",
                            category="전공선택"),
        ],
    )
    return EvalCase(
        slug="26-scope-discipline", persona=persona, agent="roadmap",
        prompt="로드맵에 있는 데이터베이스를 4학년 2학기로 옮겨주세요. 그것만요.",
        expectations=[
            ExpectedBehavior("tool_called", "propose_change",
                             reason="요청한 이동은 실제로 제안해야 함"),
            ExpectedBehavior("tool_called", "finish_response",
                             reason="좁은 요청은 턴을 다 쓰지 않고 정상 종료해야 한다 "
                                    "(폴백 요약으로 끝나면 finished=False)"),
            ExpectedBehavior("pending_change_count", ("<=", 1),
                             reason="'그것만'이라고 못박은 요청에 추가 제안을 끼워넣으면 안 된다"),
        ],
    )


def case_unscoped_roadmap_request() -> EvalCase:
    """27: "성장 로드맵 만들어줘"처럼 범위(다음 학기 vs 졸업까지)를 안 밝힌 요청.

    2026-08-23 추가. 다음 학기 하나만 제안하고 "승인해주시면 이어서"로 끝내던
    문제(PR #194)를 반대쪽에서도 잘못 고치지 않기 위한 케이스 — 범위가 정해지지
    않았는데 매번 다음 학기 하나만 조용히 골라 진행하면, 사실 졸업까지 전체를 원한
    사용자는 매번 "이어서 해달라"고 다시 요청해야 한다. 범위 자체를 모를 때는
    제안부터 만들지 말고 먼저 되물어야 한다(`unscoped_build_request` 규칙).
    """
    depts, majors = _cs_hierarchy()
    persona = PersonaSpec(
        id="unscoped-roadmap", label="정컴 신입 1학년 · 범위 미지정 로드맵 요청",
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
        slug="27-unscoped-roadmap-request", persona=persona, agent="roadmap",
        prompt="성장 로드맵 만들어주세요.",
        expectations=[
            ExpectedBehavior("tool_not_called", "propose_change",
                             reason="범위를 모르는 채로 바로 제안부터 만들면 안 된다"),
            ExpectedBehavior("tool_not_called", "propose_term_plan",
                             reason="범위를 모르는 채로 바로 전체 계획부터 만들면 안 된다"),
            ExpectedBehavior(
                "llm_judge",
                "응답이 '졸업까지 전체 학기'로 계획할지 '다음 학기만' 계획할지 "
                "사용자에게 명확히 되묻는가? (둘 중 하나를 이미 확정해서 계획을 "
                "만들어버렸다면 No)",
                reason="범위 미지정 요청은 바로 만들지 말고 먼저 범위를 확인해야 한다",
            ),
        ],
    )


def _schedule_offering_ids(result) -> set[int]:
    ids: set[int] = set()
    for s in result.schedules:
        ids.update(s.get("offering_ids") or [])
    return ids


def case_tt_prereq_blocked() -> EvalCase:
    """28: 시간표 챗 버전 선수과목 차단. 로드맵 챗(23)과 같은 페르소나 패턴을
    시간표 에이전트로 재현 — prereq_blocked가 로드맵/시간표 양쪽에서 똑같이
    지켜지는지 별도로 확인한다(공유 헬퍼 `_compute_prereq_blocked`를 쓰지만,
    실제로 반영하는 경로는 도구 스키마가 다른 별개 에이전트라 따로 검증 필요)."""
    depts, majors = _cs_hierarchy()
    catalog = [c for c in _cs_catalog() if c.course_name != "운영체제"] + [
        CourseSpec(id=1020, course_name="운영체제", department_id=DEPT_CS, major_id=MAJOR_CS,
                   category="전공선택", credits=3, year="3", semester="1",
                   description="프로세스·메모리 관리를 다룬다. 선수과목: 자료구조"),
    ]
    offerings = [
        OfferingSpec(id=7001, course_id=1020, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30"), ("수", "09:00", "10:30")]),
        OfferingSpec(id=7002, course_id=1023, year="2026", semester="2학기",  # 컴퓨터네트워크
                     times=[("화", "13:00", "14:30"), ("목", "13:00", "14:30")]),
    ]
    persona = PersonaSpec(
        id="tt-prereq-blocked", label="시간표: 자료구조 미이수 상태로 운영체제 요청",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="시스템 프로그래밍",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2025")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2025", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=catalog,
        # 자료구조는 이수하지 않았다 — 그래서 운영체제가 prereq_blocked에 오른다.
        records=[
            RecordSpec(raw_course_name=n, category="전공기초", year=y, semester=sem,
                       grade=g, grade_point=gp)
            for (n, g, gp), (y, sem) in zip(
                [("컴퓨터프로그래밍(I)", "B0", 3.0), ("컴퓨터프로그래밍(II)", "B+", 3.5)],
                _terms_ending_at_last_completed(2),
            )
        ],
        offerings=offerings,
    )
    return EvalCase(
        slug="28-tt-prereq-blocked", persona=persona, agent="timetable",
        prompt="이번 학기 시간표 짜주세요. 운영체제도 꼭 넣어주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "get_student_context",
                             reason="prereq_blocked는 이 도구 응답에만 있음"),
            ExpectedBehavior(
                "custom",
                lambda r: (f"선수과목 미이수인 운영체제(offering 7001)가 조합에 포함됨: "
                           f"{r.schedules}") if 7001 in _schedule_offering_ids(r) else None,
                reason="prereq_blocked 과목의 offering은 build_timetable 후보에서 "
                       "빠져야 한다 — 로드맵 챗의 create 금지와 동등한 시간표 챗 버전",
            ),
            ExpectedBehavior(
                "llm_judge",
                "운영체제를 바로 넣어주는 대신, 선수과목인 '자료구조'가 아직 미이수라는 점을 "
                "이유로 들어 이번 학기엔 담을 수 없다고 안내했는가? 선수과목 얘기 없이 "
                "그냥 운영체제를 시간표에 넣었으면 fail.",
                reason="시간표에서 조용히 빠지기만 하고 이유를 설명 안 하면 사용자는 버그로 오인한다",
            ),
        ],
    )


def case_tt_exact_credits() -> EvalCase:
    """29: '정확히 15학점만' — build_timetable(credit_mode='exact')이 실제로
    쓰이고, 반환된 조합의 학점 합계가 정확히 목표와 일치하는지.

    카탈로그가 전부 3학점이라 5과목 = 15학점으로 정확히 맞아떨어지게 설계했다 —
    안 맞는 조합이 나오면 credit_mode를 안 썼거나(at_least로 더 채움) 엔진이
    잘못 계산한 것이다."""
    depts, majors = _cs_hierarchy()
    # 서로 안 겹치는 5개 분반. 5×3=15로 정확히 채워지려면 이 5개가 전부 들어가야 한다.
    offerings = [
        OfferingSpec(id=8001, course_id=1020, year="2026", semester="1학기",  # 운영체제
                     times=[("월", "09:00", "10:30")]),
        OfferingSpec(id=8002, course_id=1021, year="2026", semester="1학기",  # 시스템프로그래밍
                     times=[("월", "10:30", "12:00")]),
        OfferingSpec(id=8003, course_id=1024, year="2026", semester="1학기",  # 인공지능
                     times=[("화", "09:00", "10:30")]),
        OfferingSpec(id=8004, course_id=1010, year="2026", semester="1학기",  # 자료구조
                     times=[("화", "10:30", "12:00")]),
        OfferingSpec(id=8005, course_id=1011, year="2026", semester="1학기",  # 알고리즘
                     times=[("수", "09:00", "10:30")]),
    ]
    persona = PersonaSpec(
        id="tt-exact-credits", label="시간표: 정확히 15학점만",
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
        )],
        courses=_cs_catalog(), offerings=offerings,
    )
    return EvalCase(
        slug="29-tt-exact-credits", persona=persona, agent="timetable",
        timetable_year="2026", timetable_semester="1학기",
        prompt="이번 학기 시간표 정확히 15학점만 짜주세요. 더도 덜도 말고요.",
        expectations=[
            ExpectedBehavior("tool_called", "build_timetable",
                             reason="숫자를 콕 집었으니 credit_mode='exact'로 호출해야 함"),
            ExpectedBehavior("schedules_count", (">=", 1),
                             reason="5개 분반이 전혀 안 겹치니 조합이 반드시 나와야 함"),
            ExpectedBehavior(
                "custom",
                lambda r: (
                    None
                    if any(
                        c.get("name") == "build_timetable"
                        and (c.get("args") or {}).get("credit_mode") == "exact"
                        for c in r.tool_calls
                    )
                    else f"build_timetable 호출에 credit_mode='exact'가 없음: {r.tool_calls}"
                ),
                reason="'정확히 15학점'처럼 숫자를 콕 집으면 exact를 써야 한다는 "
                       "도구 스키마 지침이 실제로 지켜지는지",
            ),
            ExpectedBehavior(
                "custom",
                lambda r: (
                    None
                    if not r.schedules
                    or sum(
                        3.0 for oid in (r.schedules[0].get("offering_ids") or [])
                    ) == 15.0
                    else f"첫 조합 학점 합계가 15가 아님: {r.schedules[0]}"
                ),
                reason="카탈로그가 전부 3학점이라 조합 학점 합계는 offering 개수*3 — "
                       "정확히 15가 아니면 exact 모드가 목표를 못 맞춘 것",
            ),
        ],
    )


# --- 4차 배치: 시간표 챗 커버리지 확장 -------------------------------------
#
# PR #209 Q&A에서 명시적으로 남긴 후속 과제 3개 — 복수전공 시간 충돌, 재수강(시간표
# 버전), 졸업위험(critical_missing) — 를 채운다. 로드맵 챗엔 이미 대응하는 케이스가
# 있지만(09 dual, 22 retake, 13 critical_missing), 시간표 챗은 도구 스키마가 달라서
# (build_timetable에는 propose_change의 is_retake 같은 우회 플래그가 아예 없음, 조건부
# 규칙도 별도 파일) 같은 로직이라도 따로 검증해야 실제로 지켜지는지 알 수 있다.


def case_tt_dual_major_conflict() -> EvalCase:
    """30: 복수전공(수학과) 시간표. 주전공 필수(자료구조)와 복수전공 필수(해석학)
    분반이 완전히 같은 시간대라 반드시 충돌한다.

    시간 충돌 회피 자체는 프로그램 구분 없이 동작하는 일반 규칙이지만, 지금까지
    골든셋의 유일한 dual 케이스(09)는 로드맵 챗이라 "복수전공 두 학과 과목이 동시에
    후보 풀에 들어왔을 때도 충돌 회피가 정상 동작하는가"는 실측된 적이 없다."""
    depts, majors = _cs_hierarchy()
    depts = depts + [DepartmentSpec(id=DEPT_MATH, name="수학과", college_name="자연과학대학")]
    offerings = [
        # 자료구조(주전공 필수)와 해석학(복수전공 필수) — 월요일 같은 시간대라 충돌.
        OfferingSpec(id=9001, course_id=1010, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30")]),
        OfferingSpec(id=9002, course_id=4001, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30")]),
        # 안 겹치는 대안 하나씩 — 조합 자체는 나와야 한다.
        OfferingSpec(id=9003, course_id=1011, year="2026", semester="2학기",  # 알고리즘
                     times=[("화", "09:00", "10:30")]),
        OfferingSpec(id=9004, course_id=4002, year="2026", semester="2학기",  # 선형대수학
                     times=[("수", "09:00", "10:30")]),
    ]
    persona = PersonaSpec(
        id="tt-dual-conflict", label="시간표: 정컴+수학과 dual, 필수과목 시간 충돌",
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
                            required_total_credits=133, required_major_required=30),
            RequirementSpec(department_id=DEPT_MATH, program_type="dual",
                            curriculum_year="2024", required_total_credits=36,
                            required_major_required=18),
        ],
        courses=_cs_catalog() + [
            CourseSpec(id=4001, course_name="해석학", department_id=DEPT_MATH,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=4002, course_name="선형대수학", department_id=DEPT_MATH,
                       category="전공필수", credits=3, year="2", semester="1"),
        ],
        offerings=offerings,
    )
    return EvalCase(
        slug="30-tt-dual-major-conflict", persona=persona, agent="timetable",
        prompt="정컴 주전공이랑 수학과 복수전공 둘 다 이번 학기 필수과목 넣어서 시간표 짜주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior("tool_called", "build_timetable"),
            ExpectedBehavior("schedules_count", (">=", 1),
                             reason="안 겹치는 대안이 있으니 조합 자체는 나와야 함"),
            ExpectedBehavior(
                "custom",
                lambda r: next(
                    (f"자료구조(9001)·해석학(9002)이 같은 조합에 동시에 들어감: {s}"
                     for s in r.schedules
                     if {9001, 9002} <= set(s.get("offering_ids") or [])),
                    None,
                ),
                reason="주전공·복수전공 필수과목이라도 시간이 겹치면 같은 조합에 "
                       "동시에 들어가면 안 된다 — 프로그램 구분 없이 충돌 회피가 "
                       "지켜지는지가 이 케이스의 핵심",
            ),
        ],
    )


def case_tt_retake_advisory_only() -> EvalCase:
    """31: 자료구조 C0로 재수강 후보인 학생이 "재수강하면 뭐가 좋을지" 직접 질문.

    로드맵 챗은 propose_change(is_retake=True)로 재수강을 실제 반영하는 우회 경로가
    있지만, 시간표 챗의 build_timetable에는 그런 플래그가 아예 없다(설계 의도:
    "재수강은 별도 신청 절차" — timetable_chat.py 조건부 규칙 retake_candidates 참고).
    즉 시간표 챗은 **조언만 하고 실제 시간표에 강제로 넣으면 안 된다** — 이미 이수한
    과목은 build_timetable 필터에서 무조건 빠지므로(우회 불가), 조언은 하되 시간표에
    안 들어가는 게 정상 동작이다. 이걸 실측한 적이 없었다."""
    depts, majors = _cs_hierarchy()
    offerings = [
        # 자료구조 분반이 이번 학기에도 있다 — 그래도 이미 이수했으니 빠져야 정상.
        OfferingSpec(id=9101, course_id=1010, year="2026", semester="2학기",
                     times=[("월", "09:00", "10:30")]),
        OfferingSpec(id=9102, course_id=1021, year="2026", semester="2학기",  # 시스템프로그래밍
                     times=[("화", "09:00", "10:30")]),
    ]
    persona = PersonaSpec(
        id="tt-retake-advisory", label="시간표: 자료구조 C0 · 재수강 후보 조언 요청",
        departments=depts, majors=majors,
        department_id=DEPT_CS, major_id=MAJOR_CS,
        career_goal="백엔드 개발자",
        programs=[ProgramSpec(department_id=DEPT_CS, major_id=MAJOR_CS,
                              program_type="primary", curriculum_year="2024")],
        requirements=[RequirementSpec(
            department_id=DEPT_CS, major_id=MAJOR_CS, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
            required_major_required=30, required_major_elective=27,
        )],
        courses=_cs_catalog(),
        records=[
            RecordSpec(raw_course_name=n, category=cat, year=y, semester=sem,
                       grade=g, grade_point=gp)
            for (n, cat, g, gp), (y, sem) in zip(
                [("컴퓨터프로그래밍(I)", "전공기초", "B+", 3.5),
                 ("컴퓨터프로그래밍(II)", "전공기초", "A0", 4.0),
                 ("자료구조", "전공필수", "C0", 2.0),
                 ("알고리즘", "전공필수", "B0", 3.0)],
                _terms_ending_at_last_completed(4),
            )
        ],
        offerings=offerings,
    )
    return EvalCase(
        slug="31-tt-retake-advisory-only", persona=persona, agent="timetable",
        prompt="자료구조 C0 받았는데 재수강하면 학점 오르나요? 뭐 재수강하면 좋을지 알려주세요.",
        timetable_year="2026", timetable_semester="2학기",
        expectations=[
            ExpectedBehavior(
                "custom",
                lambda r: next(
                    (f"이미 이수한 자료구조(offering 9101)가 조합에 포함됨: {s}"
                     for s in r.schedules
                     if 9101 in (s.get("offering_ids") or [])),
                    None,
                ),
                reason="build_timetable엔 is_retake 우회가 없다 — 재수강 후보라도 "
                       "이미 이수한 과목은 무조건 빠져야 한다(설계 의도: 재수강은 "
                       "별도 신청 절차)",
            ),
            ExpectedBehavior(
                "llm_judge",
                "자료구조를 C0로 이수했다는 사실과 재수강 시 GPA 개선 가능성을 "
                "언급하며 조언했는가(구체적 학점 재계산 방식까지는 몰라도 됨)? "
                "재수강 얘기를 아예 안 했거나, 반대로 재수강 과목을 이번 학기 "
                "시간표에 그냥 넣어버렸으면 fail.",
                reason="'조언은 하되 강제로 편성하지 않는다'는 설계 의도가 응답에도 "
                       "드러나야 함",
            ),
        ],
    )


def case_tt_critical_missing_reclassified() -> EvalCase:
    """32: 컴퓨터구조(전공필수, 카탈로그 semester='2')를 미이수한 채 1학기 시간표를
    요청. 카탈로그만 보면 "1학기엔 개설 안 됨"이라 critical_missing_required에
    잡히지만, **실제로는 1학기에도 분반이 열려 있다** — `_critical_missing_split`이
    이런 경우를 `missing_required_offered_this_term`으로 재분류해서 오히려 1순위
    후보로 올려야 한다(반대로 조용히 "개설 안 됨"이라고 오판하면 진짜 버그).

    이 재분류 로직 자체가 실제 관측된 사고(공학작문및발표 사례, 코드 주석 참고)를
    고친 것인데 지금까지 골든셋에 회귀 방지 장치가 없었다.

    **관측된 신뢰도 (2026-08-24, gpt-5.4-nano, N=10)**: 8/10 통과. 백엔드 로직
    (`_critical_missing_split`)은 tool_calls 직접 검사로 재현한 결과 10/10 항상
    정확했다 — 실패 2건의 원인은 `list_offered_courses`를 필터 없이 넓게(예:
    `program_type=primary`만, query/category 없이) 호출했을 때 0건이 나오면 LLM이
    가끔 재검색 없이 바로 사용자에게 되묻고 끝내는 tool-use 전략의 비결정성이다
    (나머지 8건은 같은 0건 상황에서도 `query="컴퓨터구조"`로 좁혀 재검색해 항상
    9201을 찾음). 카탈로그가 이 케이스에서 의도적으로 극단적으로 얇아서(비교양
    과목이 1개뿐) 실제 서비스보다 이 경로를 더 자주 밟을 수 있다 — 실제 카탈로그
    규모에서 재현되는지는 확인 안 됨. 이 케이스를 지우거나 assertion을 느슨하게
    풀지 않고 그대로 둔다 — 검증하려는 대상(재분류 로직)은 실제로 100% 정확하고,
    남은 20% 실패는 "빈 검색 결과 시 재검색 유도" 프롬프트 개선 후보로 남긴다."""
    depts, majors = _cs_hierarchy()
    offerings = [
        # 컴퓨터구조: 카탈로그는 2학기 전용이라고 돼 있지만 1학기에도 실제 분반이 있다.
        OfferingSpec(id=9201, course_id=1012, year="2026", semester="1학기",
                     times=[("월", "09:00", "10:30")]),
    ]
    persona = PersonaSpec(
        id="tt-critical-reclassified", label="시간표: 컴퓨터구조 미이수, 1학기에도 실개설",
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
            CourseSpec(id=1010, course_name="자료구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="1"),
            CourseSpec(id=1011, course_name="알고리즘", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="2"),
            # 카탈로그상 2학기 전용 — 그래서 1학기 요청 시 critical_missing 후보가 된다.
            CourseSpec(id=1012, course_name="컴퓨터구조", department_id=DEPT_CS, major_id=MAJOR_CS,
                       category="전공필수", credits=3, year="2", semester="2"),
        ],
        # 컴퓨터구조만 미이수.
        records=[
            RecordSpec(raw_course_name=n, category="전공필수", year=y, semester=sem,
                       grade="B+", grade_point=3.5)
            for n, (y, sem) in zip(
                ["자료구조", "알고리즘"], _terms_ending_at_last_completed(2),
            )
        ],
        offerings=offerings,
    )
    return EvalCase(
        slug="32-tt-critical-missing-reclassified", persona=persona, agent="timetable",
        prompt="이번 학기 시간표 짜주세요.",
        timetable_year="2026", timetable_semester="1학기",
        expectations=[
            ExpectedBehavior("tool_called", "get_student_context",
                             reason="missing_required_offered_this_term 재분류는 이 도구 응답에만 있음"),
            ExpectedBehavior(
                "custom",
                lambda r: None if 9201 in _schedule_offering_ids(r)
                else (f"실제로 1학기에 개설 중인 미이수 필수 컴퓨터구조(offering 9201)가 "
                      f"후보에서 빠짐: {r.schedules}"),
                reason="카탈로그 권장학기(2학기)만 보고 '개설 안 됨'으로 오판하면 안 된다 — "
                       "실제 course_offerings 기준으로 재분류해서 1순위 후보에 올려야 함",
            ),
            ExpectedBehavior(
                "llm_judge",
                "컴퓨터구조가 미이수 필수 과목인데 이번 학기에 실제로 들을 수 있다는 "
                "점을 짚어주며 추천했는가? '이번 학기엔 개설 안 된다'고 잘못 말했으면 "
                "fail.",
                reason="재분류 로직의 목적 자체가 이 오판을 막는 것",
            ),
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
    # 도구 자동 판정 필드 · 가드 커버리지
    case_retake_request(),            # 22
    case_prereq_blocked_request(),    # 23
    case_credit_cap_swap(),           # 24
    case_seasonal_course_excluded(),  # 25
    case_scope_discipline(),          # 26
    case_unscoped_roadmap_request(),  # 27
    case_tt_prereq_blocked(),         # 28
    case_tt_exact_credits(),          # 29
    case_tt_dual_major_conflict(),    # 30
    case_tt_retake_advisory_only(),   # 31
    case_tt_critical_missing_reclassified(),  # 32
]
