"""부산대 웹메일 기반 회원가입과 로그인.

로그인 아이디는 학번이 아니라 부산대 웹메일(@pusan.ac.kr)이다. 부산대 구성원
여부를 도메인으로 1차 확인하기 위한 것으로, 7/3 회의 "주제 4. 아이디 변경"
결정 사항이다. 학번은 로그인 수단이 아니라 학사 크롤링용 식별자로만 남는다.

docs/backend/features/core-auth.md 참고. 소셜 로그인(auth_accounts)은 아직 없음.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
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

# 부산대 웹메일 도메인. 신규 가입에만 적용하고, 이미 다른 도메인으로 가입한
# 계정의 로그인까지 막지는 않는다.
PNU_EMAIL_DOMAIN = "@pusan.ac.kr"


class AcademicProgramInput(BaseModel):
    # 학과 자체가 전공 단위인 경우에는 major를 만들지 않고 department만 저장한다.
    major: str | None = None
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
    email: EmailStr
    password: str
    name: str
    student_id: str
    academic_year: int | None = Field(default=None, ge=1, le=6)
    school: str | None = None
    college: str | None = None
    department: str | None = None
    career_goal: str | None = None
    # 주전공 하나, 복수전공/부전공 여러 개까지 한 번에 등록 가능
    academic_programs: list[AcademicProgramInput] = []

    @field_validator("student_id")
    @classmethod
    def _check_student_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("학번을 입력해야 합니다")
        return value

    @field_validator("email")
    @classmethod
    def _check_pnu_email(cls, value: str) -> str:
        if not value.lower().endswith(PNU_EMAIL_DOMAIN):
            raise ValueError(f"부산대 웹메일({PNU_EMAIL_DOMAIN})로만 가입할 수 있습니다")
        return value.lower()


class LoginRequest(BaseModel):
    """로그인 아이디는 부산대 웹메일. 프론트는 아이디 + 고정 도메인으로 조합해 보낸다."""

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AcademicProgramResponse(BaseModel):
    major: str
    program_type: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    student_id: str | None
    department: str | None
    major: str | None
    academic_year: int | None
    career_goal: str | None
    advisor_name: str | None
    advisor_consulted: bool
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
        email=user.email,
        name=user.name,
        student_id=user.student_id,
        department=_department_name(db, user.department_id),
        major=_major_name(db, user.major_id),
        academic_year=user.academic_year,
        career_goal=user.career_goal,
        advisor_name=user.advisor_name,
        advisor_consulted=user.advisor_consulted,
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

    existing = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다")

    existing_student = db.scalar(select(User).where(User.student_id == payload.student_id))
    if existing_student is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 학번입니다")

    top_department_id, _ = resolve_hierarchy(
        db, payload.school, payload.college, payload.department, None
    )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        student_id=payload.student_id,
        academic_year=payload.academic_year,
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
    # 기존 계정 중 대소문자가 섞인 이메일이 있어 소문자로 맞춰 비교한다.
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

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
