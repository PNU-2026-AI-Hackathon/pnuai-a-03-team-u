"""users.privacy_consent / privacy_consent_at 추가 — 회원가입 동의 기록

보안·개인정보 계획 P2 "개인정보처리방침 + 수집 동의"를 구현한다. 지금까지
온보딩에 "✓ 개인정보 수집 · 이용 동의"라는 정적 문구만 있고 실제로 사용자
응답을 받는 컨트롤이 없었다 — 사용자가 무엇을 하든 항상 "✓"로 보여서, 동의를
안 받은 것보다 오히려 문제였다(README 1.3/F-08, 2026-08-24 발견).

회원가입 시 필수 체크박스로 동의를 받고 그 시각을 기록한다. 기존 가입자는
동의를 받은 적이 없으므로 privacy_consent=false, privacy_consent_at=NULL로
남는다 — 허위로 true를 채우지 않는다. 재동의 유도 UI는 이번 범위 밖.

Revision ID: b8d89abee0ab
Revises: 26790dcb3180
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d89abee0ab'
down_revision: Union[str, Sequence[str], None] = '26790dcb3180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("privacy_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("privacy_consent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "privacy_consent_at")
    op.drop_column("users", "privacy_consent")
