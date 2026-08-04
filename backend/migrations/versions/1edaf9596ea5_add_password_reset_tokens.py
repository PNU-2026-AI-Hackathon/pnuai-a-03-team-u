"""add password_reset_tokens

Revision ID: 1edaf9596ea5
Revises: d2913a8e3330
Create Date: 2026-08-04 11:52:54.992842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1edaf9596ea5'
down_revision: Union[str, Sequence[str], None] = 'd2913a8e3330'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    autogenerate가 함께 뽑아낸 두 가지는 의도적으로 뺐다.
    - `course_descriptions` 생성: 모델에는 있는데 라이브 DB에만 없는 기존 드리프트라
      이 작업과 무관하다(회의록 "확인 필요" 4번). 별도로 원인을 확인하고 처리한다.
    - `ix_rag_chunks_embedding` 삭제: pgvector ivfflat 인덱스로, 지우면 RAG 벡터
      검색이 순차 스캔으로 떨어진다. 모델에 선언이 없어 드리프트로 잡힌 것뿐이다.
    """
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_password_reset_tokens_token_hash'), 'password_reset_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_token_hash'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
