"""학번/비밀번호 회원가입·로그인.

로그인 식별자는 학번(student_id)이다 — 이메일은 쓰지 않는다(2026-07-14 변경,
와이어프레임 "1b. 로그인 → 학생정보 입력" 참고). docs/backend/features/core-auth.md
참고. 소셜 로그인(auth_accounts)은 아직 없음.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.domains.academics.hierarchy import resolve_hierarchy
from app.domains.academics.models import Department, Major, UserAcademicProgram
from app.domains.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# 주전공/복수전공/부전공/연계전공 — UserAcademicProgram.program_type과 값 일치시킴
_VALID_PROGRAM_TYPES = {"primary", "dual", "minor", "interdisciplinary"}


class AcademicProgramInput(BaseModel):
    major: str
    # 비워두면 SignupRequest의 최상위 school/college/department를 사용한다.
    school: str | None = None
    college: str | None = None
    department: str | None = None
    program_type: str = "primary"

    @field_validator("program_type")
    @classmethod
    def _check_program_type(cls, v: str) -> str:
        if v not in _VALID_PROGRAM_TYPES:
            raise ValueError(f"program_type은 {sorted(_VALID_PROGRAM_TYPES)} 중 하나여야 합니다")
        return v


class SignupRequest(BaseModel):
    student_id: str
    password: str
    name: str
    school: str | None = None
    college: str | None = None
    department: str | None = None
    career_goal: str | None = None
    # 주전공 하나, 복수전공/부전공 여러 개까지 한 번에 등록 가능
    academic_programs: list[AcademicProgramInput] = []


class LoginRequest(BaseModel):
    student_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AcademicProgramResponse(BaseModel):
    major: str
    program_type: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    name: str
    student_id: str | None
    department: str | None
    major: str | None
    career_goal: str | None
    academic_programs: list[AcademicProgramResponse] = []

    model_config = {"from_attributes": True}


def _department_name(db: Session, department_id: int | None) -> str | None:
    if department_id is None:
        return None
    department = db.get(Department, department_id)
    return department.name if department else None


def _major_name(db: Session, major_id: int | None) -> str | None:
    if major_id is None:
        return None
    major = db.get(Major, major_id)
    return major.name if major else None


def _load_user_response(db: Session, user: User) -> UserResponse:
    programs = db.scalars(
        select(UserAcademicProgram).where(UserAcademicProgram.user_id == user.id)
    ).all()
    return UserResponse(
        id=user.id,
        name=user.name,
        student_id=user.student_id,
        department=_department_name(db, user.department_id),
        major=_major_name(db, user.major_id),
        career_goal=user.career_goal,
        academic_programs=[
            AcademicProgramResponse(
                major=_major_name(db, p.major_id) or "",
                program_type=p.program_type,
            )
            for p in programs
        ],
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다")

    existing = db.scalar(select(User).where(User.student_id == payload.student_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 학번입니다")

    top_department_id, _ = resolve_hierarchy(
        db, payload.school, payload.college, payload.department, None
    )

    user = User(
        password_hash=hash_password(payload.password),
        name=payload.name,
        student_id=payload.student_id,
        department_id=top_department_id,
        career_goal=payload.career_goal,
    )
    db.add(user)
    db.flush()

    for program in payload.academic_programs:
        program_department_id, program_major_id = resolve_hierarchy(
            db,
            program.school or payload.school,
            program.college or payload.college,
            program.department or payload.department,
            program.major,
        )
        db.add(
            UserAcademicProgram(
                user_id=user.id,
                department_id=program_department_id,
                major_id=program_major_id,
                program_type=program.program_type,
            )
        )
        if program.program_type == "primary" and program_major_id:
            user.major_id = program_major_id

    db.commit()
    db.refresh(user)
    return _load_user_response(db, user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.student_id == payload.student_id))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="학번 또는 비밀번호가 올바르지 않습니다")

    return TokenResponse(access_token=create_access_token(user.id))


def get_current_user(
    token: str | None = Depends(_oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthorized

    user_id = decode_access_token(token)
    if user_id is None:
        raise unauthorized

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _load_user_response(db, current_user)
