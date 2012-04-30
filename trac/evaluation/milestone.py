from datetime import datetime
from collections import OrderedDict
from sqlalchemy import text
from random import shuffle

from trac.util.datefmt import utc
from trac.util.translation import _, N_

from trac.core import Component, implements, TracError
from trac.config import IntOption
from trac.resource import get_resource_url
from trac.perm import IPermissionRequestor

from trac.web.chrome import add_ctxtnav, add_warning, add_notice, \
                            add_stylesheet, Chrome

from trac.project.api import ProjectManagement
from trac.user.api import UserRole
from trac.evaluation.api.components import EvaluationManagement
from trac.evaluation.api import EvalModelError, SubjectArea

import formencode
from formencode import validators, variabledecode
from trac.util.formencode_addons import EqualSet, State, make_plain_errors_list


# classes and vars to handle forms

class MilestoneUserEvalRow(formencode.Schema):

    target = validators.String(not_empty=True)
    value = validators.Int(not_empty=True, min=0)
    public_comment  = validators.String(min=10, max=2000)
    private_comment = validators.String(min=0,  max=2000)

class MilestoneTeamEvalFormValidator(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    team = ()
    sum = 0

    pre_validators = [variabledecode.NestedVariables()]
    chained_validators = []

    def __init__(self, *args, **kwargs):
        super(MilestoneTeamEvalFormValidator, self).__init__(*args, **kwargs)
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
        'not_valid_sum': N_('Sum of earned scores field must be %(sum)s'),
    }

    def validate_python(self, value, state):
        sum = reduce(lambda s, r: s+r['value'], value['devs'], 0)
        if sum != self.sum:
            raise formencode.Invalid(self.message('not_valid_sum', State(state), sum=self.sum), sum, state)

_team_eval_form_labels = {
    'devs': N_('Evaluation form'),
    'value': N_('Earned amount'),
    'public_comment': N_('Public comment'),
    'private_comment': N_('Private comment'),
}
_eval_form_labels = {
    'weight': N_('Weight'),
    'rating': N_('Rating'),
}


class MilestoneEvalFormValidator(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    weight = validators.Int(min=0)
    rating = validators.Int(min=0, max=100)



class MilestoneEvaluation(Component):
    """
    This class provides API to control milestone evaluation.
    """

    implements(IPermissionRequestor)

    permissions = ('EVAL_MILESTONE', 'EVAL_TEAM_MILESTONE',
                   'MILESTONE_MODIFY_WEIGHT', 'MILESTONE_MODIFY_RATING')

    milestone_eval_sum = IntOption('evaluation', 'milestone_eval_sum', default='100',
                        doc="""Sum, that should be distributed between developers in a team.""", switcher=True)

    def __init__(self):
        self.pm = ProjectManagement(self.env)
        self.evmanager = EvaluationManagement(self.env)
        md = self.env.get_sa_metadata()
        self.ev_tab  = md.tables['team_milestone_evaluation']
        self.res_tab = md.tables['team_milestone_evaluation_results']

    # IPermissionRequestor

    def get_permission_actions(self):
        return self.permissions

    # Outer request handlers
    # Project and milestone access check must be done beforehand!

    def do_team_milestone_eval(self, req, milestone):
        '''Handler for milestone team evaluation actions'''
        req.perm.require('EVAL_VIEW')

        if req.args.has_key('cancel'):
            kwargs = {
                'action': 'teameval',
                'subaction': req.args.get('back'),
            }
            req.redirect(get_resource_url(self.env, milestone.resource, req.href, **kwargs))

        subaction = req.args.get('subaction', 'view')
        data = {
            'milestone': milestone,
            'subaction': subaction,
        }

        if subaction in ('view', 'edit'):
            self._do_team_participate(req, milestone, subaction, data)
        elif subaction in ('manage', 'approve', 'disapprove'):
            self._do_team_manage(req, milestone, subaction, data)

        add_ctxtnav(req, _('Back to milestone view'), get_resource_url(self.env, milestone.resource, req.href))
        add_stylesheet(req, 'common/css/roadmap.css')

        return 'milestone_team_eval.html', data, None

    def do_milestone_eval(self, req, milestone):
        '''Handler for milestone evaluation actions'''
        req.perm.require('EVAL_VIEW')
        req.perm(milestone.resource).require('MILESTONE_MODIFY')
        req.perm(milestone.resource).require('EVAL_MILESTONE')

        subaction = req.args.get('subaction')
        weight = req.args.get('weight', milestone.weight)
        rating = req.args.get('rating', milestone.rating)

        data = {
            'milestone': milestone,
        }

        if req.method == 'POST':
            if req.args.has_key('cancel'):
                req.redirect(get_resource_url(self.env, milestone.resource, req.href))
            elif subaction == 'save':
                cleaned_data, errs = self._me_fetch_and_validate_data(req)
                weight = cleaned_data.get('weight', weight)
                rating = cleaned_data.get('rating', rating)
                if not errs:
                    if weight != milestone.weight:
                        req.perm(milestone.resource).require('MILESTONE_MODIFY_WEIGHT')
                        milestone.weight = weight
                    if rating != milestone.rating:
                        req.perm(milestone.resource).require('MILESTONE_MODIFY_RATING')
                        milestone.rating = rating
                    milestone.update()
                    add_notice(req, _('Milestone evaluation data updated'))
                    req.redirect(get_resource_url(self.env, milestone.resource, req.href))
                data.update({
                    'errors': errs,
                })

        project_id  = req.data['project_id']
        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        milestone_vars = model.get_milestone_rating_vars()
        vars = OrderedDict()
        if milestone_vars:
            for var in milestone_vars:
                try:
                    var.project(project_id)
                    var.milestone(milestone.name)
                    var_value = var.get()
                    vars[var] = var_value
                except EvalModelError:
                    continue
            if vars:
                data['milestone_vars'] = vars

        data.update({
            'weight': weight,
            'rating': rating,
        })

        add_ctxtnav(req, _('Back to milestone view'), get_resource_url(self.env, milestone.resource, req.href))

        return 'milestone_eval.html', data, None

    # internal methods for team evaluation

    def _do_team_participate(self, req, milestone, subaction, data):
        req.perm(milestone.resource).require('EVAL_TEAM_MILESTONE')

        if req.authname not in self.pm.get_project_users(milestone.pid):
            raise TracError(_('You can not participate in team milestone evaluation '
                              'because you are not team member.'))

        completed = self.get_completed(req.authname, milestone.pid, milestone.name)

        is_new = completed is None
        data['is_new'] = is_new
        if is_new:
            data['subaction'] = subaction = 'edit'
        edit = subaction == 'edit'
        if not is_new:
            complete, completed_on, approved = completed
            if not complete:
                raise NotImplementedError
            if edit and approved:
                raise TracError(_('Your results have been approved already. You can not edit them.'))
            data['completed_on'] = completed_on
            data['approved'] = approved

        # Save data or prepare errors to display
        if req.method == 'POST':
            self._te_prepare_edit_data(req, milestone, data)
            cleaned_data, errs = self._te_fetch_and_validate_data(req, data)
            if not errs:
                cleaned_data.update({
                    'author': data['author'],
                    'milestone': milestone.name,
                    'project_id': milestone.pid,
                    'completed_on': datetime.now(utc),
                })
                self._te_save(cleaned_data, is_new=is_new)
                req.redirect(get_resource_url(self.env, milestone.resource, req.href, action='teameval'))
            data.update({
                'edit': True,
                'errors': errs,
            })
        elif edit:
            self._te_prepare_edit_data(req, milestone, data, is_existent=not is_new)
        else:
            self._te_prepare_view_data(req, req.authname, milestone, data)

        if edit:
            Chrome(self.env).add_wiki_toolbars(req)

    def _do_team_manage(self, req, milestone, subaction, data):
        req.perm(milestone.resource).require('EVAL_MILESTONE')

        all_completed = self.get_completed_all(milestone.pid, milestone.name)

        if subaction in ('approve', 'disapprove'):
            user = req.args.get('user')
            approved = subaction == 'approve'
            if not user:
                raise TracError(_('User must be specified'))
            if user not in all_completed:
                raise TracError(_('User %(user)s not in project #%(pid)s members',
                                  user=user, pid=milestone.pid))
            if not all_completed[user]:
                raise TracError(_('User %(user)s did not complete team evaluation form '
                                  'for milestone "%(milestone)s"',
                                  user=user, milestone=milestone.name))
            self.approve_results(user, milestone.pid, milestone.name, approved)
            kwargs = {
                'action': 'teameval',
                'subaction': 'manage',
            }
            add_notice(req, _('Milestone evaluation data updated'))
            req.redirect(get_resource_url(self.env, milestone.resource, req.href, **kwargs))

        forms = {}
        for dev, info in all_completed.iteritems():
            if info:
                results = {}
                self._te_prepare_view_data(req, dev, milestone, results)
                forms[dev] = {
                    'completed_on': info[1],
                    'approved': info[2],
                }
                forms[dev].update(results)
            else:
                forms[dev] = None
        data['forms'] = forms

        users = sorted(all_completed.keys())
        data['users'] = users

        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        milestone_vars = model.get_milestone_team_eval_vars(UserRole.MANAGER)
        if milestone_vars:
            vvalues = self._init_user_vars(milestone, milestone_vars, users)
            if vvalues:
                data['user_vars'] = vvalues

    def _init_user_vars(self, milestone, vars, users):
        user_vars = [var for var in vars
                     if SubjectArea.USER in var.subject_support]
        vvalues = OrderedDict()
        for var in user_vars:
            uvalues = OrderedDict()
            var.project(milestone.pid)
            var.milestone(milestone.name)
            for user in users:
                try:
                    var.user(user)
                    var_value = var.get()
                except EvalModelError, e:
                    var_value = e.message
                uvalues[user] = var_value
            vvalues[var] = uvalues
        return vvalues

    def _te_prepare_view_data(self, req, username, milestone, data):
        res = self.get_results_by_user(username, milestone.pid, milestone.name)
        devs = data['devs'] = []
        for row in res:
            devs.append({
                'target': row['target'],
                'value': row['value'],
                'public_comment': row['public_comment'],
                'private_comment': row['private_comment'],
            })

        all_completed = self.get_completed_all(milestone.pid, milestone.name)
        all_completed = all(all_completed.values())
        data['all_completed'] = all_completed

        users = self.pm.get_project_users(milestone.pid)
        data['users'] = users

        if all_completed:
            comments = {}
            for user in users:
                user_comments = self.get_comments(user, milestone.pid, milestone.name)
                shuffle(user_comments)
                comments[user] = user_comments
            data['comments'] = comments

        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        milestone_vars = model.get_milestone_team_eval_vars(UserRole.DEVELOPER)
        if milestone_vars:
            vvalues = self._init_user_vars(milestone, milestone_vars, users)
            if vvalues:
                data['user_vars'] = vvalues


    def _te_prepare_edit_data(self, req, milestone, data, is_existent=False):
        devs = self.pm.get_project_users(milestone.pid)
        syllabus_id = self.pm.get_project_syllabus(milestone.pid)
        sum = self.milestone_eval_sum.syllabus(syllabus_id)
        data.update({
            'author': req.authname,
            'targets': devs,
            'sum': sum,
        })
        if not is_existent:
            return

        # Request args update for existent results
        validator = MilestoneTeamEvalFormValidator(team=devs, sum=sum)
        res = self.get_results_by_user(req.authname, milestone.pid, milestone.name)
        args_upd = validator.from_python({'devs': res})
        req.args.update(args_upd)

    def _te_fetch_and_validate_data(self, req, data):
        errs = ()
        args = req.args
        devs = data['targets']
        sum = data['sum']
        validator = MilestoneTeamEvalFormValidator(team=devs, sum=sum)
        try:
            cleaned_data = validator.to_python(args)
        except formencode.Invalid, e:
            cleaned_data = {}
            errs = e.unpack_errors()
            labels = {k: _(v) for k,v in _team_eval_form_labels.iteritems()}
            errs = make_plain_errors_list(errs, labels)
        return cleaned_data, errs

    def _te_save(self, data, is_new):
        self.save_results(data['author'], data['project_id'],
            data['milestone'], data['completed_on'], data['devs'], is_new=is_new)

    # internal methods for milestone evaluation

    def _me_fetch_and_validate_data(self, req):
        errs = ()
        args = req.args
        validator = MilestoneEvalFormValidator()
        try:
            cleaned_data = validator.to_python(args)
        except formencode.Invalid, e:
            cleaned_data = {}
            errs = e.unpack_errors()
            labels = {k: _(v) for k,v in _eval_form_labels.iteritems()}
            errs = make_plain_errors_list(errs, labels)
        return cleaned_data, errs

    # API

    def get_completed(self, username, pid, milestone):
        '''Returns (<bool (is completed)>, <datetime (when)>, <bool (is approved)>)
        or None'''
        assert username
        res = self._get_completed_query(pid, milestone, username)
        return res and (res['complete'], res['completed_on'], res['approved'])

    def get_completed_all(self, pid, milestone, approved_only=False):
        '''Returns dict {<username>: (<bool>, <datetime>, <bool>) or None, ...}

        See also `get_completed`.'''
        users = self.pm.get_project_users(pid)
        res = self._get_completed_query(pid, milestone, approved_only=approved_only)
        res = {r['username']: (r['complete'], r['completed_on'], r['approved']) for r in res}
        return {u: res.get(u) for u in users}

    def check_completed_all(self, pid, milestone):
        '''Return whether all team members evaluated each other'''
        users = self.pm.get_project_users(pid)
        # TODO: also check for every target result individually (project team may change)
        t = self.ev_tab
        q = t.select().with_only_columns([t.c.username]).\
                where((t.c.project_id==pid) & (t.c.milestone==milestone))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        users_compl = [r[0] for r in res.fetchall()]
        if not users_compl:
            return False
        return set(users) <= set(users_compl)

    def check_approved_any(self, pid, milestone):
        '''Returns whether there is any approved results'''
        t = self.ev_tab
        q = t.select().with_only_columns([text('1')]).\
                where((t.c.project_id==pid) & (t.c.milestone==milestone) &
                      (t.c.approved==True)).limit(1)
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        return bool(res.fetchone())

    def _get_completed_query(self, pid, milestone, username=None, approved_only=False):
        t = self.ev_tab
        where_expr = (t.c.project_id==pid) & (t.c.milestone==milestone)
        if approved_only:
            where_expr &= (t.c.approved==True)
        columns = [t.c.complete, t.c.completed_on, t.c.approved]
        if username:
            where_expr &= (t.c.username==username)
        else:
            columns = [t.c.username] + columns
        q = t.select().with_only_columns(columns).where(where_expr)
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        if username:
            res = res.fetchone()
        else:
            res = res.fetchall()
        return res

    def get_results_by_user(self, username, pid, milestone):
        '''Get milestone team results evaluated by `username`.

        Returns list of dicts {'target': ..., 'value': ..., 'comment': ...}
        '''
        t = self.res_tab
        q = t.select().with_only_columns(
                     [t.c.target, t.c.value, t.c.public_comment, t.c.private_comment]
                     ).where((t.c.author==username) &
                             (t.c.project_id==pid) &
                             (t.c.milestone==milestone))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        res = res.fetchall()
        return res or []

    def get_comments(self, username, pid, milestone):
        '''Get all public comments for `username`.

        Returns list of comments.
        '''
        t = self.res_tab
        q = t.select().with_only_columns([t.c.public_comment]
                     ).where((t.c.target==username) &
                             (t.c.project_id==pid) &
                             (t.c.milestone==milestone))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        res = res.fetchall()
        return res

    def approve_results(self, user, pid, milestone, approved=True):
        '''Approve team evaluation results for specified user and milestone'''
        et = self.ev_tab
        q_ev = et.update().\
            where((et.c.username==user) & (et.c.milestone==milestone) &
                  (et.c.project_id==pid)).\
            values(approved=approved)
        conn = self.env.get_sa_connection()
        conn.execute(q_ev)

    def save_results(self, author, pid, milestone, completed_on, results, is_new=False):
        '''Save milestone team evaluation results.

        `results` is list of dicts {'target': ..., 'value': ...,
                                    'public_comment': ..., 'private_comment': ...}
        '''
        rt = self.res_tab
        et = self.ev_tab
        # TODO: check for every target individually (project team may change)
        if is_new:
            q_res = rt.insert().\
                values(author=author, milestone=milestone,
                       project_id=pid)
            q_ev = et.insert().\
                values(username=author, milestone=milestone,
                       project_id=pid, complete=True,
                       completed_on=completed_on)
        else:
            from sqlalchemy import bindparam
            results = [{'target_' if k=='target' else k: v for k, v in row.iteritems()} for row in results]
            q_res = rt.update().\
                where((rt.c.author==author) & (rt.c.milestone==milestone) &
                      (rt.c.project_id==pid) & (rt.c.target==bindparam('target_'))).\
                values({rt.c.target: bindparam('target_')})
            q_ev = et.update().\
                where((et.c.username==author) & (et.c.milestone==milestone) &
                      (et.c.project_id==pid)).\
                values(complete=True, completed_on=completed_on)
        conn = self.env.get_sa_connection()
        trans = conn.begin()
        try:
            conn.execute(q_res, results)
            conn.execute(q_ev)
            trans.commit()
        except:
            trans.rollback()
            raise
