from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    course_code: Mapped[str | None] = mapped_column(String(50), index=True)
    course_name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    default_category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column()
