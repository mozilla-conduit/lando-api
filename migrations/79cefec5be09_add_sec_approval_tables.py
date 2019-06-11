"""add sec-approval tables

Revision ID: 79cefec5be09
Revises: 77c763c1cf82
Create Date: 2019-06-12 13:20:39.222573

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy.dialects import postgresql

revision = "79cefec5be09"
down_revision = "77c763c1cf82"
branch_labels = ()
depends_on = None


def upgrade():
    phid_column_type = sa.String(length=128)

    op.create_table(
        "secapproval_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phid", phid_column_type, nullable=False, unique=True),
    )

    op.create_table(
        "secapproval_request_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey("secapproval_revisions.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "comment_candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("secapproval_request_events")
    op.drop_table("secapproval_revisions")
