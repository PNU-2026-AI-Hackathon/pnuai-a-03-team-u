"""add general_education_area to courses

Revision ID: 5ae96e0e4d56
Revises: 2df2a992d532
Create Date: 2026-08-23 00:13:56.783002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ae96e0e4d56'
down_revision: Union[str, Sequence[str], None] = '2df2a992d532'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 이번 리비전과 무관한 인덱스 drop(uq_graduation_requirements_scope, ix_rag_chunks_embedding)은
    # autogenerate가 로컬 DB와 모델 메타데이터 차이로 잘못 잡아낸 것이라 제거했다 — 실제 스키마엔
    # 그대로 있고, 이 리비전은 courses.general_education_area 추가만 한다.
    op.add_column('courses', sa.Column('general_education_area', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('courses', 'general_education_area')
