"""균형·창의 교양 개설강좌/세부영역 병렬 마이그레이션 병합

Revision ID: 26790dcb3180
Revises: 5ae96e0e4d56, 7b3e9c1a4f20
Create Date: 2026-08-23 18:21:40.058816

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26790dcb3180'
down_revision: Union[str, Sequence[str], None] = ('5ae96e0e4d56', '7b3e9c1a4f20')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
