"""
Golden Data Set for Graduation Requirements Engine.
이 데이터는 여러 종류의 학생 케이스를 가상으로 정의한 골든 데이터셋입니다.
나중에 졸업 요건 엔진이 업그레이드될 때마다 이 데이터셋을 통과(pass)하는지 테스트(Regression Test)하는 용도로 사용됩니다.
"""

GOLDEN_SCENARIOS = [
    {
        "scenario_id": "TC01_STANDARD_PASS",
        "description": "일반 주전공 졸업 (모든 요건 정확히 충족)",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "CS전필1", "department": "컴퓨터공학과", "category": "전공필수", "credits": 20.0},
            {"name": "CS전필2", "department": "컴퓨터공학과", "category": "전공필수", "credits": 20.0},
            {"name": "CS전선1", "department": "컴퓨터공학과", "category": "전공선택", "credits": 30.0},
            {"name": "교양1", "department": "교양교육원", "category": "교양", "credits": 35.0},
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": True, "failed_categories": []}
        }
    },
    {
        "scenario_id": "TC02_GEN_ED_FAIL",
        "description": "교양 학점 미달 학생 (전공은 모두 채웠으나 교양이 부족)",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "CS전필1", "department": "컴퓨터공학과", "category": "전공필수", "credits": 40.0},
            {"name": "CS전선1", "department": "컴퓨터공학과", "category": "전공선택", "credits": 35.0},
            {"name": "교양1", "department": "교양교육원", "category": "교양", "credits": 20.0}, # 필요: 35, 이수: 20
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": False, "failed_categories": ["교양"]}
        }
    },
    {
        "scenario_id": "TC03_TRANSFER_STUDENT",
        "description": "타과(수학과)에서 컴공으로 전과한 학생 (이전 전공 과목은 일반선택으로 빠지고 전필 부족)",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "이산수학", "department": "수학과", "category": "일반선택", "credits": 40.0}, # 타과 전공은 보통 일반선택이나 일선 처리
            {"name": "CS전필1", "department": "컴퓨터공학과", "category": "전공필수", "credits": 20.0}, # 필요: 40, 이수: 20 (미달)
            {"name": "CS전선1", "department": "컴퓨터공학과", "category": "전공선택", "credits": 30.0},
            {"name": "교양1", "department": "교양교육원", "category": "교양", "credits": 40.0},
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": False, "failed_categories": ["전공필수"]}
        }
    },
    {
        "scenario_id": "TC04_WRONG_CATEGORY",
        "description": "총 전공 학점은 넘치지만 전공필수를 안 듣고 전공선택만 들은 학생",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "CS전선1", "department": "컴퓨터공학과", "category": "전공선택", "credits": 90.0}, # 전선은 과다
            {"name": "교양1", "department": "교양교육원", "category": "교양", "credits": 35.0},
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": False, "failed_categories": ["전공필수"]}
        }
    },
    {
        "scenario_id": "TC05_DUAL_MAJOR_PASS",
        "description": "컴공(주전공) + 수학(복수전공) - 양쪽 모두 완벽히 충족",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"},
            {"code": "MATH01", "type": "dual", "major": "수학과"}
        ],
        "courses": [
            {"name": "CS전필", "department": "컴퓨터공학과", "category": "전공필수", "credits": 40.0},
            {"name": "CS전선", "department": "컴퓨터공학과", "category": "전공선택", "credits": 30.0},
            {"name": "수학전필", "department": "수학과", "category": "전공필수", "credits": 35.0},
            {"name": "수학전선", "department": "수학과", "category": "전공선택", "credits": 20.0},
            {"name": "교양", "department": "교양교육원", "category": "교양", "credits": 35.0},
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": True, "failed_categories": []},
            "dual": {"status": "evaluated", "all_passed": True, "failed_categories": []}
        }
    },
    {
        "scenario_id": "TC06_MINOR_FAIL",
        "description": "컴공(주전공) + 수학(부전공) - 주전공은 통과했으나 부전공 필수 과목 부족",
        "programs": [
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"},
            {"code": "MATH01", "type": "minor", "major": "수학과"}
        ],
        "courses": [
            {"name": "CS전필", "department": "컴퓨터공학과", "category": "전공필수", "credits": 40.0},
            {"name": "CS전선", "department": "컴퓨터공학과", "category": "전공선택", "credits": 30.0},
            {"name": "교양", "department": "교양교육원", "category": "교양", "credits": 35.0},
            {"name": "수학전필", "department": "수학과", "category": "전공필수", "credits": 10.0}, # 필요: 21, 이수: 10 (미달)
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": True, "failed_categories": []},
            "minor": {"status": "evaluated", "all_passed": False, "failed_categories": ["수학전공필수(부)"]}
        }
    },
    {
        "scenario_id": "TC07_CROSS_DEPT_TO_FREE_ELECTIVE",
        "description": "타학과 전공선택 과목을 들으면 그 학과 전공 학점이 아니라 일반선택 학점으로 잡혀야 함",
        "programs": [
            {"code": "CS02", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "CS전필", "department": "컴퓨터공학과", "category": "전공필수", "credits": 20.0},
            # 수학과 소속 과목을 전공선택으로 들었지만, 컴공 프로그램 입장에서는
            # 전공 학점이 아니라 일반선택으로 인정돼야 한다 (필요: 6, 이수: 6).
            {"name": "수학전선", "department": "수학과", "category": "전공선택", "credits": 6.0},
        ],
        "expected_results": {
            "primary": {"status": "evaluated", "all_passed": True, "failed_categories": []}
        }
    },
    {
        "scenario_id": "TC08_REQUIRED_COURSE_CHOICE_GROUP",
        "description": "선택형(택1) 필수과목 - 대체 과목 중 하나만 이수해도 충족으로 인정돼야 함",
        "programs": [
            {"code": "CS03", "type": "primary", "major": "컴퓨터공학과"}
        ],
        "courses": [
            {"name": "CS전필", "department": "컴퓨터공학과", "category": "전공필수", "credits": 20.0},
            # 필수과목 요건은 "캡스톤디자인|종합설계" 중 하나를 요구한다. 학생은
            # 두 번째 대체 과목("종합설계")만 들었으므로, 문자열 그대로 비교하면
            # 절대 못 찾지만 실제로는 충족된 것으로 인정돼야 한다.
            {"name": "종합설계", "department": "컴퓨터공학과", "category": "전공선택", "credits": 3.0},
        ],
        "expected_results": {
            "primary": {
                "status": "evaluated",
                "all_passed": True,
                "failed_categories": [],
                "required_courses_completed": ["캡스톤디자인 / 종합설계"],
                "required_courses_missing": [],
            }
        }
    }
]

if __name__ == "__main__":
    import json
    print(json.dumps(GOLDEN_SCENARIOS, indent=2, ensure_ascii=False))
