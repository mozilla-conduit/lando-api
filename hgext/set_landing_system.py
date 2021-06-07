# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from mercurial import commands, encoding, extensions

testedwith = b"5.1 5.5"

EXTRA_KEY = b"moz-landing-system"


def commitcommand(orig, ui, repo, *args, **kwargs):
    repo.moz_landing_system = kwargs.get("landing_system")
    return orig(ui, repo, *args, **kwargs)


def reposetup(ui, repo):
    if not repo.local():
        return

    class MozLandingRepo(repo.__class__):
        def commit(self, *args, **kwargs):
            if hasattr(self, "moz_landing_system"):
                kwargs.setdefault("extra", {})
                kwargs["extra"][EXTRA_KEY] = encoding.tolocal(self.moz_landing_system)
            return super().commit(*args, **kwargs)

    repo.__class__ = MozLandingRepo


def extsetup(ui):
    entry = extensions.wrapcommand(commands.table, b"commit", commitcommand)
    options = entry[1]
    options.append(
        (b"", b"landing_system", b"", b"set commit's landing-system identifier")
    )
