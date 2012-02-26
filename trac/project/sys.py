import re

from trac.core import Component, implements, ExtensionPoint
from trac.perm import IPermissionRequestor
from trac.web.main import IRequestHandler, IRequestFilter

from trac.web import chrome
from trac.web.chrome import INavigationContributor
from genshi.core import Markup
from genshi.builder import tag

from trac.project.api import IProjectSwitchListener, ProjectManagement


class ProjectSystem(Component):
    """
    Project Management core component
    """

    implements(IPermissionRequestor)

    permissions = ('MULTIPROJECT_ACTION',)

    def __init__(self):
        pass

    # IPermissionRequestor methods

    def get_permission_actions(self):
        return self.permissions

    # Request init methods

    def init_request(self, req):
        self.extract_project_id(req)
        req._proj_syl_cache = {} # project_id: syllabus_id

    def extract_project_id(self, req):
        match = re.match(r'(.*)/project/(\d+)/?(.*)$', req.path_info)
        if match:
            req.args['pid'] = int(match.group(2))
            req.environ['PATH_INFO'] = str(match.group(1) + '/' + match.group(3)).rstrip('/')
            return True
        return False

    # Request callbacks methods

    def get_session_user_projects(self, req):
        return [int(pid) for pid in req.session.get('projects', '').split()]

    def get_session_project(self, req):
        s = req.session
        if 'project' not in s:
            return None
        return int(s['project'])


STEP_SET_ROLE    = 1
STEP_SET_PROJECT = 10

STEP_INIT         = STEP_SET_ROLE


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
                multiproject = 'MULTIPROJECT_ACTION' in req.perm
                if multiproject:
                    s['projects'] = ' '.join([str(p[0]) for p in data['projects']])
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
        return 'postlogin.html', data, None

    # Internals methods

    def _postlogin_passed(self, req):
        pl_attr = req.session.get('postlogin', '')
        sid = 'trac_auth' in req.incookie and req.incookie['trac_auth'].value
        return pl_attr == sid

