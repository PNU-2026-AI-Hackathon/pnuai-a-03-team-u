"""recompute roadmap grades for transfer students

이미 만들어진 로드맵의 planned_grade는 옛 규칙으로 계산돼 있다.

옛 규칙의 문제 두 가지:
  1. 재학 학기 순번을 항상 1학년부터 셌다 → 편입생의 첫 학기(3학년 1학기)가
     1학년 1학기로 찍혔다.
  2. 입학전성적을 3학년 1학기로 못 박았다 → 편입생이 실제로 이수한 3학년 1학기와
     같은 칸에 합쳐졌다.

sync_completed_courses_to_roadmap이 다음 포털 동기화 때 새 규칙으로 다시 쓰지만,
그때까지 기존 사용자의 로드맵은 학년이 어긋난 채로 보인다. 여기서 한 번 맞춰 둔다.

앱 코드를 import하지 않고 같은 규칙을 이 파일 안에서 다시 구현한다. 마이그레이션은
과거 시점의 스키마에 대해 동작해야 하는데 app 모델은 계속 바뀌기 때문이다.

Revision ID: d963e1473009
Revises: 1d11da3bd26e
Create Date: 2026-08-06 15:24:28.416142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd963e1473009'
down_revision: Union[str, Sequence[str], None] = '1d11da3bd26e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REGULAR_SEMESTERS = ("1학기", "2학기")
_PRE_ADMISSION_SEMESTERS = ("입학전성적", "편입인정")
_TRANSFER_ENTRY_GRADE = 3


def _semester_order(year: str, semester: str) -> tuple[int, int]:
    return (int(year), 1 if semester == "1학기" else 2)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    users = bind.execute(
        sa.text(
            """
            SELECT DISTINCT u.id, u.admission_type
            FROM users u
            JOIN course_roadmaps m ON m.user_id = u.id
            """
        )
    ).fetchall()

    for user_id, admission_type in users:
        entry_grade = _TRANSFER_ENTRY_GRADE if admission_type == "transfer" else 1

        records = bind.execute(
            sa.text(
                """
                SELECT raw_course_name, year, semester
                FROM student_course_records
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        ).fetchall()
        if not records:
            continue

        # 실제 등록된 정규 학기만 시간순으로 1-based 순번을 매긴다.
        # 휴학 학기는 등록 기록이 없어 자연스럽게 순번에서 빠진다.
        keys = set()
        for _, year, semester in records:
            if not year or semester not in _REGULAR_SEMESTERS:
                continue
            try:
                _semester_order(year, semester)
            except (TypeError, ValueError):
                continue
            keys.add((year, semester))
        rank_by_key = {
            key: index + 1
            for index, key in enumerate(sorted(keys, key=lambda k: _semester_order(*k)))
        }

        for course_name, year, semester in records:
            if semester in _PRE_ADMISSION_SEMESTERS:
                # 어느 학년에도 속하지 않는 lump-sum. 화면이 별도 칸으로 그린다.
                planned_grade, planned_semester = None, semester
            else:
                rank = rank_by_key.get((year, semester))
                if rank is None:
                    continue
                grade = entry_grade + (rank - 1) // 2
                if not (1 <= grade <= 4):
                    continue
                planned_grade = grade
                planned_semester = "1학기" if rank % 2 == 1 else "2학기"

            bind.execute(
                sa.text(
                    """
                    UPDATE course_roadmap_items
                    SET planned_grade = :planned_grade,
                        planned_semester = :planned_semester
                    WHERE status = 'completed'
                      AND source = 'manual'
                      AND course_name = :course_name
                      AND planned_year = :planned_year
                      AND roadmap_id IN (
                          SELECT id FROM course_roadmaps WHERE user_id = :user_id
                      )
                    """
                ),
                {
                    "planned_grade": planned_grade,
                    "planned_semester": planned_semester,
                    "course_name": course_name,
                    "planned_year": year,
                    "user_id": user_id,
                },
            )


def downgrade() -> None:
    """Downgrade schema.

    옛 학년 값을 되돌리지 않는다. 원본은 student_course_records에 그대로 있고,
    다음 포털 동기화가 어느 쪽 규칙이든 다시 계산해 덮어쓴다.
    """
    pass
