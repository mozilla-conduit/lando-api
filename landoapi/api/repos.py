# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from flask import current_app, g

from landoapi import auth
from landoapi.models.repo import RepoNotice
from landoapi.repos import get_repos_for_env, SCM_ALLOW_DIRECT_PUSH
from landoapi.storage import db

logger = logging.getLogger(__name__)
auth_params = {"scopes": ("lando", "profile", "email"), "userinfo": True}


@auth.require_auth0(**auth_params)
def get_repo_notices():
    if SCM_ALLOW_DIRECT_PUSH.active_group not in g.auth0_user.groups:
        raise auth._not_authorized_problem_exception()
    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repos = list(supported_repos.keys())
    notices = RepoNotice.query.filter(RepoNotice.is_archived == False).order_by(
        RepoNotice.updated_at.desc()
    )

    return {"notices": [n.serialize() for n in notices], "repos": repos}, 200


@auth.require_auth0(**auth_params)
def post_repo_notice(data):
    if SCM_ALLOW_DIRECT_PUSH.active_group not in g.auth0_user.groups:
        raise auth._not_authorized_problem_exception()
    notice = RepoNotice()
    for attr in data:
        setattr(notice, attr, data[attr])
    db.session.add(notice)
    db.session.commit()
    logger.info(f"{notice.id} was created.")
    return notice.serialize(), 201


@auth.require_auth0(**auth_params)
def put_repo_notice(notice_id, data):
    if SCM_ALLOW_DIRECT_PUSH.active_group not in g.auth0_user.groups:
        raise auth._not_authorized_problem_exception()
    notice = RepoNotice.get(notice_id)
    for attr in data:
        setattr(notice, attr, data[attr])
    db.session.add(notice)
    db.session.commit()
    return notice.serialize(), 200


@auth.require_auth0(**auth_params)
def delete_repo_notice(notice_id):
    if SCM_ALLOW_DIRECT_PUSH.active_group not in g.auth0_user.groups:
        raise auth._not_authorized_problem_exception()
    notice = RepoNotice.query.get(notice_id)
    notice.is_archived = True
    db.session.add(notice)
    db.session.commit()
    return notice.serialize(), 200
