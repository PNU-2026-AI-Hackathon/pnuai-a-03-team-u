"""add course_descriptions

학과가 예전에 공개한 "교과목개요" 원문(과목명+설명)을 저장한다. 과목명이 개편으로
바뀌거나 없어진 경우가 섞여 있어 courses.id에 직접 FK로 고정하지 않고, 조회 시점에
이름을 정규화해 courses와 라이브 매칭한다 (app/domains/courses/course_description_matching.py).

Revision ID: 636a0efff10d
Revises: c9d0e1f2a3b4
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '636a0efff10d'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'course_descriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('source_course_name', sa.String(length=255), nullable=False),
        sa.Column('normalized_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('source_document', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
        sa.ForeignKeyConstraint(['major_id'], ['majors.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'department_id', 'major_id', 'normalized_name',
            name='uq_course_description_dept_major_name',
        ),
    )
    op.create_index(
        op.f('ix_course_descriptions_department_id'),
        'course_descriptions',
        ['department_id'],
    )
    op.create_index(
        op.f('ix_course_descriptions_major_id'),
        'course_descriptions',
        ['major_id'],
    )
    op.create_index(
        op.f('ix_course_descriptions_normalized_name'),
        'course_descriptions',
        ['normalized_name'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('course_descriptions')
