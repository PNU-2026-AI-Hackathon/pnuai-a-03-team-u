"""add graduation requirement detail tables

Revision ID: 2d8a6f1c9b40
Revises: 7a1d9c2f4b30
Create Date: 2026-07-02 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d8a6f1c9b40"
down_revision: Union[str, Sequence[str], None] = "7a1d9c2f4b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_requirement_sets_program_type_year",
        "requirement_sets",
        ["academic_program_code", "program_type", "curriculum_year"],
    )

    op.create_table(
        "requirement_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=False),
        sa.Column("requirement_set_id", sa.Integer(), nullable=False),
        sa.Column("academic_program_code", sa.String(length=50), nullable=True),
        sa.Column("program_name", sa.String(length=200), nullable=True),
        sa.Column("program_type", sa.String(length=20), nullable=True),
        sa.Column("category_code", sa.String(length=80), nullable=False),
        sa.Column("category_name", sa.String(length=120), nullable=True),
        sa.Column("minimum_credits", sa.String(length=50), nullable=True),
        sa.Column("rule_type", sa.String(length=80), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("source_file", sa.String(length=1000), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_program_code"],
            ["academic_programs.academic_program_code"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_set_id"],
            ["requirement_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_requirement_categories_external_id"),
    )
    op.create_index(op.f("ix_requirement_categories_external_id"), "requirement_categories", ["external_id"])
    op.create_index(
        op.f("ix_requirement_categories_requirement_set_id"),
        "requirement_categories",
        ["requirement_set_id"],
    )
    op.create_index(
        op.f("ix_requirement_categories_academic_program_code"),
        "requirement_categories",
        ["academic_program_code"],
    )
    op.create_index(op.f("ix_requirement_categories_program_type"), "requirement_categories", ["program_type"])
    op.create_index(op.f("ix_requirement_categories_category_code"), "requirement_categories", ["category_code"])
    op.create_index(op.f("ix_requirement_categories_needs_review"), "requirement_categories", ["needs_review"])

    op.create_table(
        "requirement_courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=False),
        sa.Column("requirement_set_id", sa.Integer(), nullable=False),
        sa.Column("academic_program_code", sa.String(length=50), nullable=True),
        sa.Column("college_name", sa.String(length=100), nullable=True),
        sa.Column("program_name", sa.String(length=200), nullable=True),
        sa.Column("program_type", sa.String(length=20), nullable=True),
        sa.Column("curriculum_year", sa.String(length=10), nullable=True),
        sa.Column("category_code", sa.String(length=80), nullable=True),
        sa.Column("recommended_year", sa.String(length=20), nullable=True),
        sa.Column("recommended_semester", sa.String(length=20), nullable=True),
        sa.Column("raw_course_code", sa.String(length=80), nullable=True),
        sa.Column("raw_course_name", sa.String(length=255), nullable=True),
        sa.Column("raw_credit", sa.String(length=50), nullable=True),
        sa.Column("matched_course_code", sa.String(length=80), nullable=True),
        sa.Column("matched_course_name", sa.String(length=255), nullable=True),
        sa.Column("match_status", sa.String(length=50), nullable=True),
        sa.Column("match_method", sa.String(length=100), nullable=True),
        sa.Column("matched_terms", sa.Text(), nullable=True),
        sa.Column("matched_departments", sa.Text(), nullable=True),
        sa.Column("choice_rule_types", sa.String(length=200), nullable=True),
        sa.Column("choice_rule_raw", sa.Text(), nullable=True),
        sa.Column("source_table", sa.String(length=100), nullable=True),
        sa.Column("source_file", sa.String(length=1000), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_program_code"],
            ["academic_programs.academic_program_code"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_set_id"],
            ["requirement_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_requirement_courses_external_id"),
    )
    op.create_index(op.f("ix_requirement_courses_external_id"), "requirement_courses", ["external_id"])
    op.create_index(op.f("ix_requirement_courses_requirement_set_id"), "requirement_courses", ["requirement_set_id"])
    op.create_index(
        op.f("ix_requirement_courses_academic_program_code"),
        "requirement_courses",
        ["academic_program_code"],
    )
    op.create_index(op.f("ix_requirement_courses_program_type"), "requirement_courses", ["program_type"])
    op.create_index(op.f("ix_requirement_courses_curriculum_year"), "requirement_courses", ["curriculum_year"])
    op.create_index(op.f("ix_requirement_courses_category_code"), "requirement_courses", ["category_code"])
    op.create_index(op.f("ix_requirement_courses_matched_course_code"), "requirement_courses", ["matched_course_code"])
    op.create_index(op.f("ix_requirement_courses_match_status"), "requirement_courses", ["match_status"])
    op.create_index(op.f("ix_requirement_courses_needs_review"), "requirement_courses", ["needs_review"])

    op.create_table(
        "requirement_text_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=False),
        sa.Column("requirement_set_id", sa.Integer(), nullable=True),
        sa.Column("academic_program_code", sa.String(length=50), nullable=True),
        sa.Column("program_name", sa.String(length=200), nullable=True),
        sa.Column("program_type", sa.String(length=50), nullable=True),
        sa.Column("category_code", sa.String(length=100), nullable=True),
        sa.Column("rule_text", sa.Text(), nullable=True),
        sa.Column("rule_field", sa.String(length=120), nullable=True),
        sa.Column("rule_value", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("source_file", sa.String(length=1000), nullable=True),
        sa.Column("source_title", sa.String(length=500), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_program_code"],
            ["academic_programs.academic_program_code"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_set_id"],
            ["requirement_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_requirement_text_rules_external_id"),
    )
    op.create_index(op.f("ix_requirement_text_rules_external_id"), "requirement_text_rules", ["external_id"])
    op.create_index(
        op.f("ix_requirement_text_rules_requirement_set_id"),
        "requirement_text_rules",
        ["requirement_set_id"],
    )
    op.create_index(
        op.f("ix_requirement_text_rules_academic_program_code"),
        "requirement_text_rules",
        ["academic_program_code"],
    )
    op.create_index(op.f("ix_requirement_text_rules_program_type"), "requirement_text_rules", ["program_type"])
    op.create_index(op.f("ix_requirement_text_rules_category_code"), "requirement_text_rules", ["category_code"])
    op.create_index(op.f("ix_requirement_text_rules_needs_review"), "requirement_text_rules", ["needs_review"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_requirement_text_rules_needs_review"), table_name="requirement_text_rules")
    op.drop_index(op.f("ix_requirement_text_rules_category_code"), table_name="requirement_text_rules")
    op.drop_index(op.f("ix_requirement_text_rules_program_type"), table_name="requirement_text_rules")
    op.drop_index(op.f("ix_requirement_text_rules_academic_program_code"), table_name="requirement_text_rules")
    op.drop_index(op.f("ix_requirement_text_rules_requirement_set_id"), table_name="requirement_text_rules")
    op.drop_index(op.f("ix_requirement_text_rules_external_id"), table_name="requirement_text_rules")
    op.drop_table("requirement_text_rules")

    op.drop_index(op.f("ix_requirement_courses_needs_review"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_match_status"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_matched_course_code"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_category_code"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_curriculum_year"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_program_type"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_academic_program_code"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_requirement_set_id"), table_name="requirement_courses")
    op.drop_index(op.f("ix_requirement_courses_external_id"), table_name="requirement_courses")
    op.drop_table("requirement_courses")

    op.drop_index(op.f("ix_requirement_categories_needs_review"), table_name="requirement_categories")
    op.drop_index(op.f("ix_requirement_categories_category_code"), table_name="requirement_categories")
    op.drop_index(op.f("ix_requirement_categories_program_type"), table_name="requirement_categories")
    op.drop_index(op.f("ix_requirement_categories_academic_program_code"), table_name="requirement_categories")
    op.drop_index(op.f("ix_requirement_categories_requirement_set_id"), table_name="requirement_categories")
    op.drop_index(op.f("ix_requirement_categories_external_id"), table_name="requirement_categories")
    op.drop_table("requirement_categories")

    op.drop_constraint("uq_requirement_sets_program_type_year", "requirement_sets", type_="unique")
