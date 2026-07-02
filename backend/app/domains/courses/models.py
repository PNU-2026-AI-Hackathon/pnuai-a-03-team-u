from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    course_code: Mapped[str | None] = mapped_column(String(50), index=True)
    course_name: Mapped[str] = mapped_column(String(255))
    # department/major: 원본 텍스트 그대로 보존(크롤러가 채움, 표시용).
    # department_id: departments 테이블 FK — 검증/조인은 이쪽을 기준으로 한다.
    department: Mapped[str | None] = mapped_column(String(200))
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    major: Mapped[str | None] = mapped_column(String(200))
    default_category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column()
