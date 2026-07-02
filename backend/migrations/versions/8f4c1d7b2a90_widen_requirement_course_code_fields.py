"""widen requirement course code fields

Revision ID: 8f4c1d7b2a90
Revises: 2d8a6f1c9b40
Create Date: 2026-07-02 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f4c1d7b2a90"
down_revision: Union[str, Sequence[str], None] = "2d8a6f1c9b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "requirement_courses",
        "raw_course_code",
        existing_type=sa.String(length=80),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "requirement_courses",
        "matched_course_code",
        existing_type=sa.String(length=80),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "requirement_courses",
        "matched_course_code",
        existing_type=sa.Text(),
        type_=sa.String(length=80),
        existing_nullable=True,
    )
    op.alter_column(
        "requirement_courses",
        "raw_course_code",
        existing_type=sa.Text(),
        type_=sa.String(length=80),
        existing_nullable=True,
    )
