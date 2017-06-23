# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from flask_alembic import Alembic
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
alembic = Alembic()
