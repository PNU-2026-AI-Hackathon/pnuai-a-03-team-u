"""add college to users and user_academic_programs

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-07 00:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('college', sa.String(length=200), nullable=True))
    op.add_column('user_academic_programs', sa.Column('college', sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_academic_programs', 'college')
    op.drop_column('users', 'college')
