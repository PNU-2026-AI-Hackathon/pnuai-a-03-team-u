"""merge user_external_activities + user_competitions into user_activities

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('organization', sa.String(length=255), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('role', sa.String(length=100), nullable=True),
        sa.Column('award', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_activities_user_id'), 'user_activities', ['user_id'])

    # 기존 데이터 이관 (테스트 데이터뿐이지만 있으면 보존)
    op.execute(
        """
        INSERT INTO user_activities
            (user_id, title, organization, role, description, start_date, end_date, created_at, updated_at)
        SELECT user_id, title, organization, role, description, start_date, end_date, created_at, updated_at
        FROM user_external_activities
        """
    )
    op.execute(
        """
        INSERT INTO user_activities
            (user_id, title, category, award, description, start_date, created_at, updated_at)
        SELECT user_id, title, category, award, description, held_at, created_at, updated_at
        FROM user_competitions
        """
    )

    op.drop_table('user_competitions')
    op.drop_table('user_external_activities')


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("테이블 병합 마이그레이션은 downgrade를 지원하지 않습니다.")
