"""add users.admission_type

신입학/편입학 구분. 편입생은 1·2학년 커리큘럼을 밟지 않으므로 로드맵과 내 정보
화면을 "입학 전 인정 학점 + 3·4학년"으로 구성해야 하는데, 지금까지는 이 구분이
스키마에 없어서 StudentCourseRecord의 semester="입학전성적" 행 유무로 추론했다.

NOT NULL로 만들지 않는다. 이 컬럼이 없던 시절에 만들어진 행이 이미 있고,
server_default 없이 NOT NULL을 걸면 그 행들과 컬럼을 모르는 옛 코드의 INSERT가
모두 깨진다(실제로 한 번 겪었다 — 회원가입이 500으로 죽었다). nullable로 두고
server_default="freshman"으로 기존 행을 채운 뒤, 값 해석은 애플리케이션에서
"transfer가 아니면 신입학"으로 처리한다.

Revision ID: 1d11da3bd26e
Revises: e31ca57796ff
Create Date: 2026-08-06 15:11:19.011521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d11da3bd26e'
down_revision: Union[str, Sequence[str], None] = 'e31ca57796ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "admission_type",
            sa.String(length=20),
            nullable=True,
            server_default="freshman",
        ),
    )
    # 이미 "입학전성적" 이수 기록이 있는 사용자는 편입생으로 보고 미리 채운다.
    # 지금까지 화면이 쓰던 추론 규칙과 같은 기준이라, 마이그레이션 직후에도
    # 기존 사용자가 보던 화면이 그대로 유지된다.
    op.execute(
        """
        UPDATE users
        SET admission_type = 'transfer'
        WHERE id IN (
            SELECT DISTINCT user_id
            FROM student_course_records
            WHERE semester = '입학전성적'
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "admission_type")
