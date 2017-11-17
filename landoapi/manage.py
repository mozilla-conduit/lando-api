# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

from flask_script import Manager

from landoapi.app import create_app
from landoapi.storage import alembic

version_path = os.getenv('VERSION_PATH', '/app/version.json')
app = create_app(version_path)
manager = Manager(app.app)


@manager.command
def revision(message):
    """Generate a new migration revision."""
    return alembic.revision(message)


@manager.command
def upgrade(hash='head'):
    """Run upgrades."""
    return alembic.upgrade(hash)


@manager.command
def downgrade(hash):
    """Downgrade to a hash."""
    return alembic.downgrade(hash)


if __name__ == "__main__":
    manager.run()
