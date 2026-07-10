"""drop flat graduation_requirements table (superseded — kept as no-op)

원래는 flat 스텁(graduation_requirements)을 제거하고
requirement_sets/requirement_categories/requirement_courses로 대체하려
했으나, 2026-07-10 "학과별 졸업요건 vs 학생 이수내역 매칭" 기능을 이
flat 테이블 기준으로 만들기로 재결정하면서 이 리비전을 no-op으로 바꿨다.
이 마이그레이션은 라이브 DB에 한 번도 적용된 적이 없어(head가 여전히
f6a7b8c9d0e1) 되돌릴 데이터가 없으므로, drop을 실행하는 대신 리비전
체인만 유지하고 아무 것도 하지 않는다. graduation_requirements 테이블은
계속 존재한다.

Revision ID: e5a7c9d1f3b6
Revises: d4f6b8c0e2a5
Create Date: 2026-07-09 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9d1f3b6'
down_revision: Union[str, Sequence[str], None] = 'd4f6b8c0e2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass  # graduation_requirements 유지로 결정 — no-op


def downgrade() -> None:
    """Downgrade schema."""
    pass
