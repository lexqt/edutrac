from trac.core import Component, TracError

from trac.util.translation import _

# init sqlalchemy models
from trac.user.model import *


class UnknownGroupLevel(ValueError):
    pass

class UnknownProjectUserRealm(TracError):
    pass



class GroupLevel(object):
    TEAM = 1
    STUDGROUP = 2
    METAGROUP = 3

    @classmethod
    def get_column(cls, level):
        if level == cls.TEAM:
            column = 'team_id'
        elif level == cls.STUDGROUP:
            column = 'studgroup_id'
        elif level == cls.METAGROUP:
            column = 'metagroup_id'
        else:
            raise UnknownGroupLevel
        return column



class UserRoleInstance(object):
    '''
    Wrapper class for user roles to support
    internal bitwise operations for metaroles.
    '''

    def __init__(self, code):
        self._code = int(code)

    def __eq__(self, role):
        '''Is role equal to other `role`.

        `role`: UserRoleInstance or integer code.'''
        if isinstance(role, UserRoleInstance):
            return self._code == role._code
        return self._code == role

    def __ne__(self, role):
        return not self == role

    def __str__(self):
        return str(self._code)

    def __int__(self):
        return self._code

    def __long__(self):
        return self._code

    def __contains__(self, role):
        return self.include(role)

    def include(self, role):
        '''Does role include other `role`

        `role`: UserRoleInstance or integer code.
        '''
        if isinstance(role, UserRoleInstance):
            return (self._code & role._code) == role._code
        return (self._code & role) == role


class UserRole(object):

    # include bit logic for metaroles

    NONE            = UserRoleInstance(0)  # 00000b
    DEVELOPER       = UserRoleInstance(1)  # 00001b

    PROJECT_MANAGER = UserRoleInstance(2)  # 00100b
    GROUP_MANAGER   = UserRoleInstance(4)  # 00010b
    MANAGER         = UserRoleInstance(6)  # 00110b

    ADMIN           = UserRoleInstance(14) # 01110b

    def __new__(cls, code):
        if not code: # None, empty string, etc
            return cls.NONE
        try:
            return UserRoleInstance(code)
        except (TypeError, ValueError):
            return cls.NONE

    @classmethod
    def label(cls, role):
        if role == cls.DEVELOPER:
            return _('Developer')
        elif role == cls.MANAGER:
            return _('Manager')
        elif role == cls.GROUP_MANAGER:
            return _('Group manager')
        elif role == cls.PROJECT_MANAGER:
            return _('Project manager')
        elif role == cls.ADMIN:
            return _('Administrator')
        return _('Unknown role')



class UserManagement(Component):
    """
    This class implements API to manage teams and groups.
    """

    VALID_PROJECT_USER_REALMS = ('team', 'manager')

    def user_exists(self, username):
        """
        Returns whether the user exists.
        """
        db = self.env.get_read_db()
        cursor = db.cursor()

        q = '''
            SELECT 1
            FROM users
            WHERE username=%s
            LIMIT 1
        '''
        cursor.execute(q, (username,))
        return cursor.rowcount==1

    def get_project_users(self, pid, realms, perm_groups=None):
        # checks
        assert realms
        if not set(realms) <= set(self.VALID_PROJECT_USER_REALMS):
            raise UnknownProjectUserRealm('Invalid user realm')

        query = ''
        args = []
        if len(realms) == 1:
            realm = realms[0]
            if realm == 'team':
                query = '''
                    SELECT dp.username
                    FROM developer_projects dp
                    WHERE dp.project_id=%s
                '''
                args.append(pid)
            elif realm == 'manager':
                query = '''
                    SELECT mp.username
                    FROM manager_projects mp
                    WHERE mp.project_id=%s
                '''
                args.append(pid)
        elif set(realms) == set(('team', 'manager')):
                query = '''
                    SELECT dp.username
                    FROM developer_projects dp
                    WHERE dp.project_id=%s
                    UNION
                    SELECT mp.username
                    FROM manager_projects mp
                    WHERE mp.project_id=%s
                '''
                args += (pid, pid)
        if perm_groups:
            perm_groups = tuple(perm_groups)
            query = '''
            ( %s )
            INTERSECT
            SELECT username FROM (
                SELECT username, action
                FROM permission
                UNION
                SELECT username, action
                FROM project_permissions
                WHERE project_id=%%s
            ) AS uniperm
            WHERE action in %%s
            ''' % (query,)
            args.append(pid)
            args.append(perm_groups)

        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, args)

        return [row[0] for row in cursor.fetchall()]

    def get_user_fullname(self, username, req=None, with_username=False):
        if not username:
            return username
        if req is not None:
            if username not in req.data['user_fullname_cache']:
                req.data['user_fullname_cache'][username] = self._get_user_fullname(username)
            fullname = req.data['user_fullname_cache'][username]
        else:
            fullname = self._get_user_fullname(username)
        if not with_username:
            return fullname
        if fullname == username:
            return fullname
        return u'{0} ({1})'.format(fullname, username)

    def _get_user_fullname(self, username):
        q = '''
            SELECT fullname
            FROM user_info
            WHERE username=%s
        '''
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(q, (username,))
        res = cursor.fetchone()
        if not res or not res[0]:
            return username
        return res[0]

    def get_group_users(self, gid, group_lvl=GroupLevel.TEAM):
        column = GroupLevel.get_column(group_lvl)
        query = '''
            SELECT username
            FROM membership
            WHERE {column}=%s
            ORDER BY username
        '''
        query = query.format(column=column)

        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, (gid,))
        rows = cursor.fetchall()
        return [r[0] for r in rows]

    def get_group_user_count(self, gid, group_lvl=GroupLevel.TEAM):
        column = GroupLevel.get_column(group_lvl)
        query = '''
            SELECT COUNT(*)
            FROM membership
            WHERE {column}=%s
        '''
        query = query.format(column=column)

        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, (gid,))
        row = cursor.fetchone()
        return row[0]

