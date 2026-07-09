"""add academic_programs master and hierarchy bridge columns

졸업요건 기준 학사 프로그램 마스터(academic_programs, AIS 편제 코드 기준)와
검색/매칭용 별칭 테이블을 추가하고, 회원가입/조회용 계층(departments/majors)과
잇는 브리지 컬럼(academic_program_code)을 계층 쪽에 추가한다.
설계 근거는 docs/progress/graduation-requirement-schema-redesign.md 참고.

Revision ID: a1c3e5b7d9f2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-09 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c3e5b7d9f2'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'academic_programs',
        sa.Column('academic_program_code', sa.String(length=50), nullable=False),
        sa.Column('survey_year', sa.Integer(), nullable=True),
        sa.Column('survey_round', sa.Integer(), nullable=True),
        sa.Column('school_code', sa.String(length=20), nullable=True),
        sa.Column('school_name', sa.String(length=100), nullable=True),
        sa.Column('campus_code', sa.String(length=20), nullable=True),
        sa.Column('campus_name', sa.String(length=100), nullable=True),
        sa.Column('college_code', sa.String(length=20), nullable=True),
        sa.Column('college_name', sa.String(length=100), nullable=True),
        sa.Column('program_name', sa.String(length=200), nullable=False),
        sa.Column('normalized_program_name', sa.String(length=300), nullable=True),
        sa.Column('parent_department_name', sa.String(length=200), nullable=True),
        sa.Column('major_name', sa.String(length=200), nullable=True),
        sa.Column('day_night_code', sa.String(length=20), nullable=True),
        sa.Column('day_night_name', sa.String(length=50), nullable=True),
        sa.Column('program_feature_code', sa.String(length=20), nullable=True),
        sa.Column('program_feature_name', sa.String(length=100), nullable=True),
        sa.Column('duration_code', sa.String(length=20), nullable=True),
        sa.Column('duration_name', sa.String(length=50), nullable=True),
        sa.Column('status_code', sa.String(length=20), nullable=True),
        sa.Column('status_name', sa.String(length=50), nullable=True),
        sa.Column('education_ministry_5_category', sa.String(length=100), nullable=True),
        sa.Column('degree_level', sa.String(length=50), nullable=True),
        sa.Column('quota_adjustment_type', sa.String(length=100), nullable=True),
        sa.Column('first_admission_year', sa.String(length=10), nullable=True),
        sa.Column('free_major_type_code', sa.String(length=20), nullable=True),
        sa.Column('free_major_type_name', sa.String(length=100), nullable=True),
        sa.Column('kedi_7_category', sa.String(length=100), nullable=True),
        sa.Column('source_updated_at', sa.String(length=50), nullable=True),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_bachelor', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('academic_program_code'),
    )
    op.create_index(op.f('ix_academic_programs_college_name'), 'academic_programs', ['college_name'])
    op.create_index(op.f('ix_academic_programs_program_name'), 'academic_programs', ['program_name'])
    op.create_index(
        op.f('ix_academic_programs_normalized_program_name'),
        'academic_programs',
        ['normalized_program_name'],
    )
    op.create_index(op.f('ix_academic_programs_is_active'), 'academic_programs', ['is_active'])
    op.create_index(op.f('ix_academic_programs_is_bachelor'), 'academic_programs', ['is_bachelor'])

    op.create_table(
        'academic_program_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('academic_program_code', sa.String(length=50), nullable=False),
        sa.Column('alias_type', sa.String(length=50), nullable=False),
        sa.Column('alias_name', sa.String(length=300), nullable=False),
        sa.Column('normalized_alias_name', sa.String(length=300), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ['academic_program_code'],
            ['academic_programs.academic_program_code'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'academic_program_code', 'alias_type', 'alias_name', name='uq_academic_program_alias'
        ),
    )
    op.create_index(
        op.f('ix_academic_program_aliases_academic_program_code'),
        'academic_program_aliases',
        ['academic_program_code'],
    )
    op.create_index(
        op.f('ix_academic_program_aliases_alias_name'), 'academic_program_aliases', ['alias_name']
    )
    op.create_index(
        op.f('ix_academic_program_aliases_normalized_alias_name'),
        'academic_program_aliases',
        ['normalized_alias_name'],
    )

    # 계층 ↔ 졸업요건 브리지. 코드가 세부 전공 쪽에만 있는 학부제 케이스가 있어 양쪽 다 nullable.
    op.add_column(
        'departments', sa.Column('academic_program_code', sa.String(length=50), nullable=True)
    )
    op.create_foreign_key(
        'fk_departments_academic_program_code',
        'departments',
        'academic_programs',
        ['academic_program_code'],
        ['academic_program_code'],
    )
    op.create_index(
        'uq_departments_academic_program_code',
        'departments',
        ['academic_program_code'],
        unique=True,
        postgresql_where=sa.text('academic_program_code IS NOT NULL'),
    )

    op.add_column(
        'majors', sa.Column('academic_program_code', sa.String(length=50), nullable=True)
    )
    op.create_foreign_key(
        'fk_majors_academic_program_code',
        'majors',
        'academic_programs',
        ['academic_program_code'],
        ['academic_program_code'],
    )
    op.create_index(
        'uq_majors_academic_program_code',
        'majors',
        ['academic_program_code'],
        unique=True,
        postgresql_where=sa.text('academic_program_code IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_majors_academic_program_code', table_name='majors')
    op.drop_constraint('fk_majors_academic_program_code', 'majors', type_='foreignkey')
    op.drop_column('majors', 'academic_program_code')

    op.drop_index('uq_departments_academic_program_code', table_name='departments')
    op.drop_constraint('fk_departments_academic_program_code', 'departments', type_='foreignkey')
    op.drop_column('departments', 'academic_program_code')

    op.drop_table('academic_program_aliases')
    op.drop_table('academic_programs')
