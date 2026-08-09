"""add course_plans.title

시간표 화면이 course_plans를 "이름 붙인 시간표 문서"로 쓰기 시작하면서
사용자 표시용 이름이 필요해졌다. 스키마만 있고 아무도 안 쓰던 테이블이라
(0행) 데이터 백필은 없다.

Revision ID: a4b9e7872662
Revises: d963e1473009
Create Date: 2026-08-09 12:30:30.412683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b9e7872662'
down_revision: Union[str, Sequence[str], None] = 'd963e1473009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("course_plans", sa.Column("title", sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("course_plans", "title")
