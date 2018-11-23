# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

import flask
from celery import Celery

logger = logging.getLogger(__name__)


class FlaskCelery(Celery):
    """Celery which executes task in a flask app context."""

    def __init__(self, *args, **kwargs):
        # Avoid passing the flask app to base Celery.
        flask_app = kwargs.pop("app", None)

        super().__init__(*args, **kwargs)

        # Important to run this after __init__ since task_cls
        # argument to base Celery can change what we're basing on.
        self._flask_override_task_class()

        if flask_app is not None:
            self.init_app(flask_app)

    def init_app(self, app, config=None):
        """Initialize with a flask app."""
        self.app = app
        self.conf.update(main=app.import_name, **config)

    def _flask_override_task_class(self):
        """Change Task class to one which executes in a flask context."""
        BaseTask = self.Task
        celery_self = self

        class FlaskTask(BaseTask):
            def __call__(self, *args, **kwargs):
                if flask.has_app_context():
                    return super().__call__(*args, **kwargs)

                with celery_self.app.app_context():
                    return super().__call__(*args, **kwargs)

        self.Task = FlaskTask


celery = FlaskCelery()


@celery.task
def log_landing_failure(request_id: int, error_msg: str):
    """Log that the Transplant service failed to land the user's code.

    Args:
        request_id: A Transplant service request identifier.
        error_msg: The error message returned by the Transplant service.
    """
    logger.info(f"Transplant request {request_id} failed! Reason: {error_msg}")
