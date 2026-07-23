"""add user academic year and graduation override

Revision ID: b8c9d0e1f2a3
Revises: 15310c3ef065
Create Date: 2026-07-22 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "15310c3ef065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("academic_year", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("graduation_override", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "graduation_override")
    op.drop_column("users", "academic_year")
