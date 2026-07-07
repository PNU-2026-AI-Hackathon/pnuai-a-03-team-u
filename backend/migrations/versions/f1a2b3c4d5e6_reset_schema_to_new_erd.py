"""reset schema to new ERD

기존 스키마(구 domains 구조 + 팀원 미머지 브랜치가 공유 DB에 직접 적용한
academic_programs/requirement_categories 등)를 전부 지우고, 새 ERD 기준
스키마로 다시 만든다. 팀 상의 후 실행할 것 — 기존 크롤링 데이터
(activities, user_activity_recommendations 제외 나머지)가 모두 사라진다.

Revision ID: f1a2b3c4d5e6
Revises: 3c9d5e1a7f24
Create Date: 2026-07-07 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '3c9d5e1a7f24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 지금까지 main/팀원 브랜치를 통틀어 존재했던 모든 구 테이블.
# activities / user_activity_recommendations는 실사용 중인 기능이라 제외(유지).
_OLD_TABLES = [
    "departments",
    "requirement_sets",
    "graduation_audits",
    "graduation_audit_program_results",
    "academic_programs",
    "academic_program_aliases",
    "department_academic_program_mappings",
    "requirement_categories",
    "requirement_courses",
    "requirement_text_rules",
    # 기존 이름 그대로 재생성되는 테이블도 컬럼 구조가 바뀌었으므로 drop 후 재생성
    "courses",
    "student_course_records",
    "user_academic_programs",
]


def upgrade() -> None:
    """Upgrade schema."""
    for table in _OLD_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')

    # 새 ERD 기준 스키마 전체를 SQLAlchemy 모델 메타데이터로 생성한다.
    # (activities 도메인은 이미 존재하므로 create_all이 자동으로 건너뛴다.)
    import app.domains.academics.models  # noqa: F401
    import app.domains.activities.models  # noqa: F401
    import app.domains.content.models  # noqa: F401
    import app.domains.courses.models  # noqa: F401
    import app.domains.planning.models  # noqa: F401
    import app.domains.users.models  # noqa: F401
    from app.core.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("전면 리셋 마이그레이션은 downgrade를 지원하지 않습니다.")
