"""add timetable_chat_sessions and timetable_chat_messages

시간표 AI 상담을 스테이트리스에서 DB 영속으로 전환. 사용자가 로그인·새로고침 후에도
지난 시간표 대화를 이어갈 수 있게 세션·메시지 두 테이블 추가.

세션은 (user_id, year, semester) 스코프로 여러 개 병존 가능 — 같은 학기 안에서도
"새 대화 시작" 버튼으로 스레드 분리 (로드맵 챗과 동일 패턴). 로드맵 챗과 달리
roadmap_id에 매이지 않는다 — 시간표 챗은 로드맵과 독립 아키텍처(2026-08-03 결정).

기존 데이터 이관 대상 없음 (이번 도입 전까지 시간표 챗은 완전히 스테이트리스라 서버에
저장된 대화가 없다).

Revision ID: 125c05c5df60
Revises: a4b9e7872662
Create Date: 2026-08-11 00:00:00.000000

Note: 원래 리비전 ID로 `b8c9d0e1f2a3`를 시도했으나 옛 마이그레이션
(add_user_profile_and_graduation_override)와 충돌해 재발급.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "125c05c5df60"
down_revision: Union[str, Sequence[str], None] = "a4b9e7872662"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timetable_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("year", sa.String(length=10), nullable=False),
        sa.Column("semester", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        op.f("ix_timetable_chat_sessions_user_id"),
        "timetable_chat_sessions",
        ["user_id"],
    )

    op.create_table(
        "timetable_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("timetable_chat_sessions.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        op.f("ix_timetable_chat_messages_session_id"),
        "timetable_chat_messages",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_timetable_chat_messages_session_id"),
        table_name="timetable_chat_messages",
    )
    op.drop_table("timetable_chat_messages")
    op.drop_index(
        op.f("ix_timetable_chat_sessions_user_id"),
        table_name="timetable_chat_sessions",
    )
    op.drop_table("timetable_chat_sessions")
