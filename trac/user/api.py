from trac.config import Option, ExtensionOption
from trac.core import Component, implements, TracError
from trac.db import with_transaction, call_db_func



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


GL_MAP = {
    GroupLevel.TEAM:      'team',
    GroupLevel.STUDGROUP: 'stud',
    GroupLevel.METAGROUP: 'meta',
}


class UserManagement(Component):
    """
    This class implements API to manage teams and groups.
    """

    USER_ROLE_DEVELOPER = 1
    USER_ROLE_MANAGER   = 2
    USER_ROLE_ADMIN     = 3

    VALID_PROJECT_USER_REALMS = ('team', 'manager')

    def group_exists(self, gid, group_lvl=GroupLevel.TEAM):
        """
        Returns whether the group exists.
        """

        db = self.env.get_read_db()
#        cursor = db.cursor()
#
#        query = '''
#            SELECT 1
#            FROM {table_group}
#            WHERE id=%s
#            LIMIT 1
#        '''
#        query = self._process_query(query, group_lvl)

        cursor = call_db_func(db, 'check_group_exists', (gid, GL_MAP[group_lvl]))
        res = cursor.fetchone()[0]

        return res

    def has_user(self, user, gid, group_lvl=GroupLevel.TEAM):
        """
        Returns whether the group has user.
        """

        db = self.env.get_read_db()
#        cursor = db.cursor()
#
#        query = '''
#            SELECT 1
#            FROM users u JOIN team_members tm ON u.id=tm.user_id
#                JOIN teams t ON t.id=tm.team_id
#                {extra_joins}
#                
#            WHERE u.username=%s AND {target}.id=%s
#            LIMIT 1
#        '''
#        if group_lvl == GroupLevel.TEAM:
#            extra  = ''
#            target = 't'
#        elif group_lvl == GroupLevel.STUDGROUP:
#            extra  += '''
#                JOIN teamgroup_rel tr ON tr.team_id=t.id
#                JOIN student_groups sg ON sg.id=tr.studgroup_id'''
#            target = 'sg'
#        elif group_lvl == GroupLevel.METAGROUP:
#            extra  += '''
#                JOIN groupmeta_rel gr ON gr.studgroup_id=sg.id
#                JOIN metagroups mg ON mg.id=gr.metagroup_id'''
#            target = 'mg'
#            
#        query = query.format(extra_joins=extra, target=target)

        cursor = call_db_func(db, 'check_membership', (user, gid, GL_MAP[group_lvl]))
        res = cursor.fetchone()[0]

        return res

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
            query = '''
            ( %s )
            INTERSECT
            SELECT username
            FROM permission
            WHERE action in %%s
            ''' % (query,)
            args.append(tuple(perm_groups))

        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, args)

        return [row[0] for row in cursor.fetchall()]

    def get_user_fullname(self, username, req=None):
        if req is not None:
            if username not in req._user_fullname_cache:
                req._user_fullname_cache[username] = self._get_user_fullname(username)
            return req._user_fullname_cache[username]
        return self._get_user_fullname(username)

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

    def add_group(self, name, group_lvl=GroupLevel.TEAM, extra=None):
        pass

    def del_group(self, gid, group_lvl=GroupLevel.TEAM):
        pass

    def alter_group(self, gid, changes, group_lvl=GroupLevel.TEAM):
        pass

    def add_group_to_group(self, gid, parent_gid, group_lvl=GroupLevel.TEAM, parent_lvl=None):
        if group_lvl == GroupLevel.METAGROUP:
            raise ValueError
        if parent_lvl is not None:
            if parent_lvl <= group_lvl:
                raise ValueError
        else:
            parent_lvl = group_lvl+1
        pass

    def has_parent_group(self, child_gid, parent_gid, child_lvl=GroupLevel.TEAM, parent_lvl=None):
        if child_lvl == GroupLevel.METAGROUP:
            raise ValueError
        if parent_lvl is not None:
            if parent_lvl <= child_lvl:
                raise ValueError
        else:
            parent_lvl = child_lvl+1

        db = self.env.get_read_db()
        cursor = call_db_func(db, 'check_group_has_parent', (
            child_gid, GL_MAP[child_lvl], parent_gid, GL_MAP[parent_lvl]))
        res = cursor.fetchone()[0]

        return res

    def get_child_groups(self, gid, group_lvl=GroupLevel.STUDGROUP, child_lvl=None):
        if group_lvl < GroupLevel.STUDGROUP:
            raise ValueError
        if child_lvl is not None:
            if child_lvl >= group_lvl:
                raise ValueError
        else:
            child_lvl = group_lvl-1
        pass

    def get_parent_group(self, gid, group_lvl=GroupLevel.TEAM, parent_lvl=None):
        if group_lvl == GroupLevel.METAGROUP:
            raise ValueError
        if parent_lvl is not None:
            if parent_lvl <= group_lvl:
                raise ValueError
        else:
            parent_lvl = group_lvl+1
        col     = GroupLevel.get_column(group_lvl)
        par_col = GroupLevel.get_column(parent_lvl)
        query = '''
            SELECT {parent_column}
            FROM group_hierarchy
            WHERE {column}=%s
        '''
        query = query.format(parent_column=par_col, column=col)

        db = self.env.get_read_db()
        cursor = db.cursor()
        res = cursor.execute(query, (gid))
        row = res.fetchone()
        return row[0]

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
        res = cursor.execute(query, (gid))
        rows = res.fetchall()
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
        res = cursor.execute(query, (gid))
        row = res.fetchone()
        return row[0]

    def get_user_group(self, user, group_lvl=GroupLevel.TEAM):
        pass

    def add_user_to_team(self, user, gid):
        pass

    def move_user_to_team(self, user, gid):
        pass

    def del_user_from_team(self, user, gid):
        pass

    tables = {
        GroupLevel.TEAM: {
            'tbl': 'teams',
            'rel': 'team_members'
        },
        GroupLevel.STUDGROUP: {
            'tbl': 'student_groups',
            'rel': 'teamgroup_rel'
        },
        GroupLevel.METAGROUP: {
            'tbl': 'metagroups',
            'rel': 'groupmeta_rel'
        },
    }

    def _process_query(self, query, group_lvl):
        if isinstance(group_lvl, int):
            multi = False
        else:
            multi = True

        kwargs = {}
        try:
            if multi:
                idx = 1
                for lvl in group_lvl:
                    kwargs['table_group_{0}'.format(idx)]    = self.tables[lvl]['tbl']
                    kwargs['table_relation_{0}'.format(idx)] = self.tables[lvl]['rel']
                    idx += 1
            else:
                kwargs['table_group']    = self.tables[lvl]['tbl']
                kwargs['table_relation'] = self.tables[lvl]['rel']
        except KeyError:
            raise UnknownGroupLevel

        return query.format(**kwargs)

