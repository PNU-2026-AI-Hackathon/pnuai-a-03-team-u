"""add department_id fk to courses and requirement_sets

Revision ID: 452075704d10
Revises: c4e6074f47f9
Create Date: 2026-07-02 16:34:41.776641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '452075704d10'
down_revision: Union[str, Sequence[str], None] = 'c4e6074f47f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('courses', sa.Column('department_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_courses_department_id'), 'courses', ['department_id'], unique=False)
    op.create_foreign_key(
        'fk_courses_department_id', 'courses', 'departments', ['department_id'], ['id']
    )
    op.add_column('requirement_sets', sa.Column('department_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_requirement_sets_department_id'), 'requirement_sets', ['department_id'], unique=False)
    op.create_foreign_key(
        'fk_requirement_sets_department_id', 'requirement_sets', 'departments',
        ['department_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_requirement_sets_department_id', 'requirement_sets', type_='foreignkey')
    op.drop_index(op.f('ix_requirement_sets_department_id'), table_name='requirement_sets')
    op.drop_column('requirement_sets', 'department_id')
    op.drop_constraint('fk_courses_department_id', 'courses', type_='foreignkey')
    op.drop_index(op.f('ix_courses_department_id'), table_name='courses')
    op.drop_column('courses', 'department_id')
