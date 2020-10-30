# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import binascii

testedwith = b"5.5"

# For clarity
PASS, FAIL = 0, 1


def postfix_hook(ui, repo, replacements=None, wdirwritten=False, **kwargs):
    """Hook that runs after `hg fix` is complete."""
    if wdirwritten:
        ui.warn(b"Working directory was written; this should not happen\n")
        return FAIL

    if replacements:
        # Write a line containing the replacements after a separator
        ui.write(b"\nREPLACEMENTS: ")
        ui.write(b",".join(binascii.hexlify(binary) for binary in replacements))
        ui.write(b"\n")

    return PASS
