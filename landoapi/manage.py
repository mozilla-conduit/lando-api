# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.app import create_app
from landoapi.models.storage import db

from flask_script import Manager

app = create_app('/version.json')
manager = Manager(app.app)


@manager.command
def create_db():
    """Creates SQLAlchemy database schema."""
    return db.create_all()


if __name__ == "__main__":
    manager.run()
