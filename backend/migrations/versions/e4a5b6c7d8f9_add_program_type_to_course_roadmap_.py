"""add program_type to course_roadmap_items

로드맵 항목이 어느 프로그램(주전공/부전공/복수전공/융합)용인지 태깅. LLM이 부전공
필수과목을 제안할 때 propose_change로 program_type='minor'를 넘기면 그대로 저장돼,
나중에 판정 함수가 해당 프로그램의 이수 현황을 정확히 계산할 수 있다.

기존 로우는 전부 NULL(=주전공/미지정 취급). 판정 로직도 NULL을 주전공으로 해석해
후방 호환됨.

Revision ID: e4a5b6c7d8f9
Revises: d2913a8e3330
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4a5b6c7d8f9'
down_revision: Union[str, Sequence[str], None] = 'd2913a8e3330'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'course_roadmap_items',
        sa.Column('program_type', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'pending_roadmap_changes',
        sa.Column('program_type', sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('pending_roadmap_changes', 'program_type')
    op.drop_column('course_roadmap_items', 'program_type')
