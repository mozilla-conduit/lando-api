# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import copy
import logging
import shlex
import uuid

import hglib

logger = logging.getLogger(__name__)


class HgCommandError(Exception):
    def __init__(self, hg_args, out):
        # we want to strip out any sensitive --config options
        hg_args = map(lambda x: x if not x.startswith("bugzilla") else "xxx", hg_args)
        message = "hg error in cmd: hg %s: %s" % (" ".join(hg_args), out)
        super().__init__(message)


class HgRepo:
    ENCODING = "utf-8"
    DEFAULT_CONFIGS = {
        "ui.interactive": "False",
        "extensions.purge": "",
        "extensions.strip": "",
    }

    def __init__(self, path, config=None):
        self.path = path
        self.config = copy.copy(self.DEFAULT_CONFIGS)
        if config is not None:
            self.config.update(config)

    def __enter__(self):
        configs = ["ui.interactive=False", "extensions.purge=", "extensions.strip="]
        self.hg_repo = hglib.open(self.path, encoding=self.ENCODING, configs=configs)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.clean_repo()
        except Exception as e:
            logger.exception(e)
        self.hg_repo.close()

    def push_bookmark(self, destination, bookmark):
        # Don't let unicode leak into command arguments.
        assert isinstance(bookmark, str), "bookmark arg is not str"

        target_cset = self.update_repo()

        rev = self.apply_changes(target_cset)
        self.run_hg_cmds(
            [["bookmark", bookmark], ["push", "-B", bookmark, destination]]
        )

        return rev

    def push(self, destination):
        target_cset = self.update_repo()

        rev = self.apply_changes(target_cset)
        self.run_hg_cmds([["push", "-r", "tip", destination]])

        return rev

    def update_repo(self):
        # Obtain remote tip. We assume there is only a single head.
        target_cset = self.get_remote_head()

        # Strip any lingering changes.
        self.clean_repo()

        # Pull from "upstream".
        self.update_from_upstream(target_cset)

        return target_cset

    def apply_changes(self, target_cset):
        raise NotImplementedError("abstract method call: apply_changes")

    def run_hg(self, args):
        correlation_id = uuid.uuid4()
        logger.info(
            "running hg command",
            extra={
                "command": ["hg"] + [shlex.quote(arg) for arg in args],
                "command_id": correlation_id,
                "path": self.path,
                "hg_pid": self.hg_repo.server.pid,
            },
        )

        out = hglib.util.BytesIO()
        err = hglib.util.BytesIO()
        out_channels = {b"o": out.write, b"e": err.write}
        ret = self.hg_repo.runcommand(
            [
                arg.encode(self.ENCODING) if isinstance(arg, str) else arg
                for arg in args
            ],
            {},
            out_channels,
        )

        out = out.getvalue()
        err = err.getvalue()
        if out:
            logger.info(
                "output from hg command",
                extra={
                    "command_id": correlation_id,
                    "path": self.path,
                    "hg_pid": self.hg_repo.server.pid,
                    "output": out.rstrip(),
                },
            )

        if ret:
            raise hglib.error.CommandError(args, ret, out, err)

        return out

    def run_hg_cmds(self, cmds):
        last_result = ""
        for cmd in cmds:
            try:
                last_result = self.run_hg(cmd)
            except hglib.error.CommandError as e:
                raise HgCommandError(cmd, e.out)
        return last_result

    def clean_repo(self, strip_non_public_commits=True):
        # Clean working directory.
        try:
            self.run_hg(["--quiet", "revert", "--no-backup", "--all"])
        except hglib.error.CommandError:
            pass
        try:
            self.run_hg(["purge", "--all"])
        except hglib.error.CommandError:
            pass

        # Strip any lingering draft changesets.
        if strip_non_public_commits:
            try:
                self.run_hg(["strip", "--no-backup", "-r", "not public()"])
            except hglib.error.CommandError:
                pass

    def dirty_files(self):
        return self.run_hg(
            [
                "status",
                "--modified",
                "--added",
                "--removed",
                "--deleted",
                "--unknown",
                "--ignored",
            ]
        )

    def get_remote_head(self):
        # Obtain remote head. We assume there is only a single head.
        # TODO: use a template here
        cset = self.run_hg_cmds([["identify", "upstream", "-r", "default"]])

        # Output can contain bookmark or branch name after a space. Only take
        # first component.
        cset = cset.split()[0]

        assert len(cset) == 12, cset
        return cset

    def update_from_upstream(self, remote_rev):
        # Pull "upstream" and update to remote tip.
        cmds = [
            ["pull", "upstream"],
            # TODO: why there is a -r?
            ["rebase", "--abort", "-r", remote_rev],
            ["update", "--clean", "-r", remote_rev],
        ]

        for cmd in cmds:
            try:
                self.run_hg(cmd)
            except hglib.error.CommandError as e:
                output = e.out
                if "abort: no rebase in progress" in output:
                    # there was no rebase in progress, nothing to see here
                    continue
                else:
                    raise HgCommandError(cmd, e.out)

    def rebase(self, base_revision, target_cset):
        # Perform rebase if necessary. Returns tip revision.
        cmd = ["rebase", "-s", base_revision, "-d", target_cset]

        assert len(target_cset) == 12

        # If rebasing onto the null revision, force the merge policy to take
        # our content, as there is no content in the destination to conflict
        # with us.
        if target_cset == "0" * 12:
            cmd.extend(["--tool", ":other"])

        try:
            self.run_hg(cmd)
        except hglib.error.CommandError as e:
            if "nothing to rebase" not in e.out:
                raise HgCommandError(cmd, e.out)

        return self.run_hg_cmds([["log", "-r", "tip", "-T", "{node}"]])
