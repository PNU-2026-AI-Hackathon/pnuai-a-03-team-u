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
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    # 학부제로 다전공(복수전공/부전공)까지 나뉘는 경우의 세부 전공.
    # "OO과"처럼 학과 자체가 곧 전공이라 세부 전공 구분이 없으면 null.
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    career_goal: Mapped[str | None] = mapped_column(String(255))
    advisor_consulted: Mapped[bool] = mapped_column(default=False)
    # One-Stop 포털 학적부(fetch_student_record)의 "지도교수" 필드에서 크롤링.
    # 없으면 아직 동기화 전이거나 지도교수가 아직 배정되지 않은 것.
    advisor_name: Mapped[str | None] = mapped_column(String(100))


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


class UserActivity(TimestampMixin, Base):
    """비교과 활동. 동아리/인턴/봉사 같은 외부활동과 공모전/수상을 하나로 합친 테이블.

    "내 정보" 페이지의 비교과 활동 리스트가 이 둘을 구분 없이 하나의 목록으로
    보여줘서(기관명/설명/링크만 있으면 됨) 굳이 두 테이블로 나눌 이유가 없었다.
    """

    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255))
    # 자유 텍스트 분류(예: "동아리", "공모전", "인턴", "프로젝트"). 정해진 값 집합 없음.
    category: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(100))
    award: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)


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
