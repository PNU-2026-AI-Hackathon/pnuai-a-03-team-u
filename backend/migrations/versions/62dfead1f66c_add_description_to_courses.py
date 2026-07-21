"""add description to courses

course_descriptions에서 이름이 정확히 일치하는 것만 골라 복사해 넣는 nullable 텍스트 컬럼.
매 조회마다 course_descriptions를 라이브 조회/매칭하던 이전 방식(636a0efff10d 도입 당시 설계) 대신
한 번 매칭한 결과를 courses에 직접 materialize한다 — pgvector/rag_chunks 경로는 이 기능에서
쓰지 않기로 함(2026-07-20 방향 전환). scripts/sync_course_descriptions_to_courses.py로 채운다.

Revision ID: 62dfead1f66c
Revises: 636a0efff10d
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '62dfead1f66c'
down_revision: Union[str, Sequence[str], None] = '636a0efff10d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('courses', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('courses', 'description')
