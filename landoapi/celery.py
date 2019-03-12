# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

import flask
from celery import Celery
from celery.signals import (
    after_task_publish,
    heartbeat_sent,
    setup_logging,
    task_failure,
    task_retry,
    task_success,
)
from datadog import statsd

from landoapi.systems import Subsystem

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

    @property
    def dispatch_disabled(self):
        """Will the Celery job system dispatch tasks to the workers?"""
        return bool(self.app.config.get("DISABLE_CELERY"))

    def init_app(self, app, config=None):
        """Initialize with a flask app."""
        self.app = app

        config = config or {}
        self.conf.update(main=app.import_name, **config)

        if self.dispatch_disabled:
            logger.warning(
                "DISABLE_CELERY application configuration variable set, the Celery job "
                "system has been disabled! Any features that depend on the job system "
                "will not function."
            )

    def _flask_override_task_class(self):
        """Change Task class to one which executes in a flask context."""
        # Define a Task subclass that saves a reference to self in the Task object so
        # the task object can find self.app (the Flask application object) even if
        # self.app hasn't been set yet.
        #
        # We need to delay all of the task's calls to self.app using a custom Task class
        # because the reference to self.app may not be valid at the time the Celery
        # application object creates it set of Task objects.  The programmer may
        # set self.app via the self.init_app() method at any time in the future.
        #
        # self.app is expected to be valid and usable by Task objects after the web
        # application is fully initialized and ready to serve requests.
        BaseTask = self.Task
        celery_self = self

        class FlaskTask(BaseTask):
            """A Celery Task subclass that has a reference to a Flask app."""

            def __call__(self, *args, **kwargs):
                # Override immediate calling of tasks, such as mytask().  This call
                # method is used by the Celery worker process.
                if flask.has_app_context():
                    return super().__call__(*args, **kwargs)

                with celery_self.app.app_context():
                    return super().__call__(*args, **kwargs)

            def apply_async(self, *args, **kwargs):
                # Override delayed calling of tasks, such as mytask.apply_async().
                # This call method is used by the Celery app when it wants to
                # schedule a job for eventual execution on a worker.
                if celery_self.dispatch_disabled:
                    return None
                else:
                    return super().apply_async(*args, **kwargs)

        self.Task = FlaskTask


celery = FlaskCelery()


@after_task_publish.connect
def count_task_published(**kwargs):
    # This is published by the app when a new task is kicked off.  It is also
    # published by workers when they put a task back on the queue for retrying.
    statsd.increment("lando-api.celery.tasks_published")


@heartbeat_sent.connect
def count_heartbeat(**kwargs):
    statsd.increment("lando-api.celery.heartbeats_from_workers")


@task_success.connect
def count_task_success(**kwargs):
    statsd.increment("lando-api.celery.tasks_succeeded")


@task_failure.connect
def count_task_failure(**kwargs):
    statsd.increment("lando-api.celery.tasks_failed")


@task_retry.connect
def count_task_retried(**kwargs):
    statsd.increment("lando-api.celery.tasks_retried")


@setup_logging.connect
def setup_celery_logging(**kwargs):
    # Prevent celery from overriding our logging configuration.
    pass


class CelerySubsystem(Subsystem):
    name = "celery"

    def init_app(self, app):
        super().init_app(app)

        # Import tasks to discover celery tasks.
        import landoapi.tasks  # noqa

        celery.init_app(
            self.flask_app,
            config={"broker_url": self.flask_app.config.get("CELERY_BROKER_URL")},
        )
        celery.log.setup()

    def ready(self):
        if self.flask_app.config.get("DISABLE_CELERY"):
            return True

        # TODO: Check connection to CELERY_BROKER_URL
        return True


celery_subsystem = CelerySubsystem()
