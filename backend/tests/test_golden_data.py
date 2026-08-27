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
- is_ai_track: ProgramProgress.is_ai_track과 대조 — AI융합트랙(program_type=
  'interdisciplinary' + special_rules.certification_type='AI융합트랙') 판정이
  실제로 이 진행도 계산에 쓰인 요건 행 기준으로 나오는지 검증한다.

TC01~TC06은 컴퓨터공학과 위주였다. TC07~TC09가 다양성을 보강한다: TC07은 AI융합트랙
대상 14개 학과 중 하나(산업공학과)의 interdisciplinary 트랙 판정, TC08은 비CS
학과(간호학과)의 전 카테고리 기준학점 대조, TC09는 골든셋에 없던 부전공(minor)
시나리오다. 셋 다 실 Supabase의 실제 department/major/학점 구성을 그대로 썼다
(2026-08-23 조회 기준).

TC10~TC11(2026-08-26 추가)은 엔진 코드에 이미 있던 두 방어 로직(major→department
폴백, 중복 요건 행 경고)이 실제 프로덕션 인시던트(2026-08-13, `_find_requirement`/
`_find_in_scope` docstring 참고)에서 나왔는데도 골든셋에 회귀 방지 장치가 전혀
없던 사각지대를 메운다. 이 둘은 합성 데이터(`run_golden_tests.py`의 "테스트학과"/
"미배정전공")로만 구성 — 실 Supabase 데이터를 흉내 낼 필요 없이 엔진의 두 분기
자체를 트리거하기만 하면 된다.
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
                # 이 dual 요건엔 special_rules.groups도 program_courses도 없어
                # 하이브리드 판정이 flat로 폴백한다(2026-08-27) — 그 경고를 고정한다.
                "warning_contains": "총 이수학점만 대조됨",
            },
            # dual이 flat 폴백이므로 primary/dual의 earned_total_credits가 여전히 같다(공유 풀).
            "shared_earned_total_credits": True,
        },
    },
    {
        "scenario_id": "TC07_AI_TRACK_INTERDISCIPLINARY",
        "description": (
            "AI융합트랙 대상 14개 학과 중 하나(산업공학과, 비SW 학과)가 실제 트랙 "
            "요건(21학점, special_rules.certification_type=AI융합트랙)을 채우면 "
            "is_ai_track=True로 판정돼야 함"
        ),
        "programs": [
            {
                "type": "interdisciplinary",
                "department": "산업공학과",
                "major": "산업AI(SW융합트랙)",
                "curriculum_year": "2026",
            },
        ],
        # 트랙은 flat 카테고리 컬럼을 안 쓰고 총학점(21)만 본다 — 학과전공 15 + AI융합
        # 공통교과목(전부 일반선택) 6이라는 실제 구성 그대로 채운다.
        "courses": [
            {"category": "전공선택", "credits": 15.0},
            {"category": "일반선택", "credits": 6.0},
        ],
        "expected": {
            "interdisciplinary": {
                "requirement_found": True,
                "satisfied": True,
                "is_ai_track": True,
                # 이 골든 요건의 special_rules엔 groups가 없어(certification_type만) 하이브리드
                # 판정이 flat로 폴백한다 — 실 DB의 AI융합트랙은 groups가 있어 실판정된다.
                "warning_contains": "총 이수학점만 대조됨",
            },
        },
    },
    {
        "scenario_id": "TC08_NON_CS_PRIMARY_FULL_BREAKDOWN",
        "description": (
            "간호학과(비CS, 전공필수 비중이 아주 큰 실제 커리큘럼) 주전공 — 컴공 "
            "위주였던 골든셋에 다른 학문 계열의 전 카테고리 기준학점 대조를 추가"
        ),
        "programs": [
            {"type": "primary", "department": "간호학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공기초", "credits": 19.0},
            {"category": "전공필수", "credits": 77.0},
            {"category": "전공선택", "credits": 8.0},
            {"category": "교양필수", "credits": 9.0},
            {"category": "교양선택", "credits": 21.0},
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
                },
            },
        },
    },
    {
        "scenario_id": "TC09_MINOR_PROGRAM",
        "description": (
            "경영학과 부전공(minor) — 골든셋에 지금까지 복수전공만 있고 부전공이 "
            "아예 없었다. 실 데이터에서도 minor 요건 행 다수가 카테고리 세분 없이 "
            "총학점만 있는 실제 모양 그대로 재현"
        ),
        "programs": [
            {"type": "minor", "department": "경영학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공선택", "credits": 21.0},
        ],
        "expected": {
            "minor": {
                "requirement_found": True,
                "satisfied": True,
                # 카테고리·groups·program_courses가 전혀 없는 minor 요건 → flat 폴백 경고.
                "warning_contains": "총 이수학점만 대조됨",
            },
        },
    },
    {
        "scenario_id": "TC10_MAJOR_FALLBACK_TO_DEPARTMENT",
        "description": (
            "산업공학과 소속 '미배정전공' 학생 — 그 전공만의 기준학점 행이 없어 "
            "학과 단위(major_id IS NULL) 행으로 폴백해야 함. TC04(연도 폴백)와 다른 "
            "폴백 경로라 curriculum_year는 학과 단위 행과 정확히 일치시켜(2024) "
            "두 폴백이 섞이지 않게 한다. 2026-08-13 실제 사고(활성 학적 6건 중 3건이 "
            "이 경로에 걸려 판정 자체가 안 됨) 재현 — 회귀 방지 장치가 없었다."
        ),
        "programs": [
            {"type": "primary", "department": "산업공학과", "major": "미배정전공", "curriculum_year": "2024"},
        ],
        "courses": [
            {"category": "전공필수", "credits": 20.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "categories": {"전공필수": True},
                "warning_contains": "학과 단위 기준으로 판정",
            },
        },
    },
    {
        "scenario_id": "TC11_DUPLICATE_REQUIREMENT_ROWS",
        "description": (
            "같은 조건(학과/전공/이수유형/교육과정연도)의 기준학점 행이 2개 존재 — "
            "graduation_requirements에 unique 제약이 없어 데이터 정리 실수로 생길 수 "
            "있다. 2026-08-13 실제 사고(간호학과 dual 2026 중복 2행 → 졸업요건 조회 "
            "MultipleResultsFound로 500 에러) 재현. 500으로 죽지 않고 하나를 "
            "결정적으로(id 오름차순) 골라 계산 + 경고를 남기는지 검증 — "
            "회귀 방지 장치가 없었다."
        ),
        "programs": [
            {"type": "primary", "department": "테스트학과", "major": None, "curriculum_year": "2026"},
        ],
        "courses": [
            {"category": "전공필수", "credits": 30.0},
        ],
        "expected": {
            "primary": {
                "requirement_found": True,
                "categories": {"전공필수": True},
                # id가 더 작은(먼저 넣은) 행(30학점)이 결정적으로 선택돼야 한다 —
                # 두 번째 행(35학점)이 골라졌다면 이 값이 안 맞는다.
                "category_required_credits": {"전공필수": 30},
                "warning_contains": "같은 조건의 기준학점 행이",
            },
        },
    },
    {
        "scenario_id": "TC12_MINOR_RULE_BASED_JUDGMENT",
        "description": (
            "special_rules.groups + program_courses가 있는 부전공은 하이브리드 판정으로 "
            "지정 과목 이수 여부를 실제 확인한다(2026-08-27). 필수 지정 3과목 중 2과목만 "
            "이수 → 총 학점(21)을 아무리 채워도 satisfied=False, 부족 그룹이 warnings에."
        ),
        "programs": [
            {"type": "minor", "department": "테스트학과", "major": None, "curriculum_year": "2026"},
        ],
        # flat이면 통과할 만큼 총 학점은 넉넉히 — 하이브리드가 이걸 무시하고 그룹으로 판정하는지 본다.
        "courses": [
            {"category": "전공선택", "credits": 30.0},
        ],
        # 하이브리드용 추가 시드 (run_golden_tests.py가 처리).
        "program_course_pool": [
            {"name": "TC12_필수A", "credits": 3.0, "group": "필수 (3과목)"},
            {"name": "TC12_필수B", "credits": 3.0, "group": "필수 (3과목)"},
            {"name": "TC12_필수C", "credits": 3.0, "group": "필수 (3과목)"},
        ],
        "completed_from_pool": ["TC12_필수A", "TC12_필수B"],
        "minor_special_rules": {
            "total_credits": 9,
            "groups": [{"type": "min_courses", "n": 3, "label": "필수 (3과목)"}],
        },
        "minor_required_total_credits": 9,
        "expected": {
            "minor": {
                "requirement_found": True,
                "satisfied": False,
                "warning_contains": "필수 (3과목)",
            },
        },
    },
]

if __name__ == "__main__":
    import json

    print(json.dumps(GOLDEN_SCENARIOS, indent=2, ensure_ascii=False))
