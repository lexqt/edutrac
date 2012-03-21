import pkg_resources
from datetime import datetime

from trac.util.translation import _, tag_
from trac.util.datefmt import utc

from trac.core import Component, implements
from trac.web.api import IRequestHandler
from trac.project.api import ProjectManagement
from trac.web.chrome import ITemplateProvider
from trac.perm import IPermissionRequestor
from trac.resource import get_resource_url
from trac.config import IntOption

from trac.evaluation.api import EvaluationManagement
from trac.evaluation.milestone import MilestoneEvaluation

import formencode
from formencode import validators, variabledecode
from trac.util.formencode_addons import EqualSet, make_plain_errors_list



class MilestoneUserEvalRow(formencode.Schema):

    target = validators.String(not_empty=True)
    value = validators.Int(not_empty=True, min=0)
    comment = validators.String(max=2000)

class MilestoneEvalFormValidator(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    team = ()
    sum = 0

    pre_validators = [variabledecode.NestedVariables()]
    chained_validators = []

    def __init__(self, *args, **kwargs):
        super(MilestoneEvalFormValidator, self).__init__(*args, **kwargs)
        self.pre_validators.append(TeamSetValidator(team_set=set(self.team)))
        self.chained_validators.append(ValuesSumValidator(sum=self.sum))

    devs = formencode.ForEach(MilestoneUserEvalRow())


class TeamSetValidator(validators.FormValidator):

    team_set = set()

    def validate_python(self, value, state):
        targets = [d['target'] for d in value['devs']]
        validator = EqualSet(equal_to_set=self.team_set)
        validator.validate_python(targets, state)

class ValuesSumValidator(validators.FormValidator):

    sum = 0

    messages = {
        'not_valid_sum': 'Sum of earned scores field must be %(sum)s',
    }

    def validate_python(self, value, state):
        sum = reduce(lambda s, r: s+r['value'], value['devs'], 0)
        if sum != self.sum:
            raise formencode.Invalid(self.message('not_valid_sum', state, sum=self.sum), sum, state)

_milestone_eval_labels = {
    'devs': _('Evaluation form'),
    'value': _('Earned score'),
    'comment': _('Comment'),
}



class EvaluationStatsModule(Component):

    implements(IPermissionRequestor, IRequestHandler, ITemplateProvider)

    permissions = ('EVAL_TEAM_MILESTONE',)

    def __init__(self):
        self.evmanager = EvaluationManagement(self.env)
        self.milestone_eval = MilestoneEvaluation(self.env)

    # IPermissionRequestor methods

    def get_permission_actions(self):
        return self.permissions

    # IRequestHandler methods
    
    def match_request(self, req):
        return req.path_info == '/eval'

    def process_request(self, req):
        pm = ProjectManagement(self.env)

        pid = pm.get_current_project(req)

        model = self.evmanager.get_model_by_project(pid)

        var1 = model.vars['test'].project(pid).user('dev1')
        var2 = model.vars['test'].project(pid)
        var3 = model.vars['milestone_grade'].project(pid).user('dev1').milestone('milestone1')
        var4 = model.vars['milestone_grade_self_weighted'].project(pid).user('dev1').milestone('milestone1')

        data = {
            'vars': [var1, var2, var3, var4],
        }

        return 'dummy.html', data, None

    # Outer handlers

    def team_milestone_eval(self, req, milestone):
        '''Handler for "teameval" action on milestone'''
        # TODO: differentiate user roles
        # now let it Developer
        req.perm.require('EVAL_TEAM_MILESTONE')
        
        completed = self.milestone_eval.get_completed(req.authname, milestone.pid, milestone.name)
        data = {
            'milestone': milestone,
        }

        subaction = req.args.get('subaction', 'view')
        is_new = completed is None
        edit = is_new or subaction == 'edit'
        if not is_new:
            complete, completed_on = completed
            if not complete:
                raise NotImplementedError
            data['completed_on'] = completed_on
        data.update({
            'is_new': is_new,
            'edit': edit,
        })

        # Save data or prepare errors to display
        if req.method == 'POST':
            self._prepare_milestone_eval_edit_data(req, milestone, data)
            cleaned_data, errs = self._fetch_and_validate_data(req, data)
            if not errs:
                cleaned_data.update({
                    'author': data['author'],
                    'milestone': milestone.name,
                    'project_id': milestone.pid,
                    'completed_on': datetime.now(utc),
                })
                self._save_milestone_eval(cleaned_data, is_new=is_new)
                req.redirect(req.href(get_resource_url(self.env, milestone.resource), action='teameval'))
            data.update({
                'edit': True,
                'errors': errs,
            })
        elif edit:
            self._prepare_milestone_eval_edit_data(req, milestone, data, is_existent=not is_new)
        else:
            self._prepare_milestone_eval_view_data(req, milestone, data)

        return 'milestone_eval.html', data, None

    #

    def _prepare_milestone_eval_view_data(self, req, milestone, data):
        res = self.milestone_eval.get_results_by_user(req.authname, milestone.pid, milestone.name)
        devs = data['devs'] = []
        for row in res:
            devs.append({
                'target': row['target'],
                'value': row['value'],
                'comment': row['comment'],
            })

    def _prepare_milestone_eval_edit_data(self, req, milestone, data, is_existent=False):
        pm = ProjectManagement(self.env)
        devs = pm.get_project_users(milestone.pid)
        syllabus_id = pm.get_project_syllabus(milestone.pid)
        sum = self.milestone_eval.milestone_eval_sum.syllabus(syllabus_id)
        data.update({
            'author': req.authname,
            'targets': devs,
            'sum': sum,
        })
        if not is_existent:
            return

        # Request args update for existent results 
        validator = MilestoneEvalFormValidator(team=devs, sum=sum)
        res = self.milestone_eval.get_results_by_user(req.authname, milestone.pid, milestone.name)
        args_upd = validator.from_python({'devs': res})
        req.args.update(args_upd)

    def _fetch_and_validate_data(self, req, data):
        errs = ()
        args = req.args
        devs = data['targets']
        sum = data['sum']
        validator = MilestoneEvalFormValidator(team=devs, sum=sum)
        try:
            cleaned_data = validator.to_python(args)
        except formencode.Invalid, e:
            cleaned_data = ()
            errs = e.unpack_errors()
            errs = make_plain_errors_list(errs, _milestone_eval_labels)
        return cleaned_data, errs

    def _save_milestone_eval(self, data, is_new):
        self.milestone_eval.save_results(data['author'], data['project_id'],
            data['milestone'], data['completed_on'], data['devs'], is_new=is_new)


    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        return []

    def get_templates_dirs(self):
        return [pkg_resources.resource_filename(__name__, 'templates')]


