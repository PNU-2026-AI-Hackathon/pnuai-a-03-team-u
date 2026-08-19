"""One-Stop 졸업예정정보의 학교 공식 판정 스냅샷 테이블 2개 추가

`student_graduation_categories`(이수구분별 기준/취득학점·이수여부)와
`student_graduation_requirements`(표준외국어능력시험·TOPCIT·졸업과제 등 자격 요건).

크롤링은 원래 되고 있었는데 `portal_sync`가 표 0과 균형교양 세부영역만 쓰고 나머지를
버려서, "졸업요건이랑 토익 등 자격증을 못 가져온다"는 문제로 보였다.

⚠️ autogenerate가 만든 초안에는 `uq_graduation_requirements_scope`와
`ix_rag_chunks_embedding`을 **drop하는 DDL이 끼어 있었다.** 둘 다 raw SQL로 만들어져
모델에 선언이 없다 보니 "모델에 없음 = 제거됨"으로 오탐한 것이다. 그대로 뒀으면
운영 DB의 유니크 제약(간호학과 중복 요건 사고를 막는 것)과 pgvector 인덱스를 날렸다.
**autogenerate 결과는 반드시 눈으로 확인할 것.**

Revision ID: 6285e7acb5ba
Revises: 883cd0847a1e
Create Date: 2026-08-19 15:01:46.616157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6285e7acb5ba'
down_revision: Union[str, Sequence[str], None] = '883cd0847a1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('student_graduation_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('program_type', sa.String(length=30), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('required_credits', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('earned_credits', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('registered_credits', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('expected_credits', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('satisfied', sa.Boolean(), nullable=True),
    sa.Column('failure_reason', sa.String(length=200), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'program_type', 'category', name='uq_student_graduation_categories_scope')
    )
    op.create_index(op.f('ix_student_graduation_categories_user_id'), 'student_graduation_categories', ['user_id'], unique=False)
    op.create_table('student_graduation_requirements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('program_type', sa.String(length=30), nullable=False),
    sa.Column('requirement_name', sa.String(length=100), nullable=False),
    sa.Column('detail_name', sa.String(length=200), nullable=False),
    sa.Column('pass_type', sa.String(length=50), nullable=True),
    sa.Column('acquired_date', sa.String(length=30), nullable=True),
    sa.Column('satisfied', sa.Boolean(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'program_type', 'requirement_name', 'detail_name', name='uq_student_graduation_requirements_scope')
    )
    op.create_index(op.f('ix_student_graduation_requirements_user_id'), 'student_graduation_requirements', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_student_graduation_requirements_user_id'), table_name='student_graduation_requirements')
    op.drop_table('student_graduation_requirements')
    op.drop_index(op.f('ix_student_graduation_categories_user_id'), table_name='student_graduation_categories')
    op.drop_table('student_graduation_categories')
