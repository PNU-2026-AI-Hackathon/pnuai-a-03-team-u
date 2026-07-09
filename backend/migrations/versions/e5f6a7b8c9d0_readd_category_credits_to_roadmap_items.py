"""re-add category/credits to course_roadmap_items as write-time snapshots

department_name/major_name(모호할 수 있어 join 방식 유지)와 달리
category/credits는 쓰는 시점(과거 이력=StudentCourseRecord, 신규/수정=
선택한 course_id)에 이미 확정된 값이라 스냅샷으로 다시 넣는다. 과거 이력은
성적표 원본에 학점이 정확히 있는데, course_id가 unmatched인 경우가 흔해서
join만으로는 학점을 못 보여주는 문제가 있었다.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-08 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('course_roadmap_items', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column('course_roadmap_items', sa.Column('credits', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('course_roadmap_items', 'credits')
    op.drop_column('course_roadmap_items', 'category')
