"""status-as-enum

Revision ID: eb1679fbba86
Revises: 0cf34e32042e
Create Date: 2017-10-21 10:22:45.158192

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

from landoapi.models.landing import LandingStatus

# revision identifiers, used by Alembic.
revision = 'eb1679fbba86'
down_revision = '0cf34e32042e'
branch_labels = ()
depends_on = None


def upgrade():
    # Change type of `status` to Enum.
    conn = op.get_bind()
    conn.execute(
        text("UPDATE landings SET status='aborted' WHERE status='pending'")
    )
    conn.execute(
        text("UPDATE landings SET status='submitted' WHERE status='started'")
    )
    enum_type = sa.Enum(LandingStatus)
    enum_type.create(op.get_bind(), checkfirst=False)
    op.alter_column(
        'landings',
        'status',
        type_=enum_type,
        existing_type=sa.String(30),
        postgresql_using='status::landingstatus'
    )


def downgrade():
    # Change back the type of `status` to String
    enum_type = sa.Enum(LandingStatus)
    op.alter_column(
        'landings',
        'status',
        type_=sa.String(30),
        existing_type=sa.Enum(LandingStatus)
    )
    enum_type.drop(op.get_bind(), checkfirst=False)
    conn = op.get_bind()
    conn.execute(
        text("UPDATE landings SET status = 'pending' WHERE status='aborted'")
    )
    conn.execute(
        text(
            "UPDATE landings SET status = 'started' WHERE status='submitted'"
        )
    )
