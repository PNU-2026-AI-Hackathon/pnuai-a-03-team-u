import sys
import os

# Add backend directory to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.users.models import User
from app.domains.courses import models as _courses_models  # noqa: F401 — student_course_records.course_id FK 해석용
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    School,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.academics.graduation_progress import compute_graduation_progress
from tests.test_golden_data import GOLDEN_SCENARIOS

DEPT_IDS: dict[str, int] = {}
MAJOR_IDS: dict[str, int] = {}


def setup_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def setup_hierarchy(db):
    school = School(name="부산대학교")
    db.add(school)
    db.commit()
    college = College(school_id=school.id, name="테스트단과대학")
    db.add(college)
    db.commit()

    for name in ("컴퓨터공학과", "수학과", "산업공학과", "간호학과", "경영학과", "테스트학과"):
        dept = Department(college_id=college.id, name=name)
        db.add(dept)
        db.commit()
        DEPT_IDS[name] = dept.id

    major = Major(department_id=DEPT_IDS["컴퓨터공학과"], name="데이터사이언스전공")
    db.add(major)
    db.commit()
    MAJOR_IDS["데이터사이언스전공"] = major.id

    # TC07 — 산업공학과는 AI융합트랙 대상 14개 학과 중 하나다(정보컴퓨터공학부 같은
    # SW 학과는 대상이 아니다). 실 Supabase 기준 실제 트랙 전공명·학점 구성 그대로.
    ai_track_major = Major(department_id=DEPT_IDS["산업공학과"], name="산업AI(SW융합트랙)")
    db.add(ai_track_major)
    db.commit()
    MAJOR_IDS["산업AI(SW융합트랙)"] = ai_track_major.id

    # TC10 — 산업공학과 소속이지만 이 전공만의 기준학점 행은 없다(전공 요건 미등록
    # 학과·전공 조합, 2026-08-13 발견된 실제 사고 패턴 — _find_requirement 폴백
    # docstring 참고). 요건 행은 일부러 안 만든다.
    fallback_major = Major(department_id=DEPT_IDS["산업공학과"], name="미배정전공")
    db.add(fallback_major)
    db.commit()
    MAJOR_IDS["미배정전공"] = fallback_major.id


def setup_requirements(db):
    """flat graduation_requirements 마스터 데이터.

    TC03(요건 없음)을 위해 컴퓨터공학과×dual 조합은 의도적으로 만들지 않는다.
    """
    db.add_all(
        [
            # TC01/TC02/TC06(primary 쪽) — 컴퓨터공학과 주전공, 2026년.
            GraduationRequirement(
                department_id=DEPT_IDS["컴퓨터공학과"],
                major_id=None,
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=130,
                required_major_foundation=9,
                required_major_required=40,
                required_major_elective=30,
                required_general_required=15,
                required_general_elective=20,
                required_free_elective=16,
            ),
            # TC04 — 산업공학과 주전공, 2024년 행만 존재(학생은 2026년 요청 → 폴백).
            GraduationRequirement(
                department_id=DEPT_IDS["산업공학과"],
                major_id=None,
                program_type="primary",
                curriculum_year="2024",
                required_total_credits=None,
                required_major_foundation=None,
                required_major_required=20,
                required_major_elective=None,
                required_general_required=None,
                required_general_elective=None,
                required_free_elective=None,
            ),
            # TC05 — 데이터사이언스전공(major_id) 레벨 기준학점. 학과 레벨(40)과
            # 다른 값(25)을 넣어 major_id 우선순위를 검증한다.
            GraduationRequirement(
                department_id=DEPT_IDS["컴퓨터공학과"],
                major_id=MAJOR_IDS["데이터사이언스전공"],
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=None,
                required_major_foundation=None,
                required_major_required=25,
                required_major_elective=None,
                required_general_required=None,
                required_general_elective=None,
                required_free_elective=None,
            ),
            # TC06(dual 쪽) — 수학과 복수전공, 2026년.
            GraduationRequirement(
                department_id=DEPT_IDS["수학과"],
                major_id=None,
                program_type="dual",
                curriculum_year="2026",
                required_total_credits=50,
                required_major_foundation=None,
                required_major_required=8,
                required_major_elective=12,
                required_general_required=None,
                required_general_elective=None,
                required_free_elective=None,
            ),
            # TC07 — 산업공학과 AI융합트랙(interdisciplinary). 졸업요건이 아니라 인증
            # 프로그램이라 flat 카테고리 컬럼(전공기초/필수/선택 등)은 안 쓰고 특성상
            # required_total_credits(21)만 채워진다 — 실 데이터도 이 모양이다. 세부
            # 학점 구성(전공 15 + AI공통 6)은 special_rules에만 있다(app/domains/
            # academics/tracks.py가 이 special_rules로 트랙 여부를 판별한다).
            GraduationRequirement(
                department_id=DEPT_IDS["산업공학과"],
                major_id=MAJOR_IDS["산업AI(SW융합트랙)"],
                program_type="interdisciplinary",
                curriculum_year="2026",
                required_total_credits=21,
                special_rules={
                    "certification_type": "AI융합트랙",
                    "not_graduation_requirement": True,
                    "dept_credits": {"min": 15, "max": 15},
                    "ai_common_credits": {"min": 6, "max": 6},
                },
            ),
            # TC08 — 간호학과 주전공(비CS, 전공필수 비중이 아주 큰 실제 케이스). 컴공
            # 위주였던 골든셋에 다른 학문 계열 전 카테고리 기준학점을 추가한다.
            GraduationRequirement(
                department_id=DEPT_IDS["간호학과"],
                major_id=None,
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=134,
                required_major_foundation=19,
                required_major_required=77,
                required_major_elective=8,
                required_general_required=9,
                required_general_elective=21,
                required_free_elective=None,
            ),
            # TC09 — 경영학과 부전공(minor). 골든셋에 지금까지 minor 시나리오가 아예
            # 없었다(복수전공만 있었음). 실 데이터에서도 minor 요건 행 다수가 카테고리
            # 세분 없이 총학점만 있다 — 그 실제 모양 그대로 재현한다.
            GraduationRequirement(
                department_id=DEPT_IDS["경영학과"],
                major_id=None,
                program_type="minor",
                curriculum_year="2026",
                required_total_credits=21,
            ),
            # TC11 — 같은 조건(department/major/program_type/curriculum_year)의 기준학점
            # 행이 2개(2026-08-13 실제 발견: 간호학과 dual 2026이 2행이라 조회가
            # MultipleResultsFound로 500 에러 났었다 — _find_in_scope 폴백 docstring
            # 참고). unique 제약이 없어 데이터 정리 실수로 또 생길 수 있다 — 500으로
            # 죽지 않고 하나를 골라(id 오름차순) 계산 + 경고를 남기는지 검증한다.
            GraduationRequirement(
                department_id=DEPT_IDS["테스트학과"],
                major_id=None,
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=130,
                required_major_required=30,
            ),
            GraduationRequirement(
                department_id=DEPT_IDS["테스트학과"],
                major_id=None,
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=140,  # 위 행과 값이 달라 "어느 걸 골랐는지"가 실제로 드러남
                required_major_required=35,
            ),
        ]
    )
    db.commit()


def _check_program_result(scenario_id, program_type, res, expected, failures):
    if res is None:
        failures.append(f"{program_type} 프로그램 결과 자체가 없음")
        return

    if res.requirement_found != expected["requirement_found"]:
        failures.append(
            f"{program_type}: requirement_found 불일치 "
            f"(Expected: {expected['requirement_found']}, Actual: {res.requirement_found})"
        )

    if "satisfied" in expected and res.satisfied != expected["satisfied"]:
        failures.append(
            f"{program_type}: 총계 satisfied 불일치 "
            f"(Expected: {expected['satisfied']}, Actual: {res.satisfied})"
        )

    if "is_ai_track" in expected and res.is_ai_track != expected["is_ai_track"]:
        failures.append(
            f"{program_type}: is_ai_track 불일치 "
            f"(Expected: {expected['is_ai_track']}, Actual: {res.is_ai_track})"
        )

    categories_by_name = {cat.category_name: cat for cat in res.categories}

    for cat_name, expected_satisfied in expected.get("categories", {}).items():
        cat = categories_by_name.get(cat_name)
        if cat is None:
            failures.append(f"{program_type}: '{cat_name}' 카테고리가 결과에 없음")
            continue
        if cat.satisfied != expected_satisfied:
            failures.append(
                f"{program_type}: '{cat_name}' satisfied 불일치 "
                f"(Expected: {expected_satisfied}, Actual: {cat.satisfied}, "
                f"{cat.earned_credits}/{cat.required_credits})"
            )

    for cat_name, expected_required in expected.get("category_required_credits", {}).items():
        cat = categories_by_name.get(cat_name)
        if cat is None:
            failures.append(f"{program_type}: '{cat_name}' 카테고리가 결과에 없음")
            continue
        if cat.required_credits != expected_required:
            failures.append(
                f"{program_type}: '{cat_name}' required_credits 불일치 "
                f"(Expected: {expected_required}, Actual: {cat.required_credits}) "
                "— major_id 우선순위 판정 로직을 확인할 것"
            )

    if "warning_contains" in expected:
        needle = expected["warning_contains"]
        if not any(needle in w for w in res.warnings):
            failures.append(f"{program_type}: warnings에 '{needle}' 포함된 항목이 없음 (실제: {res.warnings})")


def run_golden_tests():
    db = setup_db()
    setup_hierarchy(db)
    setup_requirements(db)

    print("=== 🚀 Golden Data Set 테스트 시작 ===\n")
    all_passed = True

    for scenario in GOLDEN_SCENARIOS:
        print(f"▶ 테스트 케이스: {scenario['scenario_id']} - {scenario['description']}")
        failures: list[str] = []

        user = User(
            email=f"{scenario['scenario_id']}@test.com",
            password_hash="dummy",
            name=scenario["scenario_id"],
        )
        db.add(user)
        db.commit()

        for p in scenario["programs"]:
            db.add(
                UserAcademicProgram(
                    user_id=user.id,
                    department_id=DEPT_IDS.get(p["department"]) if p["department"] else None,
                    major_id=MAJOR_IDS.get(p["major"]) if p["major"] else None,
                    program_type=p["type"],
                    curriculum_year=p["curriculum_year"],
                    status="active",
                )
            )
        db.commit()

        for c in scenario["courses"]:
            db.add(
                StudentCourseRecord(
                    user_id=user.id,
                    course_id=None,
                    raw_course_name=f"{scenario['scenario_id']}_{c['category']}",
                    category=c["category"],
                    credits=c["credits"],
                    match_status="unmatched",
                )
            )
        db.commit()

        results = compute_graduation_progress(db, user.id)
        results_by_type = {res.program_type: res for res in results}

        for program_type, expected in scenario["expected"].items():
            if program_type == "shared_earned_total_credits":
                continue
            _check_program_result(
                scenario["scenario_id"], program_type, results_by_type.get(program_type), expected, failures
            )

        if scenario["expected"].get("shared_earned_total_credits"):
            totals = {res.earned_total_credits for res in results}
            if len(totals) != 1:
                failures.append(
                    f"프로그램 간 earned_total_credits가 같아야 하는데 다름: "
                    f"{[(res.program_type, res.earned_total_credits) for res in results]}"
                )

        if not failures:
            print("  ✅ PASS: 모든 기대 결과와 정확히 일치합니다.\n")
        else:
            all_passed = False
            for failure in failures:
                print(f"  ❌ FAIL: {failure}")
            print()

    if all_passed:
        print("🎉 모든 골든 데이터셋 시나리오를 완벽하게 통과했습니다!")
    else:
        print("⚠️ 일부 시나리오가 실패했습니다.")
        sys.exit(1)


if __name__ == "__main__":
    run_golden_tests()
