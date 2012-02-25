import re

from trac.core import Component, Interface, TracError

from trac.project.model import ProjectNotSet
from trac.user.api import UserManagement


class IProjectSwitchListener(Interface):
    """Extension point interface for components which want to perform
    some action after project was chosen at logon or switched.
    """

    def project_switched(req, pid, old_pid):
        """Perform some action on project switch.
        
        `old_pid` may be None if project was chosen at logon.
        """

class ProjectManagement(Component):
    """
    This class implements API to manage projects.
    """

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

    def get_session_project(self, req, err_msg=None):
        s = req.session
        if 'project' not in s:
            msg = err_msg or 'Can not get session project variable'
            raise ProjectNotSet(msg)
        return int(s['project'])

    def check_session_project(self, req, pid):
        cur_pid = self.get_session_project(req)
        pid     = int(pid)
        return cur_pid == pid

    # optional req argument for per-request cache
    # TODO: per-env cache?
    def get_project_syllabus(self, pid, req=None, fail_on_none=False):
        pid = int(pid)
        if req is None or pid not in req._proj_syl_cache:
            s = self._get_syllabus(pid)
            if req is None:
                return s
            req._proj_syl_cache[pid] = s
        if fail_on_none and req._proj_syl_cache[pid] is None:
            raise TracError('Project #%s is not associated with any syllabus' % pid)
        return req._proj_syl_cache[pid]

    def get_project_info(self, pid, fail_on_none=False):
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
        names  = [r[0] for r in cursor.description]
        return dict(zip(names, values))

    # Internal methods

    def _get_syllabus(self, pid):
        db = self.env.get_read_db()
        cursor = db.cursor()
        query = '''
            SELECT syllabus_id
            FROM project_info
            WHERE project_id=%s
        '''
        cursor.execute(query, (pid,))
        row = cursor.fetchone()
        return row and row[0]

