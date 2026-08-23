"""학생 이수과목에 균형교양 세부영역 전용 컬럼 추가

Revision ID: 7b3e9c1a4f20
Revises: 2df2a992d532
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b3e9c1a4f20"
down_revision: Union[str, Sequence[str], None] = "2df2a992d532"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AREAS = (
    "사상과역사",
    "사회와문화",
    "문학과예술",
    "과학과기술",
    "건강과레포츠",
    "외국어",
    "융복합",
)


def upgrade() -> None:
    op.add_column(
        "student_course_records",
        sa.Column("liberal_area", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_student_course_records_liberal_area",
        "student_course_records",
        ["liberal_area"],
        unique=False,
    )

    # 기존 구현은 세부영역을 category에 덮어썼다. 값을 잃지 않고 전용 컬럼으로 옮긴 뒤
    # 상위 이수구분을 교양선택으로 복구한다.
    area_sql = ", ".join(f"'{area}'" for area in _AREAS)
    op.execute(
        sa.text(
            f"""
            UPDATE student_course_records
               SET liberal_area = category,
                   category = '교양선택'
             WHERE category IN ({area_sql})
            """
        )
    )


def downgrade() -> None:
    # 구버전 코드가 다시 읽을 수 있도록 세부영역을 category로 되돌린다.
    op.execute(
        sa.text(
            """
            UPDATE student_course_records
               SET category = liberal_area
             WHERE liberal_area IS NOT NULL
            """
        )
    )
    op.drop_index("ix_student_course_records_liberal_area", table_name="student_course_records")
    op.drop_column("student_course_records", "liberal_area")
