"""add rag chunks for curriculum and graduation requirement retrieval

Revision ID: a3b4c5d6e7f8
Revises: f6a7b8c9d0e1
Create Date: 2026-07-13 10:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        'rag_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=50), nullable=False),
        sa.Column('source_table', sa.String(length=100), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('major_id', sa.Integer(), nullable=True),
        sa.Column('curriculum_year', sa.String(length=10), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('grade', sa.String(length=10), nullable=True),
        sa.Column('semester', sa.String(length=20), nullable=True),
        sa.Column('course_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=255), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('embedding', Vector(dim=1536), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
        sa.ForeignKeyConstraint(['major_id'], ['majors.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_type', 'source_table', 'source_id', 'category', name='uq_rag_chunk_source'),
    )
    op.create_index(op.f('ix_rag_chunks_category'), 'rag_chunks', ['category'], unique=False)
    op.create_index(op.f('ix_rag_chunks_course_id'), 'rag_chunks', ['course_id'], unique=False)
    op.create_index(op.f('ix_rag_chunks_curriculum_year'), 'rag_chunks', ['curriculum_year'], unique=False)
    op.create_index(op.f('ix_rag_chunks_department_id'), 'rag_chunks', ['department_id'], unique=False)
    op.create_index(op.f('ix_rag_chunks_document_type'), 'rag_chunks', ['document_type'], unique=False)
    op.create_index(op.f('ix_rag_chunks_grade'), 'rag_chunks', ['grade'], unique=False)
    op.create_index(op.f('ix_rag_chunks_major_id'), 'rag_chunks', ['major_id'], unique=False)
    op.create_index(op.f('ix_rag_chunks_semester'), 'rag_chunks', ['semester'], unique=False)
    op.create_index(op.f('ix_rag_chunks_source_id'), 'rag_chunks', ['source_id'], unique=False)
    op.create_index(op.f('ix_rag_chunks_source_table'), 'rag_chunks', ['source_table'], unique=False)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding "
        "ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding")
    op.drop_index(op.f('ix_rag_chunks_source_table'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_source_id'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_semester'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_major_id'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_grade'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_document_type'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_department_id'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_curriculum_year'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_course_id'), table_name='rag_chunks')
    op.drop_index(op.f('ix_rag_chunks_category'), table_name='rag_chunks')
    op.drop_table('rag_chunks')
