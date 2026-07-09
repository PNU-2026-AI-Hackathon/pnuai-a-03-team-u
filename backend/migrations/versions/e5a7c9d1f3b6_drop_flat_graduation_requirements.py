"""drop flat graduation_requirements table

flat 스텁(graduation_requirements)은 코드 참조가 없고 라이브에서도 빈
테이블이며, requirement_sets/requirement_categories/requirement_courses가
역할을 대체하므로 제거한다.

Revision ID: e5a7c9d1f3b6
Revises: d4f6b8c0e2a5
Create Date: 2026-07-09 12:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9d1f3b6'
down_revision: Union[str, Sequence[str], None] = 'd4f6b8c0e2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('graduation_requirements')


def downgrade() -> None:
    """Downgrade schema."""
    # e6f7a8b9c0d1(hierarchy) 이후 시점의 형태로 재생성한다. 빈 테이블이라 무손실.
    op.create_table(
        'graduation_requirements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('program_type', sa.String(length=20), nullable=True),
        sa.Column('curriculum_year', sa.String(length=10), nullable=True),
        sa.Column('required_total_credits', sa.Integer(), nullable=True),
        sa.Column('required_major_foundation', sa.Integer(), nullable=True),
        sa.Column('required_major_required', sa.Integer(), nullable=True),
        sa.Column('required_major_elective', sa.Integer(), nullable=True),
        sa.Column('required_general_required', sa.Integer(), nullable=True),
        sa.Column('required_general_elective', sa.Integer(), nullable=True),
        sa.Column('required_free_elective', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_graduation_requirements_department_id'),
        'graduation_requirements',
        ['department_id'],
    )
    op.create_index(
        op.f('ix_graduation_requirements_major_id'), 'graduation_requirements', ['major_id']
    )
    op.create_foreign_key(
        'fk_gr_department_id', 'graduation_requirements', 'departments', ['department_id'], ['id']
    )
    op.create_foreign_key('fk_gr_major_id', 'graduation_requirements', 'majors', ['major_id'], ['id'])
