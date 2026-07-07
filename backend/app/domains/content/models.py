from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class AcademicInfoArticle(TimestampMixin, Base):
    """수강신청/휴복학/졸업/장학/복수전공 등 학사정보 안내 글."""

    __tablename__ = "academic_info_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

# 비교과 프로그램 추천(ExtracurricularProgram)은 추천활동 기능을 나중에
# 다시 설계해서 구현할 예정이라 지금은 테이블을 두지 않는다.
