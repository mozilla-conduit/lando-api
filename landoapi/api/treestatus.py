# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import collections
import copy
import datetime
import functools
import json
import logging
from typing import (
    Any,
    Callable,
    Optional,
)

import pytz
import sqlalchemy as sa
from connexion import ProblemException
from flask import g

from landoapi import auth
from landoapi.cache import cache
from landoapi.models.treestatus import (
    DEFAULT_TREE,
    Log,
    StatusChange,
    StatusChangeTree,
    Tree,
    load_last_state,
)
from landoapi.storage import db

logger = logging.getLogger(__name__)


TREE_SUMMARY_LOG_LIMIT = 5

CombinedTree = collections.namedtuple(
    "CombinedTree",
    ["tree", "message_of_the_day", "tags", "status", "reason", "log_id", "model"],
)


def get_combined_tree(
    tree: Tree,
    tags: Optional[list[str]] = None,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    log_id: Optional[int] = None,
) -> CombinedTree:
    """Combined view of the Tree.

    This also shows status, reason and tags from last Tree Log.
    """
    result = copy.deepcopy(DEFAULT_TREE)
    result.update(tree.to_dict())

    if tags is not None:
        result["tags"] = json.loads(tags)

    if status is not None:
        result["status"] = status

    if reason is not None:
        result["reason"] = reason

    if log_id is not None:
        result["log_id"] = log_id

    result["model"] = tree

    return CombinedTree(**result)


def combinedtree_as_dict(tree: CombinedTree) -> dict[str, Any]:
    """Convert a `CombinedTree` to a dict.

    Removes the `model` field as part of the conversion.
    """
    return {field: value for field, value in tree._asdict().items() if field != "model"}


def result_object_wrap(f: Callable) -> Callable:
    """Wrap the value returned from `f` in a result object.

    Return a result wrapped in an object with a `result` key, like so:
        {"result": ...}
    """

    @functools.wraps(f)
    def wrap_output(*args, **kwargs) -> dict[str, Any]:
        result = f(*args, **kwargs)
        return {"result": result}

    return wrap_output


def serialize_last_state(old_tree: dict, new_tree: CombinedTree) -> str:
    """Serialize a `last_state` value for a `StatusChangeTree`."""
    return json.dumps(
        {
            "status": old_tree["status"],
            "reason": old_tree["reason"],
            "tags": old_tree["tags"],
            "log_id": old_tree["log_id"],
            "current_status": new_tree.status,
            "current_reason": new_tree.reason,
            "current_tags": new_tree.tags,
            "current_log_id": new_tree.log_id,
        }
    )


@cache.memoize()
def get_tree_by_name(tree: str) -> Optional[CombinedTree]:
    """Retrieve a `CombinedTree` representation of a tree by name.

    Returns `None` if no tree can be found.
    """
    query = (
        Tree.query.distinct(Tree.tree)
        .add_columns(
            Log._tags,
            Log.status,
            Log.reason,
            Log.id,
        )
        .outerjoin(
            Log,
            Log.tree == Tree.tree,
        )
        .order_by(Tree.tree.desc(), Log.created_at.desc())
        .filter(Tree.tree == tree)
    )

    result = query.one_or_none()
    if result:
        return get_combined_tree(*result)


def remove_tree_by_name(tree_name: str):
    """Completely remove the tree with the specified name.

    Note: this function commits the session.
    """
    session = db.session
    tree = Tree.query.filter_by(tree=tree_name).one_or_none()
    if not tree:
        raise ProblemException(
            404,
            f"No tree {tree_name} found.",
            "The tree does not exist.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
    session.delete(tree)

    # Delete from logs and change stack, too.
    Log.query.filter_by(tree=tree_name).delete()
    StatusChangeTree.query.filter_by(tree=tree_name).delete()
    session.commit()
    cache.delete_memoized(get_tree_by_name, tree_name)


def update_tree_log(
    id: int, tags: Optional[list[str]] = None, reason: Optional[str] = None
):
    """Update the log with the given id with new `tags` and/or `reason`."""
    if tags is None and reason is None:
        return

    log = Log.query.get(id)

    if log is None:
        raise ProblemException(
            404,
            f"No tree log for id {id} found."
            f"The tree log does not exist for id {id}.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    if tags is not None:
        log._tags = json.dumps(tags)
    if reason is not None:
        log.reason = reason


def get_combined_trees(trees: Optional[list[Tree]] = None) -> list[CombinedTree]:
    """Return a `CombinedTree` representation of trees.

    If `trees` is set, return the `CombinedTree` for those trees, otherwise
    return all known trees.
    """
    query = (
        Tree.query.distinct(Tree.tree)
        .add_columns(
            Log._tags,
            Log.status,
            Log.reason,
            Log.id,
        )
        .outerjoin(
            Log,
            Log.tree == Tree.tree,
        )
        .order_by(Tree.tree.desc(), Log.created_at.desc())
    )

    if trees:
        query = query.filter(Tree.tree.in_(trees))

    return [get_combined_tree(*result) for result in query.all()]


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)


def update_tree_status(
    session: sa.orm.Session,
    tree: Tree,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    tags: Optional[list[str]] = None,
    message_of_the_day: Optional[str] = None,
):
    """Update the given tree's status.

    Note that this does not commit the session.
    """
    if not tags:
        tags = []

    if status is not None:
        tree.status = status

    if reason is not None:
        tree.reason = reason

    if message_of_the_day is not None:
        tree.message_of_the_day = message_of_the_day

    # Create a log entry if the reason or status has changed.
    if status or reason:
        if status is None:
            status = "no change"
        if reason is None:
            reason = "no change"
        log = Log(
            tree=tree.tree,
            created_at=_now(),
            changed_by=g.auth0_user.user_id(),
            status=status,
            reason=reason,
            tags=tags,
        )
        session.add(log)

    cache.delete_memoized(get_tree_by_name, tree.tree)


@result_object_wrap
def get_stack() -> list[dict]:
    """Handler for `GET /stack`."""
    return [
        status_change.to_dict()
        for status_change in StatusChange.query.order_by(StatusChange.created_at.desc())
    ]


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def update_stack(id: int, body: dict) -> tuple[None, int]:
    """Handler for `PATCH /stack/{id}`."""
    session = db.session

    change = StatusChange.query.get(id)
    if not change:
        raise ProblemException(
            404,
            f"No stack {id} found.",
            "The change stack does not exist.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    for tree in change.trees:
        last_state = load_last_state(tree.last_state)
        last_state["current_tags"] = body.get("tags", last_state["current_tags"])
        last_state["current_reason"] = body.get("reason", last_state["current_reason"])
        update_tree_log(
            last_state["current_log_id"],
            last_state["current_tags"],
            last_state["current_reason"],
        )
        tree.last_state = json.dumps(last_state)

    change.reason = body.get("reason", change.reason)

    session.commit()

    return change.status, 200


def revert_change(id: int, revert: bool = False) -> tuple[None, int]:
    """Revert the status change with the given ID.

    If `revert` is passed, also revert the updated trees statuses to their
    previous values.
    """
    session = db.session
    status_change = StatusChange.query.get(id)
    if not status_change:
        raise ProblemException(
            404,
            f"No change {id} found.",
            "The change could not be found.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    if revert:
        for changed_tree in status_change.trees:
            tree = get_tree_by_name(changed_tree.tree)
            if tree is None:
                # If there's no tree to update we just continue.
                continue

            last_state = load_last_state(changed_tree.last_state)
            update_tree_status(
                session,
                tree.model,
                status=last_state["status"],
                reason=last_state["reason"],
                tags=last_state.get("tags", []),
            )

    session.delete(status_change)
    session.commit()

    return status_change.status, 200


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def delete_stack(id: int, revert: Optional[int] = None):
    """Handler for `DELETE /stack/{id}`."""
    if revert not in {0, 1, None}:
        raise ProblemException(
            400,
            "Unexpected value for `revert`.",
            "Unexpected value for `revert`.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    return revert_change(id, revert=bool(revert))


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def discard_change(id: int):
    """Handler for `DELETE /stack2/discard/{id}`.

    Remove the change from the stack without changing the settings on the tree.
    """
    return revert_change(id, revert=False)


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def restore_change(id: int):
    """Handler for `DELETE /stack2/restore/{id}`.

    Applies the settings that were present before the change to the affected trees.
    """
    return revert_change(id, revert=True)


@result_object_wrap
def get_trees() -> dict:
    """Handler for `GET /trees`."""
    return {tree.tree: combinedtree_as_dict(tree) for tree in get_combined_trees()}


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def update_trees(body: dict):
    """Handler for `PATCH /trees`."""
    session = db.session

    # Fetch all trees.
    trees = get_combined_trees(body["trees"])

    # Check that we fetched all the trees.
    if len(trees) != len(body["trees"]):
        trees_diff = set(body["trees"]) - {tree.tree for tree in trees}
        raise ProblemException(
            404,
            f"Could not fetch the following trees: {trees_diff}"
            "Could not fetch all the requested trees.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # Check for other constraints.
    if "tags" not in body and body.get("status") == "closed":
        raise ProblemException(
            400,
            "Tags are required when closing a tree.",
            "Tags are required when closing a tree.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if (
        "remember" in body
        and body["remember"] is True
        and any(field not in body for field in {"status", "reason", "tags"})
    ):
        raise ProblemException(
            400,
            "Must specify status, reason and tags to remember the change.",
            "Must specify status, reason and tags to remember the change.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    # Update the trees as requested.
    new_status = body.get("status")
    new_reason = body.get("reason")
    new_motd = body.get("message_of_the_day")
    new_tags = body.get("tags", [])

    old_trees = {}

    for tree in trees:
        old_trees[tree.tree] = {}
        old_trees[tree.tree]["status"] = tree.status
        old_trees[tree.tree]["reason"] = tree.reason
        old_trees[tree.tree]["tags"] = tree.tags
        old_trees[tree.tree]["log_id"] = tree.log_id

        update_tree_status(
            session,
            tree.model,
            status=new_status,
            reason=new_reason,
            message_of_the_day=new_motd,
            tags=new_tags,
        )

    if "remember" in body and body["remember"] is True:
        # Add a new stack entry with the new and existing states.
        status_change = StatusChange(
            changed_by=g.auth0_user.user_id(),
            reason=body["reason"],
            created_at=_now(),
            status=body["status"],
        )

        # Re-fetch new updated trees.
        new_trees = get_combined_trees(body["trees"])
        for tree in new_trees:
            status_change_tree = StatusChangeTree(
                tree=tree.tree,
                last_state=serialize_last_state(old_trees[tree.tree], tree),
            )
            status_change.trees.append(status_change_tree)

        session.add(status_change)

    session.commit()

    return [
        {
            "tree": tree.tree,
            "status": new_status,
            "reason": new_reason,
            "message_of_the_day": new_motd,
        }
        for tree in trees
    ], 200


@result_object_wrap
def get_tree(tree: str) -> dict:
    """Handler for `GET /trees/{tree}`."""
    result = get_tree_by_name(tree)
    if result is None:
        raise ProblemException(
            404,
            f"No tree {tree} found.",
            "The tree does not exist.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
    return combinedtree_as_dict(result)


@auth.require_auth0(
    groups=(auth.TREESTATUS_ADMIN), scopes=("lando", "profile", "email"), userinfo=True
)
def make_tree(tree: str, body: dict):
    """Handler for `PUT /trees/{tree}`."""
    session = db.session
    if body["tree"] != tree:
        raise ProblemException(
            400,
            f"Tree names must match, {tree} from url and {body['tree']} from body do not.",
            "Tree names must match.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    new_tree = Tree(
        tree=tree,
        status=body["status"],
        reason=body["reason"],
        message_of_the_day=body["message_of_the_day"],
    )
    try:
        session.add(new_tree)
        session.commit()
    except (sa.exc.IntegrityError, sa.exc.ProgrammingError):
        raise ProblemException(
            400,
            f"Tree {tree} already exists.",
            "Tree already exists.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    return new_tree.to_dict(), 200


@auth.require_auth0(
    groups=(auth.TREESTATUS_ADMIN), scopes=("lando", "profile", "email"), userinfo=True
)
def delete_tree(tree: str) -> tuple[str, int]:
    """Handler for `DELETE /trees/{tree}`."""
    remove_tree_by_name(tree)
    return tree, 200


@auth.require_auth0(
    groups=(auth.TREESTATUS_USERS), scopes=("lando", "profile", "email"), userinfo=True
)
def update_log(id: int, body: dict):
    """Handler for `PATCH /log/{id}`."""
    session = db.session

    tags = body.get("tags")
    reason = body.get("reason")

    if tags is None and reason is None:
        return

    # Update the log table.
    update_tree_log(id, tags, reason)

    # Iterate over all stack.
    for status_change in StatusChange.query.all():
        for tree in status_change.trees:
            last_state = load_last_state(tree.last_state)

            if last_state["current_log_id"] != id:
                continue

            if reason:
                last_state["current_reason"] = reason
            if tags:
                last_state["current_tags"] = tags

            tree.last_state = json.dumps(last_state)

    session.commit()

    return {"tags": tags, "reason": reason}, 200


def get_logs_for_tree(tree_name: str, limit_logs: bool = True) -> list[dict]:
    """Return a list of Log entries as dicts.

    If `limit_logs` is `True`, limit the number of returned logs to the log limit.
    """
    # Verify the tree exists first.
    tree = Tree.query.filter_by(tree=tree_name).one_or_none()
    if not tree:
        raise ProblemException(
            404,
            f"No tree {tree_name} found.",
            "Could not find the requested tree.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    query = Log.query.filter_by(tree=tree_name).order_by(Log.created_at.desc())
    if limit_logs:
        query = query.limit(TREE_SUMMARY_LOG_LIMIT)

    return [log.to_dict() for log in query]


@result_object_wrap
def get_logs_all(tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs_all`."""
    return get_logs_for_tree(tree, limit_logs=False)


@result_object_wrap
def get_logs(tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs`."""
    return get_logs_for_tree(tree, limit_logs=True)


@result_object_wrap
def get_trees2() -> list[dict]:
    """Handler for `GET /trees2`."""
    return [combinedtree_as_dict(tree) for tree in get_combined_trees()]
