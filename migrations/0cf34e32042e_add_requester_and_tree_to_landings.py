"""add_requester_and_tree_to_landings

Revision ID: 0cf34e32042e
Revises: 6ddedb19080c
Create Date: 2017-11-14 22:00:30.366222

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0cf34e32042e'
down_revision = '6ddedb19080c'
branch_labels = ()
depends_on = None


def upgrade():
    op.add_column(
        'landings',
        sa.Column('requester_email', sa.String(length=128), nullable=True)
    )
    op.add_column(
        'landings', sa.Column('tree', sa.String(length=128), nullable=True)
    )


def downgrade():
    op.drop_column('landings', 'result')
    op.drop_column('landings', 'error')
