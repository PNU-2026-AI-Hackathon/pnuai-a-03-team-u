"""이메일/비밀번호 회원가입·로그인.

docs/features/core-auth.md 참고. 소셜 로그인(auth_accounts)은 아직 없음.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.domains.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    student_id: str | None = None
    school: str | None = None
    department: str | None = None
    career_goal: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    student_id: str | None
    school: str | None
    department: str | None
    career_goal: str | None

    model_config = {"from_attributes": True}


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다")

    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        student_id=payload.student_id,
        school=payload.school,
        department=payload.department,
        career_goal=payload.career_goal,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
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
def read_me(current_user: User = Depends(get_current_user)):
    return current_user
