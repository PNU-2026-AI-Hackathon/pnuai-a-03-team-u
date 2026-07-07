"""add school/college/department/major hierarchy, drop text columns

기존에 courses/graduation_requirements/users/user_academic_programs에
자유 텍스트로 흩어져 있던 school/college/department/major를
schools -> colleges -> departments -> majors 4단 FK 계층으로 정규화한다.

기존 데이터는 테스트 데이터뿐이라 백필 없이 컬럼을 drop/add한다.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-07 01:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'schools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_schools_name'), 'schools', ['name'])

    op.create_table(
        'colleges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('school_id', 'name', name='uq_college_school_name'),
    )
    op.create_index(op.f('ix_colleges_school_id'), 'colleges', ['school_id'])

    op.create_table(
        'departments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('college_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['college_id'], ['colleges.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('college_id', 'name', name='uq_department_college_name'),
    )
    op.create_index(op.f('ix_departments_college_id'), 'departments', ['college_id'])

    op.create_table(
        'majors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('department_id', 'name', name='uq_major_department_name'),
    )
    op.create_index(op.f('ix_majors_department_id'), 'majors', ['department_id'])

    # users: school/college/department/major 텍스트 -> department_id/major_id FK
    op.drop_column('users', 'school')
    op.drop_column('users', 'college')
    op.drop_column('users', 'department')
    op.drop_column('users', 'major')
    op.add_column('users', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('major_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_department_id'), 'users', ['department_id'])
    op.create_index(op.f('ix_users_major_id'), 'users', ['major_id'])
    op.create_foreign_key('fk_users_department_id', 'users', 'departments', ['department_id'], ['id'])
    op.create_foreign_key('fk_users_major_id', 'users', 'majors', ['major_id'], ['id'])

    # user_academic_programs: school/college/department/major 텍스트 -> FK
    op.drop_column('user_academic_programs', 'school')
    op.drop_column('user_academic_programs', 'college')
    op.drop_column('user_academic_programs', 'department')
    op.drop_column('user_academic_programs', 'major')
    op.add_column('user_academic_programs', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('user_academic_programs', sa.Column('major_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_user_academic_programs_department_id'), 'user_academic_programs', ['department_id']
    )
    op.create_index(op.f('ix_user_academic_programs_major_id'), 'user_academic_programs', ['major_id'])
    op.create_foreign_key(
        'fk_uap_department_id', 'user_academic_programs', 'departments', ['department_id'], ['id']
    )
    op.create_foreign_key('fk_uap_major_id', 'user_academic_programs', 'majors', ['major_id'], ['id'])

    # courses: school/department/major 텍스트 -> FK
    op.drop_column('courses', 'school')
    op.drop_column('courses', 'department')
    op.drop_column('courses', 'major')
    op.add_column('courses', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('courses', sa.Column('major_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_courses_department_id'), 'courses', ['department_id'])
    op.create_index(op.f('ix_courses_major_id'), 'courses', ['major_id'])
    op.create_foreign_key('fk_courses_department_id', 'courses', 'departments', ['department_id'], ['id'])
    op.create_foreign_key('fk_courses_major_id', 'courses', 'majors', ['major_id'], ['id'])

    # graduation_requirements: school/department/major 텍스트 -> FK
    op.drop_column('graduation_requirements', 'school')
    op.drop_column('graduation_requirements', 'department')
    op.drop_column('graduation_requirements', 'major')
    op.add_column('graduation_requirements', sa.Column('department_id', sa.Integer(), nullable=True))
    op.add_column('graduation_requirements', sa.Column('major_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_graduation_requirements_department_id'), 'graduation_requirements', ['department_id']
    )
    op.create_index(op.f('ix_graduation_requirements_major_id'), 'graduation_requirements', ['major_id'])
    op.create_foreign_key(
        'fk_gr_department_id', 'graduation_requirements', 'departments', ['department_id'], ['id']
    )
    op.create_foreign_key('fk_gr_major_id', 'graduation_requirements', 'majors', ['major_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("계층 정규화 마이그레이션은 downgrade를 지원하지 않습니다.")
