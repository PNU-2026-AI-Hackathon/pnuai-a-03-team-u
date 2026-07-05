"""make courses.course_code unique

Revision ID: a1c47e0f9d52
Revises: 8f4c1d7b2a90
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1c47e0f9d52"
down_revision: Union[str, Sequence[str], None] = "8f4c1d7b2a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f("ix_courses_course_code"), table_name="courses")
    op.create_index(
        op.f("ix_courses_course_code"), "courses", ["course_code"], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_courses_course_code"), table_name="courses")
    op.create_index(
        op.f("ix_courses_course_code"), "courses", ["course_code"], unique=False
    )
