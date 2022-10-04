# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""This module contains the abstract repo worker implementation."""

import logging
import os
import subprocess
import re
from time import sleep
from landoapi.repos import repo_clone_subsystem
from landoapi.treestatus import treestatus_subsystem
from landoapi.models.configuration import ConfigurationVariable


logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, sleep_seconds=5, with_ssh=True):
        SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"
        self.sleep_seconds = sleep_seconds

        # The list of all repos that are enabled for this worker
        self.applicable_repos = (
            list(repo_clone_subsystem.repos)
            if hasattr(repo_clone_subsystem, "repos")
            else []
        )

        # The list of all repos that have open trees; refreshed when needed via
        # `self.refresh_enabled_repos`.
        self.enabled_repos = []

        if with_ssh:
            # Fetch ssh private key from the environment. Note that this key should be
            # stored in standard format including all new lines and new line at the end
            # of the file.
            self.ssh_private_key = os.environ.get(SSH_PRIVATE_KEY_ENV_KEY)
            if not self.ssh_private_key:
                logger.warning(f"No {SSH_PRIVATE_KEY_ENV_KEY} present in environment.")

    @staticmethod
    def _setup_ssh(ssh_private_key):
        """Add a given private ssh key to ssh agent.

        SSH keys are needed in order to push to repositories that have an ssh
        push path.

        The private key should be passed as it is in the key file, including all
        new line characters and the new line character at the end.

        Args:
            ssh_private_key (str): A string representing the private SSH key file.
        """
        # Set all the correct environment variables
        agent_process = subprocess.run(
            ["ssh-agent", "-s"], capture_output=True, universal_newlines=True
        )

        # This pattern will match keys and values, and ignore everything after the
        # semicolon. For example, the output of `agent_process` is of the form:
        #     SSH_AUTH_SOCK=/tmp/ssh-c850kLXXOS5e/agent.120801; export SSH_AUTH_SOCK;
        #     SSH_AGENT_PID=120802; export SSH_AGENT_PID;
        #     echo Agent pid 120802;
        pattern = re.compile("(.+)=([^;]*)")
        for key, value in pattern.findall(agent_process.stdout):
            logger.info(f"_setup_ssh: setting {key} to {value}")
            os.environ[key] = value

        # Add private SSH key to agent
        # NOTE: ssh-add seems to output everything to stderr, including upon exit 0.
        add_process = subprocess.run(
            ["ssh-add", "-"],
            input=ssh_private_key,
            capture_output=True,
            universal_newlines=True,
        )
        if add_process.returncode != 0:
            raise Exception(add_process.stderr)
        logger.info("Added private SSH key from environment.")

    @property
    def _paused(self):
        return ConfigurationVariable.get(self.PAUSE_KEY, False)

    @property
    def _running(self):
        # When STOP_KEY is False, the worker is running.
        return not ConfigurationVariable.get(self.STOP_KEY, False)

    def _setup(self):
        if hasattr(self, "ssh_private_key"):
            self._setup_ssh(self.ssh_private_key)

    def _start(self, *args, **kwargs):
        while self._running:
            while self._paused:
                self.sleep(self.sleep_seconds)
            self.loop(*args, **kwargs)
        logger.info(f"{self} exited.")

    def sleep(self, sleep_seconds):
        sleep(self.sleep_seconds)

    def refresh_enabled_repos(self):
        self.enabled_repos = [
            r
            for r in self.applicable_repos
            if treestatus_subsystem.client.is_open(repo_clone_subsystem.repos[r].tree)
        ]
        logger.info(f"{len(self.enabled_repos)} enabled repos: {self.enabled_repos}")

    def start(self):
        self._setup()
        self._start()

    def loop(self, *args, **kwargs):
        raise NotImplementedError()


class RevisionWorker(Worker):
    """A worker that pre-processes revisions.

    This worker continuously synchronises revisions with the remote Phabricator API
    and runs all applicable checks and processes on each revision, if needed.
    """

    # DB configuration.
    PAUSE_KEY = "REVISION_WORKER_PAUSED"
    STOP_KEY = "REVISION_WORKER_STOPPED"
    CAPACITY_KEY = "REVISION_WORKER_CAPACITY"
    THROTTLE_KEY = "REVISION_WORKER_THROTTLE_SECONDS"

    def __init__(self, *args, **kwargs):
        super().__init__(with_ssh=False, *args, **kwargs)

    @property
    def throttle_delay(self):
        return ConfigurationVariable.get(self.THROTTLE_KEY, 3)

    def throttle(self):
        sleep(self.throttle_delay)

    @property
    def capacity(self):
        """
        The number of revisions that this worker will fetch for processing per batch.
        """
        return ConfigurationVariable.get(self.CAPACITY_KEY, 2)
