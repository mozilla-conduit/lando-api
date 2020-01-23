"""add_landing_jobs

Revision ID: e9017f5b5524
Revises: 79cefec5be09
Create Date: 2020-01-31 00:33:42.165980

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e9017f5b5524"
down_revision = "79cefec5be09"
branch_labels = ()
depends_on = None


def upgrade():
    # TODO: CHECK constraints.
    op.create_table(
        "landing_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUBMITTED",
                "IN_PROGRESS",
                "FAILED",
                "LANDED",
                "CANCELLED",
                name="landingjobstatus",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revision_to_diff_id",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "revision_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requester_email", sa.String(length=254), nullable=False),
        sa.Column("repository_name", sa.Text(), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=True),
        sa.Column("landed_commit_id", sa.Text(), nullable=True),
        sa.Column("bug_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("landing_jobs")
