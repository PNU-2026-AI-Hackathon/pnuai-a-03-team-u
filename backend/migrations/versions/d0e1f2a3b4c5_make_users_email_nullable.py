"""make users.email nullable

로그인 식별자를 이메일 -> 학번(student_id)으로 바꾼다. 신규 가입은 이메일을
받지 않으므로 email 컬럼을 nullable로 바꾼다. student_id는 이미
nullable+unique로 되어있던 컬럼이라 스키마 변경 없음(애플리케이션 레벨에서
항상 채우도록 강제).

주의: 기존 라이브 데이터 중 student_id가 비어있는 행이 있다면(예: 예전
테스트 계정) 로그인 식별자가 없어 로그인이 불가능해진다 — 필요하면 직접
정리할 것.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=False)
