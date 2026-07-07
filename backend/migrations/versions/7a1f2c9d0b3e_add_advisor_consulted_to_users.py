"""add advisor_consulted to users

Revision ID: 7a1f2c9d0b3e
Revises: 452075704d10
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1f2c9d0b3e'
down_revision: Union[str, Sequence[str], None] = '452075704d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('advisor_consulted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'advisor_consulted', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'advisor_consulted')
