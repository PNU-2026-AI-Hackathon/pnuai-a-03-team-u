"""drop course_descriptions and add source_document to courses

course_descriptions 테이블을 폐기하고 courses에 source_document 컬럼을 추가한다.
새 파이프라인: `scripts/import_course_descriptions.py`가 원문 md를 파싱하면서
이름 매칭되는 courses의 description·source_document를 직접 채운다. 매칭 안 되는
항목은 스킵(원문 자체가 개편 이전 자료라 이름이 다른 경우가 흔함).

Revision ID: 419d94f88803
Revises: e4a5b6c7d8f9
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '419d94f88803'
down_revision: Union[str, Sequence[str], None] = 'e4a5b6c7d8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    이 마이그레이션 이전 시점에 어떤 이유로든 course_descriptions 테이블이 없는 환경도
    안전하게 지원하기 위해 drop_table을 raw SQL의 IF EXISTS로 실행한다.
    """
    op.add_column(
        "courses",
        sa.Column("source_document", sa.String(length=255), nullable=True),
    )
    op.drop_index("ix_course_descriptions_department_id", table_name="course_descriptions", if_exists=True)
    op.drop_index("ix_course_descriptions_major_id", table_name="course_descriptions", if_exists=True)
    op.drop_index("ix_course_descriptions_normalized_name", table_name="course_descriptions", if_exists=True)
    op.execute("DROP TABLE IF EXISTS course_descriptions")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "course_descriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("major_id", sa.Integer(), nullable=True),
        sa.Column("source_course_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_document", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["major_id"], ["majors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id", "major_id", "normalized_name",
            name="uq_course_description_dept_major_name",
        ),
    )
    op.create_index(
        "ix_course_descriptions_department_id", "course_descriptions", ["department_id"]
    )
    op.create_index(
        "ix_course_descriptions_major_id", "course_descriptions", ["major_id"]
    )
    op.create_index(
        "ix_course_descriptions_normalized_name", "course_descriptions", ["normalized_name"]
    )
    op.drop_column("courses", "source_document")
