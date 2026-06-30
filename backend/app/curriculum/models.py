from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class RequirementSet(TimestampMixin, Base):
    """학과/전공/교육과정연도별 졸업요건 세트. curriculum 모듈이 규칙을 보관하며,
    실제 충족여부 계산은 graduation_engine이 담당한다 (이 모델은 규칙 저장용).
    """

    __tablename__ = "requirement_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    program_type: Mapped[str | None] = mapped_column(String(20))
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(String(255))
    required_total_credits: Mapped[int | None] = mapped_column()
    rule_metadata: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
