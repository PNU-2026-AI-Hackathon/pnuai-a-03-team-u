"""add department_name to roadmap items, summary to course_roadmaps

시간표 추천(course_plans/course_plan_items)은 나중에 별도로 구현할
예정이라 여기서는 건드리지 않는다.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-08 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('course_roadmap_items', sa.Column('department_name', sa.String(length=200), nullable=True))
    op.add_column('course_roadmaps', sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('course_roadmaps', 'summary')
    op.drop_column('course_roadmap_items', 'department_name')
