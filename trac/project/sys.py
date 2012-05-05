import re

from trac.core import Component, implements, ExtensionPoint, TracError
from trac.web.main import IRequestHandler, IRequestFilter

from trac.web import chrome
from genshi.core import Markup
from genshi.builder import tag
from trac.util.translation import _, tag_
from trac.util.text import exception_to_unicode
from trac.web.chrome import add_warning

from trac.project.api import IProjectSwitchListener, ProjectManagement


class ProjectSystem(Component):
    """
    Project Management core component
    """

#    implements(IPermissionRequestor)

#    permissions = ('MULTIPROJECT_ACTION',)

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # IPermissionRequestor methods

#    def get_permission_actions(self):
#        return self.permissions

    # Request init methods

    def init_request(self, req):
        self.extract_project_id(req)

    def extract_project_id(self, req):
        '''Extracts project ID from URL.
        To form such URL you need place '/project/<id>' in the beginning of URL.
        '''
        match = re.match(r'/project/(\d+)/?(.*)$', req.path_info)
        if match:
#            pre  = match.group(1)
            post = match.group(2)
            pid  = match.group(1)
#            if pre and post:
#                # 'project' in the middle
#                return False
            req.data['project_id'] = int(pid)
            req.environ['PATH_INFO'] = unicode('/' + post).rstrip('/').encode('utf-8')
            return True
        return False

    # Request callbacks methods

    def get_session_user_projects(self, req):
        if req.data.get('force_httpauth'):
            return [req.session_project]
        return [int(pid) for pid in req.session.get('projects', '').split()]

    def get_session_project(self, req):
        '''Return current session project ID'''
        if req.data.get('force_httpauth'):
            return req.data['project_id']
        s = req.session
        if 'project' not in s:
            return None
        return int(s['project'])

    # API

    def set_request_data(self, req, project_id):
        '''Set project info data for current request.
        Other components consider this data as reliable and
        can use it directly without preliminary check.
        But they must check if 'project_id' in req.data.
        If True, then all project info keys are in data.
        '''
        if not req.session.authenticated:
            return False
        try:
            info = self.pm.get_project_info(project_id, fail_on_none=True)
        except TracError, e:
            add_warning(req, exception_to_unicode(e))
            req.session.pop('postlogin', None)
            req.redirect(req.href.postlogin(force=1))
        # see `ProjectManagement.get_project_info` for list of info keys
        req.data.update(info)


STEP_SET_ROLE    = 1
STEP_SET_PROJECT = 10

STEP_INIT         = STEP_SET_ROLE


class PostloginModule(Component):
    """
    Module for control session variables setup
    """

    project_switch_listeners = ExtensionPoint(IProjectSwitchListener)

    implements(IRequestHandler, IRequestFilter)

    def __init__(self):
        self.pm = ProjectManagement(self.env)
        self.ps = ProjectSystem(self.env)
    
    def project_switch_url(self, href):
        return href.postlogin(step=STEP_SET_PROJECT)

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        # TODO: remove this, only for tracd deployment
        if req.path_info.startswith('/chrome/'):
            return handler

        s = req.session
        if not s.authenticated:
            if 'project_id' in req.data:
                # specified in url
                req.redirect(req.href.login())
            return handler

        if req.data.get('force_httpauth'):
            return handler

        if self._postlogin_passed(req):
            # session user project and projects are ready

            # set and check project_id
            spid = req.session_project
            pid = spid
            check = True
            if 'project_id' in req.data:
                # project extracted from URL
                upid = req.data['project_id']
                if spid != upid:
                    # check user rights
                    check = self.pm.check_session_project(req, upid, fail_on_false=False)
                    # substitute session project, force url rewrite
                    pid = upid
                    if check:
                        req.href = req.project_href
            # else use session project

            if not check:
                # revert pid to session
                failed_pid = pid
                pid = spid

            # set project data
            self.ps.set_request_data(req, pid)
            req.data['role'] = s['role']

            if not check:
                # now raise exception
                self.pm.check_session_project(req, failed_pid, fail_on_false=True)

            return handler
        if req.path_info in ('/login', '/postlogin'):
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
                tag_('Please log in first.'))))
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
                    raise TracError(tag(tag_(
                        'User has no roles. Can not continue login.'
                        ' You may %(logout)s to continue work as anonymous user.',
                        logout=tag.a(_('logout'), href=req.href.logout())
                    )))
            elif step == STEP_SET_PROJECT:
                role = int(s['role'])
                data['projects'] = self.pm.get_user_projects(req.authname, role)
                if req.method != 'POST':
                    prev_project_id = s.get('project')
                    data['prev_project'] = int(prev_project_id) if prev_project_id is not None else None
                    cur_pid = req.data.get('project_id')
                    if not cur_pid:
                        return
                    data.update({
                        'current_project': cur_pid,
                        'current_project_name': req.data['project_name'],
                    })

        step_preprocess(step)

        if req.method == 'POST':
            if step == STEP_SET_ROLE and 'role' in req.args:
                role = int(req.args['role'])
                if role not in [rid for rid, rname in data['roles']]:
                    chrome.add_warning(req, _('Select role from availables only!'))
                    req.redirect(req.href.postlogin())
                step = STEP_SET_PROJECT
                s['role']           = role
                s['postlogin_step'] = step
                step_preprocess(step)
            elif step == STEP_SET_PROJECT and 'project' in req.args:
                project_id = int(req.args['project'])
                if project_id not in [pid for pid, pname in data['projects']]:
                    chrome.add_warning(req, _('Select project from availables only!'))
                    req.redirect(req.href.postlogin())
                old_project_id = s.get('project') if not s.get('postlogin_change_param') else None
                old_project_id = int(old_project_id) if old_project_id is not None else None
                s['project']  = project_id
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
            req.href.project_id = None
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

