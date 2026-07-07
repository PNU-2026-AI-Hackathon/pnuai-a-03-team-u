import datetime

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    student_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    school: Mapped[str | None] = mapped_column(String(100))
    # 단과대학(예: "정보의생명공학대학"). 소속학과 원문에 단과대가 없으면 null.
    college: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    # 학부제로 다전공(복수전공/부전공)까지 나뉘는 경우의 세부 전공명.
    # "OO과"처럼 학과 자체가 곧 전공이라 세부 전공 구분이 없으면 null.
    major: Mapped[str | None] = mapped_column(String(200))
    career_goal: Mapped[str | None] = mapped_column(String(255))
    advisor_consulted: Mapped[bool] = mapped_column(default=False)


class PortalCredential(TimestampMixin, Base):
    """학교 포털(One-Stop 등) 자동 크롤링을 위한 계정정보.

    비밀번호는 평문 저장하지 않고 app.core.security.encrypt_secret()으로
    암호화한 값만 저장한다.
    """

    __tablename__ = "portal_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    portal: Mapped[str] = mapped_column(String(50), default="pnu_onestop")
    login_id: Mapped[str] = mapped_column(String(100))
    encrypted_password: Mapped[str] = mapped_column(String(500))


class UserExternalActivity(TimestampMixin, Base):
    """외부활동(동아리/인턴/봉사 등)."""

    __tablename__ = "user_external_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)


class UserCompetition(TimestampMixin, Base):
    """내부활동/공모전 참가 및 수상 이력."""

    __tablename__ = "user_competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    award: Mapped[str | None] = mapped_column(String(100))
    held_at: Mapped[datetime.date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)


class UserCertification(TimestampMixin, Base):
    """자격증 보유 이력."""

    __tablename__ = "user_certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime.date | None] = mapped_column(Date)


class UserLanguageScore(TimestampMixin, Base):
    """어학 성적 보유 이력."""

    __tablename__ = "user_language_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    test_name: Mapped[str] = mapped_column(String(100))
    score: Mapped[str] = mapped_column(String(50))
    expires_at: Mapped[datetime.date | None] = mapped_column(Date)
