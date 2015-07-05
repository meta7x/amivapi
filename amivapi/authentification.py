# -*- coding: utf-8 -*-
#
# license: AGPLv3, see LICENSE for details. In addition we strongly encourage
#          you to buy us beer if we meet and you like the software.

"""
This file provides token based authentification(identification of users). A
user can POST the /sessions resource to obtain a token.

When a user sends his token with a request the g.logged_in_user global variable
will be set.
If an apikey is sent instead of a token, then g.apikey will be set to that key
and g.logged_in_user is set to -1
"""


from os import urandom
from base64 import b64encode
from datetime import datetime

from flask import current_app as app
from flask import Blueprint, abort, g

from eve.methods.common import payload
from eve.auth import TokenAuth
from eve.methods.post import post_internal
from eve.render import send_response
from eve.utils import debug_error_message, config

from sqlalchemy.orm.exc import NoResultFound

from amivapi.utils import create_new_hash, check_hash
from amivapi import models


class TokenAuth(TokenAuth):
    """ We could have used eve's allowed_roles parameter, but that does not
    support roles on endpoint level, but only on resource level"""
    def check_auth(self, token, allowed_roles, resource, method):
        """ This is the authentification function called by eve. It will parse
        the send token and determine if it is from a valid user or a know
        apikey.

        You should not call this function directly. Use the functions in
        authorization.py instead(have a look at common_authorization()).

        :global g.logged_in_user: This is set to the user id of the
                                  authentificated user or to -1 if an apikey
                                  was sent
        :global g.apikey: If an apikey was sent it will be saved here. For a
                          normal user this will not be set

        :param token: The token or apikey sent by the user
        :param allowed_roles: unused, passed by eve
        :param resource: name of the requested resource, used for logging
        :param method: name of the requested resource, used for logging

        :returns: True if token or apikey was valid, aborts with 401 if not
        """

        # Handle apikeys
        if token in config.APIKEYS:
            g.logged_in_user = -1
            g.apikey = token
            return True

        dbsession = app.data.driver.session

        try:
            sess = dbsession.query(models.Session).filter(
                models.Session.token == token).one()
        except NoResultFound:
            error = ("Access denied for %s %s: unknown token %s"
                     % (method, resource, token))
            app.logger.debug(error)
            abort(401, description=debug_error_message(error))

        # Update last access time
        sess._updated = datetime.utcnow()
        dbsession.commit()

        g.logged_in_user = sess.user_id
        return True


authentification = Blueprint('authentification', __name__)


def _token_response(user_id):
    # Everything is alright, create token for user
    token = b64encode(urandom(256)).decode('utf_8')

    # Make sure token is unique
    while app.data.driver.session.query(models.Session).filter_by(
            token=token).count() != 0:
        token = b64encode(urandom(256)).decode('utf_8')

    response = post_internal(
        'sessions',
        {
            'user_id': user_id,
            'token': token
        }
    )

    return response


@authentification.route('/sessions', methods=['POST'])
def process_login():
    """ Login
    A POST to /sessions exspects a username and password. If they are correct a
    token is created and used to register a session in the database, which is
    sent back to the user.

    First of all we will try to authenticate the user with LDAP (if enabled).
    If this succeeds we update or create (if not yet in db) the user data

    If LDAP auth fails and the user is in the db, we will compare the received
    pw with the pw in the db.

    :returns: Flask.Response object
    """
    p_data = payload()
    if 'username' not in p_data:
        abort(422, description=debug_error_message(
            "Please provide a username."))
    if 'password' not in p_data:
        abort(422, description=debug_error_message(
            "Please provide the password."))

    # Query user first
    user = app.data.driver.session.query(models.User).filter_by(
        username=p_data['username']).first()

    error = ""

    # PHASE 1: LDAP
    # If LDAP is enabled, try to authenticate the user
    # If this is successful, create/update user data
    if config.ENABLE_LDAP:  # To LDAP or not to LDAP?
        if app.ldap_connector.authenticate(
                p_data['username'], p_data['password']):
            # LDAP success, now get data

            # Create or update user

            # Successful login and db update with ldap, send response
            # TODO: using root for now, replace with actual user id
            return send_response('sessions', _token_response(0))
        else:
            error += "LDAP authentication failed, "  # Prove additional info
    else:
        error += "LDAP authentication deactivated; "  # Prove additional info

    # PHASE 2: database
    # If LDAP fails or is not accessible, try to find user in database
    if user:
        if check_hash(p_data['password'], user.password):
            # Sucessful login with db, send response
            return send_response('sessions', _token_response(user.id))
        else:
            error += "Login with db failed: Password does not match!"
            app.logger.debug(error)
            abort(401, description=debug_error_message(error))

    # PHASE 3: Abort if everything else fails
    # LDAP is unsuccessful (deactivated/wrong credentials) and user not found
    error += "Login with db failed: User not found!"

    app.logger.debug(error)
    abort(401, description=debug_error_message(error))


#
#
# Hooks to hash passwords when user entries are changed in the database
#
#


def hash_password_before_insert(users):
    """ Hook to hash the password when a new user is inserted into the
    database """
    for u in users:
        if 'password' in u:
            u['password'] = create_new_hash(u['password'])


def hash_password_before_update(user, original_user):
    """ Hook to hash the password when it is changed """
    hash_password_before_insert([user])


def hash_password_before_replace(user, original_user):
    """ Hook to hash the password when a user is replaced with a new one """
    hash_password_before_insert([user])


#
#
# Hooks to add _author field to all database inserts
#
#


def set_author_on_insert(resource, items):
    """ Hook to set the _author field for all new objects """
    _author = getattr(g, 'logged_in_user', -1)
    for i in items:
        i['_author'] = _author


def set_author_on_replace(resource, item, original):
    """ Hook to set the _author field when a new object is inserted
    during a PUT request """
    set_author_on_insert(resource, [item])
