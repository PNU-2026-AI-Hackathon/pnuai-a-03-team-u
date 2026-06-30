from sqlalchemy import ForeignKey, String
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
    department: Mapped[str | None] = mapped_column(String(200))
    career_goal: Mapped[str | None] = mapped_column(String(255))


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
