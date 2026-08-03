"""Golden Data Set for the graduation requirements engine.

이 데이터는 `app/domains/academics/graduation_progress.compute_graduation_progress`
(flat `graduation_requirements` 테이블 기준)의 회귀 테스트용 시나리오다.

주의: 이 파일은 한때 `RequirementSet`/`RequirementCategory`/`RequirementCourse`
(팀원의 PR #59, 2026-07-10에 전체 철회됨) 기준으로 작성됐던 적이 있다. 그 스키마는
택N/M 필수과목, 타학과 과목 재분류, 최소전공 총학점 합산 같은 세부 규칙을 지원했지만
전부 삭제됐고, 지금 유일하게 남은 판정 로직은 이수구분(category)별 합계 학점만
단순 대조하는 flat 엔진이다 (`graduation_progress.py` 모듈 docstring 참고). 이 파일은
그 flat 엔진을 기준으로 다시 작성됐다 — 예전 시나리오(택1 필수과목, 최소전공 합산 등)는
지금 엔진이 아예 지원하지 않으므로 재현하지 않는다.

각 시나리오의 "programs"/"courses"는 run_golden_tests.py가 다음처럼 해석한다:
- programs[].department / major: run_golden_tests.py가 미리 만들어둔 마스터 데이터의
  학과명/전공명 키. 대응하는 department_id/major_id로 해석된다.
- courses[].category: StudentCourseRecord.category. 그대로 저장되고
  이수구분별 합계로만 집계된다 — course_id/학과 매칭은 현재 엔진에 없다.

"expected"는 program_type을 키로 하는 dict:
- requirement_found: 해당 학과/전공×이수유형에 대응하는 GraduationRequirement 행을
  찾았는지.
- satisfied: 총 이수학점이 required_total_credits 이상인지 (필드가 없으면 None).
- categories: {category_name: satisfied bool} — 명시된 카테고리만 검증한다.
- category_required_credits: {category_name: 기대하는 required_credits 값} — 특정
  기준학점 행이 선택됐는지(예: major_id 우선순위) 직접 검증할 때만 사용.
- warning_contains: warnings 리스트 중 하나가 이 문자열을 포함해야 함.
"""

GOLDEN_SCENARIOS = [
    {
        "scenario_id": "TC01_STANDARD_PASS",
        "description": "표준 주전공(컴퓨터공학과) 졸업 — 6개 카테고리 전부 정확히 충족",
        "programs": [
            {"type": "primary", "department": "컴퓨터공학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공기초", "credits": 9.0},
            {"category": "전공필수", "credits": 40.0},
            {"category": "전공선택", "credits": 30.0},
            {"category": "교양필수", "credits": 15.0},
            {"category": "교양선택", "credits": 20.0},
            {"category": "일반선택", "credits": 16.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "satisfied": True,
                "categories": {
                    "전공기초": True,
                    "전공필수": True,
                    "전공선택": True,
                    "교양필수": True,
                    "교양선택": True,
                    "일반선택": True,
                },
            },
        },
    },
    {
        "scenario_id": "TC02_CATEGORY_SHORTFALL",
        "description": "전공선택 학점만 미달 — 해당 카테고리와 총계가 함께 미충족으로 잡혀야 함",
        "programs": [
            {"type": "primary", "department": "컴퓨터공학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공기초", "credits": 9.0},
            {"category": "전공필수", "credits": 40.0},
            {"category": "전공선택", "credits": 20.0},  # 필요: 30, 이수: 20 (미달)
            {"category": "교양필수", "credits": 15.0},
            {"category": "교양선택", "credits": 20.0},
            {"category": "일반선택", "credits": 16.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "satisfied": False,
                "categories": {
                    "전공기초": True,
                    "전공필수": True,
                    "전공선택": False,
                    "교양필수": True,
                    "교양선택": True,
                    "일반선택": True,
                },
            },
        },
    },
    {
        "scenario_id": "TC03_MISSING_REQUIREMENT_ROW",
        "description": "요건 데이터 자체가 없는 학과×이수유형(컴퓨터공학과×복수전공) — 판정 불가 상태로 명확히 남아야 함",
        "programs": [
            {"type": "dual", "department": "컴퓨터공학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [],
        "expected": {
            "dual": {
                "requirement_found": False,
                "satisfied": None,
            },
        },
    },
    {
        "scenario_id": "TC04_CURRICULUM_YEAR_FALLBACK",
        "description": "학생 교육과정연도(2026)와 정확히 일치하는 산업공학과 기준학점이 없어 2024년도 행으로 대체돼야 함",
        "programs": [
            {"type": "primary", "department": "산업공학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공필수", "credits": 20.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "satisfied": None,  # 이 행은 required_total_credits가 비어 있음
                "categories": {"전공필수": True},
                "warning_contains": "2024년 기준으로 대체함",
            },
        },
    },
    {
        "scenario_id": "TC05_MAJOR_SPECIFIC_OVERRIDE",
        "description": "major_id가 있으면 학과 레벨(컴퓨터공학과 40학점)이 아니라 전공 레벨(데이터사이언스전공 25학점) 기준학점을 써야 함",
        "programs": [
            {
                "type": "primary",
                "department": "컴퓨터공학과",
                "major": "데이터사이언스전공",
                "curriculum_year": "2026",
            },
        ],
        "courses": [
            {"category": "전공필수", "credits": 25.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "categories": {"전공필수": True},
                "category_required_credits": {"전공필수": 25},
            },
        },
    },
    {
        "scenario_id": "TC06_DUAL_PROGRAM_SHARES_EARNED_POOL",
        "description": (
            "복수전공(컴퓨터공학과 주전공 + 수학과 복수전공) 병행 시, 이수학점 집계가 "
            "프로그램별로 분리되지 않고 사용자 전체 이수내역을 그대로 공유한다는 현재 "
            "엔진의 알려진 단순화를 고정한다 (course_id 기반 학과 필터링 없음, "
            "CLAUDE.md 테스트/검증 절 '알려진 한계' 참고)"
        ),
        "programs": [
            {"type": "primary", "department": "컴퓨터공학과", "major": None, "curriculum_year": "2026"},
            {"type": "dual", "department": "수학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공기초", "credits": 9.0},
            {"category": "전공필수", "credits": 48.0},
            {"category": "전공선택", "credits": 42.0},
            {"category": "교양필수", "credits": 15.0},
            {"category": "교양선택", "credits": 20.0},
            {"category": "일반선택", "credits": 16.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "satisfied": True,
                "categories": {"전공필수": True, "전공선택": True},
            },
            "dual": {
                "requirement_found": True,
                "satisfied": True,
                "categories": {"전공필수": True, "전공선택": True},
            },
            # primary/dual의 earned_total_credits가 정확히 같아야 함(공유 풀 검증).
            "shared_earned_total_credits": True,
        },
    },
]

if __name__ == "__main__":
    import json

    print(json.dumps(GOLDEN_SCENARIOS, indent=2, ensure_ascii=False))
