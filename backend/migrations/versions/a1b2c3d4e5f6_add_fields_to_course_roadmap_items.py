"""add category/credits/status/is_confirmed to course_roadmap_items

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-07-08 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('course_roadmap_items', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column('course_roadmap_items', sa.Column('credits', sa.Float(), nullable=True))
    op.add_column(
        'course_roadmap_items',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='planned'),
    )
    op.add_column(
        'course_roadmap_items',
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('course_roadmap_items', 'status', server_default=None)
    op.alter_column('course_roadmap_items', 'is_confirmed', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('course_roadmap_items', 'is_confirmed')
    op.drop_column('course_roadmap_items', 'status')
    op.drop_column('course_roadmap_items', 'credits')
    op.drop_column('course_roadmap_items', 'category')
