# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from flask_migrate import Migrate

from landoapi.systems import Subsystem

db = SQLAlchemy()
migrate = Migrate()


def _lock_table_for(
    db_session, mode="SHARE ROW EXCLUSIVE MODE", table=None, model=None
):
    """Locks a given table in the given database with the given mode.

    Args:
        db_session (SQLAlchemy.db.session): the database session to use
        mode (str): the lock mode to apply to the table when locking
        model (SQLAlchemy.db.model): a model to fetch the table name from
        table (str): a string representing the table name in the database

    Raises:
        TypeError: if either both model and table arguments are missing or provided
    """
    if table is not None and model is not None:
        raise TypeError("Only one of table or model should be provided")
    if table is None and model is None:
        raise TypeError("Missing table or model argument")

    query = f"LOCK TABLE {model.__table__.name} IN {mode};"
    db.session.execute(query)


class DBSubsystem(Subsystem):
    name = "database"

    def init_app(self, app):
        super().init_app(app)
        db.init_app(app)
        migrate.init_app(app=app, db=db)

    def healthy(self):
        try:
            with db.engine.connect() as conn:
                conn.execute("SELECT 1;")
        except DBAPIError as exc:
            return "DBAPIError: {!s}".format(exc)
        except SQLAlchemyError as exc:
            return "SQLAlchemyError: {!s}".format(exc)

        return True


db_subsystem = DBSubsystem()
