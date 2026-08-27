"""add source to user academic programs

Revision ID: a17f9c2d8e31
Revises: 46c01c006fa1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a17f9c2d8e31"
down_revision: Union[str, Sequence[str], None] = "46c01c006fa1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_academic_programs", sa.Column("source", sa.String(length=30), nullable=True))
    op.create_index(op.f("ix_user_academic_programs_source"), "user_academic_programs", ["source"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_academic_programs_source"), table_name="user_academic_programs")
    op.drop_column("user_academic_programs", "source")
