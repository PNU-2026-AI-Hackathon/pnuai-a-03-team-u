"""add course_roadmap_chat_messages and pending_roadmap_changes

AI 로드맵 상담 기능의 대화 기록 테이블 + human-in-the-loop 승인 대기 변경안
테이블. 로드맵당 하나의 연속 대화로 취급한다.

Revision ID: c9d0e1f2a3b4
Revises: f6a7b8c9d0e1
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'course_roadmap_chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roadmap_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['roadmap_id'], ['course_roadmaps.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_roadmap_chat_messages_roadmap_id'),
        'course_roadmap_chat_messages',
        ['roadmap_id'],
    )

    op.create_table(
        'pending_roadmap_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roadmap_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=True),
        sa.Column('planned_grade', sa.Integer(), nullable=True),
        sa.Column('planned_year', sa.String(length=10), nullable=True),
        sa.Column('planned_semester', sa.String(length=20), nullable=True),
        sa.Column('before_snapshot', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['roadmap_id'], ['course_roadmaps.id']),
        sa.ForeignKeyConstraint(['item_id'], ['course_roadmap_items.id']),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_pending_roadmap_changes_roadmap_id'),
        'pending_roadmap_changes',
        ['roadmap_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('pending_roadmap_changes')
    op.drop_table('course_roadmap_chat_messages')
