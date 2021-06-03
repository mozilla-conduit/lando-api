# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from landoapi.models.base import Base


class TestModelsBase:
    """Tests various attributes on the `Base` model."""

    def test___tablename__(self):
        """Checks various capitalization combinations get parsed correctly."""

        class SomeModel(Base):
            pass

        class ALLCAPSModel(Base):
            pass

        class Model(Base):
            pass

        assert SomeModel.__tablename__ == "some_model"
        assert Model.__tablename__ == "model"
        assert ALLCAPSModel.__tablename__ == "allcaps_model"

    def test___repr__(self):
        """Checks the default printable representation of the Base model."""

        class AnotherModel(Base):
            pass

        test = AnotherModel(id=1)
        assert repr(test) == "<AnotherModel: 1>"
