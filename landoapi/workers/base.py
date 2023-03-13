# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""This module contains the abstract repo worker implementation."""
from __future__ import annotations

import logging
import os
import subprocess
import re
from time import sleep
from landoapi.repos import repo_clone_subsystem
from landoapi.treestatus import treestatus_subsystem
from landoapi.models.configuration import ConfigurationVariable, ConfigurationKey


logger = logging.getLogger(__name__)


class Worker:
    """A base class for repository workers."""

    @property
    def THROTTLE_KEY(self) -> int:
        """Return the configuration key that specifies throttle delay."""
        return ConfigurationKey.WORKER_THROTTLE_SECONDS

    @property
    def STOP_KEY(self) -> ConfigurationKey:
        """Return the configuration key that prevents the worker from starting."""
        raise NotImplementedError()

    @property
    def PAUSE_KEY(self) -> ConfigurationKey:
        """Return the configuration key that pauses the worker."""
        raise NotImplementedError()

    def __init__(self, sleep_seconds: float = 5, with_ssh: bool = True):
        SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"

        # `sleep_seconds` is how long to sleep for if the worker is paused,
        # before checking if the worker is still paused.
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
    def _setup_ssh(ssh_private_key: str):
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
    def _paused(self) -> bool:
        """Return the value of the pause configuration variable."""
        # When the pause variable is True, the worker is temporarily paused. The worker
        # resumes when the key is reset to False.
        return ConfigurationVariable.get(self.PAUSE_KEY, False)

    @property
    def _running(self) -> bool:
        """Return the value of the stop configuration variable."""
        # When the stop variable is True, the worker will exit and will not restart,
        # until the value is changed to False.
        return not ConfigurationVariable.get(self.STOP_KEY, False)

    def _setup(self):
        """Perform various setup actions."""
        if hasattr(self, "ssh_private_key"):
            self._setup_ssh(self.ssh_private_key)

    def _start(self, max_loops: int | None = None, *args, **kwargs):
        """Run the main event loop."""
        # NOTE: The worker will exit when max_loops is reached, or when the stop
        # variable is changed to True.
        loops = 0
        while self._running:
            if max_loops is not None and loops >= max_loops:
                break
            while self._paused:
                # Wait a set number of seconds before checking paused variable again.
                self.throttle(self.sleep_seconds)
            self.loop(*args, **kwargs)
            loops += 1

        logger.info(f"{self} exited after {loops} loops.")

    @property
    def throttle_seconds(self) -> int:
        """The duration to pause for when the worker is being throttled."""
        return ConfigurationVariable.get(self.THROTTLE_KEY, 3)

    def throttle(self, seconds: int | None = None):
        """Sleep for a given number of seconds."""
        sleep(seconds if seconds is not None else self.throttle_seconds)

    def refresh_enabled_repos(self):
        """Refresh the list of repositories based on treestatus."""
        self.enabled_repos = [
            r
            for r in self.applicable_repos
            if treestatus_subsystem.client.is_open(repo_clone_subsystem.repos[r].tree)
        ]
        logger.info(f"{len(self.enabled_repos)} enabled repos: {self.enabled_repos}")

    def start(self, max_loops: int | None = None):
        """Run setup sequence and start the event loop."""
        if ConfigurationVariable.get(self.STOP_KEY, False):
            logger.warning(f"{self.STOP_KEY} set to True, will not start worker.")
            return
        self._setup()
        self._start(max_loops=max_loops)

    def loop(self, *args, **kwargs):
        """The main event loop."""
        raise NotImplementedError()
