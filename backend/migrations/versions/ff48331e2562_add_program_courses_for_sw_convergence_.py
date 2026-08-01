"""add program_courses for SW convergence programs

다중전공 프로그램(SW융합트랙·연계전공·융합전공)의 인정 과목을 담는 다대다 테이블.
`courses`는 department_id/major_id를 하나씩만 가져서 "정보컴퓨터공학부 과목이면서
동시에 경영학과 SW융합트랙 인정 과목"을 표현할 수 없기 때문에 필요하다.

주의: autogenerate가 아래 두 가지를 같이 잡아냈지만 의도적으로 뺐다.
  1. `course_descriptions` 생성 — 이 테이블은 마이그레이션 636a0efff10d가 만들게
     돼 있는데 라이브 DB에는 없다(별개 이슈). 여기서 곁다리로 만들면 원인이 묻히므로
     별도로 다룬다.
  2. `ix_rag_chunks_embedding` 삭제 — 모델에 선언만 안 돼 있을 뿐 pgvector ivfflat
     인덱스로 실제 사용 중이다. 지우면 벡터 검색 성능이 떨어진다.

Revision ID: ff48331e2562
Revises: ef43f83514ff
Create Date: 2026-08-01 23:54:48.217906

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ff48331e2562'
down_revision: Union[str, Sequence[str], None] = 'ef43f83514ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'program_courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        # 학과 자체가 프로그램 단위인 경우(핀테크융합전공)는 null.
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('requirement_group', sa.String(length=50), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('curriculum_year', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['major_id'], ['majors.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'department_id', 'major_id', 'course_id', 'curriculum_year',
            name='uq_program_course',
        ),
    )
    op.create_index(op.f('ix_program_courses_course_id'), 'program_courses', ['course_id'], unique=False)
    op.create_index(op.f('ix_program_courses_department_id'), 'program_courses', ['department_id'], unique=False)
    op.create_index(op.f('ix_program_courses_major_id'), 'program_courses', ['major_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_program_courses_major_id'), table_name='program_courses')
    op.drop_index(op.f('ix_program_courses_department_id'), table_name='program_courses')
    op.drop_index(op.f('ix_program_courses_course_id'), table_name='program_courses')
    op.drop_table('program_courses')
