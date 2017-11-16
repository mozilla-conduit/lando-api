"""Revision id to int

Revision ID: 63931b4fc767
Revises: eb1679fbba86
Create Date: 2017-11-16 19:19:29.627343

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = '63931b4fc767'
down_revision = 'eb1679fbba86'
branch_labels = ()
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Convert existing revision ids to digit format
    conn.execute(
        text("UPDATE landings SET revision_id = REPLACE(revision_id,'D','')")
    )
    op.alter_column(
        'landings',
        'revision_id',
        existing_type=sa.VARCHAR(length=30),
        type_=sa.Integer(),
        postgresql_using='revision_id::numeric',
        nullable=True
    )
    # ### end Alembic commands ###


def downgrade():
    op.alter_column(
        'landings',
        'revision_id',
        existing_type=sa.Integer(),
        type_=sa.VARCHAR(length=30),
        nullable=True
    )
    # ### end Alembic commands ###
