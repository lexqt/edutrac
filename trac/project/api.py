from trac.config import Option, ExtensionOption
from trac.perm import IPermissionGroupProvider
from trac.db import with_transaction, call_db_func
from argparse import ArgumentError


from trac.core import Component, ExtensionPoint, Interface, implements, TracError
from trac.resource import IResourceManager
from trac.web.main import IRequestHandler, IRequestFilter

from trac.web import chrome
from trac.web.chrome import INavigationContributor

from genshi.core import Markup
from genshi.builder import tag
from trac.project.model import ProjectNotSet

import re

USER_ROLE_DEVELOPER = 1
USER_ROLE_MANAGER   = 2
USER_ROLE_ADMIN     = 3

STEP_SET_ROLE    = 1
STEP_SET_PROJECT = 10

STEP_INIT         = STEP_SET_ROLE

class IProjectSwitchListener(Interface):
    """Extension point interface for components which want to perform
    some action after project was chosen at logon or switched.
    """

    def project_switched(req, pid, old_pid):
        """Perform some action on project switch.
        
        `old_pid` may be None if project was chosen at logon.
        """


class PostloginModule(Component):
    """
    Module for control session variables setup
    """

    project_switch_listeners = ExtensionPoint(IProjectSwitchListener)

    implements(INavigationContributor, IRequestHandler, IRequestFilter)

    def __init__(self):
        self.pm = ProjectManagement(self.env)
    
#    # IResourceManager methods
#
#    def get_resource_realms(self):
#        yield 'project'
#
#    def get_resource_description(self, resource, format=None, **kwargs):
#        return 'Project %s' % resource.id
#
#    def resource_exists(self, resource):
#        db = self.env.get_read_db()
#        cursor = db.cursor()
#        cursor.execute('SELECT 1 FROM projects WHERE id=%s LIMIT 1',
#                       (resource.id,))
#        return bool(cursor.rowcount)

    #INavigationContributor

    def get_active_navigation_item(self, req):
        pass

    def get_navigation_items(self, req):
        if req.session.authenticated:
            yield ('metanav', 'changeproject',
                   tag.a("Change project", href=req.href.postlogin(step=STEP_SET_PROJECT))
                  )

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        # TODO: remove this, only for tracd deployment
        if req.path_info.startswith('/chrome/'):
            return handler

        s = req.session
        if not s.authenticated:
            return handler

        if self._postlogin_passed(req) or\
                req.path_info == '/login' or\
                req.path_info == '/postlogin':
            return handler
        if req.path_info == '/logout':
            for key in ('postlogin', 'postlogin_step'):
                if key in s:
                    s.pop(key, None)
            return handler

        req.redirect(req.href.postlogin(force=1))

    def post_process_request(self, req, template, data, content_type):
        return template, data, content_type

    # IRequestHandler methods

    def match_request(self, req):
        return req.path_info == '/postlogin'

    def process_request(self, req):
        if not req.session.authenticated:
            chrome.add_warning(req, Markup(tag.span(
                "Please log in first.")))
            req.redirect(req.href.login())

        s = req.session

        step_arg  = req.args.getint('step')
        force = 'force' in req.args
        change_param = step_arg is not None and self._postlogin_passed(req)
        if force:
            step = s['postlogin_step'] = STEP_INIT
        elif change_param:
            step = s['postlogin_step'] = step_arg
        else:
            step = int(s.get('postlogin_step', STEP_INIT))

        data = {}
        data['finalize'] = False

        def step_preprocess(step):
            if step == STEP_SET_ROLE:
                data['roles']    = self.pm.get_user_roles(req.authname)
                if not data['roles']:
                    chrome.add_warning(req, 'User has no roles. Can not continue login.')
                    req.redirect(req.href.logout())
            elif step == STEP_SET_PROJECT:
                role = int(s['role'])
#                if role not in (USER_ROLE_DEVELOPER, USER_ROLE_MANAGER):
#                    data['finalize'] = True
#                else:
                data['projects'] = self.pm.get_user_projects(req.authname, role)

        step_preprocess(step)

        if req.method == 'POST':
            if step == STEP_SET_ROLE and 'role' in req.args:
                role = int(req.args['role'])
                if role not in [rid for rid, rname in data['roles']]:
                    chrome.add_warning(req, 'Select role from availables only!')
                    req.redirect(req.href.postlogin())
                step = STEP_SET_PROJECT
                s['role']           = role
                s['postlogin_step'] = step
                step_preprocess(step)
            elif step == STEP_SET_PROJECT and 'project' in req.args:
                project_id = int(req.args['project'])
                if project_id not in [pid for pid, pname in data['projects']]:
                    chrome.add_warning(req, 'Select project from availables only!')
                    req.redirect(req.href.postlogin())
                info = self.pm.get_project_info(project_id, fail_on_none=True)
                old_project_id = s.get('project') if not s.get('postlogin_change_param') else None
                old_project_id = int(old_project_id) if old_project_id is not None else None
                s['project']  = project_id
                s['syllabus'] = info['syllabus_id']
                s['project_team']      = info['team_id']
                s['project_studgroup'] = info['studgroup_id']
                s['project_metagroup'] = info['metagroup_id']
                data['finalize'] = True
                for listener in self.project_switch_listeners:
                    listener.project_switched(req, project_id, old_project_id)

            if s.get('postlogin_change_param'):
                s.pop('postlogin_change_param', None)
                data['finalize'] = True

        if data['finalize']:
            s['postlogin'] = req.incookie['trac_auth'].value
            s.pop('postlogin_step', None)
            req.redirect(req.href())

        # next POST request will be the last
        if change_param:
            s['postlogin_change_param'] = True

        data['step']        = step
        data['set_role']    = STEP_SET_ROLE
        data['set_project'] = STEP_SET_PROJECT
        return 'postlogin.xhtml', data, None

    # Internals methods

    def _postlogin_passed(self, req):
        pl_attr = req.session.get('postlogin', '')
        sid = 'trac_auth' in req.incookie and req.incookie['trac_auth'].value
        return pl_attr == sid


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
            roles.append((USER_ROLE_DEVELOPER, 'Developer'))

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
            roles.append((USER_ROLE_MANAGER, 'Project manager'))

        # check for admin
        query = '''
            SELECT 1
            FROM permission
            WHERE username=%s AND action='TRAC_ADMIN'
            LIMIT 1
        '''
        cursor.execute(query, (username,))
        if cursor.rowcount:
            roles.append((USER_ROLE_ADMIN, 'Administrator'))

        return roles

    def get_user_projects(self, username, role=USER_ROLE_DEVELOPER):
        db = self.env.get_read_db()
        cursor = db.cursor()

        if role == USER_ROLE_DEVELOPER:
            query = '''
                SELECT project_id, project_name
                FROM developer_projects
                WHERE username=%s
            '''
        elif role == USER_ROLE_MANAGER:
            query = '''
                SELECT project_id, project_name
                FROM manager_projects
                WHERE username=%s
            '''
        elif role == USER_ROLE_ADMIN:
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

