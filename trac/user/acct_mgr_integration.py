import re
from base64 import b64decode

from trac.config import ListOption, ExtensionOption
from trac.core import Component, implements, TracError
from trac.db import with_transaction
from trac.admin import IAdminCommandProvider
from trac.web.api import IRequestFilter, RequestDone, IAuthenticator
from trac.perm import PermissionError
from trac.project.sys import ProjectSystem
from trac.project.api import ProjectManagement
from trac.user.api import UserManagement

from genshi.builder import tag
from trac.util.translation import _

from acct_mgr.api import AccountManager, IPasswordStore, IAccountChangeListener, \
            del_user_attribute, set_user_attribute
from acct_mgr.api import _ as am_
from acct_mgr.web_ui import EmailVerificationModule
from acct_mgr.pwhash import IPasswordHashMethod
from random import Random


def generatePassword(passwordLength=10):
    rng = Random()
    righthand = '23456qwertasdfgzxcvbQWERTASDFGZXCVB'
    lefthand = '789yuiophjknmYUIPHJKLNM'
    allchars = righthand + lefthand
    passwd=''
    for i in xrange(passwordLength):
        passwd+=rng.choice(allchars)
    return passwd


class AccountManagerIntegration(Component):
    """
    This class implements DB password store for AccountManager.

    It can be used as primary Password store
    or as just AccountChangeListener (then it replicates all
    user/password info in `users` table)
    """

    hash_method = ExtensionOption('account-manager', 'hash_method', IPasswordHashMethod, 'HtPasswdHashMethod')

    implements(IPasswordStore, IAccountChangeListener, IAdminCommandProvider)

    def __init__(self):
        self.acctmgr = AccountManager(self.env)

    # IPasswordStore

    def get_users(self):
        """
        Returns an iterable of the known usernames.
        """

        db = self.env.get_read_db()
        cursor = db.cursor()

        query='''
            SELECT username
            FROM users
            ORDER BY username
        '''

        cursor.execute(query)
        for row in cursor:
            yield row[0]

    def has_user(self, user):
        """
        Returns whether the user account exists.
        """

        db = self.env.get_read_db()
        cursor = db.cursor()

        query = '''
            SELECT 1
            FROM users
            WHERE username=%s
            LIMIT 1
        '''
        cursor.execute(query, (user,))

        return cursor.rowcount == 1

    def set_password(self, user, password, old_password = None):
        """Sets the password for the user.  This should create the user account
        if it doesn't already exist.
        Returns True if a new account was created, False if an existing account
        was updated.
        """

        pwdhash = self.hash_method.generate_hash(user, password)

        res = {'created': False}

        @with_transaction(self.env)
        def set_password_db(db):
            cursor = db.cursor()

            query = '''
                UPDATE users
                SET password=%s
                WHERE username=%s
            '''
            cursor.execute(query, (pwdhash, user))

            if cursor.rowcount > 0:
                self.log.debug('AccountManagerIntegration: set_password: an existing user was updated')
                return

            query = '''
                INSERT INTO users (username, password)
                VALUES (%s, %s)
            '''
            cursor.execute(query, (user, pwdhash))

            res['created'] = True

        return res['created']

    def check_password(self, user, password):
        """Checks if the password is valid for the user.

        Returns True if the correct user and password are specified.  Returns
        False if the incorrect password was specified.  Returns None if the
        user doesn't exist in this password store.

        Note: Returning `False` is an active rejection of the login attempt.
        Return None to let the auth fall through to the next store in the
        chain.
        """

        db = self.env.get_read_db()
        cursor = db.cursor()

        query = '''
            SELECT password
            FROM users
            WHERE username=%s
        '''
        cursor.execute(query, (user,))

        row = cursor.fetchone()
        if row is None:
            return None
        pwdhash = row[0]
        return self.hash_method.check_hash(user, password, pwdhash)

    def delete_user(self, user):
        """Deletes the user account.
        Returns True if the account existed and was deleted, False otherwise.
        """

        if not self.has_user(user):
            return False

        @with_transaction(self.env)
        def delete_user_db(db):
            cursor = db.cursor()

            query = '''
                DELETE FROM users
                WHERE username=%s
            '''
            cursor.execute(query, (user,))

        del_user_attribute(self.env, username=user)
        return True

    # IAccountChangeListener

    def user_created(self, user, password):
        """
        Create a New user
        """

        if self.has_user(user):
            return False

        res = self.set_password(user, password)
        self.log.debug("AccountManagerIntegration: user_created: %s, %s" % (user, res))
        return res

    def user_password_changed(self, user, password):
        """Password changed
        """
        res = self.set_password(user, password)
        self.log.debug("AccountManagerIntegration: user_password_changed: %s" % user)
        return res

    def user_deleted(self, user):
        """User deleted
        """
        res = self.delete_user(user)
        self.log.debug("AccountManagerIntegration: user_deleted: %s" % user)
        return res

    def user_password_reset(self, user, email, password):
        """User password reset
        """
        pass

    def user_email_verification_requested(self, user, token):
        """User verification requested
        """
        pass

    # IAdminCommandProvider

    def get_admin_commands(self):
        yield ('account add', '<username> <password> [<name> [<email>]]',
               'Add user account',
               None, self._do_add_account)
        yield ('account remove', '<username>',
               'Remove user account',
               None, self._do_remove_account)

    def _do_add_account(self, username, password, *attrs):
        '''See acct_mgr.web_ui._create_user function'''
        username = self.acctmgr.handle_username_casing(username)
        attr_cnt = len(attrs)
        name = ''
        email = ''
        if attr_cnt > 0:
            name = attrs[0]
        if attr_cnt > 1:
            email = attrs[1]

        account = {
            'username' : username,
            'name' : name,
            'email' : email,
        }
        error = TracError('')
        error.account = account

        if username in ['authenticated', 'anonymous']:
            error.message = am_("Username %s is not allowed.") % username
            raise error

        if self.acctmgr.has_user(username):
            error.message = am_(
                "Another account or group named %s already exists.") % username
            raise error

        # Skip checking for match with permission groups here.
        # It is too resource-intensive query for this op

        from acct_mgr.util import containsAny
        blacklist = self.acctmgr.username_char_blacklist
        if containsAny(username, blacklist):
            pretty_blacklist = ''
            for c in blacklist:
                if pretty_blacklist == '':
                    pretty_blacklist = tag(' \'', tag.b(c), '\'')
                else:
                    pretty_blacklist = tag(pretty_blacklist,
                                           ', \'', tag.b(c), '\'')
            error.message = tag(am_(
                "The username must not contain any of these characters:"),
                pretty_blacklist)
            raise error

        if email:
            if not re.match('^[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,6}$',
                              email, re.IGNORECASE):
                error.message = am_("""The email address specified appears to be
                                  invalid. Please specify a valid email address.
                                  """)
                raise error

        if self.env.is_enabled(EmailVerificationModule) and self.acctmgr.verify_email:
            if not email:
                error.message = am_("You must specify a valid email address.")
                raise error
            if self.acctmgr.has_email(email):
                error.message = am_("""The email address specified is already in
                                  use. Please specify a different one.
                                  """)
                raise error

        self.acctmgr.set_password(username, password)

        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1 FROM session WHERE sid=%s LIMIT 1',
                (username,))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute('''
                INSERT INTO session
                        (sid,authenticated,last_visit)
                VALUES  (%s,0,0)
                ''', (username,))

        extra = {
            'name': name,
            'email': email,
        }
        for attr, val in extra.iteritems():
            if not val:
                continue
            set_user_attribute(self.env, username, attr, val)

    def _do_remove_account(self, username):
        if not self.acctmgr.has_user(username):
            raise TracError(_('User with username %(username)s does not exists',
                                   username=username))
        self.acctmgr.delete_user(username)



# Author of original HTTPAuthFilter component:
# Noah Kantrowitz (noah@coderanger.net)
# Modificated by Aleksey A. Porfirov, 2012

class HTTPAuthFilter(Component):
    """Request filter and handler to provide HTTP authentication."""

    paths = ListOption('httpauth', 'paths', default='/login/xmlrpc',
                       doc='Paths to force HTTP authentication on.')

    formats = ListOption('httpauth', 'formats', default='rss',
                         doc='Request formats to force HTTP authentication on')

    implements(IRequestFilter, IAuthenticator)

    def __init__(self):
        self.ps = ProjectSystem(self.env)
        self.pm = ProjectManagement(self.env)

    # IRequestFilter

    def pre_process_request(self, req, handler):
        '''HTTPAuthFilter preprocess request before PostloginModule.
        HTTP Auth request must be processed autonomously and must not
        use/change req.session variables (like current session project).
        To indicate this special request it sets req.data['force_httpauth'] flag,
        that other essential components must respect'''
        check = False
        for path in self.paths:
            if req.path_info.startswith(path):
                check = True
                break
        else:
            check = req.args.get('format') in self.formats

        if check:
            if not self._check_password(req):
                self.log.info('HTTPAuthFilter: Authentication required. Returing HTTP 401')
                return self
            if 'project_id' not in req.data:
                raise TracError('Can not continue process request with no project ID. '
                                'Insert "/project/<id>/" in your URL.')
            pid = req.data['project_id']

            # check project
            # TODO: what about user role?
            req.data['role'] = None
            for role in (UserManagement.USER_ROLE_DEVELOPER, UserManagement.USER_ROLE_MANAGER):
                pids = self.pm.get_user_projects(req.authname, role=role, pid_only=True)
                if pid in pids:
                    req.data['role'] = role
                    self.ps.set_request_data(req, pid)
                    break
            else:
                del req.data['project_id']
                req.data['http_auth_fail_project_check'] = True
                raise PermissionError(msg='You have no access to requested project')

            # authentication and request data preparation done
            req.data['force_httpauth'] = True
        return handler

    def post_process_request(self, req, template, content_type):
        if 'http_auth_fail_project_check' in req.data:
            raise PermissionError(msg='You have no access to requested project')
        return template, content_type

    # IRequestHandler
    # (for handler substitution by pre_process_request)

    def process_request(self, req):
        if req.session:
            req.session.save() # Just in case

        auth_req_msg = 'Authentication required'
        req.send_response(401)
        req.send_header('WWW-Authenticate', 'Basic realm="EduTrac"')
        req.send_header('Content-Type', 'text/plain')
        req.send_header('Pragma', 'no-cache')
        req.send_header('Cache-control', 'no-cache')
        req.send_header('Expires', 'Fri, 01 Jan 1999 00:00:00 GMT')
        req.send_header('Content-Length', str(len(auth_req_msg)))
        req.end_headers()

        if req.method != 'HEAD':
            req.write(auth_req_msg)
        raise RequestDone

    # IAuthenticator

    def authenticate(self, req):
        user = self._check_password(req)
        if user:
            req.environ['REMOTE_USER'] = user
            self.log.debug('HTTPAuthFilter: Authentication passed for %s', user)
            return user

    # Internal methods

    def _check_password(self, req):
        header = req.get_header('Authorization')
        if header:
            token = header.split()[1]
            user, passwd = b64decode(token).split(':', 1)
            if AccountManager(self.env).check_password(user, passwd):
                return user
