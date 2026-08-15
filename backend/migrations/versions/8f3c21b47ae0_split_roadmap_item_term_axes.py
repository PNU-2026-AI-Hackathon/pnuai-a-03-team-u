"""로드맵 항목의 학기를 달력 축과 커리큘럼 축으로 분리

course_roadmap_items는 planned_year에 달력 연도를, planned_semester에는
커리큘럼 학기를 넣고 있었다. 두 값을 짝지어 읽으면 존재한 적 없는 학기가 된다 —
한 학기 휴학한 학생의 2026년 1학기 이수 기록이 "2026 / 2학기"로 저장돼,
성장 로드맵 화면과 DB가 서로 다른 학기를 가리켰다.

curriculum_semester를 새로 두어 축을 나눈다.
  planned_year + planned_semester : 달력 학기 (성적표·개설 강좌와 같은 기준)
  planned_grade + curriculum_semester : 커리큘럼 학기 (로드맵 학년 슬롯)

백필은 기존 planned_semester를 커리큘럼 축으로 옮긴 뒤, 달력 학기를
student_course_records 원본에서 되살린다. 이수 기록에 대응이 없는 항목
(AI가 계획한 미래 학기 등)은 planned_semester를 그대로 둔다 — 그쪽은 애초에
달력 학기로 저장돼 있었다.

Revision ID: 8f3c21b47ae0
Revises: 125c05c5df60
"""

from alembic import op
import sqlalchemy as sa

revision = "8f3c21b47ae0"
down_revision = "125c05c5df60"
branch_labels = None
depends_on = None

_REGULAR = ("1학기", "2학기")


def upgrade() -> None:
    op.add_column(
        "course_roadmap_items",
        sa.Column("curriculum_semester", sa.String(length=20), nullable=True),
    )

    # 1) 정규 학기 항목의 기존 planned_semester는 커리큘럼 학기였다 → 옮긴다.
    #    계절수업·입학전성적은 커리큘럼 학년에 속하지 않으므로 null로 남긴다.
    op.execute(
        sa.text(
            """
            UPDATE course_roadmap_items
               SET curriculum_semester = planned_semester
             WHERE planned_semester IN :regular
            """
        ).bindparams(sa.bindparam("regular", value=_REGULAR, expanding=True))
    )

    # 2) 달력 학기를 성적표 원본에서 복원한다. 이수 기록으로 만들어진 항목
    #    (status='completed', source='manual')만 대응이 존재한다.
    op.execute(
        sa.text(
            """
            UPDATE course_roadmap_items AS i
               SET planned_semester = r.semester
              FROM course_roadmaps AS m, student_course_records AS r
             WHERE m.id = i.roadmap_id
               AND r.user_id = m.user_id
               AND r.raw_course_name = i.course_name
               AND r.year = i.planned_year
               AND i.status = 'completed'
               AND i.source = 'manual'
               AND i.planned_semester IN :regular
               AND r.semester IN :regular
               AND r.semester <> i.planned_semester
            """
        ).bindparams(sa.bindparam("regular", value=_REGULAR, expanding=True))
    )


def downgrade() -> None:
    # 커리큘럼 학기를 planned_semester로 되돌려 놓아야 구버전 코드가 학년 슬롯을
    # 다시 찾을 수 있다.
    op.execute(
        """
        UPDATE course_roadmap_items
           SET planned_semester = curriculum_semester
         WHERE curriculum_semester IS NOT NULL
        """
    )
    op.drop_column("course_roadmap_items", "curriculum_semester")
