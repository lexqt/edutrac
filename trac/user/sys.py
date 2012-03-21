from trac.core import Component


class UserSystem(Component):
    """
    User Management core component
    """

    # Request init methods

    def init_request(self, req):
        req._user_fullname_cache = {}

