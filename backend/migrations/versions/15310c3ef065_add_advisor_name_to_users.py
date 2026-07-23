"""add advisor_name to users

One-Stop 포털 학적부(fetch_student_record)의 "지도교수" 필드에서 크롤링한
지도교수명을 저장한다.

Revision ID: 15310c3ef065
Revises: 62dfead1f66c
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '15310c3ef065'
down_revision: Union[str, Sequence[str], None] = '62dfead1f66c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('advisor_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'advisor_name')
