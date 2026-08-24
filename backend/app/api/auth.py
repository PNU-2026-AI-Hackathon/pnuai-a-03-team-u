"""부산대 웹메일 기반 회원가입과 로그인.

로그인 아이디는 학번이 아니라 부산대 웹메일(@pusan.ac.kr)이다. 부산대 구성원
여부를 도메인으로 1차 확인하기 위한 것으로, 7/3 회의 "주제 4. 아이디 변경"
결정 사항이다. 학번은 로그인 수단이 아니라 학사 크롤링용 식별자로만 남는다.

docs/backend/features/core-auth.md 참고. 소셜 로그인(auth_accounts)은 아직 없음.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import (
    LOGIN_LIMIT, PASSWORD_RESET_LIMIT, SIGNUP_LIMIT, limiter,
)
from app.core.mailer import send_password_reset_email
from app.core.security import (
    create_access_token, decode_access_token, hash_password,
    password_fingerprint, verify_password,
)
from app.domains.academics.hierarchy import resolve_hierarchy
from app.domains.academics.models import Department, Major, UserAcademicProgram
from app.domains.users.admission import AdmissionType, normalize_admission_type
from app.domains.users.models import PasswordResetToken, User

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
    # "freshman" | "transfer". 편입생은 1·2학년 커리큘럼을 밟지 않아 로드맵 구성이 다르다.
    admission_type: AdmissionType = "freshman"
    school: str | None = None
    college: str | None = None
    department: str | None = None
    career_goal: str | None = None
    # 주전공 하나, 복수전공/부전공 여러 개까지 한 번에 등록 가능
    academic_programs: list[AcademicProgramInput] = []
    # 개인정보 수집·이용 및 LLM/Langfuse 처리위탁 동의 체크박스. 프론트가 필수로
    # 막아도 서버에서 다시 검증한다 — 클라이언트 검증만 믿으면 API 직접 호출로
    # 우회된다.
    privacy_consent: bool

    @field_validator("privacy_consent")
    @classmethod
    def _check_privacy_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("개인정보 수집·이용에 동의해야 가입할 수 있습니다")
        return value

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


class PasswordResetRequest(BaseModel):
    """재설정 링크를 받을 부산대 웹메일 + 본인 이름."""

    email: EmailStr
    name: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("이름을 입력해야 합니다")
        return value


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

    @field_validator("token")
    @classmethod
    def _check_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("토큰이 필요합니다")
        return value


class MessageResponse(BaseModel):
    message: str


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
    # 옛 행은 NULL일 수 있어 "transfer가 아니면 신입학"으로 정규화해서 내려준다.
    # 프론트가 null 분기를 따로 하지 않아도 되게 하려는 것이다.
    admission_type: AdmissionType
    career_goal: str | None
    advisor_name: str | None
    advisor_consulted: bool
    privacy_consent: bool
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
        admission_type=normalize_admission_type(user.admission_type),
        career_goal=user.career_goal,
        advisor_name=user.advisor_name,
        advisor_consulted=user.advisor_consulted,
        privacy_consent=user.privacy_consent,
        academic_programs=[
            AcademicProgramResponse(
                major=_major_name(db, p.major_id) or "",
                program_type=p.program_type,
            )
            for p in programs
        ],
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(SIGNUP_LIMIT)
def signup(request: Request, payload: SignupRequest, db: Session = Depends(get_db)):
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
        admission_type=payload.admission_type,
        department_id=top_department_id,
        career_goal=payload.career_goal,
        # 스키마 검증(_check_privacy_consent)을 통과했으므로 이 시점엔 항상 True다.
        privacy_consent=True,
        privacy_consent_at=datetime.datetime.now(datetime.UTC),
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
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    # 기존 계정 중 대소문자가 섞인 이메일이 있어 소문자로 맞춰 비교한다.
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    # 보존기간 정책이 '장기 미접속'을 판단하는 유일한 근거다(P2). 실패한 로그인은
    # 스탬프하지 않는다 — 남의 계정에 로그인 시도만 해도 파기가 미뤄지면 안 된다.
    user.last_login_at = datetime.datetime.now(datetime.UTC)
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id, user.password_hash))


def _hash_reset_token(token: str) -> str:
    """토큰 원문 대신 저장/조회에 쓸 sha256 해시.

    bcrypt가 아니라 sha256인 이유: 토큰은 사람이 만든 비밀번호와 달리 128비트
    난수라 사전 공격 대상이 아니고, 조회 때마다 해시를 다시 계산해 인덱스로 찾아야 한다.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/password-reset/request", response_model=MessageResponse)
@limiter.limit(PASSWORD_RESET_LIMIT)
def request_password_reset(request: Request, payload: PasswordResetRequest,
                            background_tasks: BackgroundTasks,
                            db: Session = Depends(get_db)):
    """웹메일과 이름이 모두 일치할 때만 재설정 링크를 메일로 보낸다.

    메일·이름이 맞지 않아도, 가입되지 않은 주소여도 응답은 항상 같다. 응답이
    갈리면 "이 메일이 가입돼 있는가"를 확인하는 수단이 되기 때문이다(사용자 열거).
    실제 본인확인은 어차피 메일 수신으로 이뤄지고, 이름은 그 앞단의 추가 확인이다.

    **메일 발송은 응답 뒤로 미룬다.** SMTP 왕복이 요청 안에서 동기로 돌면 사용자는
    버튼을 누른 채 그만큼 기다린다 — 실측 Gmail 4.2초, 발송이 실패하는 상황에서는
    38.6초까지 갔다(2026-08-20). 응답 문구는 성공/실패와 무관하게 고정이라
    (사용자 열거 방지) 발송 결과를 기다릴 이유가 애초에 없다.

    부수 효과로 타이밍 누출도 줄어든다: 예전에는 "메일을 실제로 보낸 경우"만 몇 초
    걸려서, 응답 시간만 재도 가입 여부를 알 수 있었다.
    """
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if user is not None and user.name.strip() != payload.name:
        user = None

    if user is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        # 이전에 발급했고 아직 안 쓴 토큰은 무효화한다. 링크는 항상 최신 것 하나만 살아 있다.
        for stale in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ).all():
            stale.used_at = now

        raw_token = secrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=now + datetime.timedelta(minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES),
            )
        )
        db.commit()

        background_tasks.add_task(
            send_password_reset_email,
            to=user.email,
            reset_url=f"{settings.PASSWORD_RESET_URL_BASE}?token={raw_token}",
            ttl_minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES,
        )

    return MessageResponse(
        message="가입된 메일이라면 비밀번호 재설정 링크를 보냈습니다. 메일함을 확인해 주세요."
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다")

    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_reset_token(payload.token)
        )
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    expired = record is not None and record.expires_at.replace(tzinfo=datetime.timezone.utc) <= now
    if record is None or record.used_at is not None or expired:
        raise HTTPException(
            status_code=400, detail="링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요."
        )

    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="링크가 유효하지 않습니다. 다시 요청해 주세요.")

    user.password_hash = hash_password(payload.new_password)
    record.used_at = now
    db.commit()

    return MessageResponse(message="비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.")


def get_current_user(
    request: Request,
    token: str | None = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthorized

    decoded = decode_access_token(token)
    if decoded is None:
        raise unauthorized
    user_id, fingerprint = decoded

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized

    # 비밀번호가 바뀌었으면 그 전에 발급된 토큰은 즉시 무효 (security.py 토큰 무효화 주석).
    if fingerprint != password_fingerprint(user.password_hash):
        raise unauthorized

    # 레이트 리밋이 IP가 아니라 사용자 단위로 세도록 표시해둔다 (core/ratelimit._user_or_ip).
    # IP로 세면 같은 학교 네트워크·NAT 뒤 학생들이 서로의 몫을 잡아먹는다.
    request.state.user_id = user.id
    return user


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _load_user_response(db, current_user)
