import pkg_resources
from collections import OrderedDict

from trac.util.translation import _
from trac.util.text import exception_to_unicode

from genshi.builder import tag

from trac.core import Component, implements, TracError
from trac.web.api import IRequestHandler
from trac.project.api import ProjectManagement
from trac.web.chrome import ITemplateProvider, INavigationContributor, add_warning
from trac.perm import IPermissionRequestor

from trac.evaluation.api import EvaluationManagement
from trac.evaluation.api.model import EvalModelError

from trac.evaluation.project import ProjectEvaluation


class EvaluationStatsModule(Component):

    implements(IPermissionRequestor, IRequestHandler, ITemplateProvider, INavigationContributor)

    permissions = ('EVAL_VIEW', 'EVAL_DEBUG_VAR')

    def __init__(self):
        self.pm = ProjectManagement(self.env)
        self.evmanager = EvaluationManagement(self.env)

    # IPermissionRequestor

    def get_permission_actions(self):
        return self.permissions

    # INavigationContributor

    def get_active_navigation_item(self, req):
        action = req.args.get('action', 'project')
        if action == 'project':
            return 'project_eval'
        elif action == 'individual':
            return 'individual_eval'
        elif action == 'debug_var':
            return 'debug_eval_var'

    def get_navigation_items(self, req):
        if 'EVAL_VIEW' not in req.perm:
            return
        yield ('mainnav', 'project_eval', 
               tag.a(_('Project evaluation'), href=req.href.eval(action='project')))
        yield ('mainnav', 'individual_eval', 
               tag.a(_('Individual evaluation'), href=req.href.eval(action='individual')))
        if 'EVAL_DEBUG_VAR' in req.perm:
            yield ('mainnav', 'debug_eval_var', 
                   tag.a(_('Debug eval var'), href=req.href.eval(action='debug_var')))

    # IRequestHandler
    
    def match_request(self, req):
        return req.path_info == '/eval'

    def process_request(self, req):
        req.perm.require('EVAL_VIEW')

        # check project
        _pid = self.pm.get_current_project(req)

        action = req.args.get('action', 'project')

        if action == 'debug_var':
            return self._do_debug_eval_var(req)
        elif action == 'individual':
            return self._do_individual_eval(req)
        elif action == 'project':
            return ProjectEvaluation(self.env).do_project_eval(req)

    def _do_debug_eval_var(self, req):
        req.perm.require('EVAL_DEBUG_VAR')

        var_name      = req.args.get('var_name')
        var_project   = req.args.getint('var_project')
        var_username  = req.args.get('var_username')
        var_milestone = req.args.get('var_milestone')

        do_not_process = req.args.getbool('do_not_process', False)

        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        all_vars = model.vars.all()
        all_vars = sorted(all_vars, key=lambda v: v.label)
        var = None
        var_value = None

        if not do_not_process and var_name:
            if var_project is None:
                raise TracError(_('Variable project ID undefined'))
            psyll = self.pm.get_project_syllabus(var_project)
            if psyll != syllabus_id:
                raise TracError(_('Current syllabus and requested project syllabus are mismatching. '
                                  'Try to switch current session project.'))
            self.pm.check_session_project(req, var_project)
            if var_name in model.vars:
                var = model.vars[var_name]
                var.project(var_project)
                if var_username:
                    var.user(var_username)
                if var_milestone:
                    var.milestone(var_milestone)
            else:
                add_warning(req, _('Unknown variable %(var_name)s', var_name=var_name))

        if var:
            # try to get var value here to prevent
            # unhandled exception in template
            try:
                var_value = var.get()
            except EvalModelError, e:
                add_warning(req, exception_to_unicode(e))

        data = {
            'var_name': var_name,
            'all_vars': all_vars,
            'var_project': var_project,
            'var_username': var_username,
            'var_milestone': var_milestone,
            'var': var,
            'var_value': var_value,
        }

        return 'show_var.html', data, None

    def _do_individual_eval(self, req):
        data = {}
        syllabus_id = req.data['syllabus_id']
        project_id  = req.data['project_id']

        users = self.pm.get_project_users(project_id)
        model = self.evmanager.get_model(syllabus_id)
        user_vars = model.get_individual_rating_vars()

        ivalues = OrderedDict()
        for var in user_vars:
            uvalues = OrderedDict()
            var.project(project_id)
            for user in users:
                try:
                    var.user(user)
                    var_value = var.get()
                except EvalModelError, e:
                    var_value = e.message
                uvalues[user] = var_value
            ivalues[var] = uvalues

        if req.authname in users:
            data['current_user'] = req.authname

        data.update({
            'users': users,
            'user_vars': ivalues,
        })
        return 'individual_eval.html', data, None

    # ITemplateProvider

    def get_htdocs_dirs(self):
        return []

    def get_templates_dirs(self):
        return [pkg_resources.resource_filename(__name__, 'templates')]
