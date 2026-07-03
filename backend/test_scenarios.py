import sys
import os
from decimal import Decimal

# Add backend directory to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
from app.domains.academics.graduation_engine import evaluate_graduation


def setup_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def create_mock_data(db):
    # Requirement Sets
    cs_req = RequirementSet(
        academic_program_code="CS01",
        program_type="primary",
        curriculum_year="2026",
        name="Computer Science Primary 2026",
        is_active=True,
    )
    math_minor_req = RequirementSet(
        academic_program_code="MATH01",
        program_type="minor",
        curriculum_year="2026",
        name="Mathematics Minor 2026",
        is_active=True,
    )
    math_dual_req = RequirementSet(
        academic_program_code="MATH01",
        program_type="dual",
        curriculum_year="2026",
        name="Mathematics Dual Major 2026",
        is_active=True,
    )
    db.add_all([cs_req, math_minor_req, math_dual_req])
    db.commit()

    # Requirement Categories for CS
    cs_cat1 = RequirementCategory(
        external_id="cs_req1",
        requirement_set_id=cs_req.id,
        category_code="major_required",
        category_name="전공필수",
        minimum_credits="40",
        rule_type="minimum_credits",
        needs_review=False,
    )
    cs_cat2 = RequirementCategory(
        external_id="cs_req2",
        requirement_set_id=cs_req.id,
        category_code="major_elective",
        category_name="전공선택",
        minimum_credits="30",
        rule_type="minimum_credits",
        needs_review=False,
    )
    cs_cat3 = RequirementCategory(
        external_id="cs_req3",
        requirement_set_id=cs_req.id,
        category_code="general_total",
        category_name="교양",
        minimum_credits="35",
        rule_type="minimum_credits",
        needs_review=False,
    )

    # Requirement Categories for Math Minor
    # Usually minor requires some major_required or just a specific minor code, 
    # but based on the engine, if a user takes "전공필수" it maps to "major_required".
    # Note: Minor courses might have their own category strings in reality, 
    # but let's assume they map to major_required / major_elective here.
    math_minor_cat = RequirementCategory(
        external_id="math_minor1",
        requirement_set_id=math_minor_req.id,
        category_code="major_required",
        category_name="수학전공필수(부)",
        minimum_credits="21",
        rule_type="minimum_credits",
        needs_review=False,
    )

    # Requirement Categories for Math Dual
    math_dual_cat1 = RequirementCategory(
        external_id="math_dual1",
        requirement_set_id=math_dual_req.id,
        category_code="major_required",
        category_name="수학전공필수(복)",
        minimum_credits="35",
        rule_type="minimum_credits",
        needs_review=False,
    )
    math_dual_cat2 = RequirementCategory(
        external_id="math_dual2",
        requirement_set_id=math_dual_req.id,
        category_code="major_elective",
        category_name="수학전공선택(복)",
        minimum_credits="20",
        rule_type="minimum_credits",
        needs_review=False,
    )

    db.add_all([cs_cat1, cs_cat2, cs_cat3, math_minor_cat, math_dual_cat1, math_dual_cat2])
    db.commit()

    return {
        "cs_req": cs_req,
        "math_minor_req": math_minor_req,
        "math_dual_req": math_dual_req,
    }


def add_student_scenario(db, scenario_name, programs, courses):
    user = User(email=f"{scenario_name}@test.com", password_hash="dummy", name=scenario_name)
    db.add(user)
    db.commit()

    for p in programs:
        db.add(UserAcademicProgram(
            user_id=user.id,
            academic_program_code=p["code"],
            program_type=p["type"],
            major=p["major"],
            curriculum_year="2026",
            status="active"
        ))

    for c in courses:
        db.add(StudentCourseRecord(
            user_id=user.id,
            raw_course_name=c["name"],
            category=c["category"],
            credits=c["credits"],
            match_status="matched"
        ))
    db.commit()
    return user


def run_scenarios():
    db = setup_db()
    reqs = create_mock_data(db)

    print("=== 졸업요건 판정 시나리오 테스트 ===\n")

    # 1. 일반 졸업 학생 (요건 모두 충족)
    # CS: 전필 40, 전선 30, 교양 35 필요
    u1 = add_student_scenario(
        db, "일반졸업학생",
        programs=[{"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}],
        courses=[
            {"name": "자료구조", "category": "전공필수", "credits": 45.0},
            {"name": "알고리즘", "category": "전공선택", "credits": 35.0},
            {"name": "컴퓨팅사고", "category": "교양", "credits": 40.0},
        ]
    )

    # 2. 전과생 (요건 미충족)
    # 전과로 인해 전필 부족
    u2 = add_student_scenario(
        db, "전과생",
        programs=[{"code": "CS01", "type": "primary", "major": "컴퓨터공학과"}],
        courses=[
            {"name": "이산수학", "category": "전공필수", "credits": 20.0},
            {"name": "프로그래밍", "category": "전공선택", "credits": 40.0},
            {"name": "일반수학", "category": "교양", "credits": 50.0},
        ]
    )

    # 3. 부전공 학생 (CS 주전공 + Math 부전공)
    # Math 부전공 요건(전공필수 21학점) 테스트.
    # 참고: StudentCourseRecord의 category가 '전공필수'면 engine에서 major_required로 집계됨.
    # 현재 엔진은 과목별로 주전공/부전공을 구분하지 않고 합산하여 처리하는 구조적 한계가 있을 수 있음.
    # (이를 확인하기 위해 테스트)
    u3 = add_student_scenario(
        db, "부전공학생",
        programs=[
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"},
            {"code": "MATH01", "type": "minor", "major": "수학과"}
        ],
        courses=[
            {"name": "CS전필", "category": "전공필수", "credits": 40.0},
            {"name": "CS전선", "category": "전공선택", "credits": 30.0},
            {"name": "교양", "category": "교양", "credits": 35.0},
            {"name": "수학부전공", "category": "전공필수", "credits": 21.0}, # 부전공 학점
        ]
    )

    # 4. 복수전공 학생 (CS 주전공 + Math 복수전공)
    u4 = add_student_scenario(
        db, "복수전공학생",
        programs=[
            {"code": "CS01", "type": "primary", "major": "컴퓨터공학과"},
            {"code": "MATH01", "type": "dual", "major": "수학과"}
        ],
        courses=[
            {"name": "CS전필", "category": "전공필수", "credits": 40.0},
            {"name": "CS전선", "category": "전공선택", "credits": 30.0},
            {"name": "교양", "category": "교양", "credits": 35.0},
            {"name": "수학전필", "category": "전공필수", "credits": 35.0},
            {"name": "수학전선", "category": "전공선택", "credits": 20.0},
        ]
    )

    users = [u1, u2, u3, u4]

    for user in users:
        print(f"--- [ 시나리오: {user.name} ] ---")
        results = evaluate_graduation(db, user.id)
        for res in results:
            print(f"프로그램: {res.major} ({res.program_type}) - 평가상태: {res.status}")
            for warning in res.warnings:
                print(f"  [경고] {warning}")
            for cat in res.categories:
                status_str = "통과" if cat.satisfied else "미달" if cat.satisfied is False else "판정불가"
                print(f"  카테고리: {cat.category_name} (필요: {cat.minimum_credits}, 이수: {cat.earned_credits}) -> {status_str}")
        print("\n")

if __name__ == "__main__":
    run_scenarios()
