# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from copy import deepcopy

from landoapi.phabricator import (
    PhabricatorAPIException,
    PhabricatorClient,
    RevisionStatus,
    ReviewerStatus,
)

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
        self._users = []
        self._projects = []
        self._revisions = []
        self._reviewers = []
        self._repos = []
        self._diffs = []
        self._diff_refs = []
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

    @staticmethod
    def get_phabricator_client():
        return PhabricatorClient("https://localhost", "DOESNT-MATTER")

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
    ):
        revision_id = self._new_id(self._revisions)
        phid = self._new_phid("DREV-")
        uri = "http://phabricator.test/D{}".format(revision_id)
        title = "my test revision title"

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
            "summary": "my test revision summary",
            "testPlan": "my revision test plan",
            "lineCount": "2",
            "commits": [],
            "ccs": [],
            "hashes": [],
            "bugzilla.bug-id": bug_id,
            "repositoryPHID": repo["phid"] if repo is not None else None,
            "sourcePath": None,
            "projectPHIDs": [project["phid"] for project in projects],
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

        diff = {
            "id": diff_id,
            "phid": phid,
            "type": "DIFF",
            "rawdiff": rawdiff,
            "bookmark": None,
            "branch": None,
            "changes": deepcopy(CANNED_DEFAULT_DIFF_CHANGES),
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

    def repo(self, *, name="mozilla-central"):
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

    def project(self, name, *, no_slug=False):
        """Return a Phabricator Project."""
        projects = [p for p in self._projects if p["name"] == name]
        if projects:
            return projects[0]

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
                    "attachments": {},
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

            resp = {
                "id": i["id"],
                "type": i["type"],
                "phid": i["phid"],
                "fields": {
                    "title": i["title"],
                    "authorPHID": i["authorPHID"],
                    "status": {
                        "value": i["status"].value,
                        "name": i["status"].output_name,
                        "closed": i["status"].closed,
                        "color.ansi": i["status"].color,
                    },
                    "repositoryPHID": i["repositoryPHID"],
                    "diffPHID": diffs[-1]["phid"],
                    "summary": i["summary"],
                    "dateCreated": i["dateCreated"],
                    "dateModified": i["dateModified"],
                    "policy": {"view": "public", "edit": "users"},
                    "bugzilla.bug-id": bug_id,
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

        items = [r for r in self._revisions]

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
            auxiliary = {
                "phabricator:depends-on": dependencies,
                "phabricator:projects": [],
                "bugzilla.bug-id": bug_id,
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

    @conduit_method("phid.query")
    def phid_query(self, *, phids=None):
        if phids is None:
            error_info = "Argument 1 passed to PhabricatorHandleQuery::withPHIDs() must be of the type array, null given, called in /app/phabricator/src/applications/phid/conduit/PHIDQueryConduitAPIMethod.php on line 28 and defined"  # noqa
            raise PhabricatorAPIException(
                error_info, error_code="ERR-CONDUIT-CORE", error_info=error_info
            )

        return {i["phid"]: deepcopy(i) for i in self._phids if i["phid"] in phids}

    def _new_phid(self, prefix):
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
