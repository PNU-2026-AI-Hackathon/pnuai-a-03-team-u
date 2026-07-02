"""add fk constraints to user_activity_recommendations

Revision ID: ec32676909bf
Revises: 9138e7c65da1
Create Date: 2026-07-02 09:29:54.338078

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec32676909bf'
down_revision: Union[str, Sequence[str], None] = '9138e7c65da1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_foreign_key(
        'fk_user_activity_recommendations_user_id', 'user_activity_recommendations', 'users',
        ['user_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_user_activity_recommendations_activity_id', 'user_activity_recommendations', 'activities',
        ['activity_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_user_activity_recommendations_activity_id', 'user_activity_recommendations', type_='foreignkey')
    op.drop_constraint('fk_user_activity_recommendations_user_id', 'user_activity_recommendations', type_='foreignkey')
