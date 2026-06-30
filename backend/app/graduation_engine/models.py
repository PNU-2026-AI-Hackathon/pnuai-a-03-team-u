import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class GraduationAudit(TimestampMixin, Base):
    """졸업요건 충족여부 스냅샷. 크롤러가 가져온 졸업요건 원시 데이터를
    summary_json에 그대로 보관해, 추후 graduation_engine의 결정론적
    판정 로직과 비교/검증할 수 있게 한다.
    """

    __tablename__ = "graduation_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    audit_year: Mapped[str | None] = mapped_column(String(10))
    audit_semester: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="crawled")  # crawled/computed
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    crawled_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class GraduationAuditProgramResult(TimestampMixin, Base):
    __tablename__ = "graduation_audit_program_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("graduation_audits.id"), index=True)
    user_academic_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_academic_programs.id"), nullable=True
    )
    requirement_set_id: Mapped[int | None] = mapped_column(ForeignKey("requirement_sets.id"), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON)
