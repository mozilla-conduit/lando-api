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
        self._revisions = []
        self._reviewers = []
        self._repos = []
        self._diffs = []
        self._diff_refs = []
        self._phids = []
        self._phid_counters = {}
        self._edges = []
        self._handlers = self._build_handlers()

        monkeypatch.setattr(
            PhabricatorClient, 'call_conduit', self.call_conduit
        )

    def call_conduit(self, method, **kwargs):
        handler = self._handlers.get(method)

        if handler is None:
            raise ValueError(
                'PhabricatorDouble does not have support for "{}". '
                'If you have added a new call to this method please '
                'update PhabricatorDouble to support it.'.format(method)
            )

        return handler(**kwargs)

    def revision(
        self,
        *,
        diff=None,
        author=None,
        repo=None,
        status=RevisionStatus.ACCEPTED,
        depends_on=[],
        bug_id=None
    ):
        revision_id = self._new_id(self._revisions)
        phid = self._new_phid('DREV-')
        uri = "http://phabricator.test/D{}".format(revision_id)
        title = "my test revision title"

        author = self.user() if author is None else author

        diff = self.diff() if diff is None else diff
        diff['revisionID'] = revision_id
        diff['revisionPHID'] = phid
        diff['authorPHID'] = author['phid']

        revision = {
            "id": revision_id,
            "type": "DREV",
            "phid": phid,
            "title": title,
            "uri": uri,
            "dateCreated": 1495638270,
            "dateModified": 1496239141,
            "authorPHID": author['phid'],
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
            "repositoryPHID": repo['phid'] if repo is not None else None,
            "sourcePath": None,
        }

        for rev in depends_on:
            self._edges.append(
                {
                    'edgeType': 'revision.parent',
                    'sourcePHID': phid,
                    'destinationPHID': rev['phid'],
                }
            )
            self._edges.append(
                {
                    'edgeType': 'revision.child',
                    'sourcePHID': rev['phid'],
                    'destinationPHID': phid,
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

    def user(self, *, username='imadueme_admin'):
        """Return a Phabricator User."""
        users = [u for u in self._users if u['userName'] == username]
        if users:
            return users[0]

        phid = self._new_phid('USER-{}'.format(username))
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
            "policy": {
                "view": "public",
                "edit": "no-one",
            },
            "userName": username,
            "realName": fullname,
            "image": "https://example.com/image.png",  # noqa
            "uri": uri,
            "roles": [
                "verified",
                "approved",
                "activated",
            ],
        }  # yapf: disable

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
        self, *, revision=None, rawdiff=CANNED_RAW_DEFAULT_DIFF, repo=None
    ):
        diff_id = self._new_id(self._diffs)
        phid = self._new_phid('DIFF-')
        uri = "http://phabricator.test/differential/diff/{}/".format(diff_id)
        revision_id = revision['id'] if revision is not None else None
        revision_phid = revision['phid'] if revision is not None else None
        author_phid = revision['authorPHID'] if revision is not None else None
        repo_phid = (
            repo['phid'] if repo is not None else
            (revision['repositoryPHID'] if revision is not None else None)
        )

        base = 'cff9ba1622714e0dd82c39f912f405210489fce8'

        self._diff_refs += [
            {
                'diff_id': diff_id,
                'type': 'base',
                'identifier': base,
            },
        ]

        diff = {
            'id': diff_id,
            'phid': phid,
            'type': 'DIFF',
            'rawdiff': rawdiff,
            'bookmark': None,
            'branch': None,
            'changes': deepcopy(CANNED_DEFAULT_DIFF_CHANGES),
            'creationMethod': 'arc',
            'dateCreated': 1516718328,
            'dateModified': 1516718341,
            'description': None,
            'lintStatus': '0',
            'properties': [],
            'revisionID': revision_id,
            'revisionPHID': revision_phid,
            'authorPHID': author_phid,
            'repositoryPHID': repo_phid,
            'sourceControlBaseRevision': base,
            'sourceControlPath': '/',
            'sourceControlSystem': 'hg',
            'unitStatus': '0',
            'authorName': "Mark Cote",
            'authorEmail': "mcote@mozilla.example",
            'policy': {
                'view': 'public',
            },
        }  # yapf: disable

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

    def repo(self, *, name='mozilla-central'):
        repos = [r for r in self._repos if r['name'] == name]
        if repos:
            return repos[0]

        repo_id = self._new_id(self._repos)
        phid = self._new_phid('REPO-')
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
            "policy": {
                "view": "public",
                "edit": "admin",
                "diffusion.push": "no-one",
            }
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
        user,
        *,
        status=ReviewerStatus.ACCEPTED,
        isBlocking=False,
        actor=None,
        on_diff=None,
        voided_by_phid=None
    ):
        if on_diff is None:
            # Default to the latest.
            diffs = sorted(
                (d for d in self._diffs if d['revisionID'] == revision['id']),
                key=lambda d: d['id']
            )
            on_diff = diffs[-1]
        actor_phid = revision['authorPHID'] if actor is None else actor['phid']
        reviewer = {
            'revisionPHID': revision['phid'],
            'revisionID': revision['id'],
            'reviewerPHID': user['phid'],
            'reviewerID': user['id'],
            'status': status,
            'isBlocking': isBlocking,
            'actorPHID': actor_phid,
            'diffPHID': on_diff['phid'],
            'voidedPHID': voided_by_phid,
        }

        current_reviewers = [
            r for r in self._reviewers
            if (
                r['revisionID'] == revision['id'] and
                r['reviewerPHID'] == reviewer['reviewerPHID']
            )
        ]

        if current_reviewers:
            current_reviewers[0].update(reviewer)
        else:
            self._reviewers.append(reviewer)

        return reviewer

    @conduit_method('differential.diff.search')
    def differential_diff_search(
        self,
        *,
        queryKey=None,
        constraints=None,
        attachments=None,
        order=None,
        before=None,
        after=None,
        limit=100
    ):
        def to_response(i):
            refs = [r for r in self._diff_refs if r['diff_id'] == i['id']]
            return deepcopy(
                {
                    'id': i['id'],
                    'type': i['type'],
                    'phid': i['phid'],
                    'fields': {
                        'revisionPHID': i['revisionPHID'],
                        'authorPHID': i['authorPHID'],
                        'repositoryPHID': i['repositoryPHID'],
                        'refs': [
                            {
                                'type': r['type'],
                                'identifier': r['identifier'],
                            } for r in refs
                        ],
                        'dateCreated': i['dateCreated'],
                        'dateModified': i['dateModified'],
                        'policy': {
                            'view': i['policy']['view'],
                        },
                    },
                    'attachments': {},
                }
            )  # yapf: disable

        items = [r for r in self._diffs]

        if constraints and 'ids' in constraints:
            items = [i for i in items if i['id'] in constraints['ids']]

        if constraints and 'phids' in constraints:
            items = [i for i in items if i['phid'] in constraints['phids']]

        if constraints and 'revisionPHIDs' in constraints:
            items = [
                i for i in items
                if i['revisionPHID'] in constraints['revisionPHIDs']
            ]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {
                "queryKey": queryKey,
            },
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            }
        }

    @conduit_method('edge.search')
    def edge_search(
        self,
        *,
        sourcePHIDs=None,
        types=None,
        destinationPHIDs=None,
        before=None,
        after=None,
        limit=100
    ):
        def to_response(i):
            return deepcopy(
                {
                    'edgeType': i['edgeType'],
                    'sourcePHID': i['sourcePHID'],
                    'destinationPHID': i['destinationPHID'],
                }
            )

        if not sourcePHIDs:
            error_info = 'Edge object query must be executed with a nonempty list of source PHIDs.'  # noqa
            raise PhabricatorAPIException(
                error_info,
                error_code='ERR-CONDUIT-CORE',
                error_info=error_info
            )

        if not types:
            error_info = 'Edge search must specify a nonempty list of edge types.'  # noqa
            raise PhabricatorAPIException(
                error_info,
                error_code='ERR-CONDUIT-CORE',
                error_info=error_info
            )

        if not set(types) <= set(
            (
                'commit.revision', 'commit.task', 'mention', 'mentioned-in',
                'revision.child', 'revision.commit', 'revision.parent',
                'revision.task', 'task.commit', 'task.duplicate',
                'task.merged-in', 'task.parent', 'task.revision',
                'task.subtask',
            )
        ):
            error_info = 'Edge type "<type-is-here>" is not a recognized edge type.'  # noqa
            raise PhabricatorAPIException(
                error_info,
                error_code='ERR-CONDUIT-CORE',
                error_info=error_info
            )

        items = [e for e in self._edges]
        items = [i for i in items if i['sourcePHID'] in sourcePHIDs]
        items = [i for i in items if i['edgeType'] in types]

        if destinationPHIDs:
            items = [
                i for i in items if i['destinationPHID'] in destinationPHIDs
            ]

        return {
            "data": [to_response(i) for i in items],
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
            }
        }

    @conduit_method('differential.revision.search')
    def differential_revision_search(
        self,
        *,
        queryKey=None,
        constraints=None,
        attachments=None,
        order=None,
        before=None,
        after=None,
        limit=100
    ):
        def to_response(i):
            diffs = sorted(
                (d for d in self._diffs if d['revisionID'] == i['id']),
                key=lambda d: d['id']
            )
            bug_id = (
                str(i['bugzilla.bug-id'])
                if i['bugzilla.bug-id'] is not None else None
            )

            resp = {
                'id': i['id'],
                'type': i['type'],
                'phid': i['phid'],
                'fields': {
                    'title': i['title'],
                    'authorPHID': i['authorPHID'],
                    'status': {
                        'value': i['status'].value,
                        'name': i['status'].output_name,
                        'closed': i['status'].closed,
                        'color.ansi': i['status'].color,
                    },
                    'repositoryPHID': i['repositoryPHID'],
                    'diffPHID': diffs[-1]['phid'],
                    'summary': i['summary'],
                    'dateCreated': i['dateCreated'],
                    'dateModified': i['dateModified'],
                    'policy': {
                        'view': 'public',
                        'edit': 'users',
                    },
                    'bugzilla.bug-id': bug_id,
                },
                'attachments': {},
            }

            reviewers = [
                r for r in self._reviewers if r['revisionPHID'] == i['phid']
            ]

            if attachments and attachments.get('reviewers'):
                resp['attachments']['reviewers'] = {
                    'reviewers': [
                        {
                            'reviewerPHID': r['reviewerPHID'],
                            'status': r['status'].value,
                            'isBlocking': r['isBlocking'],
                            'actorPHID': r['actorPHID'],
                        } for r in reviewers
                    ],
                }

            if attachments and attachments.get('reviewers-extra'):
                resp['attachments']['reviewers-extra'] = {
                    'reviewers-extra': [
                        {
                            'reviewerPHID': r['reviewerPHID'],
                            'voidedPHID': r['voidedPHID'],
                            'diffPHID': r['diffPHID'],
                        } for r in reviewers
                    ],
                }

            return deepcopy(resp)

        items = [r for r in self._revisions]

        if constraints and 'ids' in constraints:
            items = [i for i in items if i['id'] in constraints['ids']]

        if constraints and 'phids' in constraints:
            items = [i for i in items if i['phid'] in constraints['phids']]

        if constraints and 'statuses' in constraints:
            status_set = set(constraints['statuses'])
            if 'open()' in status_set:
                status_set.remove('open()')
                status_set.update(
                    {
                        s.value
                        for s in RevisionStatus
                        if not s.closed and
                        s is not RevisionStatus.UNEXPECTED_STATUS
                    }
                )
            if 'closed()' in status_set:
                status_set.remove('closed()')
                status_set.update(
                    {
                        s.value
                        for s in RevisionStatus
                        if s.closed and
                        s is not RevisionStatus.UNEXPECTED_STATUS
                    }
                )

            items = [i for i in items if i['status'].value in status_set]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {
                "queryKey": queryKey,
            },
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            }
        }

    @conduit_method('differential.query')
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
        branches=None
    ):
        def to_response(i):
            diffs = sorted(
                (d for d in self._diffs if d['revisionID'] == i['id']),
                key=lambda d: d['id']
            )

            dependencies = [
                e['destinationPHID'] for e in self._edges
                if (
                    e['edgeType'] == 'revision.parent' and
                    e['sourcePHID'] == i['phid']
                )
            ]

            auxiliary = {
                'phabricator:depends-on': dependencies,
                'phabricator:projects': [],
            }
            if i['bugzilla.bug-id'] is not None:
                auxiliary['bugzilla.bug-id'] = i['bugzilla.bug-id']

            resp = {
                'id': str(i['id']),
                'dateCreated': str(i['dateCreated']),
                'dateModified': str(i['dateModified']),
                'lineCount': str(i['lineCount']),
                'activeDiffPHID': diffs[-1]['phid'],
                'diffs': [str(d['id']) for d in reversed(diffs)],
                'auxiliary': auxiliary,
                'status': i['status'].deprecated_id,
                'statusName': i['status'].output_name,
                'reviewers': {
                    r['reviewerPHID']: r['reviewerPHID']
                    for r in self._reviewers if r['revisionPHID'] == i['phid']
                },
            }

            for k in (
                "phid", "title", "uri", "authorPHID", "properties", "branch",
                "summary", "testPlan", "hashes", "ccs", "repositoryPHID",
                "sourcePath",
            ):
                resp[k] = i[k]

            return deepcopy(resp)

        items = self._revisions

        if ids:
            items = [i for i in items if i['id'] in ids]

        if phids:
            items = [i for i in items if i['phid'] in phids]

        return [to_response(i) for i in items]

    @conduit_method('diffusion.repository.search')
    def diffusion_repository_search(
        self,
        *,
        queryKey=None,
        constraints={},
        attachments={},
        order=None,
        before=None,
        after=None,
        limit=100
    ):
        def to_response(i):
            return deepcopy(
                {
                    "id": i['id'],
                    "type": i['type'],
                    "phid": i['phid'],
                    "fields": {
                        "name": i['name'],
                        "vcs": i['vcs'],
                        "callsign": i['callsign'],
                        "shortName": i['shortName'],
                        "status": i['status'],
                        "isImporting": i['isImporting'],
                        "spacePHID": i['spacePHID'],
                        "dateCreated": i['dateCreated'],
                        "dateModified": i['dateModified'],
                        "policy": i['policy']
                    },
                    "attachments": {}
                }
            )

        items = [r for r in self._repos]

        if 'ids' in constraints:
            items = [i for i in items if i['id'] in constraints['ids']]

        if 'phids' in constraints:
            items = [i for i in items if i['phid'] in constraints['phids']]

        if 'callsigns' in constraints:
            items = [
                i for i in items if i['callsign'] in constraints['callsigns']
            ]

        if 'shortNames' in constraints:
            items = [
                i for i in items if i['shortName'] in constraints['shortNames']
            ]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {
                "queryKey": queryKey,
            },
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            }
        }

    @conduit_method('differential.getrawdiff')
    def differential_getrawdiff(self, *, diffID=None):
        def to_response(i):
            return i['rawdiff']

        diffs = [d for d in self._diffs if d['id'] == diffID]
        if diffID is None or not diffs:
            raise PhabricatorAPIException(
                'Diff not found.',
                error_code='ERR_NOT_FOUND',
                error_info='Diff not found.'
            )

        return to_response(diffs[0])

    @conduit_method('differential.querydiffs')
    def differential_querydiffs(self, *, ids=None, revisionIDs=None):
        def to_response(i):
            resp = {
                'id': str(i['id']),
                'revisionID': str(i['revisionID']),
                'dateCreated': str(i['dateCreated']),
                'dateModified': str(i['dateModified']),
            }

            for k in (
                'bookmark', 'branch', 'changes', 'creationMethod',
                'description', 'lintStatus', 'properties',
                'sourceControlBaseRevision', 'sourceControlPath',
                'sourceControlSystem', 'unitStatus', 'authorName',
                'authorEmail'
            ):
                resp[k] = i[k]

            return deepcopy(resp)

        items = self._diffs

        if ids:
            items = [i for i in items if i['id'] in ids]

        if revisionIDs:
            items = [i for i in items if i['revisionID'] in revisionIDs]

        return {str(i['id']): to_response(i) for i in items}

    @conduit_method('user.search')
    def user_search(
        self,
        *,
        queryKey=None,
        constraints={},
        attachments={},
        order=None,
        before=None,
        after=None,
        limit=100
    ):
        def to_response(u):
            return deepcopy(
                {
                    "id": u['id'],
                    "type": u['type'],
                    "phid": u['phid'],
                    "fields": {
                        "username": u['userName'],
                        "realName": u['realName'],
                        "roles": u['roles'],
                        "dateCreated": u['dateCreated'],
                        "dateModified": u['dateModified'],
                        "policy": u['policy'],
                    },
                    "attachments": {},
                }
            )

        items = [u for u in self._users]

        if 'ids' in constraints:
            items = [i for i in items if i['id'] in constraints['ids']]

        if 'phids' in constraints:
            items = [i for i in items if i['phid'] in constraints['phids']]

        if 'usernames' in constraints:
            items = [
                i for i in items if i['userName'] in constraints['usernames']
            ]

        if 'nameLike' in constraints:
            items = [
                i for i in items if constraints['nameLike'] in i['userName']
            ]

        return {
            "data": [to_response(i) for i in items],
            "maps": {},
            "query": {
                "queryKey": queryKey,
            },
            "cursor": {
                "limit": limit,
                "after": after,
                "before": before,
                "order": order,
            }
        }

    @conduit_method('user.query')
    def user_query(
        self,
        *,
        usernames=None,
        emails=None,
        realnames=None,
        phids=None,
        ids=None,
        offset=None,
        limit=None
    ):
        def to_response(i):
            return deepcopy(
                {
                    "phid": i['phid'],
                    "userName": i['userName'],
                    "realName": i['realName'],
                    "image": i['image'],
                    "uri": i['uri'],
                    "roles": i['roles'],
                }
            )

        items = [u for u in self._users]

        if usernames:
            items = [i for i in items if i['userName'] in usernames]

        if emails:
            items = [i for i in items if i['email'] in emails]

        if realnames:
            items = [i for i in items if i['realName'] in realnames]

        if phids:
            items = [i for i in items if i['phid'] in phids]

        if ids:
            items = [i for i in items if i['id'] in ids]

        return [to_response(i) for i in items]

    @conduit_method('phid.query')
    def phid_query(self, *, phids=None):
        if phids is None:
            error_info = 'Argument 1 passed to PhabricatorHandleQuery::withPHIDs() must be of the type array, null given, called in /app/phabricator/src/applications/phid/conduit/PHIDQueryConduitAPIMethod.php on line 28 and defined'  # noqa
            raise PhabricatorAPIException(
                error_info,
                error_code='ERR-CONDUIT-CORE',
                error_info=error_info
            )

        return {
            i['phid']: deepcopy(i)
            for i in self._phids if i['phid'] in phids
        }

    def _new_phid(self, prefix):
        suffix = self._phid_counters.get(prefix, '')
        self._phid_counters[prefix] = self._phid_counters.get(prefix, 0) + 1
        return 'PHID-{}{}'.format(prefix, suffix)

    @staticmethod
    def _new_id(items, *, field='id'):
        return max([i[field] for i in items] + [0]) + 1

    def _build_handlers(self):
        handlers = [
            getattr(self, a)
            for a in dir(self) if hasattr(getattr(self, a), '_conduit_method')
        ]
        return {handler._conduit_method: handler for handler in handlers}
