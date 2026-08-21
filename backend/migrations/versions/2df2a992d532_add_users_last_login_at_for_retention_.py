"""users.last_login_at 추가 — 보존기간 정책의 '미접속' 판단 근거

보안·개인정보 계획 P2 "보존기간 정책"을 구현하려면 마지막 접속 시각이 필요하다.
`updated_at`으로는 안 된다 — 프로필 수정·상담 토글 같은 쓰기에는 갱신되지만
로그인은 조회라 안 건드리기 때문에, 자주 쓰는 사용자가 오히려 미접속으로
잡히는 정반대 결과가 난다.

기존 행은 NULL로 남는다(로그인 기록이 없다는 사실 그대로). 파기 스크립트는
NULL을 created_at으로 대체해 "가입 후 한 번도 안 들어온 계정"으로 다룬다.

Revision ID: 2df2a992d532
Revises: 70d591f9bd02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2df2a992d532'
down_revision: Union[str, Sequence[str], None] = '70d591f9bd02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
