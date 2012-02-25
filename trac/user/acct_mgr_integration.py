from trac.config import Option, ExtensionOption
from trac.core import Component, implements
from trac.db import with_transaction

from acct_mgr.api import IPasswordStore, IAccountChangeListener, del_user_attribute
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
    """

    hash_method = ExtensionOption('account-manager', 'hash_method', IPasswordHashMethod, 'HtPasswdHashMethod')

    implements(IPasswordStore, IAccountChangeListener)

    # IPasswordStore methods
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
                self.log.debug('group_management: set_password: an existing user was updated')
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

    #IAccountChangeListener methods

    def user_created(self, user, password):
        """
        Create a New user
        """

        if self.has_user(user):
            return False

        res = self.set_password(user, password, create_user=True)
        self.log.debug("group_management: user_created: %s, %s" % (user, res))
        return res

    def user_password_changed(self, user, password):
        """Password changed
        """
        res = self.set_password(user, password, create_user=True)
        self.log.debug("group_management: user_password_changed: %s" % user)
        return res

    def user_deleted(self, user):
        """User deleted
        """
        res = self.delete_user(user)
        self.log.debug("group_management: user_deleted: %s" % user)
        return res

    def user_password_reset(self, user, email, password):
        """User password reset
        """
        pass

    def user_email_verification_requested(self, user, token):
        """User verification requested
        """
        pass

