"""revision worker changes

Revision ID: 6849fb8e7879
Revises: 50ffadceca83
Create Date: 2023-05-29 16:21:30.402756

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6849fb8e7879"
down_revision = "50ffadceca83"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("revision", sa.Column("patch_locked", sa.Boolean(), nullable=False))
    op.add_column(
        "revision", sa.Column("repo_name", sa.String(length=254), nullable=False)
    )
    op.add_column(
        "revision", sa.Column("repo_callsign", sa.String(length=254), nullable=False)
    )
    op.add_column(
        "revision",
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.add_column(
        "revision",
        sa.Column(
            "stack_graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
    )

    # ### additional commands manually added below.
    revision_status_values = (
        "NEW",
        "STALE",
        "WAITING",
        "PICKED_UP",
        "CHECKING",
        "PROBLEM",
        "READY",
        "QUEUED",
        "LANDING",
        "LANDED",
        "FAILED",
    )
    revision_status_enum = sa.Enum(*revision_status_values, name="revisionstatus")
    revision_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("revision", sa.Column("status", revision_status_enum, nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("revision", "stack_graph")
    op.drop_column("revision", "data")
    op.drop_column("revision", "repo_callsign")
    op.drop_column("revision", "repo_name")
    op.drop_column("revision", "patch_locked")

    # ### additional commands manually added below.
    revision_status_values = (
        "NEW",
        "STALE",
        "WAITING",
        "PICKED_UP",
        "CHECKING",
        "PROBLEM",
        "READY",
        "QUEUED",
        "LANDING",
        "LANDED",
        "FAILED",
    )
    revision_status_enum = sa.Enum(*revision_status_values, name="revisionstatus")
    revision_status_enum.drop(op.get_bind())

    op.drop_column("revision", "status")
    # ### end Alembic commands ###
