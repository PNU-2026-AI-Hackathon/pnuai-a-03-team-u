"""add course_roadmap_chat_sessions and session_id fk on messages

기존에는 로드맵당 하나의 연속 대화(=`course_roadmap_chat_messages` 전체를
`roadmap_id`로만 묶는 구조)였다. 세션 개념을 도입해 같은 로드맵 안에서도
여러 개의 독립된 대화 스레드를 유지할 수 있게 한다. 이전에 남아있던 메시지는
로드맵별 "기본 세션"을 하나 만들어 그 세션에 몰아 넣는다 — UI에서 안 보이게
숨기는 게 아니라, 이후 UI 목록에도 "기본" 이름으로 그대로 노출된다.

pending_roadmap_changes는 세션이 아닌 로드맵 전역이라는 원칙을 유지한다 — 사용자가
어느 세션에서 제안을 받든 승인 대상은 하나의 로드맵이다.

Revision ID: e1f2a3b4c5d6
Revises: 15310c3ef065
Create Date: 2026-07-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "15310c3ef065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_roadmap_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("roadmap_id", sa.Integer(), sa.ForeignKey("course_roadmaps.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        op.f("ix_course_roadmap_chat_sessions_roadmap_id"),
        "course_roadmap_chat_sessions",
        ["roadmap_id"],
    )

    op.add_column(
        "course_roadmap_chat_messages",
        sa.Column("session_id", sa.Integer(), nullable=True),
    )

    # 기존 메시지 이관: roadmap_id별로 기본 세션을 하나 만들고 session_id를 채운다.
    # 메시지가 하나도 없는 로드맵에는 세션을 만들지 않는다 — 대화가 시작되는 시점에
    # 새 세션이 자연스럽게 생기게 한다.
    bind = op.get_bind()
    roadmap_ids = [
        row[0]
        for row in bind.execute(
            text("SELECT DISTINCT roadmap_id FROM course_roadmap_chat_messages")
        )
    ]
    for rid in roadmap_ids:
        session_id = bind.execute(
            text(
                "INSERT INTO course_roadmap_chat_sessions (roadmap_id, title, created_at, updated_at) "
                "VALUES (:rid, :title, NOW(), NOW()) RETURNING id"
            ),
            {"rid": rid, "title": "기본 대화"},
        ).scalar_one()
        bind.execute(
            text(
                "UPDATE course_roadmap_chat_messages SET session_id = :sid "
                "WHERE roadmap_id = :rid AND session_id IS NULL"
            ),
            {"sid": session_id, "rid": rid},
        )

    op.alter_column("course_roadmap_chat_messages", "session_id", nullable=False)
    op.create_foreign_key(
        "fk_course_roadmap_chat_messages_session_id",
        "course_roadmap_chat_messages",
        "course_roadmap_chat_sessions",
        ["session_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_course_roadmap_chat_messages_session_id"),
        "course_roadmap_chat_messages",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_course_roadmap_chat_messages_session_id"),
        table_name="course_roadmap_chat_messages",
    )
    op.drop_constraint(
        "fk_course_roadmap_chat_messages_session_id",
        "course_roadmap_chat_messages",
        type_="foreignkey",
    )
    op.drop_column("course_roadmap_chat_messages", "session_id")
    op.drop_index(
        op.f("ix_course_roadmap_chat_sessions_roadmap_id"),
        table_name="course_roadmap_chat_sessions",
    )
    op.drop_table("course_roadmap_chat_sessions")
