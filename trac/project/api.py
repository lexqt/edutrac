from trac.core import Component, Interface, TracError
from trac.resource import GLOBAL_PID

from trac.project.model import ProjectNotSet, ResourceProjectMismatch
from trac.user.api import UserManagement, GroupLevel

from trac.config import ComponentDisabled

class IProjectSwitchListener(Interface):
    """Extension point interface for components which want to perform
    some action after project was chosen at logon or switched.
    """

    def project_switched(self, req, pid, old_pid):
        """Perform some action on project switch.
        
        `old_pid` may be None if project was chosen at logon.
        """
        raise NotImplementedError

class ProjectManagement(Component):
    """
    This class provides API to manage projects.
    """

    def __init__(self):
        self._proj_syl_cache = {}
        self._meta_syl_cache = {}

    def get_user_roles(self, username):
        db = self.env.get_read_db()
        cursor = db.cursor()

        roles = []

        # check for developer
        query = '''
            SELECT 1
            FROM membership
            WHERE username=%s AND team_id IS NOT NULL
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append((UserManagement.USER_ROLE_DEVELOPER, 'Developer'))

        # check for manager
        query = '''
            SELECT 1
            FROM project_managers pm JOIN users u
            ON u.id=pm.user_id
            WHERE u.username=%s
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append((UserManagement.USER_ROLE_MANAGER, 'Project manager'))

        # check for admin
        query = '''
            SELECT 1
            FROM permission
            WHERE username=%s AND action='TRAC_ADMIN'
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append((UserManagement.USER_ROLE_ADMIN, 'Administrator'))

        return roles

    def get_user_projects(self, username, role=UserManagement.USER_ROLE_DEVELOPER):
        db = self.env.get_read_db()
        cursor = db.cursor()

        if role == UserManagement.USER_ROLE_DEVELOPER:
            query = '''
                SELECT project_id, project_name
                FROM developer_projects
                WHERE username=%s
            '''
        elif role == UserManagement.USER_ROLE_MANAGER:
            query = '''
                SELECT project_id, project_name
                FROM manager_projects
                WHERE username=%s
            '''
        elif role == UserManagement.USER_ROLE_ADMIN:
            query = '''
                SELECT id project_id, name project_name
                FROM projects
            '''
        else:
            return ()

        cursor.execute(query, (username,))
        projects = cursor.fetchall()
        return projects

    def get_project_users(self, pid, role=UserManagement.USER_ROLE_DEVELOPER):
        db = self.env.get_read_db()
        cursor = db.cursor()

        if role == UserManagement.USER_ROLE_DEVELOPER:
            table = 'developer_projects'
        elif role == UserManagement.USER_ROLE_MANAGER:
            table = 'manager_projects'
        else:
            return ()
        q = '''
            SELECT username
            FROM {table}
            WHERE project_id=%s
        '''.format(table=table)

        cursor.execute(q, (pid,))
        users = cursor.fetchall()
        if not users:
            return ()
        users = [u[0] for u in users]
        users.sort()
        return users

    def get_current_project(self, req, err_msg=None, fail_on_none=True, _return_is_session=False):
        pid = req.args.getint('__pid__')
        is_session = False # is pid got from session

        if pid is None:
            msg = err_msg or 'Can not get neither request, nor session project variable'
            pid = self.get_session_project(req, err_msg=msg, fail_on_none=fail_on_none)
            is_session = True

        if _return_is_session:
            return pid, is_session
        return pid

    def get_session_project(self, req, err_msg=None, fail_on_none=True):
        if req.session_project is None:
            if fail_on_none:
                msg = err_msg or 'Can not get session project variable'
                raise ProjectNotSet(msg)
            else:
                return None
        return req.session_project

    def check_session_project(self, req, pid, allow_multi=False, fail_on_false=True):
        pid = int(pid)
        if pid == GLOBAL_PID:
            return True
        if allow_multi and 'MULTIPROJECT_ACTION' in req.perm:
            check = pid in req.user_projects
        else:
            check = pid == self.get_session_project(req)
        if fail_on_false and not check:
            raise ResourceProjectMismatch('You have not enough rights in project #%s.' % pid)
        return check

    def get_and_check_current_project(self, req, err_msg_on_get=None, allow_multi=False):
        pid, is_session = self.get_current_project(req, err_msg=err_msg_on_get, fail_on_none=True, _return_is_session=True)
        if not is_session:
            self.check_session_project(req, pid, allow_multi=allow_multi, fail_on_false=True)
        return pid

    def get_project_syllabus(self, pid, fail_on_none=True):
        pid = int(pid)
        if pid not in self._proj_syl_cache:
            s = self._get_syllabus(pid=pid)
            self._proj_syl_cache[pid] = s
        if fail_on_none and self._proj_syl_cache[pid] is None:
            raise TracError('Project #%s is not associated with any syllabus' % pid)
        return self._proj_syl_cache[pid]

    def get_group_syllabus(self, gid, fail_on_none=True):
        meta_gid = UserManagement(self.env).get_parent_group(
                            gid, group_lvl=GroupLevel.STUDGROUP, parent_lvl=GroupLevel.METAGROUP)
        if fail_on_none and meta_gid is None:
            raise TracError('Group #%s is not associated with any metagroup' % gid)
        return self.get_metagroup_syllabus(meta_gid, fail_on_none)

    def get_metagroup_syllabus(self, gid, fail_on_none=True):
        gid = int(gid)
        if gid not in self._meta_syl_cache:
            s = self._get_syllabus(metagroup_id=gid)
            self._meta_syl_cache[gid] = s
        if fail_on_none and self._meta_syl_cache[gid] is None:
            raise TracError('Metagroup #%s is not associated with any syllabus' % gid)
        return self._meta_syl_cache[gid]

    def get_project_info(self, pid, fail_on_none=True):
        """Returns dict (active, team_id, studgroup_id, metagroup_id, syllabus_id)
        """
        db = self.env.get_read_db()
        cursor = db.cursor()
        query = '''
            SELECT active, team_id, studgroup_id, metagroup_id, syllabus_id
            FROM project_info
            WHERE project_id=%s
        '''
        cursor.execute(query, (pid,))
        values = cursor.fetchone()
        if values is None:
            if fail_on_none:
                raise TracError('Project #%s is not associated with any syllabus / group info' % pid)
            else:
                return None
        from trac.db.api import get_column_names
#        names  = [r[0] for r in cursor.description]
        names  = get_column_names(cursor)
        return dict(zip(names, values))

    def check_component_enabled(self, component, pid=None, syllabus_id=None, raise_on_disabled=True):
        if pid is not None:
            syllabus_id = self.get_project_syllabus(pid)
        assert syllabus_id is not None
        if not isinstance(component, type):
            component = component.__class__
        res = self.compmgr.is_component_enabled(component, syllabus=syllabus_id)
        if raise_on_disabled and not res:
            raise ComponentDisabled('Component "%s" is disabled in the syllabus #%s.' %
                                    (component.__name__, syllabus_id))
        return res


    # Internal methods

    def _get_syllabus(self, pid=None, metagroup_id=None):
        if pid is not None:
            query = '''
                SELECT syllabus_id
                FROM project_info
                WHERE project_id=%s
            '''
            id_ = pid
        elif metagroup_id is not None:
            query = '''
                SELECT syllabus_id
                FROM metagroup_syllabus_rel
                WHERE metagroup_id=%s
            '''
            id_ = metagroup_id
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, (id_,))
        row = cursor.fetchone()
        return row and row[0]

