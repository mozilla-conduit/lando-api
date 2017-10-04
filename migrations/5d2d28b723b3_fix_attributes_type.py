"""fix-attributes-type

Revision ID: 5d2d28b723b3
Revises: 363fc0301235
Create Date: 2017-10-04 14:46:01.584606

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = '5d2d28b723b3'
down_revision = '363fc0301235'
branch_labels = ()
depends_on = None


def upgrade():
    # Change type of `status` to String. It was accidently created by Integer
    # SQLite was saving String value to this column without any error.

    # There is no full support of ALTER TABLE in SQLite.
    conn = op.get_bind()
    conn.execute(text('ALTER TABLE landings RENAME TO tmp_landings'))
    op.create_table(
        'landings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('revision_id', sa.String(length=30), nullable=True),
        sa.Column('diff_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('error', sa.String(length=128), nullable=True),
        sa.Column('result', sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('request_id')
    )
    result = conn.execute(
        text(
            'SELECT id, request_id, revision_id, diff_id, status, error, '
            'result FROM tmp_landings'
        )
    )
    for row in result:
        id, request_id, revision_id, diff_id, status, error, result = row

        conn.execute(
            text(
                'INSERT INTO landings '
                '(id, request_id, revision_id, diff_id, status, error, result)'
                'VALUES ({id}, {request_id}, "{revision_id}", {diff_id}, '
                '"{status}","{error}", "{result}")'.format(
                    id=id,
                    request_id=request_id,
                    revision_id=revision_id,
                    diff_id=diff_id,
                    status=status,
                    error=error,
                    result=result
                )
            )
        )

    op.drop_table('tmp_landings')


def downgrade():
    # I'm hesitant to downgrade the column type to Integer status when it is
    # written as string
    pass
