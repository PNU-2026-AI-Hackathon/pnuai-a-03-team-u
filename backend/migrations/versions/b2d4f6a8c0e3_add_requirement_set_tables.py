"""add requirement_sets/categories/courses tables

프로그램(학과/전공)×이수유형(program_type)×교육과정연도별 졸업요건 세트와
카테고리(학점 규칙)/과목 후보 테이블. codex/graduation-academic-programs
브랜치(세션#15 정리본)의 스키마를 main 계층 위로 포팅하면서 확장:

- scope='university_default' + academic_program_code IS NULL 행으로 학사운영규정의
  대학 공통 기본규칙(부전공 21학점/필수 9학점 등)을 표현한다.
- offering_status='not_offered' 행으로 규정상 부전공/복수전공 불가 학과를 표현한다.
- department_id/major_id FK로 main 계층과 연결한다(학과 단위 조회는
  major_id IS NULL 필터 필수).
- 교직은 program_type이 아니라 primary 세트의 teacher_training_basic(△)/
  teacher_training_pedagogy(□, 8학점) 카테고리로 표현한다.

Revision ID: b2d4f6a8c0e3
Revises: a1c3e5b7d9f2
Create Date: 2026-07-09 12:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e3'
down_revision: Union[str, Sequence[str], None] = 'a1c3e5b7d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'requirement_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), server_default='program', nullable=False),
        sa.Column('academic_program_code', sa.String(length=50), nullable=True),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('program_type', sa.String(length=20), nullable=False),
        sa.Column('curriculum_year', sa.String(length=10), nullable=False),
        sa.Column('offering_status', sa.String(length=20), server_default='offered', nullable=False),
        sa.Column('offering_note', sa.Text(), nullable=True),
        sa.Column('required_total_credits', sa.Integer(), nullable=True),
        sa.Column('rule_metadata', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(scope = 'program') = (academic_program_code IS NOT NULL)",
            name='ck_requirement_sets_scope_code',
        ),
        sa.ForeignKeyConstraint(
            ['academic_program_code'], ['academic_programs.academic_program_code']
        ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
        sa.ForeignKeyConstraint(['major_id'], ['majors.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'academic_program_code',
            'program_type',
            'curriculum_year',
            name='uq_requirement_sets_program_type_year',
        ),
    )
    op.create_index(
        op.f('ix_requirement_sets_academic_program_code'),
        'requirement_sets',
        ['academic_program_code'],
    )
    op.create_index(op.f('ix_requirement_sets_department_id'), 'requirement_sets', ['department_id'])
    op.create_index(op.f('ix_requirement_sets_major_id'), 'requirement_sets', ['major_id'])
    op.create_index(op.f('ix_requirement_sets_program_type'), 'requirement_sets', ['program_type'])
    # NULL academic_program_code는 UNIQUE 제약을 타지 않으므로,
    # university_default 행의 중복은 부분 인덱스로 막는다.
    op.create_index(
        'uq_requirement_sets_default',
        'requirement_sets',
        ['program_type', 'curriculum_year'],
        unique=True,
        postgresql_where=sa.text('academic_program_code IS NULL'),
    )

    op.create_table(
        'requirement_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=80), nullable=False),
        sa.Column('requirement_set_id', sa.Integer(), nullable=False),
        sa.Column('category_code', sa.String(length=80), nullable=False),
        sa.Column('category_name', sa.String(length=120), nullable=True),
        sa.Column('minimum_credits', sa.String(length=50), nullable=True),
        sa.Column('rule_type', sa.String(length=80), nullable=True),
        sa.Column('source_kind', sa.String(length=80), nullable=True),
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
        sa.UniqueConstraint('external_id', name='uq_requirement_categories_external_id'),
    )
    op.create_index(
        op.f('ix_requirement_categories_external_id'), 'requirement_categories', ['external_id']
    )
    op.create_index(
        op.f('ix_requirement_categories_requirement_set_id'),
        'requirement_categories',
        ['requirement_set_id'],
    )
    op.create_index(
        op.f('ix_requirement_categories_category_code'), 'requirement_categories', ['category_code']
    )
    op.create_index(
        op.f('ix_requirement_categories_needs_review'), 'requirement_categories', ['needs_review']
    )

    op.create_table(
        'requirement_courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=80), nullable=False),
        sa.Column('requirement_set_id', sa.Integer(), nullable=False),
        sa.Column('curriculum_year', sa.String(length=10), nullable=True),
        sa.Column('category_code', sa.String(length=80), nullable=True),
        sa.Column('recommended_year', sa.String(length=20), nullable=True),
        sa.Column('recommended_semester', sa.String(length=20), nullable=True),
        sa.Column('raw_course_code', sa.Text(), nullable=True),
        sa.Column('raw_course_name', sa.String(length=255), nullable=True),
        sa.Column('raw_credit', sa.String(length=50), nullable=True),
        sa.Column('matched_course_code', sa.Text(), nullable=True),
        sa.Column('matched_course_name', sa.String(length=255), nullable=True),
        sa.Column('match_status', sa.String(length=50), nullable=True),
        sa.Column('match_method', sa.String(length=100), nullable=True),
        sa.Column('matched_terms', sa.Text(), nullable=True),
        sa.Column('matched_departments', sa.Text(), nullable=True),
        sa.Column('choice_rule_types', sa.String(length=200), nullable=True),
        sa.Column('choice_rule_raw', sa.Text(), nullable=True),
        sa.Column('source_table', sa.String(length=100), nullable=True),
        sa.Column('source_file', sa.String(length=1000), nullable=True),
        sa.Column('needs_review', sa.Boolean(), nullable=False),
        sa.Column('review_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['requirement_set_id'], ['requirement_sets.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id', name='uq_requirement_courses_external_id'),
    )
    op.create_index(
        op.f('ix_requirement_courses_external_id'), 'requirement_courses', ['external_id']
    )
    op.create_index(
        op.f('ix_requirement_courses_requirement_set_id'),
        'requirement_courses',
        ['requirement_set_id'],
    )
    op.create_index(
        op.f('ix_requirement_courses_curriculum_year'), 'requirement_courses', ['curriculum_year']
    )
    op.create_index(
        op.f('ix_requirement_courses_category_code'), 'requirement_courses', ['category_code']
    )
    op.create_index(
        op.f('ix_requirement_courses_matched_course_code'),
        'requirement_courses',
        ['matched_course_code'],
    )
    op.create_index(
        op.f('ix_requirement_courses_match_status'), 'requirement_courses', ['match_status']
    )
    op.create_index(
        op.f('ix_requirement_courses_needs_review'), 'requirement_courses', ['needs_review']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('requirement_courses')
    op.drop_table('requirement_categories')
    op.drop_table('requirement_sets')
