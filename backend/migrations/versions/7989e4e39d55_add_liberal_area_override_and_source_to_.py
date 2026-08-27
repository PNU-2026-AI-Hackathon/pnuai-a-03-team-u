"""add liberal_area override and source to student_course_records

Revision ID: 7989e4e39d55
Revises: a17f9c2d8e31
Create Date: 2026-08-27 23:09:27.927348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7989e4e39d55'
down_revision: Union[str, Sequence[str], None] = 'a17f9c2d8e31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 균형/창의교양 세부영역 판정 근거('override' | 'onestop' | 'catalog' | None)와
    # 학생이 직접 고른 값(sync가 덮어쓰지 않는다)을 저장한다.
    op.add_column(
        'student_course_records',
        sa.Column('liberal_area_source', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'student_course_records',
        sa.Column('liberal_area_override', sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('student_course_records', 'liberal_area_override')
    op.drop_column('student_course_records', 'liberal_area_source')
