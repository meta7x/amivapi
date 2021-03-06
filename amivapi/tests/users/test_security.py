# -*- coding: utf-8 -*-
#
# license: AGPLv3, see LICENSE for details. In addition we strongly encourage
#          you to buy us beer if we meet and you like the software.
"""Tests for user module.

Includes item and field permissions as well as password hashing.
"""

import json
from bson import ObjectId

from passlib.hash import pbkdf2_sha256

from amivapi.tests import utils
from amivapi.users.security import (
    hash_on_insert, hash_on_update)


class PasswordHashing(utils.WebTestNoAuth):
    """Tests password hashing."""

    def assertVerify(self, plaintext, hashed_password):
        """Assert the hash matches the password."""
        self.assertTrue(pbkdf2_sha256.verify(plaintext, hashed_password))

    def test_hash_on_insert(self):
        """Test Hash insert function.

        Because of how Eve handles hooks, they all modify the input arguments.

        Need app context to find config.
        """
        with self.app.app_context():
            # First test hash on insert
            items = [
                {'password': "some_pw"},
                {'password': "other_pw"}
            ]

            # Hash passwords in list items
            hash_on_insert(items)

            # Check hashed
            self.assertVerify("some_pw", items[0]['password'])
            self.assertVerify("other_pw", items[1]['password'])

    def test_hash_on_update(self):
        """Test hash on update. Works like test for hash on insert."""
        with self.app.app_context():
            data = {'password': "some_pw"}

            # Second param is original data, but the hash function ignores
            # it so we can just set it to None
            hash_on_update(data, None)

            # Check hash
            self.assertVerify("some_pw", data['password'])

    def assertVerifyDB(self, user_id, plaintext):
        """Check that the stored password was hashed correctly.

        Shorthand to query db and compare.

        Args:
            user_id (str): The user.
            hashed_password (str): The hash which should be stored

        Returns:
            bool: True if hashed correctly.
        """
        user = self.db["users"].find_one({'_id': ObjectId(user_id)})

        self.assertTrue(pbkdf2_sha256.verify(plaintext, user['password']))

    def test_hash_hooks(self):
        """Test hash hooks.

        Assert passwort is hashed when user is created or updated through
        the api.
        """
        post_data = {
            'firstname': 'T',
            'lastname': 'Estuser',
            'gender': 'female',
            'membership': 'regular',
            'email': 'test@user.amiv',
            'password': "some_pw"
        }

        user = self.api.post("/users", data=post_data, status_code=201).json

        self.assertVerifyDB(user['_id'], "some_pw")

        patch_data = {'password': "other_pw"}

        headers = {'If-Match': user['_etag']}
        user = self.api.patch("/users/%s" % user['_id'],
                              headers=headers, data=patch_data,
                              status_code=200).json

        self.assertVerifyDB(user['_id'], "other_pw")


class UserFieldsTest(utils.WebTest):
    """Test field permissions.

    Some fields are not visible for everyone.
    Some fields can be changed by the user, some only by admins.
    """

    def create_users(self):
        """Add users with full data."""
        users = self.load_fixture({
            'users': [
                {
                    'nethz': 'pablamiv',
                    'firstname': "Pabla",
                    'lastname': "AMIV",
                    'membership': "regular",
                    'legi': "12345678",
                    'gender': 'female',
                    'department': 'itet',
                    'password': "userpass",
                    'email': "pabla@amiv.ch",
                    'rfid': "123456"
                },
                {
                    'nethz': 'pablomiv',
                    'firstname': "Pablo",
                    'lastname': "AMIV",
                    'membership': "regular",
                    'legi': "87654321",
                    'gender': 'male',
                    'department': 'mavt',
                    'password': "userpass2",
                    'email': "pablo@amiv.ch",
                    'rfid': "654321"
                }
            ]
        })
        self.user = users[0]
        self.other_user = users[1]

        self.user_token = self.get_user_token(str(self.user['_id']))
        self.root_token = self.get_root_token()

    # Important: Nobody can see passwords
    BASIC_FIELDS = ['_id', '_updated', '_created', '_etag', '_links', 'nethz',
                    'firstname', 'lastname']
    RESTRICTED_FIELDS = ['membership', 'legi', 'gender', 'department', 'email',
                         'rfid', 'password_set']
    ALL_FIELDS = BASIC_FIELDS + RESTRICTED_FIELDS

    def test_read_item(self):
        """When reading, all fields are visible for user/admin only.

        Other users only see name and nethz. No public get.
        """
        self.create_users()
        self.api.get("/users/" + str(self.user['_id']),
                     status_code=401)

        def assertFields(user, token, fields):
            response = self.api.get("/users/" + str(user['_id']),
                                    token=token,
                                    status_code=200).json
            self.assertItemsEqual(response.keys(), fields)

        assertFields(self.other_user, self.user_token, self.BASIC_FIELDS)
        assertFields(self.other_user, self.root_token, self.ALL_FIELDS)
        assertFields(self.user, self.user_token, self.ALL_FIELDS)
        assertFields(self.user, self.root_token, self.ALL_FIELDS)

    def test_read_resource(self):
        """Same as test_read_item but with GET to resource."""
        self.create_users()
        self.api.get("/users", status_code=401)

        def assertFields(token, user_fields, other_user_fields):
            response = self.api.get("/users",
                                    token=token, status_code=200).json
            for item in response['_items']:
                if item['_id'] == str(self.user['_id']):
                    self.assertItemsEqual(item.keys(), user_fields)
                elif item['_id'] == str(self.other_user['_id']):
                    self.assertItemsEqual(item.keys(), other_user_fields)

        assertFields(self.user_token, self.ALL_FIELDS, self.BASIC_FIELDS)
        assertFields(self.root_token, self.ALL_FIELDS, self.ALL_FIELDS)

    def test_embedded_read(self):
        """Test that hide hooks are also called when embedding into another
        document."""
        self.app.register_resource('test', {
            'schema': {
                'user': {
                    'data_relation': {
                        'resource': 'users',
                        'embeddable': True
                    },
                    'type': 'objectid'
                }
            }
        })

        self.create_users()
        test_obj = self.new_object('test',
                                   user=str(self.other_user['_id']))

        resp = self.api.get('/test/%s?embedded={"user":1}' % test_obj['_id'],
                            token=self.root_token, status_code=200).json
        self.assertItemsEqual(resp['user'].keys(),
                              set(self.ALL_FIELDS) - set(['_links']))

        resp = self.api.get('/test/%s?embedded={"user":1}' % test_obj['_id'],
                            token=self.user_token, status_code=200).json
        self.assertItemsEqual(resp['user'].keys(),
                              set(self.BASIC_FIELDS) - set(['_links']))

    def test_password_status(self):
        user = self.new_object('users', password='abcdefg')
        user_no_pass = self.new_object('users', password=None)

        root_token = self.get_root_token()

        resp = self.api.get('/users/%s' % user['_id'], token=root_token,
                            status_code=200).json
        self.assertTrue(resp['password_set'])

        resp = self.api.get('/users/%s' % user_no_pass['_id'], token=root_token,
                            status_code=200).json
        self.assertFalse(resp['password_set'])

    def test_change_by_user(self):
        """User can change password, email. and rfid."""
        user = self.new_object('users', email='a@b.c',
                               password='sosecure',
                               rfid='123456')

        token = self.get_user_token(str(user['_id']))
        etag = user['_etag']
        user_url = "/users/%s" % user['_id']

        good_changes = [
            {'password': 'evenmoresecure'},
            {'email': 'newmail@amiv.ch'},
            {'rfid': '654321'}
        ]

        for data in good_changes:
            response = self.api.patch(user_url,
                                      data=data,
                                      token=token,
                                      headers={'If-Match': etag},
                                      status_code=200).json
            etag = response['_etag']

    def test_not_patchable_unless_admin(self):
        """Admin can change everything, user not."""
        user = self.new_object('users', gender='female', department='itet',
                               membership="regular",
                               nethz='user', password="userpass")
        user_id = str(user['_id'])
        user_etag = user['_etag']  # This way we can overwrite it later easily

        bad_changes = [
            {"firstname": "new_name"},
            {"lastname": "new_name"},
            {"legi": "10000000"},
            {"nethz": "coolkid"},
            {"department": "mavt"},
            {"gender": "male"},
            {"membership": "none"},
        ]

        def patch(data, token, etag, status_code):
            """Shortcut for patch."""
            return self.api.patch("/users/" + user_id, token=token,
                                  headers={"If-Match": etag},
                                  data=data,
                                  status_code=status_code).json

        # The user can change none of those fields
        user_token = self.get_user_token(user_id)
        for bad_data in bad_changes:
            patch(bad_data, user_token, user_etag, 422)

        # The admin can
        admin_token = self.get_root_token()
        for data in bad_changes:
            response = patch(data, admin_token, user_etag, 200)
            # Since the change is successful we need the new etag
            user_etag = response['_etag']

    def test_query_restricted_fields(self):
        """Only admins can query restricted fields."""
        basic = [(field, 200) for field in self.BASIC_FIELDS]
        restricted = [(field, 400) for field in self.RESTRICTED_FIELDS]

        for field, status in basic + restricted:
            user_id = str(self.new_object('users')['_id'])
            user_token = self.get_user_token(user_id)
            root_token = self.get_root_token()

            # Formulate all kinds of queries Eve accepts
            python_query = '%s=="something"' % field
            mongo_query = json.dumps({field: "something"})
            nested_query = json.dumps({
                '$or': [
                    {'$and': [{field: {'$in': ["something"]}}]}
                ]
            })

            for query in (python_query, mongo_query, nested_query):
                url = '/users?where=%s' % query
                # User is not allowed
                self.api.get(url, token=user_token, status_code=status)

                # Admin is allowed
                self.api.get(url, token=root_token, status_code=200)
