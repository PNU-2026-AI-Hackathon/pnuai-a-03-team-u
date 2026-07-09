"""add requirement condition group tables (택N/M)

부전공 교육과정표의 "부전공필수과목(택3/9)" 같은 택N/M형 이수 조건을 담는
2-테이블 구조(조건그룹 + 후보과목). 부전공에서 출발했지만 전 program_type에
공통으로 쓴다. 원본 shape은 raw_data canonical CSV
(minor_requirement_condition_groups_2026.csv / ..._group_courses_2026.csv).

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e3
Create Date: 2026-07-09 12:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f4'
down_revision: Union[str, Sequence[str], None] = 'b2d4f6a8c0e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'requirement_condition_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=120), nullable=False),
        sa.Column('requirement_set_id', sa.Integer(), nullable=False),
        sa.Column('category_code', sa.String(length=80), nullable=True),
        sa.Column('condition_type', sa.String(length=50), nullable=False),
        sa.Column('group_name', sa.String(length=255), nullable=True),
        sa.Column('rule_summary', sa.Text(), nullable=True),
        sa.Column('min_courses', sa.Integer(), nullable=True),
        sa.Column('min_credits', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('max_courses', sa.Integer(), nullable=True),
        sa.Column('max_credits', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('excess_allowed', sa.Boolean(), nullable=True),
        sa.Column('source_text', sa.Text(), nullable=True),
        sa.Column('source_file', sa.String(length=1000), nullable=True),
        sa.Column('needs_review', sa.Boolean(), nullable=False),
        sa.Column('review_reason', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['requirement_set_id'], ['requirement_sets.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id', name='uq_requirement_condition_groups_external_id'),
    )
    op.create_index(
        op.f('ix_requirement_condition_groups_external_id'),
        'requirement_condition_groups',
        ['external_id'],
    )
    op.create_index(
        op.f('ix_requirement_condition_groups_requirement_set_id'),
        'requirement_condition_groups',
        ['requirement_set_id'],
    )
    op.create_index(
        op.f('ix_requirement_condition_groups_category_code'),
        'requirement_condition_groups',
        ['category_code'],
    )
    op.create_index(
        op.f('ix_requirement_condition_groups_needs_review'),
        'requirement_condition_groups',
        ['needs_review'],
    )

    # 원본 CSV에 행 단위 external_id가 없어 행 unique 제약을 두지 않는다 —
    # 시드는 그룹 단위 delete-and-reinsert로 멱등성을 확보한다.
    op.create_table(
        'requirement_condition_group_courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('condition_group_id', sa.Integer(), nullable=False),
        sa.Column('course_role', sa.String(length=30), server_default='candidate', nullable=False),
        sa.Column('raw_course_name', sa.String(length=255), nullable=True),
        sa.Column('course_code', sa.Text(), nullable=True),
        sa.Column('course_name', sa.String(length=255), nullable=True),
        sa.Column('credits', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('category_code', sa.String(length=80), nullable=True),
        sa.Column('match_status', sa.String(length=50), nullable=True),
        sa.Column('recognition_status', sa.String(length=50), nullable=True),
        sa.Column('source_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['condition_group_id'], ['requirement_condition_groups.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_requirement_condition_group_courses_condition_group_id'),
        'requirement_condition_group_courses',
        ['condition_group_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('requirement_condition_group_courses')
    op.drop_table('requirement_condition_groups')
