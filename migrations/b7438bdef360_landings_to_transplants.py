"""landings to transplants

Revision ID: b7438bdef360
Revises:
Create Date: 2018-08-13 01:42:10.713666

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import MetaData, Table
from sqlalchemy.sql import select

# revision identifiers, used by Alembic.
revision = "b7438bdef360"
down_revision = None
branch_labels = ("default",)
depends_on = None

REPO_URLS = {}


def _get_repo_url(tree):
    if REPO_URLS:
        return REPO_URLS.get(tree, None)

    from landoapi.repos import REPO_CONFIG

    for env in REPO_CONFIG:
        for _, repo in REPO_CONFIG[env].items():
            REPO_URLS[repo.tree] = repo.url


def upgrade():
    # Create the new table.
    transplants = op.create_table(
        "transplants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "aborted", "submitted", "landed", "failed", name="transplantstatus"
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
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("requester_email", sa.String(length=254), nullable=True),
        sa.Column("repository_url", sa.Text(), nullable=True),
        sa.Column("tree", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )

    # Grab the landings table using reflection.
    connection = op.get_bind()
    meta = MetaData(bind=connection)
    landings = Table("landings", meta, autoload=True)

    # Migrate all of the landings to equivalent transplants.
    # We do the silly thing and load everything into memory,
    # which is okay here since we're at about 1k rows right
    # now and this is super simple.
    landing_rows = select([landings]).order_by(landings.c.id)
    result = connection.execute(landing_rows)
    for row in result:
        # Don't specify the id so that the sequence isn't
        # broken in the end. This does mean ids might not
        # match but we don't actually use them for anything
        # at this point. That being said, since we order
        # by id in the landings query we probably end up
        # with the same ids.
        ins = transplants.insert().values(
            request_id=row[landings.c.request_id],
            status=row[landings.c.status],
            created_at=row[landings.c.created_at],
            updated_at=row[landings.c.updated_at],
            revision_to_diff_id={
                str(row[landings.c.revision_id]): row[landings.c.diff_id]
            },
            revision_order=[str(row[landings.c.revision_id])],
            error=row[landings.c.error],
            result=row[landings.c.result],
            requester_email=row[landings.c.requester_email],
            repository_url=_get_repo_url(row[landings.c.tree]),
            tree=row[landings.c.tree],
        )
        connection.execute(ins)
