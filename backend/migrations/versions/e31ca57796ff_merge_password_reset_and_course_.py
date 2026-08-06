"""merge password reset and course description heads

PR #105(비밀번호 재설정)와 PR #107(course_descriptions 인라인화)이 같은 지점
(d2913a8e3330)에서 각각 갈라진 뒤 서로를 모른 채 머지되면서 main에 alembic head가
둘이 됐다. 이 상태에서는 `alembic upgrade head`가 "Multiple head revisions"로
실패해서, 새로 clone하거나 다음 마이그레이션을 추가하는 사람이 모두 막힌다.

스키마 변경은 없고 두 갈래를 다시 하나로 잇기만 하는 빈 리비전이다.

    d2913a8e3330 ─┬─ 1edaf9596ea5 (password_reset_tokens) ─┬─ e31ca57796ff
                  └─ e4a5b6c7d8f9 ─ 419d94f88803 ──────────┘

Revision ID: e31ca57796ff
Revises: 1edaf9596ea5, 419d94f88803
Create Date: 2026-08-06 13:25:28.299446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e31ca57796ff'
down_revision: Union[str, Sequence[str], None] = ('1edaf9596ea5', '419d94f88803')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
