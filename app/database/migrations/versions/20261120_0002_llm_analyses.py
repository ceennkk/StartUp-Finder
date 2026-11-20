"""Persist validated, versioned LLM analysis attempts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_analyses",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("analyzer_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "validation_status IN ('valid', 'invalid', 'failed')",
            name=op.f("ck_llm_analyses_validation_status_valid"),
        ),
        sa.CheckConstraint(
            "(validation_status = 'valid' AND result_json IS NOT NULL AND error_code IS NULL) "
            "OR (validation_status IN ('invalid', 'failed') "
            "AND result_json IS NULL AND error_code IS NOT NULL)",
            name=op.f("ck_llm_analyses_result_matches_status"),
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('provider_error', 'output_schema_invalid', 'evidence_invalid')",
            name=op.f("ck_llm_analyses_error_code_valid"),
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0) "
            "AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
            name=op.f("ck_llm_analyses_usage_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_llm_analyses_source_record_id_source_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_analyses")),
    )
    op.create_index(
        "uq_llm_analyses_success_identity",
        "llm_analyses",
        [
            "source_record_id",
            "input_hash",
            "analyzer_version",
            "prompt_version",
            "schema_version",
            "provider_name",
            "model_version",
        ],
        unique=True,
        postgresql_where=sa.text("validation_status = 'valid'"),
    )
    op.create_index(
        "ix_llm_analyses_source_record",
        "llm_analyses",
        ["source_record_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_analyses_source_record", table_name="llm_analyses")
    op.drop_index("uq_llm_analyses_success_identity", table_name="llm_analyses")
    op.drop_table("llm_analyses")
