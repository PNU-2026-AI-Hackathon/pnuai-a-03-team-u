"""drop department_name/major_name/category/credits from course_roadmap_items

course_name만 스냅샷으로 남기고 나머지는 course_id가 있을 때 courses
(+departments+majors) join으로 가져오는 방식으로 바꾼다. course_id가
없거나 모호한(동명 과목 여러 학과 존재) 경우가 실제로 흔해서 course_name은
계속 스냅샷으로 유지한다.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('course_roadmap_items', 'department_name')
    op.drop_column('course_roadmap_items', 'major_name')
    op.drop_column('course_roadmap_items', 'category')
    op.drop_column('course_roadmap_items', 'credits')


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("스냅샷 필드 제거는 downgrade를 지원하지 않습니다.")
