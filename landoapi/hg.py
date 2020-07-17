# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import copy
import logging
import os
import shlex
import tempfile
import uuid

import hglib

from landoapi.hgexports import PatchHelper

logger = logging.getLogger(__name__)

# Username and SSH port to use when connecting to remote HG server.
landing_worker_username = os.environ.get("LANDING_WORKER_USERNAME", "app")
landing_worker_target_ssh_port = os.environ.get("LANDING_WORKER_TARGET_SSH_PORT", "22")


class HgException(Exception):
    @staticmethod
    def from_hglib_error(exc):
        out, err, args = exc.out, exc.err, exc.args
        msg = "hg error in cmd: hg {}: {}\n{}".format(
            " ".join(str(arg) for arg in args),
            out.decode(errors="replace"),
            err.decode(errors="replace"),
        ).rstrip()

        for cls in (LostPushRace, PatchConflict, TreeClosed, TreeApprovalRequired):
            for s in cls.SNIPPETS:
                if s in err or s in out:
                    return cls(msg)

        return HgCommandError(args, out, err, msg)


class HgCommandError(HgException):
    def __init__(self, hg_args, out, err, msg):
        self.hg_args = hg_args
        self.out = out
        self.err = err
        super().__init__(msg)


class TreeClosed(HgException):
    """Exception when pushing failed due to a closed tree."""

    SNIPPETS = (b"is CLOSED!",)


class TreeApprovalRequired(HgException):
    """Exception when pushing failed due to approval being required."""

    SNIPPETS = (b"APPROVAL REQUIRED!",)


class LostPushRace(HgException):
    """Exception when pushing failed due to another push happening."""

    SNIPPETS = (
        b"abort: push creates new remote head",
        b"repository changed while pushing",
    )


class PatchApplicationFailure(HgException):
    """Exception when there is a failure applying a patch."""

    pass


class NoDiffStartLine(PatchApplicationFailure):
    """Exception when patch is missing a Diff Start Line header."""

    pass


class PatchConflict(PatchApplicationFailure):
    """Exception when patch fails to apply due to a conflict."""

    # TODO: Parse affected files from hg output and present
    # them in a structured way.

    SNIPPETS = (
        b"unresolved conflicts (see hg resolve",
        b"hunk FAILED -- saving rejects to file",
        b"hunks FAILED -- saving rejects to file",
    )


class HgRepo:
    ENCODING = "utf-8"
    DEFAULT_CONFIGS = {
        "ui.username": "Otto Länd <bind-autoland@mozilla.com>",
        "ui.interactive": "False",
        "ui.merge": "internal:merge",
        "ui.ssh": (
            "ssh "
            '-o "SendEnv AUTOLAND_REQUEST_USER" '
            '-o "StrictHostKeyChecking no" '
            '-o "PasswordAuthentication no" '
            f'-o "User {landing_worker_username}" '
            f'-o "Port {landing_worker_target_ssh_port}"'
        ),
        "extensions.purge": "",
        "extensions.strip": "",
        "extensions.rebase": "",
        "extensions.set_landing_system": "/app/hgext/set_landing_system.py",
    }

    def __init__(self, path, config=None):
        self.path = path
        self.config = copy.copy(self.DEFAULT_CONFIGS)
        if config is not None:
            self.config.update(config)

    def _config_to_list(self):
        return ["{}={}".format(k, v) for k, v in self.config.items() if v is not None]

    def __enter__(self):
        self.hg_repo = hglib.open(
            self.path, encoding=self.ENCODING, configs=self._config_to_list()
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.clean_repo()
        except Exception as e:
            logger.exception(e)
        self.hg_repo.close()

    def clone(self, source):
        # Use of robustcheckout here would work, but is probably not worth
        # the hassle as most of the benefits come from repeated working
        # directory creation. Since this is a one-time clone and is unlikely
        # to happen very often, we can get away with a standard clone.
        hglib.clone(
            source=source,
            dest=self.path,
            encoding=self.ENCODING,
            configs=self._config_to_list(),
        )

    def run_hg(self, args):
        correlation_id = str(uuid.uuid4())
        logger.info(
            "running hg command",
            extra={
                "command": ["hg"] + [shlex.quote(str(arg)) for arg in args],
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
                    "output": out.rstrip().decode(self.ENCODING, errors="replace"),
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
                raise HgException.from_hglib_error(e)
        return last_result

    def clean_repo(self, *, strip_non_public_commits=True):
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

    def apply_patch(self, patch_io_buf):
        patch_helper = PatchHelper(patch_io_buf)
        if not patch_helper.diff_start_line:
            raise NoDiffStartLine()

        # Import the diff to apply the changes then commit separately to
        # ensure correct parsing of the commit message.
        f_msg = tempfile.NamedTemporaryFile()
        f_diff = tempfile.NamedTemporaryFile()
        with f_msg, f_diff:
            patch_helper.write_commit_description(f_msg)
            f_msg.flush()
            patch_helper.write_diff(f_diff)
            f_diff.flush()

            similarity_args = ["-s", "95"]

            # TODO: Using `hg import` here is less than ideal because
            # it does not use a 3-way merge. It would be better
            # to use `hg import --exact` then `hg rebase`, however we
            # aren't guaranteed to have the patche's parent changeset
            # in the local repo.
            # Also, Apply the patch, with file rename detection (similarity).
            # Using 95 as the similarity to match automv's default.
            import_cmd = ["import", "--no-commit"] + similarity_args

            try:
                if patch_helper.header("Fail HG Import") == b"FAIL":
                    # For testing, force a PatchConflict exception if this header is
                    # defined.
                    raise hglib.error.CommandError(
                        (),
                        1,
                        b"",
                        b"forced fail: hunk FAILED -- saving rejects to file",
                    )
                self.run_hg(import_cmd + [f_diff.name])
            except hglib.error.CommandError as exc:
                if isinstance(HgException.from_hglib_error(exc), PatchConflict):
                    # Try again using 'patch' instead of hg's internal patch utility.
                    # But first reset to a clean working directory as hg's attempt
                    # might have partially applied the patch.
                    logger.info("import failed, retrying with 'patch'", exc_info=exc)
                    import_cmd += ["--config", "ui.patch=patch"]
                    self.clean_repo(strip_non_public_commits=False)

                    try:
                        # When using an external patch util mercurial won't
                        # automatically handle add/remove/renames.
                        self.run_hg(import_cmd + [f_diff.name])
                        self.run_hg(["addremove"] + similarity_args)
                    except hglib.error.CommandError:
                        # Use the original exception from import with the built-in
                        # patcher since both attempts failed.
                        raise HgException.from_hglib_error(exc) from exc

            # Commit using the extracted date, user, and commit desc.
            # --landing_system is provided by the set_landing_system hgext.
            self.run_hg(
                ["commit"]
                + ["--date", patch_helper.header("Date")]
                + ["--user", patch_helper.header("User")]
                + ["--landing_system", "lando"]
                + ["--logfile", f_msg.name]
            )

    def push(self, target, bookmark=None):
        if bookmark is None:
            self.run_hg(["push", "-r", "tip", target])
        else:
            self.run_hg_cmds([["bookmark", bookmark], ["push", "-B", bookmark, target]])

    def update_repo(self, source):
        # Obtain remote tip. We assume there is only a single head.
        target_cset = self.get_remote_head(source)

        # Strip any lingering changes.
        self.clean_repo()

        # Pull from "upstream".
        self.update_from_upstream(source, target_cset)

        return target_cset

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

    def get_remote_head(self, source):
        # Obtain remote head. We assume there is only a single head.
        # TODO: use a template here
        cset = self.run_hg_cmds([["identify", source, "-r", "default"]])

        # Output can contain bookmark or branch name after a space. Only take
        # first component.
        cset = cset.split()[0]

        assert len(cset) == 12, cset
        return cset

    def update_from_upstream(self, source, remote_rev):
        # Pull and update to remote tip.
        cmds = [
            ["pull", source],
            ["rebase", "--abort", "-r", remote_rev],
            ["update", "--clean", "-r", remote_rev],
        ]

        for cmd in cmds:
            try:
                self.run_hg(cmd)
            except hglib.error.CommandError as e:
                if b"abort: no rebase in progress" in e.err:
                    # there was no rebase in progress, nothing to see here
                    continue
                else:
                    raise HgException.from_hglib_error(e)

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
            if b"nothing to rebase" not in e.out:
                raise HgException.from_hglib_error(e)

        return self.run_hg_cmds([["log", "-r", "tip", "-T", "{node}"]])
