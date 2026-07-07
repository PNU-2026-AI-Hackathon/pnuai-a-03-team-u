"""drop activity recommendation tables (feature to be redesigned later)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-07 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('DROP TABLE IF EXISTS "user_activity_recommendations" CASCADE')
    op.execute('DROP TABLE IF EXISTS "activities" CASCADE')
    op.execute('DROP TABLE IF EXISTS "extracurricular_programs" CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("추천활동 테이블 삭제는 downgrade를 지원하지 않습니다.")
