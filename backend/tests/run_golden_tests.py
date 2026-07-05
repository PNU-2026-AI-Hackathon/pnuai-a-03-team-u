import sys
import os
from decimal import Decimal

# Add backend directory to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.users.models import User
from app.domains.courses.models import Course
from app.domains.academics.models import (
    UserAcademicProgram,
    StudentCourseRecord,
    RequirementSet,
    RequirementCategory,
    RequirementCourse,
)
from app.domains.academics.graduation_engine import evaluate_graduation
from tests.test_golden_data import GOLDEN_SCENARIOS

def setup_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def setup_global_requirements(db):
    # Requirement Sets
    cs_req = RequirementSet(
        academic_program_code="CS01",
        program_type="primary",
        curriculum_year="2026",
        name="Computer Science Primary 2026",
        department="컴퓨터공학과",
        is_active=True,
    )
    math_minor_req = RequirementSet(
        academic_program_code="MATH01",
        program_type="minor",
        curriculum_year="2026",
        name="Mathematics Minor 2026",
        department="수학과",
        is_active=True,
    )
    math_dual_req = RequirementSet(
        academic_program_code="MATH01",
        program_type="dual",
        curriculum_year="2026",
        name="Mathematics Dual Major 2026",
        department="수학과",
        is_active=True,
    )
    db.add_all([cs_req, math_minor_req, math_dual_req])
    db.commit()

    # Requirement Categories for CS
    cs_cat1 = RequirementCategory(external_id="cs_req1", requirement_set_id=cs_req.id, category_code="major_required", category_name="전공필수", minimum_credits="40", rule_type="minimum_credits", needs_review=False)
    cs_cat2 = RequirementCategory(external_id="cs_req2", requirement_set_id=cs_req.id, category_code="major_elective", category_name="전공선택", minimum_credits="30", rule_type="minimum_credits", needs_review=False)
    cs_cat3 = RequirementCategory(external_id="cs_req3", requirement_set_id=cs_req.id, category_code="general_total", category_name="교양", minimum_credits="35", rule_type="minimum_credits", needs_review=False)

    # TC07 전용: 타학과 과목 -> 일반선택 재분류를 검증하기 위한 별도 프로그램.
    # 기존 CS01 시나리오들에 영향 주지 않도록 새 academic_program_code를 쓴다.
    cs2_req = RequirementSet(
        academic_program_code="CS02",
        program_type="primary",
        curriculum_year="2026",
        name="Computer Science Primary 2026 (free-elective test)",
        department="컴퓨터공학과",
        is_active=True,
    )
    db.add(cs2_req)
    db.commit()
    cs2_cat1 = RequirementCategory(external_id="cs2_req1", requirement_set_id=cs2_req.id, category_code="major_required", category_name="전공필수", minimum_credits="20", rule_type="minimum_credits", needs_review=False)
    cs2_cat2 = RequirementCategory(external_id="cs2_req2", requirement_set_id=cs2_req.id, category_code="free_elective", category_name="일반선택", minimum_credits="6", rule_type="minimum_credits", needs_review=False)
    db.add_all([cs2_cat1, cs2_cat2])

    # TC08 전용: 선택형(택1) 필수과목 - matched_course_name이 "이름1|이름2"처럼
    # 파이프로 묶인 행이 대체 과목 중 하나만 이수해도 충족으로 잡히는지 검증.
    cs3_req = RequirementSet(
        academic_program_code="CS03",
        program_type="primary",
        curriculum_year="2026",
        name="Computer Science Primary 2026 (required-course choice group test)",
        department="컴퓨터공학과",
        is_active=True,
    )
    db.add(cs3_req)
    db.commit()
    cs3_cat1 = RequirementCategory(external_id="cs3_req1", requirement_set_id=cs3_req.id, category_code="major_required", category_name="전공필수", minimum_credits="20", rule_type="minimum_credits", needs_review=False)
    cs3_required_course = RequirementCourse(
        external_id="cs3_required_choice1",
        requirement_set_id=cs3_req.id,
        category_code="major_required",
        raw_course_name="캡스톤디자인",
        matched_course_name="캡스톤디자인|종합설계",
        needs_review=False,
    )
    db.add_all([cs3_cat1, cs3_required_course])

    # Requirement Categories for Math Minor
    math_minor_cat = RequirementCategory(external_id="math_minor1", requirement_set_id=math_minor_req.id, category_code="major_required", category_name="수학전공필수(부)", minimum_credits="21", rule_type="minimum_credits", needs_review=False)

    # Requirement Categories for Math Dual
    math_dual_cat1 = RequirementCategory(external_id="math_dual1", requirement_set_id=math_dual_req.id, category_code="major_required", category_name="수학전공필수(복)", minimum_credits="35", rule_type="minimum_credits", needs_review=False)
    math_dual_cat2 = RequirementCategory(external_id="math_dual2", requirement_set_id=math_dual_req.id, category_code="major_elective", category_name="수학전공선택(복)", minimum_credits="20", rule_type="minimum_credits", needs_review=False)

    db.add_all([cs_cat1, cs_cat2, cs_cat3, math_minor_cat, math_dual_cat1, math_dual_cat2])
    db.commit()


def run_golden_tests():
    db = setup_db()
    setup_global_requirements(db)

    print("=== 🚀 Golden Data Set 테스트 시작 ===\n")
    all_passed = True
    
    course_cache = {}

    for scenario in GOLDEN_SCENARIOS:
        print(f"▶ 테스트 케이스: {scenario['scenario_id']} - {scenario['description']}")
        
        # 1. User
        user = User(email=f"{scenario['scenario_id']}@test.com", password_hash="dummy", name=scenario['scenario_id'])
        db.add(user)
        db.commit()

        # 2. Programs
        for p in scenario["programs"]:
            db.add(UserAcademicProgram(
                user_id=user.id,
                academic_program_code=p["code"],
                program_type=p["type"],
                major=p["major"],
                curriculum_year="2026",
                status="active"
            ))
        
        # 3. Courses
        for c in scenario["courses"]:
            course_key = (c["name"], c["department"])
            if course_key not in course_cache:
                new_course = Course(course_name=c["name"], department=c["department"])
                db.add(new_course)
                db.commit()
                course_cache[course_key] = new_course.id
            
            course_id = course_cache[course_key]
            db.add(StudentCourseRecord(
                user_id=user.id,
                course_id=course_id,
                raw_course_name=c["name"],
                category=c["category"],
                credits=c["credits"],
                match_status="matched"
            ))
        db.commit()

        # 4. Evaluate
        results = evaluate_graduation(db, user.id)
        
        # 5. Verify against expected_results
        test_success = True
        for res in results:
            expected = scenario["expected_results"].get(res.program_type)
            if not expected:
                continue
            
            # Check if all passed matches
            actual_all_passed = all(cat.satisfied for cat in res.categories) if res.categories else False
            failed_cats = [cat.category_name for cat in res.categories if not cat.satisfied]
            
            if actual_all_passed != expected["all_passed"]:
                print(f"  ❌ FAIL: {res.program_type} 프로그램 패스 여부 불일치. (Expected: {expected['all_passed']}, Actual: {actual_all_passed})")
                test_success = False
            
            # Check failed categories
            for f_cat in expected["failed_categories"]:
                if f_cat not in failed_cats:
                    print(f"  ❌ FAIL: {res.program_type} 프로그램에서 '{f_cat}' 미달을 잡아내지 못함!")
                    test_success = False

            # Check required_courses (선택형 택1 필수과목 등) - 지정된 시나리오만 검증
            if "required_courses_completed" in expected:
                actual_completed = res.required_courses.completed_course_names if res.required_courses else []
                for name in expected["required_courses_completed"]:
                    if name not in actual_completed:
                        print(f"  ❌ FAIL: {res.program_type} 프로그램에서 필수과목 '{name}' 이수를 못 잡아냄! (실제: {actual_completed})")
                        test_success = False
            if "required_courses_missing" in expected:
                actual_missing = res.required_courses.missing_course_names if res.required_courses else []
                for name in expected["required_courses_missing"]:
                    if name not in actual_missing:
                        print(f"  ❌ FAIL: {res.program_type} 프로그램에서 필수과목 '{name}' 미이수를 못 잡아냄! (실제: {actual_missing})")
                        test_success = False

        if test_success:
            print("  ✅ PASS: 모든 기대 결과와 정확히 일치합니다.\n")
        else:
            all_passed = False
            print("  ❌ FAIL: 일부 기대 결과와 일치하지 않습니다.\n")
            # print details for debugging
            for res in results:
                print(f"    - {res.program_type} 세부 결과:")
                for cat in res.categories:
                    print(f"      [{cat.category_name}] {cat.earned_credits}/{cat.minimum_credits} -> {'통과' if cat.satisfied else '미달'}")
            print("\n")
            
    if all_passed:
        print("🎉 모든 골든 데이터셋 시나리오를 완벽하게 통과했습니다!")
    else:
        print("⚠️ 일부 시나리오가 실패했습니다.")

if __name__ == "__main__":
    run_golden_tests()
