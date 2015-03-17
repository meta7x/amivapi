from amivapi.tests import util


class AuthentificationTest(util.WebTest):

    def test_invalid_username(self):
        """ Try to login with an unknown username """
        self.new_user(username="user1")

        self.api.post("/sessions", data={'username': "user1\0",
                                         'password': ''}, status_code=401)

    def test_no_usernames(self):
        """ Try to login without username """
        self.new_user(username="user1")

        self.api.post("/sessions", data={'password': 'mypw'}, status_code=422)

    def test_no_password(self):
        """ Try to login without password """
        self.new_user(username="user1")

        self.api.post("/sessions", data={'username': 'user1'}, status_code=422)

    def test_invalid_token(self):
        """ Try to do a request using invalid token """
        self.new_session()

        self.api.get("/users", token="xxx", status_code=401)
