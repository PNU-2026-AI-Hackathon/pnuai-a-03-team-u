"""add user_academic_program_id to student_course_records

Revision ID: 3c9d5e1a7f24
Revises: 7a1f2c9d0b3e
Create Date: 2026-07-07 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c9d5e1a7f24'
down_revision: Union[str, Sequence[str], None] = '7a1f2c9d0b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'student_course_records',
        sa.Column('user_academic_program_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_student_course_records_user_academic_program_id'),
        'student_course_records',
        ['user_academic_program_id'],
    )
    op.create_foreign_key(
        'fk_student_course_records_user_academic_program_id',
        'student_course_records',
        'user_academic_programs',
        ['user_academic_program_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_student_course_records_user_academic_program_id',
        'student_course_records',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_student_course_records_user_academic_program_id'),
        table_name='student_course_records',
    )
    op.drop_column('student_course_records', 'user_academic_program_id')
