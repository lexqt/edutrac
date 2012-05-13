import threading

from trac.core import Component, Interface, TracError
from trac.resource import GLOBAL_PID, ResourceNotFound

from trac.user.api import UserManagement, GroupLevel, UserRole

from trac.config import ComponentDisabled
from trac.util.translation import _, N_

# init sqlalchemy models
from trac.project.model import *
from trac.user.model import Metagroup, Group



class ProjectNotSet(TracError):
    """Exception that indicates project hasn't set"""

    title = N_('Can not determine current project')


class ProjectMismatch(TracError):
    """Exception that indicates suppressed access to resource of another project"""

    title = N_('No access to resources of requested project')


class SyllabusMismatch(TracError):
    """Exception that indicates suppressed access to resource of another syllabus"""

    title = N_('No access to resources of requested syllabus')


class ProjectNotFound(ResourceNotFound):
    """Thrown when a non-existent project is requested"""



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
        self._syl_cache_lock = threading.Lock()
        self._proj_syl_cache = {}
        self._meta_syl_cache = {}

    def get_user_roles(self, username):
        db = self.env.get_read_db()
        cursor = db.cursor()

        roles = []

        # check for developer
        query = '''
            SELECT 1
            FROM developer_projects
            WHERE username=%s
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append(UserRole.DEVELOPER)

        # check for manager
        query = '''
            SELECT 1
            FROM manager_projects
            WHERE username=%s
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append(UserRole.MANAGER)

        # check for admin
        query = '''
            SELECT 1
            FROM permission
            WHERE username=%s AND action='TRAC_ADMIN'
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append(UserRole.ADMIN)

        return roles

    def get_user_projects(self, username, role=UserRole.DEVELOPER, with_names=False):
        db = self.env.get_read_db()
        cursor = db.cursor()

        # TODO: do not query name if not with_names
        if role == UserRole.DEVELOPER:
            query = '''
                SELECT project_id, project_name
                FROM developer_projects
                WHERE username=%s
            '''
        elif role == UserRole.MANAGER:
            query = '''
                SELECT project_id, project_name
                FROM manager_projects
                WHERE username=%s
            '''
        elif role == UserRole.ADMIN:
            query = '''
                SELECT id project_id, name project_name
                FROM projects
            '''
        else:
            return ()

        cursor.execute(query, (username,))
        projects = cursor.fetchall()
        if with_names:
            return projects
        return [r[0] for r in projects]

    def get_project_users(self, pid, role=UserRole.DEVELOPER):
        db = self.env.get_read_db()
        cursor = db.cursor()

        if role == UserRole.DEVELOPER:
            table = 'developer_projects'
        elif role == UserRole.MANAGER:
            table = 'manager_projects'
        else:
            return []
        q = '''
            SELECT username
            FROM {table}
            WHERE project_id=%s
        '''.format(table=table)

        cursor.execute(q, (pid,))
        users = cursor.fetchall()
        if not users:
            return []
        users = [u[0] for u in users]
        users.sort()
        return users

    def get_project_user_count(self, pid, role=UserRole.DEVELOPER):
        db = self.env.get_read_db()
        cursor = db.cursor()

        if role == UserRole.DEVELOPER:
            table = 'developer_projects'
        elif role == UserRole.MANAGER:
            table = 'manager_projects'
        else:
            return 0
        q = '''
            SELECT COUNT(*)
            FROM {table}
            WHERE project_id=%s
        '''.format(table=table)

        cursor.execute(q, (pid,))
        cnt = cursor.fetchone()[0]
        return cnt

    def get_current_project(self, req, err_msg=None, fail_on_none=True):
        '''Wrapper func to get project_id from req.data or optionally raise error on None'''

        pid = req.data.get('project_id')

        if fail_on_none and pid is None:
            msg = err_msg or _('Project ID is undefined (neither URL, nor session)')
            raise ProjectNotSet(msg)

        return pid

    def get_session_project(self, req, err_msg=None, fail_on_none=True):
        '''Wrapper func to get project_id from session or optionally raise error on None'''
        if fail_on_none and req.session_project is None:
            msg = err_msg or _('Can not get project ID from session. Are you logged on?')
            raise ProjectNotSet(msg)
        return req.session_project

    def check_session_project(self, req, pid, allow_multi=True, fail_on_false=True):
        pid = int(pid)
        if pid == GLOBAL_PID:
            return True
        if allow_multi:
            check = pid in req.user_projects
        else:
            check = pid == self.get_session_project(req)
        if fail_on_false and not check:
            raise ProjectMismatch(_('You have not enough rights in project #%(pid)s.', pid=pid))
        return check

    def get_project_syllabus(self, pid, fail_on_none=True):
        pid = int(pid)
        db = self.env.get_read_db() # #4465
        with self._syl_cache_lock:
            if pid not in self._proj_syl_cache:
                s = self._get_syllabus(pid=pid, db=db)
                self._proj_syl_cache[pid] = s
            s = self._proj_syl_cache[pid]
        if fail_on_none and s is None:
            raise TracError(_('Project #%(pid)s is not associated with any syllabus', pid=pid))
        return s

    def get_group_syllabus(self, gid, fail_on_none=True):
        session = self.env.get_sa_session()
        meta_gid = session.query(Metagroup.id).outerjoin(Group, Metagroup.groups).\
                           filter(Group.id==gid).scalar()
        if fail_on_none and meta_gid is None:
            raise TracError(_('Group #%(gid)s is not associated with any metagroup', gid=gid))
        return self.get_metagroup_syllabus(meta_gid, fail_on_none)

    def get_metagroup_syllabus(self, gid, fail_on_none=True):
        gid = int(gid)
        db = self.env.get_read_db() # #4465
        with self._syl_cache_lock:
            if gid not in self._meta_syl_cache:
                s = self._get_syllabus(metagroup_id=gid, db=db)
                self._meta_syl_cache[gid] = s
            s = self._meta_syl_cache[gid]
        if fail_on_none and s is None:
            raise TracError(_('Metagroup #%(gid)s is not associated with any syllabus', gid=gid))
        return s

    def get_project_info(self, pid, fail_on_none=True):
        """Returns dict (project_id, project_active, project_name, project_description,
                         team_id, group_id, metagroup_id, syllabus_id)
        """
        db = self.env.get_read_db()
        cursor = db.cursor()
        query = '''
            SELECT project_id, active AS project_active, project_name, project_description,
                   team_id, group_id AS group_id, metagroup_id, syllabus_id
            FROM project_info
            WHERE project_id=%s
        '''
        cursor.execute(query, (pid,))
        values = cursor.fetchone()
        if values is None:
            if fail_on_none:
                raise TracError(_('Project #%(pid)s is not associated with any syllabus / group info', pid=pid))
            else:
                return None
        from trac.db.api import get_column_names
        names  = get_column_names(cursor)
        return dict(zip(names, values))

    def get_syllabus_projects(self, syllabus_id, with_names=False):
        '''Return all projects connected with specified syllabus'''
        return self._get_projects('syllabus_id', syllabus_id, with_names)

    def get_metagroup_projects(self, gid, with_names=False):
        '''Return all projects connected with specified syllabus'''
        return self._get_projects('metagroup_id', gid, with_names)

    def get_group_projects(self, gid, with_names=False):
        '''Return all projects connected with specified group'''
        return self._get_projects('group_id', gid, with_names)

    def _get_projects(self, column, id, with_names=False):
        '''Return all projects from `project_info` view
        with constraint `column`=`id`.
        '''
        db = self.env.get_read_db()
        cursor = db.cursor()
        query = '''
            SELECT project_id{0}
            FROM project_info
            WHERE {1}=%s
            ORDER BY project_id
        '''
        query = query.format(', project_name' if with_names else '',
                             db.quote(column))
        cursor.execute(query, (id,))
        rows = cursor.fetchall()
        if with_names:
            return [(r[0], r[1]) for r in rows]
        else:
            return [r[0] for r in rows]

    def has_role(self, username, role, obj_id=None):
        '''Return whether `username` has `role`.
        If `obj_id` is specified, check that user has this role for some object.
        Object meaning may vary according to concrete role:
         * Developer / Project manager - project
         * Group manager - group
        '''
        if role == UserRole.MANAGER:
            role = UserRole.GROUP_MANAGER
        if role not in (UserRole.DEVELOPER, UserRole.GROUP_MANAGER, UserRole.PROJECT_MANAGER):
            obj_id = None
        if obj_id is None:
            # TODO: make it more efficient...
            return role in self.get_user_roles(username)
        if role == UserRole.DEVELOPER:
            # TODO: make it more efficient...
            return obj_id in self.get_user_projects(username, role)
        elif role == UserRole.GROUP_MANAGER:
            return self.has_group_manager(username, obj_id)
        elif role == UserRole.PROJECT_MANAGER:
            # TODO: make it more efficient...
            return obj_id in self.get_user_projects(username, UserRole.MANAGER)

        return False

    def has_group_manager(self, username, gid):
        '''Return whether username is manager of group with id=`gid`'''
        db = self.env.get_read_db()
        cursor = db.cursor()
        q = '''
            SELECT 1
            FROM group_managers m
            JOIN users u ON u.id=m.user_id AND u.username=%s
            WHERE m.group_id=%s
            LIMIT 1
        '''
        cursor.execute(q, (username, gid))
        return cursor.rowcount==1

    def check_component_enabled(self, component, pid=None, syllabus_id=None, raise_on_disabled=True):
        if pid is not None:
            syllabus_id = self.get_project_syllabus(pid)
        assert syllabus_id is not None
        if not isinstance(component, type):
            component = component.__class__
        res = self.compmgr.is_component_enabled(component, syllabus=syllabus_id)
        if raise_on_disabled and not res:
            raise ComponentDisabled(_('Component "%(cname)s" is disabled in your syllabus #%(sid)s.',
                                    cname=component.__name__, sid=syllabus_id))
        return res

    def redirect_to_project(self, req, project_id):
        q = req.query_string
        if q:
            q = req.path_info+'?'+q
        else:
            q = req.path_info
        url = req.href.copy_for_project(project_id) + q
        req.redirect(url)

    # Internal methods

    def _get_syllabus(self, pid=None, metagroup_id=None, db=None):
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
        if db is None:
            db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(query, (id_,))
        row = cursor.fetchone()
        return row and row[0]

