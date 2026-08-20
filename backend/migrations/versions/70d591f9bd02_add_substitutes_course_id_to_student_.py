"""편입 전적대 과목이 대체한 PNU 과목(substitutes_course_id) 컬럼 추가

전적대 과목은 졸업사정용성적표에서 `*I0600368 컴퓨터프로그래밍 Ⅰ` 처럼 `*I` 코드로
들어와 PNU 교과목번호와 아예 연결되지 않는다. 편입 학점 인정은 규정 표가 아니라
학과가 학생 개인에게 통보하는 것이라 데이터에 근거가 없고, 이름 유사도로 추정하면
(`데이터구조` ↔ `자료구조`) 틀렸을 때 학생이 졸업요건을 잘못 믿게 된다. 그래서
**학생 본인이 화면에서 고른 값만** 담는 컬럼을 하나 둔다.

학점 컬럼은 손대지 않는다 — 전적대 학점은 이 행에 그대로 있고 졸업요건 엔진은
category별 합계만 보므로 대체 등록이 학점 계산을 바꾸지 않는다. 실제 효과는 시간표/
로드맵 추천에서 대체된 PNU 과목을 "이미 이수함"으로 빼는 것이다.

⚠️ autogenerate 초안에는 `uq_graduation_requirements_scope`와 `ix_rag_chunks_embedding`을
drop하는 DDL이 또 끼어 있었다(6285e7acb5ba 주석과 같은 이유 — raw SQL로 만들어져 모델
선언이 없다). 지웠다.

Revision ID: 70d591f9bd02
Revises: 6285e7acb5ba
Create Date: 2026-08-20 14:56:26.884544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70d591f9bd02'
down_revision: Union[str, Sequence[str], None] = '6285e7acb5ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAME = "fk_student_course_records_substitutes_course_id_courses"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "student_course_records",
        sa.Column("substitutes_course_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_student_course_records_substitutes_course_id"),
        "student_course_records",
        ["substitutes_course_id"],
        unique=False,
    )
    op.create_foreign_key(
        _FK_NAME, "student_course_records", "courses", ["substitutes_course_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_FK_NAME, "student_course_records", type_="foreignkey")
    op.drop_index(
        op.f("ix_student_course_records_substitutes_course_id"),
        table_name="student_course_records",
    )
    op.drop_column("student_course_records", "substitutes_course_id")
