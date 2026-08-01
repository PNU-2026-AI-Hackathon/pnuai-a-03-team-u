"""merge user profile override and roadmap chat sessions

Revision ID: ef43f83514ff
Revises: b8c9d0e1f2a3, e1f2a3b4c5d6
Create Date: 2026-08-01 14:25:51.270140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef43f83514ff'
down_revision: Union[str, Sequence[str], None] = ('b8c9d0e1f2a3', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
