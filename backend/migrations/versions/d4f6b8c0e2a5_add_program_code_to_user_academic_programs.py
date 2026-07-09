"""add academic_program_code to user_academic_programs

사용자 학적 프로그램에서 졸업요건 세트(requirement_sets)를 코드로 바로
룩업할 수 있게 브리지 컬럼을 추가한다. 값은 portal-sync/가입 시점에
department/major의 브리지 컬럼에서 resolve해 채운다(엔진 어댑테이션은 후속 작업).

Revision ID: d4f6b8c0e2a5
Revises: c3e5a7b9d1f4
Create Date: 2026-07-09 12:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f6b8c0e2a5'
down_revision: Union[str, Sequence[str], None] = 'c3e5a7b9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_academic_programs',
        sa.Column('academic_program_code', sa.String(length=50), nullable=True),
    )
    op.create_foreign_key(
        'fk_uap_academic_program_code',
        'user_academic_programs',
        'academic_programs',
        ['academic_program_code'],
        ['academic_program_code'],
    )
    op.create_index(
        op.f('ix_user_academic_programs_academic_program_code'),
        'user_academic_programs',
        ['academic_program_code'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_user_academic_programs_academic_program_code'),
        table_name='user_academic_programs',
    )
    op.drop_constraint('fk_uap_academic_program_code', 'user_academic_programs', type_='foreignkey')
    op.drop_column('user_academic_programs', 'academic_program_code')
