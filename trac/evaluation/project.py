from collections import OrderedDict
from sqlalchemy import bindparam

import formencode
from trac.util.translation import _
from trac.web.chrome import add_package

from trac.core import Component, implements
from trac.perm import IPermissionRequestor

from trac.evaluation.api.components import EvaluationManagement
from trac.evaluation.api.scale import prepare_editable_var, create_scale_validator, create_group_validator
from trac.evaluation.api.error import EvalModelError


class ProjectEvalForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True



class ProjectEvaluation(Component):
    """
    This class provides API to control project evaluation.
    """

    implements(IPermissionRequestor)

    permissions = ('EVAL_PROJECT',)


    def __init__(self):
        self.evmanager = EvaluationManagement(self.env)
        md = self.env.get_sa_metadata()
        self.pe_tab  = md.tables['project_evaluation']

    # IPermissionRequestor

    def get_permission_actions(self):
        return self.permissions

    # Outer request handlers
    # Project access check must be done beforehand!

    def do_project_eval(self, req):
        subaction = req.args.get('subaction', 'view')
        view = subaction == 'view'
        save = req.method == 'POST'

        if not view or save:
            req.perm.require('EVAL_PROJECT')

        if save and req.args.has_key('cancel'):
            req.redirect(req.href.eval(action='project'))

        project_id  = req.data['project_id']
        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        criteria = model.get_project_eval_criteria()

        # prepare validator
        params = {}
        if save:
            params['not_empty'] = True
        else:
            no_data = view and _('Data is not ready') or None
            params['if_empty'] = no_data
            params['if_missing'] = no_data
            if view:
                params['if_invalid'] = _('Invalid data')
        validator = self.create_validator(criteria, params)

        # fetch data from request or DB
        if save:
            datavalues = req.args
        else:
            # fetch data from DB
            datavalues = self.fetch_db_data(project_id)

        data = {}

        # convert data, check for errors
        errors = []
        try:
            datavalues = validator.to_python(datavalues)
        except formencode.Invalid, e:
            errs = e.unpack_errors()
            if isinstance(errs, dict):
                for name, err in errs.iteritems():
                    errors.append({
                        'name': criteria[name]['label'],
                        'error': err,
                    })
            else:
                errors = [{'name': 'System error', 'error': 'Something went wrong'}]
            data['errors'] = errors

        # save and redirect on success
        if save and not errors:
            savedata = validator.from_python(datavalues)
            self.save_data(project_id, savedata)
            req.redirect(req.href.eval(action='project'))

        values = []
        for name, crit in criteria.iteritems():
            row = {
                'alias': name,
                'label': crit['label'],
                'description': crit['description'],
                'scale': crit['scale'],
                'value': datavalues[name],
                'order': crit['order'],
            }
            values.append(row)
            if view:
                continue
            # set input type, value help_text, row extra args
            scale = crit['scale']
            info = prepare_editable_var(scale)
            row.update(info)
        values.sort(key=lambda r: r['order'])

        project_id  = req.data['project_id']
        syllabus_id = req.data['syllabus_id']
        model = self.evmanager.get_model(syllabus_id)
        variables = model.get_project_rating_vars()
        vars = OrderedDict()
        if variables:
            for var in variables:
                try:
                    var.project(project_id)
                    var_value = var.get()
                except EvalModelError, e:
                    var_value = e.message
                vars[var] = var_value
            if vars:
                data['variables'] = vars

        data.update({
            'values': values,
            'view': view,
        })
        add_package(req, 'jquery.tablesorter')
        return 'project_eval.html', data, None

    # API

    def create_validator(self, criteria, each_params=None):
        '''Create FormEncode validator for given criteria

        `criteria`: dict { <alias>: { 'scale': <Scale>, ... }, ... }
        `each_params`: default kw arguments for each criterion validator
        '''
        return create_group_validator(criteria, each_params)

    def create_criterion_validator(self, scale, params):
        '''Create FormEncode validator for single criterion

        `scale`: criterion scale
        `params`: default kw arguments for validator
        '''
        return create_scale_validator(scale, params)

    def fetch_db_data(self, project_id, criterion=None):
        '''Fetch project evaluation data from DB.

        Return dict { <criterion_alias>: <string value>, ... }
        or single value if `criterion` is not None.
        `criterion`: criterion alias
        '''
        single = criterion is not None
        t = self.pe_tab
        conn = self.env.get_sa_connection()
        cols = [t.c.value]
        if not single:
            cols.insert(0, t.c.criterion)
        q = t.select().with_only_columns(cols).\
                       where(t.c.project_id==project_id)
        if single:
            q = q.where(t.c.criterion==criterion)
        res = conn.execute(q)
        if single:
            return res.scalar()
        datavalues = res.fetchall()
        return {c: v for c, v in datavalues}

    def save_data(self, project_id, data):
        '''Save project evaluation data in DB.

        `data`: dict { <criterion_alias>: <value>, ... }
        '''
        if not data:
            return
        t = self.pe_tab
        conn = self.env.get_sa_connection()
        trans = conn.begin()
        try:
            exdata = self.fetch_db_data(project_id)
            to_insert = []
            to_update = []
            for name, val in data.iteritems():
                target = None
                record = None
                val = unicode(val)
                if name in exdata:
                    if val == exdata[name]:
                        continue
                    target = to_update
                    record = {
                        'b_criterion': name,
                        'value': val,
                    }
                else:
                    target = to_insert
                    record = {
                        'project_id': project_id,
                        'criterion': name,
                        'value': val,
                    }
                target.append(record)
            if to_insert:
                q = t.insert()
                conn.execute(q, to_insert)
            if to_update:
                q = t.update().where((t.c.project_id==project_id) & (t.c.criterion==bindparam('b_criterion'))).\
                               values({t.c.criterion: bindparam('b_criterion')})
                conn.execute(q, to_update)
            trans.commit()
        except:
            trans.rollback()
            raise

