"""add advisor_consulted to users (missed in reset migration)

users 테이블은 스키마 리셋 때 drop 대상에서 빠져 있어 새 모델의
advisor_consulted 컬럼이 누락되었다. 여기서 보완한다.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-07 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('advisor_consulted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'advisor_consulted', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'advisor_consulted')
