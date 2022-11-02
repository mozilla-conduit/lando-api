# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import hashlib
import json
from copy import deepcopy
from collections import defaultdict

from landoapi.phabricator import (
    PhabricatorAPIException,
    PhabricatorClient,
    RevisionStatus,
    ReviewerStatus,
)
from landoapi.treestatus import TreeStatus, TreeStatusError

from tests.canned_responses.phabricator.diffs import (
    CANNED_DEFAULT_DIFF_CHANGES,
    CANNED_RAW_DEFAULT_DIFF,
)


def conduit_method(method):
    """Decorator to mark methods as a conduit method handler."""

    def decorate(f):
        f._conduit_method = method
        return f

    return decorate


def validate_hunk(hunk):
    """Validate a Phabricator Diff change hunk payload

    Inspired by https://github.com/phacility/arcanist/blob/conduit-6/src/parser/diff/ArcanistDiffHunk.php#L34  # noqa
    """
    assert isinstance(hunk, dict)

    # Fixed structure
    assert sorted(hunk.keys()) == [
        "addLines",
        "corpus",
        "delLines",
        "isMissingNewNewline",
        "isMissingOldNewline",
        "newLength",
        "newOffset",
        "oldLength",
        "oldOffset",
    ]

    # Check positions
    assert int(hunk["newLength"]) >= 0
    assert int(hunk["oldLength"]) >= 0
    assert int(hunk["newOffset"]) >= 0
    assert int(hunk["oldOffset"]) >= 0

    # Check corpus
    assert isinstance(hunk["corpus"], str)
    lines = hunk["corpus"].splitlines()
    assert len(lines) > 0
    assert all([line[0] in (" ", "-", "+") for line in lines])

    return True


def validate_change(change):
    """Validate a Phabricator Diff change payload

    Inspired by https://github.com/phacility/arcanist/blob/conduit-6/src/parser/diff/ArcanistDiffChange.php#L68  # noqa
    """
    assert isinstance(change, dict)

    # Check required fields
    for key in (
        "metadata",
        "hunks",
        "oldPath",
        "currentPath",
        "type",
        "fileType",
        "commitHash",
    ):
        assert key in change, f"Missing key {key}"

    assert isinstance(change["metadata"], dict)
    assert isinstance(change["oldPath"], str) and change["oldPath"] != ""
    assert isinstance(change["currentPath"], str) and change["currentPath"] != ""
    assert isinstance(change["hunks"], list) and len(change["hunks"]) > 0
    assert 1 <= int(change["type"]) <= 8
    assert 1 <= int(change["fileType"]) <= 7

    # Check hunks
    assert all(map(validate_hunk, change["hunks"]))

    return True


def get_stack(_phid, phabdouble):
    phids = set()
    new_phids = {_phid}
    edges = []

    # Repeatedly request all related edges, adding connected revisions
    # each time until no new revisions are found.
    # NOTE: this was adapted from previous implementation of build_stack_graph.
    while new_phids:
        phids.update(new_phids)
        edges = [
            e
            for e in phabdouble._edges
            if e["sourcePHID"] in phids
            and e["edgeType"] in ("revision.parent", "revision.child")
        ]
        new_phids = set()
        for edge in edges:
            new_phids.add(edge["sourcePHID"])
            new_phids.add(edge["destinationPHID"])

        new_phids = new_phids - phids

    # Treat the stack like a commit DAG, we only care about edges going
    # from child to parent. This is enough to represent the graph.
    edges = {
        (edge["sourcePHID"], edge["destinationPHID"])
        for edge in edges
        if edge["edgeType"] == "revision.parent"
    }

    stack_graph = defaultdict(list)
    sources = [edge[0] for edge in edges]
    for source, dest in edges:
        # Check that destination phid has a corresponding source phid.
        if dest not in sources:
            # We are at a root node.
            stack_graph[dest] = []
        stack_graph[source].append(dest)
    if not stack_graph:
        # There is only one node, the root node.
        stack_graph[_phid] = []
    return dict(stack_graph)


class PhabricatorDouble:
    """Phabricator test double.

    Can generate / return data of the same form calls to Phabricator
    through the PhabricatorClient would. The PhabricatorClient is
    monkeypatched to allow use in integration testing as well.

    Not all conduit method arguments / constraints are implemented,
    many being ignored entirely, by design. As Lando API needs to make
    use of more methods / arguments support should be added.
    """

    def __init__(self, monkeypatch):
        self._transactions = []
        self._users = []
        self._projects = []
        self._revisions = []
        self._reviewers = []
        self._repos = []
        self._diffs = []
        self._diff_refs = []
        self._comments = []
        self._phids = []
        self._phid_counters = {}
        self._edges = []
        self._handlers = self._build_handlers()

        monkeypatch.setattr(PhabricatorClient, "call_conduit", self.call_conduit)

    def call_conduit(self, method, **kwargs):
        handler = self._handlers.get(method)

        if handler is None:
            raise ValueError(
                'PhabricatorDouble does not have support for "{}". '
                "If you have added a new call to this method please "
                "update PhabricatorDouble to support it.".format(method)
            )

        return handler(**kwargs)

    def api_object_for(self, mock_object: dict, **kwargs) -> dict:
        """Converts a PhabDouble object into a Phabricator search API result object.

        This is useful for tests that need to generate mock API objects, convert the
        mock to the structure as returned by the Phabricator API search methods,
        and then pass the API search result representation to the code under test.

        For example, for a `phabdouble.revision()` object, this method will return the
        same Revision object that would be found by calling
        `PhabricatorClient.call_conduit("differential.revision.search")` directly from
        the test.

        Args:
            mock_object: A Phabricator mock object returned by one of the
                PhabricatorDouble factory methods, such as revision() or diff().
            kwargs: Optional keyword arguments to pass to call_conduit.

        Returns:
            The first object in the API search result that matches the PHID of the
            mock_object argument.

        Raises:
            ValueError if this method fails to find exactly one object matching the
            mock_object's PHID in the Phabricator API search results.
        """
        search_method_for_type = {
            "DIFF": "differential.diff.search",
            "DREV": "differential.revision.search",
            "PROJ": "project.search",
            "REPO": "diffusion.repository.search",
            "USER": "user.search",
        }

        if mock_object["phid"].startswith("PHID-XACT-"):
            # Transaction objects use a special search endpoint with different
            # arguments.
            result = self.call_conduit(
                "transaction.search",
                objectIdentifier=mock_object["objectPHID"],
                constraints={"phids": [mock_object["phid"]]},
            )
        else:
            method = search_method_for_type[mock_object["type"]]
            result = self.call_conduit(
                method, constraints={"phids": [mock_object["phid"]]}, **kwargs
            )

        return PhabricatorClient.single(result, "data")

    @staticmethod
    def get_phabricator_client():
        return PhabricatorClient("https://localhost", "DOESNT-MATTER")

    def update_revision_dependencies(self, phid: str, depends_on: list[str]):
        """Updates edges of `phid` so they match `depends_on`."""
        # Remove all previous edges related to this revision.
        def philter(edge):
            return phid not in (edge["sourcePHID"], edge["destinationPHID"])

        self._edges = list(filter(philter, self._edges))

        for rev in depends_on:
            self._edges.append(
                {
                    "edgeType": "revision.parent",
                    "sourcePHID": phid,
                    "destinationPHID": rev["phid"],
                }
            )
            self._edges.append(
                {
                    "edgeType": "revision.child",
                    "sourcePHID": rev["phid"],
                    "destinationPHID": phid,
                }
            )

    def revision(
        self,
        *,
        diff=None,
        author=None,
        repo=None,
        status=RevisionStatus.ACCEPTED,
        depends_on=[],
        bug_id=None,
        projects=[],
        comments=[],
        title="",
        summary="",
        uplift=None,
    ):
        revision_id = self._new_id(self._revisions)
        phid = self._new_phid("DREV-")
        uri = "http://phabricator.test/D{}".format(revision_id)
        title = "my test revision title" if not title else title

        author = self.user() if author is None else author

        diff = self.diff() if diff is None else diff
        diff["revisionID"] = revision_id
        diff["revisionPHID"] = phid
        diff["authorPHID"] = author["phid"]

        revision = {
            "id": revision_id,
            "type": "DREV",
            "phid": phid,
            "title": title,
            "uri": uri,
            "dateCreated": 1495638270,
            "dateModified": 1496239141,
            "authorPHID": author["phid"],
            "status": status,
            "properties": [],
            "branch": None,
            "summary": summary or "my test revision summary",
            "testPlan": "my revision test plan",
            "lineCount": "2",
            "commits": [],
            "ccs": [],
            "hashes": [],
            "bugzilla.bug-id": bug_id,
            "uplift.request": uplift,
            "repositoryPHID": repo["phid"] if repo is not None else None,
            "fields": {
                "repositoryPHID": repo["phid"] if repo is not None else None,
                "uplift.request": uplift,
            },
            "sourcePath": None,
            # projectPHIDs is left for backwards compatibility for older tests, though
            # it appears to no longer be in the response from the Phabricator API.
            "projectPHIDs": [project["phid"] for project in projects],
            "attachments": {
                "projects": {"projectPHIDs": [project["phid"] for project in projects]}
            },
        }

        for rev in depends_on:
            self._edges.append(
                {
                    "edgeType": "revision.parent",
                    "sourcePHID": phid,
                    "destinationPHID": rev["phid"],
                }
            )
            self._edges.append(
                {
                    "edgeType": "revision.child",
                    "sourcePHID": rev["phid"],
                    "destinationPHID": phid,
                }
            )

        self._revisions.append(revision)
        self._phids.append(
            {
                "phid": phid,
                "uri": uri,
                "typeName": "Differential Revision",
                "type": "DREV",
                "name": "D{}".format(revision_id),
                "fullName": "D{} {}".format(revision_id, title),
                "status": "closed" if status.closed else "open",
            }
        )

        for comment in comments:
            self.transaction("comment", revision, comments=[comment])

        return revision

    def user(self, *, username="imadueme_admin"):
        """Return a Phabricator User."""
        users = [u for u in self._users if u["userName"] == username]
        if users:
            return users[0]

        phid = self._new_phid("USER-{}".format(username))
        fullname = "{} Name".format(username)
        email = "{}@example.com".format(username)
        uri = "http://phabricator.test/p/{}".format(username)
        user = {
            "id": self._new_id(self._users),
            "apiKey": "api-{}".format(
                hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]
            ),
            "type": "USER",
            "phid": phid,
            "email": email,
            "dateCreated": 1523372677,
            "dateModified": 1523372678,
            "policy": {"view": "public", "edit": "no-one"},
            "userName": username,
            "realName": fullname,
            "image": "https://example.com/image.png",
            "uri": uri,
            "roles": ["verified", "approved", "activated"],
        }

        self._users.append(user)
        self._phids.append(
            {
                "phid": phid,
                "uri": uri,
                "typeName": "User",
                "type": "USER",
                "name": username,
                "fullName": fullname,
                "status": "open",
            }
        )

        return user

    def diff(
        self,
        *,
        revision=None,
        rawdiff=CANNED_RAW_DEFAULT_DIFF,
        changes=None,
        repo=None,
        commits=[
            {
                "identifier": "b15b8fbc79c2c3977aff9e17f0dfcc34c66ec29f",
                "tree": None,
                "parents": ["cff9ba1622714e0dd82c39f912f405210489fce8"],
                "author": {
                    "name": "Mark Cote",
                    "email": "mcote@mozilla.com",
                    "raw": '"Mark Cote" <mcote@mozilla.com>',
                    "epoch": 1524854743,
                },
                "message": "This is the commit message.",
            }
        ],
        refs=[
            {"type": "base", "identifier": "cff9ba1622714e0dd82c39f912f405210489fce8"}
        ],
    ):
        diff_id = self._new_id(self._diffs)
        phid = self._new_phid("DIFF-")
        uri = "http://phabricator.test/differential/diff/{}/".format(diff_id)
        revision_id = revision["id"] if revision is not None else None
        revision_phid = revision["phid"] if revision is not None else None
        author_phid = revision["authorPHID"] if revision is not None else None
        repo_phid = (
            repo["phid"]
            if repo is not None
            else (revision["repositoryPHID"] if revision is not None else None)
        )

        refs = deepcopy(refs)
        base = None
        for ref in refs:
            ref["diff_id"] = diff_id
            if ref["type"] == "base":
                base = ref["identifier"]

        self._diff_refs += refs

        author_name, author_email = None, None
        if commits:
            author_name = commits[0]["author"]["name"]
            author_email = commits[0]["author"]["email"]

        # Validate changes
        changes = changes or deepcopy(CANNED_DEFAULT_DIFF_CHANGES)
        assert isinstance(changes, list)
        assert len(changes) > 0, "No changes"
        assert all(map(validate_change, changes)), "Invalid changes"

        diff = {
            "id": diff_id,
            "phid": phid,
            "type": "DIFF",
            "rawdiff": rawdiff,
            "bookmark": None,
            "branch": None,
            "changes": changes,
            "creationMethod": "arc",
            "dateCreated": 1516718328,
            "dateModified": 1516718341,
            "description": None,
            "lintStatus": "0",
            "properties": [],
            "revisionID": revision_id,
            "revisionPHID": revision_phid,
            "authorPHID": author_phid,
            "repositoryPHID": repo_phid,
            "sourceControlBaseRevision": base,
            "sourceControlPath": "/",
            "sourceControlSystem": "hg",
            "unitStatus": "0",
            "authorName": author_name,
            "authorEmail": author_email,
            "policy": {"view": "public"},
            "commits": deepcopy(commits),
        }

        self._diffs.append(diff)
        self._phids.append(
            {
                "phid": phid,
                "uri": uri,
                "typeName": "Differential Diff",
                "type": "DIFF",
                "name": "Diff {}".format(diff_id),
                "fullName": "Diff {}".format(diff_id),
                "status": "open",
            }
        )

        return diff

    def repo(self, *, name="mozilla-central", projects=None):
        projects = projects or []
        repos = [r for r in self._repos if r["name"] == name]
        if repos:
            return repos[0]

        repo_id = self._new_id(self._repos)
        phid = self._new_phid("REPO-")
        callsign = name.upper()
        uri = "http://phabricator.test/source/{}/".format(name)
        repo = {
            "id": repo_id,
            "type": "REPO",
            "phid": phid,
            "name": name,
            "vcs": "hg",
            "callsign": callsign,
            "shortName": name,
            "status": "active",
            "isImporting": False,
            "spacePHID": None,
            "dateCreated": 1502986064,
            "dateModified": 1505659447,
            "policy": {"view": "public", "edit": "admin", "diffusion.push": "no-one"},
            "attachments": {
                "projects": {"projectPHIDs": [project["phid"] for project in projects]}
            },
            "defaultBranch": "default",
        }

        self._repos.append(repo)
        self._phids.append(
            {
                "phid": phid,
                "uri": uri,
                "typeName": "Repository",
                "type": "REPO",
                "name": "r{}".format(callsign),
                "fullName": "r{} {}".format(callsign, name),
                "status": "open",
            }
        )

        return repo

    def reviewer(
        self,
        revision,
        user_or_project,
        *,
        status=ReviewerStatus.ACCEPTED,
        isBlocking=False,
        actor=None,
        on_diff=None,
        voided_by_phid=None,
    ):
        if on_diff is None:
            # Default to the latest.
            diffs = sorted(
                (d for d in self._diffs if d["revisionID"] == revision["id"]),
                key=lambda d: d["id"],
            )
            on_diff = diffs[-1]
        actor_phid = revision["authorPHID"] if actor is None else actor["phid"]
        reviewer = {
            "revisionPHID": revision["phid"],
            "revisionID": revision["id"],
            "reviewerPHID": user_or_project["phid"],
            "reviewerID": user_or_project["id"],
            "status": status,
            "isBlocking": isBlocking,
            "actorPHID": actor_phid,
            "diffPHID": on_diff["phid"],
            "voidedPHID": voided_by_phid,
        }

        current_reviewers = [
            r
            for r in self._reviewers
            if (
                r["revisionID"] == revision["id"]
                and r["reviewerPHID"] == reviewer["reviewerPHID"]
            )
        ]

        if current_reviewers:
            current_reviewers[0].update(reviewer)
        else:
            self._reviewers.append(reviewer)

        return reviewer

    def project(self, name, *, attachments=None, no_slug=False):
        """Return a Phabricator Project."""
        projects = [p for p in self._projects if p["name"] == name]
        if projects:
            return projects[0]

        if not attachments:
            attachments = {}

        phid = self._new_phid("PROJ-")
        uri = "http://phabricator.test/tag/{}/".format(name)

        project = {
            "id": self._new_id(self._projects),
            "type": "PROJ",
            "phid": phid,
            "uri": uri,
            "name": name,
            "slug": None if no_slug else name,
            "milestone": None,
            # Subprojects not mocked.
            "depth": 0,
            "parent": None,
            "icon": {"key": "experimental", "name": "Experimental", "icon": "fa-flask"},
            "color": {"key": "orange", "name": "Orange"},
            "dateCreated": 1524762062,
            "dateModified": 1524762062,
            "policy": {"view": "public", "edit": "admin", "join": "admin"},
            "description": "Project named {}".format(name),
            "attachments": attachments,
        }
        self._projects.append(project)
        self._phids.append(
            {
                "phid": phid,
                "uri": uri,
                "typeName": "Project",
                "type": "PROJ",
                "name": name,
                "fullName": name,
                "status": "open",
            }
        )

        return project

    def transaction(
        self, transaction_type: str, object: dict, operations=None, comments=None
    ):
        """Return a Phabricator Transaction object.

        Args:
            transaction_type: String describing the transaction type.
                e.g. "subscribers", "projects", "accept".
            object: A dict structured as a Phabricator API object being modified by the
                transaction. e.g. a revision dict or project dict.
            operations: Optional list of operations that the transaction is performing.
                Note that this argument's value and structure can change depending on
                the value of the "type" argument.
                e.g. When adding a subscriber to a revision the transaction type would
                be "subscriber" and the operations argument would be
                [{ "operation": "add", "phid": "PHID-USER-abc123"}]
            comments: Optional list of comment objects this transaction created. Only
                applies when the transaction type is "comment" or "inline". Structure
                varies greatly depending on the comment type.

        """
        # Pull out what type of object we are operating on: DREV? PROJ?
        object_type = object["type"]
        object_phid = object["phid"]
        comments = comments or []
        fields = {}

        if operations:
            fields["operations"] = operations

        phid = self._new_phid(f"XACT-{object_type}-")
        transaction = {
            "id": self._new_id(self._transactions),
            "phid": phid,
            "type": transaction_type,
            # Not implemented.
            "authorPHID": None,
            "objectPHID": object_phid,
            "dateCreated": 1559779750,
            "dateModified": 1559779750,
            # No idea what this field is for.
            "groupID": "zmgrbvzbcclaubtg4yt2ihwwotxewc4h",
            "comments": comments,
            "fields": fields,
        }
        self._transactions.append(transaction)
        self._phids.append(
            {
                "phid": phid,
                # Unlike other objects transactions don't have a URI. This field
                # is just the hostname with no path component.
                "uri": "https://phabricator.test",
                "typeName": "Transaction",
                "type": "XACT",
                "name": "Unknown Object (Transaction)",
                "fullName": "Unknown Object (Transaction)",
                "status": "open",
            }
        )
        return transaction

    def comment(self, content, author=None):
        """Return a Phabricator Comment object.

        Args:
            content: The raw (Remarkup) comment contents.
            author: Optional Phabricator User that authored the comment. If None
                then a new User will be generated.
        """
        phid = self._new_phid("XCMT-")
        author = self.user() if author is None else author
        comment = {
            "id": self._new_id(self._comments),
            "phid": phid,
            "version": 1,
            "authorPHID": author["phid"],
            "dateCreated": 1570502242,
            "dateModified": 1570502242,
            "removed": False,
            "content": {"raw": content},
        }

        self._comments.append(comment)

        return comment

    @conduit_method("conduit.ping")
    def conduit_ping(self):
        return "ip-123-123-123-123.us-west-2.compute.internal"

    @conduit_method("project.search")
    def project_search(
        self,
        *,
        queryKey=None,
        constraints={},
        attachments={},
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            return deepcopy(
                {
                    "id": i["id"],
                    "type": i["type"],
                    "phid": i["phid"],
                    "fields": {
                        "name": i["name"],
                        "slug": i["slug"],
                        "milestone": i["milestone"],
                        "depth": i["depth"],
                        "parent": i["parent"],
                        "icon": {
                            "key": i["icon"]["key"],
                            "name": i["icon"]["name"],
                            "icon": i["icon"]["icon"],
                        },
                        "color": {"key": i["color"]["key"], "name": i["color"]["name"]},
                        "dateCreated": i["dateCreated"],
                        "dateModified": i["dateModified"],
                        "policy": {
                            "view": i["policy"]["view"],
                            "edit": i["policy"]["edit"],
                            "join": i["policy"]["join"],
                        },
                        "description": i["description"],
                    },
                    "attachments": i["attachments"],
                }
            )

        items = [p for p in self._projects]

        if "ids" in constraints:
            if not constraints["ids"]:
                error_info = 'Error while reading "ids": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["id"] in constraints["ids"]]

        if "phids" in constraints:
            if not constraints["phids"]:
                error_info = 'Error while reading "phids": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["phid"] in constraints["phids"]]

        if "slugs" in constraints:
            if not constraints["slugs"]:
                error_info = 'Error while reading "slugs": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["slug"] in constraints["slugs"]]

        return {
            "data": [to_response(i) for i in items],
            "maps": {"slugMap": {}},
            "query": {"queryKey": queryKey},
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("differential.diff.search")
    def differential_diff_search(
        self,
        *,
        queryKey=None,
        constraints=None,
        attachments=None,
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            refs = [r for r in self._diff_refs if r["diff_id"] == i["id"]]
            resp = {
                "id": i["id"],
                "type": i["type"],
                "phid": i["phid"],
                "fields": {
                    "revisionPHID": i["revisionPHID"],
                    "authorPHID": i["authorPHID"],
                    "repositoryPHID": i["repositoryPHID"],
                    "refs": [
                        {"type": r["type"], "identifier": r["identifier"]} for r in refs
                    ],
                    "dateCreated": i["dateCreated"],
                    "dateModified": i["dateModified"],
                    "policy": {"view": i["policy"]["view"]},
                },
                "attachments": {},
            }

            if attachments and attachments.get("commits"):
                resp["attachments"]["commits"] = {"commits": i["commits"]}

            return deepcopy(resp)

        items = [r for r in self._diffs]

        if constraints and "ids" in constraints:
            items = [i for i in items if i["id"] in constraints["ids"]]

        if constraints and "phids" in constraints:
            items = [i for i in items if i["phid"] in constraints["phids"]]

        if constraints and "revisionPHIDs" in constraints:
            items = [
                i for i in items if i["revisionPHID"] in constraints["revisionPHIDs"]
            ]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {"queryKey": queryKey},
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("edge.search")
    def edge_search(
        self,
        *,
        sourcePHIDs=None,
        types=None,
        destinationPHIDs=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            return deepcopy(
                {
                    "edgeType": i["edgeType"],
                    "sourcePHID": i["sourcePHID"],
                    "destinationPHID": i["destinationPHID"],
                }
            )

        if not sourcePHIDs:
            error_info = "Edge object query must be executed with a nonempty list of source PHIDs."  # noqa
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        if not types:
            error_info = "Edge search must specify a nonempty list of edge types."
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        if not set(types) <= set(
            (
                "commit.revision",
                "commit.task",
                "mention",
                "mentioned-in",
                "revision.child",
                "revision.commit",
                "revision.parent",
                "revision.task",
                "task.commit",
                "task.duplicate",
                "task.merged-in",
                "task.parent",
                "task.revision",
                "task.subtask",
            )
        ):
            error_info = 'Edge type "<type-is-here>" is not a recognized edge type.'
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        items = [e for e in self._edges]
        items = [i for i in items if i["sourcePHID"] in sourcePHIDs]
        items = [i for i in items if i["edgeType"] in types]

        if destinationPHIDs:
            items = [i for i in items if i["destinationPHID"] in destinationPHIDs]

        return {
            "data": [to_response(i) for i in items],
            "cursor": {"limit": limit, "after": after, "before": before},
        }

    @conduit_method("differential.revision.search")
    def differential_revision_search(
        self,
        *,
        queryKey=None,
        constraints=None,
        attachments=None,
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            diffs = sorted(
                (d for d in self._diffs if d["revisionID"] == i["id"]),
                key=lambda d: d["id"],
            )
            bug_id = (
                str(i["bugzilla.bug-id"]) if i["bugzilla.bug-id"] is not None else ""
            )
            uplift = i["uplift.request"] if i["uplift.request"] is not None else ""

            resp = {
                "id": i["id"],
                "type": i["type"],
                "phid": i["phid"],
                "fields": {
                    "title": i["title"],
                    "authorPHID": i["authorPHID"],
                    "stackGraph": i["stack_graph"],
                    "status": {
                        "value": i["status"].value,
                        "name": i["status"].output_name,
                        "closed": i["status"].closed,
                        "color.ansi": i["status"].color,
                    },
                    "repositoryPHID": i["repositoryPHID"],
                    "diffPHID": diffs[-1]["phid"],
                    "diffID": diffs[-1]["id"],
                    "summary": i["summary"],
                    "dateCreated": i["dateCreated"],
                    "dateModified": i["dateModified"],
                    "policy": {"view": "public", "edit": "users"},
                    "bugzilla.bug-id": bug_id,
                    "uplift.request": uplift,
                },
                "attachments": {},
            }

            reviewers = [r for r in self._reviewers if r["revisionPHID"] == i["phid"]]

            if attachments and attachments.get("reviewers"):
                resp["attachments"]["reviewers"] = {
                    "reviewers": [
                        {
                            "reviewerPHID": r["reviewerPHID"],
                            "status": r["status"].value,
                            "isBlocking": r["isBlocking"],
                            "actorPHID": r["actorPHID"],
                        }
                        for r in reviewers
                    ]
                }

            if attachments and attachments.get("reviewers-extra"):
                resp["attachments"]["reviewers-extra"] = {
                    "reviewers-extra": [
                        {
                            "reviewerPHID": r["reviewerPHID"],
                            "voidedPHID": r["voidedPHID"],
                            "diffPHID": r["diffPHID"],
                        }
                        for r in reviewers
                    ]
                }

            if attachments and attachments.get("projects"):
                resp["attachments"]["projects"] = {"projectPHIDs": i["projectPHIDs"]}

            return deepcopy(resp)

        items = []
        for r in self._revisions:
            r["stack_graph"] = get_stack(r["phid"], self)
            items.append(r)

        # TODO: add repo constraints to test feature flag.
        if constraints and "ids" in constraints:
            items = [i for i in items if i["id"] in constraints["ids"]]

        if constraints and "phids" in constraints:
            items = [i for i in items if i["phid"] in constraints["phids"]]

        if constraints and "statuses" in constraints:
            status_set = set(constraints["statuses"])
            if "open()" in status_set:
                status_set.remove("open()")
                status_set.update(
                    {
                        s.value
                        for s in RevisionStatus
                        if not s.closed and s is not RevisionStatus.UNEXPECTED_STATUS
                    }
                )
            if "closed()" in status_set:
                status_set.remove("closed()")
                status_set.update(
                    {
                        s.value
                        for s in RevisionStatus
                        if s.closed and s is not RevisionStatus.UNEXPECTED_STATUS
                    }
                )

            items = [i for i in items if i["status"].value in status_set]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {"queryKey": queryKey},
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("differential.revision.edit")
    def differential_revision_edit(self, *, transactions=None, objectIdentifier=None):
        # WARNING: This mock does not apply the real result of these
        # transactions, it only validates that the phabricator method
        # was called (mostly) correctly and performs a NOOP. Any testing
        # requiring something more advanced should isolate the component
        # and take care of mocking things manually.
        TRANSACTION_TYPES = [
            "update",
            "title",
            "summary",
            "testPlan",
            "reviewers.add",
            "reviewers.remove",
            "reviewers.set",
            "repositoryPHID",
            "tasks.add",
            "tasks.remove",
            "tasks.set",
            "parents.add",
            "parents.remove",
            "parents.set",
            "children.add",
            "children.remove",
            "children.set",
            "plan-changes",
            "request-review",
            "close",
            "reopen",
            "abandon",
            "accept",
            "reclaim",
            "reject",
            "commandeer",
            "resign",
            "draft",
            "view",
            "edit",
            "projects.add",
            "projects.remove",
            "projects.set," "subscribers.add",
            "subscribers.remove",
            "subscribers.set",
            "phabricator:auditors",
            "bugzilla.bug-id",
            "uplift.request",
            "comment",
        ]

        if transactions is None or (
            not isinstance(transactions, list) and not isinstance(transactions, dict)
        ):
            error_info = 'Parameter "transactions" is not a list of transactions.'
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        # Normalize transactions into a unified format (they can either be a
        # list or a dict). Internally phabricator treats lists as ordered
        # dictionaries (php arrays) where the keys are integers.
        if isinstance(transactions, list):
            transactions = list(enumerate(transactions))
        elif isinstance(transactions, dict):
            transactions = list((k, v) for k, v, in transactions.items())

        # Validate each transaction.
        for key, t in transactions:
            if not isinstance(t, dict):
                error_info = f'Parameter "transactions" must contain a list of transaction descriptions, but item with key "{key}" is not a dictionary.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            if "type" not in t:
                error_info = f'Parameter "transactions" must contain a list of transaction descriptions, but item with key "{key}" is missing a "type" field. Each transaction must have a type field.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            if t["type"] not in TRANSACTION_TYPES:
                given_type = t["type"]
                valid_types = " ,".join(TRANSACTION_TYPES)
                error_info = f'Transaction with key "{key}" has invalid type "{given_type}". This type is not recognized. Valid types are: {valid_types}.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

        if objectIdentifier is None:
            # A revision is being created, it must have the "title" and "update"
            # transactions present.
            transaction_types = [t[1]["type"] for t in transactions]
            if "title" not in transaction_types or "update" not in transaction_types:
                error_info = "Validation errors:"
                if "title" not in transaction_types:
                    error_info = error_info + "\n  - Revisions must have a title."
                if "update" not in transaction_types:
                    error_info = (
                        error_info
                        + "\n  - "
                        + "You must specify an initial diff when creating a revision."
                    )
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

        def identifier_to_revision(i):
            for r in self._revisions:
                if r["phid"] == i or r["id"] == i or "D{}".format(r["id"]) == i:
                    return r
            return None

        revision = identifier_to_revision(objectIdentifier)
        if objectIdentifier is not None and revision is None:
            error_info = (
                f'Monogram "{objectIdentifier}" does not identify a valid object.'
            )
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        # WARNING: This assumes all transactions actually applied. If a
        # transaction is a NOOP (such as a projects.remove which attempts
        # to remove a project that isn't there) it will not be listed
        # in the returned transactions list. Do not trust this mock for
        # testing details about the returned data.
        return {
            "object": {"id": revision["id"], "phid": revision["phid"]},
            "transactions": [
                {"phid": "PHID-XACT-DREV-fakeplaceholder"} for t in transactions
            ],
        }

    @conduit_method("differential.query")
    def differential_query(
        self,
        *,
        authors=None,
        ccs=None,
        reviewers=None,
        paths=None,
        commitHashes=None,
        status=None,
        order=None,
        limit=None,
        offset=None,
        ids=None,
        phids=None,
        subscribers=None,
        responsibleUsers=None,
        branches=None,
    ):
        def to_response(i):
            diffs = sorted(
                (d for d in self._diffs if d["revisionID"] == i["id"]),
                key=lambda d: d["id"],
            )

            dependencies = [
                e["destinationPHID"]
                for e in self._edges
                if (e["edgeType"] == "revision.parent" and e["sourcePHID"] == i["phid"])
            ]

            bug_id = (
                str(i["bugzilla.bug-id"]) if i["bugzilla.bug-id"] is not None else ""
            )
            uplift = i["uplift.request"] if i["uplift.request"] is not None else ""

            auxiliary = {
                "phabricator:depends-on": dependencies,
                "phabricator:projects": [],
                "bugzilla.bug-id": bug_id,
                "uplift.request": uplift,
            }

            resp = {
                "id": str(i["id"]),
                "dateCreated": str(i["dateCreated"]),
                "dateModified": str(i["dateModified"]),
                "lineCount": str(i["lineCount"]),
                "activeDiffPHID": diffs[-1]["phid"],
                "diffs": [str(d["id"]) for d in reversed(diffs)],
                "auxiliary": auxiliary,
                "status": i["status"].deprecated_id,
                "statusName": i["status"].output_name,
                "reviewers": {
                    r["reviewerPHID"]: r["reviewerPHID"]
                    for r in self._reviewers
                    if r["revisionPHID"] == i["phid"]
                },
            }

            for k in (
                "phid",
                "title",
                "uri",
                "authorPHID",
                "properties",
                "branch",
                "summary",
                "testPlan",
                "hashes",
                "ccs",
                "repositoryPHID",
                "sourcePath",
            ):
                resp[k] = i[k]

            return deepcopy(resp)

        items = self._revisions

        if ids:
            items = [i for i in items if i["id"] in ids]

        if phids:
            items = [i for i in items if i["phid"] in phids]

        return [to_response(i) for i in items]

    @conduit_method("diffusion.repository.search")
    def diffusion_repository_search(
        self,
        *,
        queryKey=None,
        constraints={},
        attachments={},
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            return deepcopy(
                {
                    "id": i["id"],
                    "type": i["type"],
                    "phid": i["phid"],
                    "fields": {
                        "name": i["name"],
                        "vcs": i["vcs"],
                        "callsign": i["callsign"],
                        "shortName": i["shortName"],
                        "status": i["status"],
                        "isImporting": i["isImporting"],
                        "spacePHID": i["spacePHID"],
                        "dateCreated": i["dateCreated"],
                        "dateModified": i["dateModified"],
                        "policy": i["policy"],
                        "defaultBranch": i["defaultBranch"],
                    },
                    "attachments": {},
                }
            )

        items = [r for r in self._repos]

        if "ids" in constraints:
            items = [i for i in items if i["id"] in constraints["ids"]]

        if "phids" in constraints:
            items = [i for i in items if i["phid"] in constraints["phids"]]

        if "callsigns" in constraints:
            items = [i for i in items if i["callsign"] in constraints["callsigns"]]

        if "shortNames" in constraints:
            items = [i for i in items if i["shortName"] in constraints["shortNames"]]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {"queryKey": queryKey},
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("differential.getrawdiff")
    def differential_getrawdiff(self, *, diffID=None):
        def to_response(i):
            return i["rawdiff"]

        diffs = [d for d in self._diffs if d["id"] == diffID]
        if diffID is None or not diffs:
            raise PhabricatorAPIException(
                "Diff not found.",
                error_code="ERR_NOT_FOUND",
                error_info="Diff not found.",
            )

        return to_response(diffs[0])

    @conduit_method("differential.creatediff")
    def differential_creatediff(
        self, *, changes, creationMethod, repositoryPHID, **kwargs
    ):
        assert creationMethod.startswith("lando-")

        assert isinstance(changes, list)
        assert all(map(validate_change, changes))
        assert isinstance(repositoryPHID, str)

        # Lookup the repo
        repository = PhabricatorClient.single(
            [r for r in self._repos if r["phid"] == repositoryPHID],
            none_when_empty=True,
        )
        assert repository is not None, "Unknown repository"

        def to_response(i):
            return {"diffid": i["id"], "phid": i["phid"]}

        new_diff = self.diff(changes=changes, repo=repository, commits=[])

        return to_response(new_diff)

    @conduit_method("differential.setdiffproperty")
    def differential_setdiffproperty(self, *, diff_id=None, data=None, name="default"):
        def to_response(i):
            return {"id": i["id"], "phid": i["phid"]}

        diffs = [(i, d) for i, d in enumerate(self._diffs) if d["id"] == diff_id]
        if diff_id is None or not diffs:
            raise PhabricatorAPIException(
                "Diff not found.",
                error_code="ERR_NOT_FOUND",
                error_info="Diff not found.",
            )

        pos, diff = diffs[0]
        if name == "local:commits":
            diff["commits"] = json.loads(data)
        else:
            raise PhabricatorAPIException(
                "Unsupported payload.",
                error_code="ERR_INVALID",
                error_info="Unsupported payload.",
            )

        self._diffs[pos] = diff
        return to_response(diff)

    @conduit_method("transaction.search")
    def transaction_search(
        self,
        *,
        objectIdentifier=None,
        constraints={},
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(i):
            # Explicitly tell the developer using the mock that they need to check the
            # type of transaction they are using and make sure it is serialized
            # correctly by this function.
            txn_type = i["type"]
            if txn_type not in ("comment", "dummy", "reviewers.add"):
                raise ValueError(
                    "PhabricatorDouble transactions do not have support "
                    'for the "{}" transaction type. '
                    "If you have added use of a new transaction type please "
                    "update PhabricatorDouble to support it.".format(txn_type)
                )

            if txn_type == "reviewers.add":
                # This type of transaction shows up as "type: null" in the transaction
                # search results list.
                txn_type = None

            return deepcopy(
                {
                    "id": i["id"],
                    "phid": i["phid"],
                    "type": txn_type,
                    "authorPHID": i["authorPHID"],
                    "objectPHID": i["objectPHID"],
                    "dateCreated": i["dateCreated"],
                    "dateModified": i["dateModified"],
                    "groupID": i["groupID"],
                    "comments": i["comments"],
                    "fields": i["fields"],
                }
            )

        items = list(self._transactions)

        if not objectIdentifier:
            error_info = 'When calling "transaction.search", you must provide an object to retrieve transactions for.'  # noqa
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        if not objectIdentifier.startswith("PHID-"):
            # Assume the caller is searching by object name. Find the PHID of the
            # named object the caller is searching for.
            matches = [
                obj for obj in self._phids if obj.get("name") == objectIdentifier
            ]
            if not matches:
                error_info = f'No object "{objectIdentifier}" exists.'
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            objectIdentifier = matches[0]["phid"]

        # Transactions are special. You can't retrieve them directly using search. I
        # don't know why. You have to retrieve the transaction's parent object instead.
        if objectIdentifier.startswith("PHID-XACT-"):
            error_info = '[Invalid Translation!] Object "%s" does not implement "%s", so transactions can not be loaded for it.'  # noqa
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        # Comments are special. You can't retrieve them directly using search. You
        # have to retrieve the comment's parent object instead.
        if objectIdentifier.startswith("PHID-XCMT-"):
            error_info = f'No object "{objectIdentifier}" exists.'
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        items = [i for i in items if i["objectPHID"] == objectIdentifier]

        if constraints and "phids" in constraints:
            phids = constraints["phids"]
            if not phids:
                error_info = 'Constraint "phids" to "transaction.search" requires nonempty list, empty list provided.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )
            items = [i for i in items if i["phid"] in phids]

        if constraints and "authorPHIDs" in constraints:
            items = [i for i in items if i["authorPHIDs"] in constraints["authorPHIDs"]]

        if after is None:
            after = 0

        next_page_end = after + limit
        page = items[after:next_page_end]
        # Set the 'after' cursor.
        if len(page) < limit:
            # This is the last page of results.
            after = None
        else:
            # Set the cursor to the next page of results.
            after = next_page_end

        return {
            "data": [to_response(i) for i in page],
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("user.search")
    def user_search(
        self,
        *,
        queryKey=None,
        constraints={},
        attachments={},
        order=None,
        before=None,
        after=None,
        limit=100,
    ):
        def to_response(u):
            return deepcopy(
                {
                    "id": u["id"],
                    "type": u["type"],
                    "phid": u["phid"],
                    "fields": {
                        "username": u["userName"],
                        "realName": u["realName"],
                        "roles": u["roles"],
                        "dateCreated": u["dateCreated"],
                        "dateModified": u["dateModified"],
                        "policy": u["policy"],
                    },
                    "attachments": {},
                }
            )

        items = [u for u in self._users]

        if "ids" in constraints:
            if not constraints["ids"]:
                error_info = 'Error while reading "ids": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["id"] in constraints["ids"]]

        if "phids" in constraints:
            if not constraints["phids"]:
                error_info = 'Error while reading "phids": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["phid"] in constraints["phids"]]

        if "usernames" in constraints:
            if not constraints["usernames"]:
                error_info = 'Error while reading "usernames": Expected a nonempty list, but value is an empty list.'  # noqa
                raise PhabricatorAPIException(
                    error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
                )

            items = [i for i in items if i["userName"] in constraints["usernames"]]

        if "nameLike" in constraints:
            items = [i for i in items if constraints["nameLike"] in i["userName"]]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {"queryKey": queryKey},
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            },
        }

    @conduit_method("user.query")
    def user_query(
        self,
        *,
        usernames=None,
        emails=None,
        realnames=None,
        phids=None,
        ids=None,
        offset=None,
        limit=None,
    ):
        def to_response(i):
            return deepcopy(
                {
                    "phid": i["phid"],
                    "userName": i["userName"],
                    "realName": i["realName"],
                    "image": i["image"],
                    "uri": i["uri"],
                    "roles": i["roles"],
                }
            )

        items = [u for u in self._users]

        if usernames:
            items = [i for i in items if i["userName"] in usernames]

        if emails:
            items = [i for i in items if i["email"] in emails]

        if realnames:
            items = [i for i in items if i["realName"] in realnames]

        if phids:
            items = [i for i in items if i["phid"] in phids]

        if ids:
            items = [i for i in items if i["id"] in ids]

        return [to_response(i) for i in items]

    @conduit_method("user.whoami")
    def user_whoami(self):
        def to_response(i):
            return {
                "phid": i["phid"],
                "userName": i["userName"],
                "realName": i["realName"],
                "image": i["image"],
                "uri": i["uri"],
                "roles": i["roles"],
            }

        if not self._users:
            raise PhabricatorAPIException(
                "User not found.",
                error_code="ERR_NOT_FOUND",
                error_info="User not found.",
            )

        return to_response(self._users[0])

    @conduit_method("phid.query")
    def phid_query(self, *, phids=None):
        if phids is None:
            error_info = "Argument 1 passed to PhabricatorHandleQuery::withPHIDs() must be of the type array, null given, called in /app/phabricator/src/applications/phid/conduit/PHIDQueryConduitAPIMethod.php on line 28 and defined"  # noqa
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        return {i["phid"]: deepcopy(i) for i in self._phids if i["phid"] in phids}

    def _new_phid(self, prefix):
        """Generate a unique PHID of the given type, e.g. 'PHID-DREV-123'.

        For example, given the prefix 'DREV-', the function will generate a
        PHID of 'PHID-DREV-0'. Given the prefix of 'DIFF-' it will return
        'PHID-DIFF-0'.

        Generated PHIDs start at zero and proceed sequentially for each type. For
        example, Revision PHIDs will be generated as 'PHID-DREV-0', 'PHID-DREV-1', ...

        Args:
            prefix: The string to be used as the PHID identifier. Should include the
                dash between the type and object ID, e.g. 'DREV-' or 'PROJ-'.
        """
        suffix = self._phid_counters.get(prefix, 0)
        self._phid_counters[prefix] = self._phid_counters.get(prefix, 0) + 1
        return "PHID-{}{}".format(prefix, suffix)

    @staticmethod
    def _new_id(items, *, field="id"):
        return max([i[field] for i in items] + [0]) + 1

    def _build_handlers(self):
        handlers = [
            getattr(self, a)
            for a in dir(self)
            if hasattr(getattr(self, a), "_conduit_method")
        ]
        return {handler._conduit_method: handler for handler in handlers}


class TreeStatusDouble:
    """TreeStatus test double.

    Can generate / return data of the same form calls to Tree Status
    through TreeStatus would. The TreeStatus class is
    monkeypatched to allow use in integration testing as well.

    Not all api endpoints are implemented, many being ignored entirely,
    by design. As Lando API needs to make use of more endpionts / arguments
    support should be added.
    """

    def __init__(self, monkeypatch, url):
        self.url = url
        self._trees = {}
        self._ping = True

        monkeypatch.setattr(TreeStatus, "request", self._unsupported)
        monkeypatch.setattr(TreeStatus, "get_trees", self.get_trees)
        monkeypatch.setattr(TreeStatus, "ping", self.ping)

    def set_tree(self, tree, *, status="open", reason="", message_of_the_day=""):
        assert tree
        self._trees[tree] = {
            "message_of_the_day": message_of_the_day,
            "reason": reason,
            "status": status,
            "tree": tree,
        }

    def open_tree(self, tree):
        self.set_tree(tree, status="open", reason="", message_of_the_day="")

    def close_tree(self, tree):
        self.set_tree(tree, status="closed", reason="testing closed")

    def del_tree(self, tree):
        assert tree
        self._trees.pop(tree, None)

    def ping(self):
        return self._ping

    def toggle_ping(self):
        self._ping = not self._ping

    def get_trees(self, tree=""):
        def to_response(i):
            return {
                "message_of_the_day": i["message_of_the_day"],
                "reason": i["reason"],
                "status": i["status"],
                "tree": i["tree"],
            }

        if not tree:
            return {
                "result": {
                    tree: to_response(data) for tree, data in self._trees.items()
                }
            }

        if tree not in self._trees:
            raise TreeStatusError(
                404,
                {
                    "detail": "No such tree",
                    "instance": "about:blank",
                    "status": 404,
                    "title": "404 Not Found: No such tree",
                    "type": "about:blank",
                },
            )

        return {"result": to_response(self._trees[tree])}

    def _unsupported(self, *args, **kwargs):
        raise ValueError("TestStatusDouble does not support mocking this use.")

    def get_treestatus_client(self):
        return TreeStatus(url=self.url)
