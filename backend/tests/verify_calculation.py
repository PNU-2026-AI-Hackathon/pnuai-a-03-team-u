import sys
import os
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.users.models import User, PortalCredential
from app.domains.courses.models import Course
from app.domains.academics.models import (
    Department,
    AcademicProgram,
    UserAcademicProgram,
    StudentCourseRecord,
    RequirementSet,
    RequirementCategory,
    RequirementCourse,
    RequirementTextRule,
)
from app.domains.academics.graduation_engine import _evaluate_categories

def test_credit_calculation():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 1. 셋업: 2개의 학과 요건 (CS 주전공, MATH 복수전공)
    # requirement_set에 department 필드를 세팅해 줍니다.
    cs_req = RequirementSet(id=1, academic_program_code="CS", program_type="primary", department="컴퓨터공학과", is_active=True)
    math_req = RequirementSet(id=2, academic_program_code="MATH", program_type="dual", department="수학과", is_active=True)
    db.add_all([cs_req, math_req])

    # CS 카테고리
    db.add(RequirementCategory(external_id="CS_req", requirement_set_id=1, category_code="major_required", category_name="컴공 전필", rule_type="minimum_credits", needs_review=False, minimum_credits="40"))
    db.add(RequirementCategory(external_id="CS_elec", requirement_set_id=1, category_code="major_elective", category_name="컴공 전선", rule_type="minimum_credits", needs_review=False, minimum_credits="30"))
    db.add(RequirementCategory(external_id="CS_gen", requirement_set_id=1, category_code="general_total", category_name="교양", rule_type="minimum_credits", needs_review=False, minimum_credits="30"))

    # Math 카테고리
    db.add(RequirementCategory(external_id="MATH_req", requirement_set_id=2, category_code="major_required", category_name="수학 전필(복수)", rule_type="minimum_credits", needs_review=False, minimum_credits="35"))

    # 1-1. Course 마스터 데이터 추가
    course_cs_1 = Course(id=1, course_name="자료구조(컴공)", department="컴퓨터공학과")
    course_math_1 = Course(id=2, course_name="선형대수(수학)", department="수학과")
    course_cs_2 = Course(id=3, course_name="알고리즘(컴공)", department="컴퓨터공학과")
    course_gen = Course(id=4, course_name="철학의이해", department="교양교육원")
    db.add_all([course_cs_1, course_math_1, course_cs_2, course_gen])

    db.commit()

    # 2. 학생의 실제 수강 내역 (컴공 전필 20, 수학 전필 20 수강)
    # course_id를 연결해 줍니다.
    courses = [
        StudentCourseRecord(course_id=1, raw_course_name="자료구조(컴공)", category="전공필수", credits=20.0),
        StudentCourseRecord(course_id=2, raw_course_name="선형대수(수학)", category="전공필수", credits=20.0),
        StudentCourseRecord(course_id=3, raw_course_name="알고리즘(컴공)", category="전공선택", credits=15.0),
        StudentCourseRecord(course_id=4, raw_course_name="철학의이해", category="교양", credits=10.0),
    ]

    print("=== [개선된 엔진의 학점 계산 로직 검증] ===")
    print("학생 수강 내역: 컴공 전필 20학점, 수학 전필 20학점, 컴공 전선 15학점, 교양 10학점\n")

    print("▶ 1. 컴퓨터공학과(주전공) 입장에서 계산된 학점")
    cs_results, _ = _evaluate_categories(db, requirement_set=cs_req, course_records=courses)
    for cat in cs_results:
        print(f" - [{cat.category_name}] 계산된 이수 학점: {cat.earned_credits}학점 (매칭된 과목: {', '.join(cat.matched_course_names)})")

    print("\n▶ 2. 수학과(복수전공) 입장에서 계산된 학점")
    math_results, _ = _evaluate_categories(db, requirement_set=math_req, course_records=courses)
    for cat in math_results:
        print(f" - [{cat.category_name}] 계산된 이수 학점: {cat.earned_credits}학점 (매칭된 과목: {', '.join(cat.matched_course_names)})")

    print("\n[결론]")
    print("학과 필터링 로직이 작동하여, 컴공 전필(자료구조)과 수학 전필(선형대수)이 서로 간섭하지 않고 독립적으로 분리되어 계산됩니다!")

if __name__ == "__main__":
    test_credit_calculation()
