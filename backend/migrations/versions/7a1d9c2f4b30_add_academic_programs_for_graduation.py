"""add academic programs for graduation requirements

Revision ID: 7a1d9c2f4b30
Revises: 452075704d10
Create Date: 2026-07-02 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a1d9c2f4b30"
down_revision: Union[str, Sequence[str], None] = "452075704d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "academic_programs",
        sa.Column("academic_program_code", sa.String(length=50), nullable=False),
        sa.Column("survey_year", sa.Integer(), nullable=True),
        sa.Column("survey_round", sa.Integer(), nullable=True),
        sa.Column("school_code", sa.String(length=20), nullable=True),
        sa.Column("school_name", sa.String(length=100), nullable=True),
        sa.Column("campus_code", sa.String(length=20), nullable=True),
        sa.Column("campus_name", sa.String(length=100), nullable=True),
        sa.Column("college_code", sa.String(length=20), nullable=True),
        sa.Column("college_name", sa.String(length=100), nullable=True),
        sa.Column("program_name", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column("normalized_program_name", sa.String(length=300), nullable=True),
        sa.Column("parent_department_name", sa.String(length=200), nullable=True),
        sa.Column("major_name", sa.String(length=200), nullable=True),
        sa.Column("day_night_code", sa.String(length=20), nullable=True),
        sa.Column("day_night_name", sa.String(length=50), nullable=True),
        sa.Column("program_feature_code", sa.String(length=20), nullable=True),
        sa.Column("program_feature_name", sa.String(length=100), nullable=True),
        sa.Column("duration_code", sa.String(length=20), nullable=True),
        sa.Column("duration_name", sa.String(length=50), nullable=True),
        sa.Column("status_code", sa.String(length=20), nullable=True),
        sa.Column("status_name", sa.String(length=50), nullable=True),
        sa.Column("education_ministry_5_category", sa.String(length=100), nullable=True),
        sa.Column("degree_level", sa.String(length=50), nullable=True),
        sa.Column("quota_adjustment_type", sa.String(length=100), nullable=True),
        sa.Column("first_admission_year", sa.String(length=10), nullable=True),
        sa.Column("free_major_type_code", sa.String(length=20), nullable=True),
        sa.Column("free_major_type_name", sa.String(length=100), nullable=True),
        sa.Column("kedi_7_category", sa.String(length=100), nullable=True),
        sa.Column("source_updated_at", sa.String(length=50), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_bachelor", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("academic_program_code"),
    )
    op.create_index(op.f("ix_academic_programs_college_name"), "academic_programs", ["college_name"])
    op.create_index(op.f("ix_academic_programs_is_active"), "academic_programs", ["is_active"])
    op.create_index(op.f("ix_academic_programs_is_bachelor"), "academic_programs", ["is_bachelor"])
    op.create_index(
        op.f("ix_academic_programs_normalized_program_name"),
        "academic_programs",
        ["normalized_program_name"],
    )
    op.create_index(op.f("ix_academic_programs_program_name"), "academic_programs", ["program_name"])

    op.create_table(
        "academic_program_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("academic_program_code", sa.String(length=50), nullable=False),
        sa.Column("alias_type", sa.String(length=50), nullable=False),
        sa.Column("alias_name", sa.String(length=300), nullable=False),
        sa.Column("normalized_alias_name", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["academic_program_code"],
            ["academic_programs.academic_program_code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "academic_program_code",
            "alias_type",
            "alias_name",
            name="uq_academic_program_alias",
        ),
    )
    op.create_index(
        op.f("ix_academic_program_aliases_academic_program_code"),
        "academic_program_aliases",
        ["academic_program_code"],
    )
    op.create_index(op.f("ix_academic_program_aliases_alias_name"), "academic_program_aliases", ["alias_name"])
    op.create_index(
        op.f("ix_academic_program_aliases_normalized_alias_name"),
        "academic_program_aliases",
        ["normalized_alias_name"],
    )

    op.create_table(
        "department_academic_program_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("academic_program_code", sa.String(length=50), nullable=False),
        sa.Column("relation_type", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["academic_program_code"],
            ["academic_programs.academic_program_code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            "academic_program_code",
            "relation_type",
            name="uq_department_academic_program_mapping",
        ),
    )
    op.create_index(
        op.f("ix_department_academic_program_mappings_academic_program_code"),
        "department_academic_program_mappings",
        ["academic_program_code"],
    )
    op.create_index(
        op.f("ix_department_academic_program_mappings_department_id"),
        "department_academic_program_mappings",
        ["department_id"],
    )

    op.add_column("user_academic_programs", sa.Column("academic_program_code", sa.String(length=50), nullable=True))
    op.create_index(
        op.f("ix_user_academic_programs_academic_program_code"),
        "user_academic_programs",
        ["academic_program_code"],
    )
    op.create_foreign_key(
        "fk_user_academic_programs_academic_program_code",
        "user_academic_programs",
        "academic_programs",
        ["academic_program_code"],
        ["academic_program_code"],
    )

    op.add_column("requirement_sets", sa.Column("academic_program_code", sa.String(length=50), nullable=True))
    op.create_index(
        op.f("ix_requirement_sets_academic_program_code"),
        "requirement_sets",
        ["academic_program_code"],
    )
    op.create_foreign_key(
        "fk_requirement_sets_academic_program_code",
        "requirement_sets",
        "academic_programs",
        ["academic_program_code"],
        ["academic_program_code"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_requirement_sets_academic_program_code", "requirement_sets", type_="foreignkey")
    op.drop_index(op.f("ix_requirement_sets_academic_program_code"), table_name="requirement_sets")
    op.drop_column("requirement_sets", "academic_program_code")

    op.drop_constraint(
        "fk_user_academic_programs_academic_program_code",
        "user_academic_programs",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_user_academic_programs_academic_program_code"), table_name="user_academic_programs")
    op.drop_column("user_academic_programs", "academic_program_code")

    op.drop_index(
        op.f("ix_department_academic_program_mappings_department_id"),
        table_name="department_academic_program_mappings",
    )
    op.drop_index(
        op.f("ix_department_academic_program_mappings_academic_program_code"),
        table_name="department_academic_program_mappings",
    )
    op.drop_table("department_academic_program_mappings")

    op.drop_index(op.f("ix_academic_program_aliases_normalized_alias_name"), table_name="academic_program_aliases")
    op.drop_index(op.f("ix_academic_program_aliases_alias_name"), table_name="academic_program_aliases")
    op.drop_index(
        op.f("ix_academic_program_aliases_academic_program_code"),
        table_name="academic_program_aliases",
    )
    op.drop_table("academic_program_aliases")

    op.drop_index(op.f("ix_academic_programs_program_name"), table_name="academic_programs")
    op.drop_index(op.f("ix_academic_programs_normalized_program_name"), table_name="academic_programs")
    op.drop_index(op.f("ix_academic_programs_is_bachelor"), table_name="academic_programs")
    op.drop_index(op.f("ix_academic_programs_is_active"), table_name="academic_programs")
    op.drop_index(op.f("ix_academic_programs_college_name"), table_name="academic_programs")
    op.drop_table("academic_programs")
