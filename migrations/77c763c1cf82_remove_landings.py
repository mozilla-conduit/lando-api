"""remove landings

Revision ID: 77c763c1cf82
Revises: b7438bdef360
Create Date: 2019-01-09 01:52:12.450940

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "77c763c1cf82"
down_revision = "b7438bdef360"
branch_labels = ()
depends_on = None


def upgrade():
    op.drop_table("landings")


def downgrade():
    op.create_table(
        "landings",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("revision_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("diff_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("active_diff_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "aborted", "submitted", "landed", "failed", name="landingstatus"
            ),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("error", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("result", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column(
            "requester_email",
            sa.VARCHAR(length=254),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("tree", sa.VARCHAR(length=128), autoincrement=False, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="landings_pkey"),
        sa.UniqueConstraint("request_id", name="landings_request_id_key"),
    )
