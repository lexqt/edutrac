from trac.util.translation import _
from trac.util.text import exception_to_unicode

from trac.user.api import UserRole

from trac.evaluation.api.error import *
from trac.evaluation.api.meta import *
from trac.evaluation.api.scale import *
from trac.evaluation.api.area import *


__all__ = ['EvaluationModel', 'ModelVariable', 'ModelConstant']




class EvaluationModel(object):

    # maps

    ENUM_MAP = {} # see `get_enum_value`
    PROJECT_EVAL_CRITERIA = {} # see `get_project_eval_criteria`

    # special variables names

    VAR_INDIVIDUAL_RATING = None # see `get_individual_rating_var`
    VAR_PROJECT_RATING    = None # see `get_project_rating_var`
    VAR_FINAL_RATING      = None # see `get_final_rating_var`

    # special variables groups

    VARS_MILESTONE_RATING = None # see `get_milestone_rating_vars`
    VARS_MILESTONE_TEAM_EVAL_MANAGER   = None # `see get_milestone_team_eval_vars`
    VARS_MILESTONE_TEAM_EVAL_DEVELOPER = None # `see get_milestone_team_eval_vars`
    VARS_PROJECT_RATING = None # see `get_project_rating_vars`
    VARS_INDIVIDUAL_RATING = None # see `get_individual_rating_vars`

    # misc

    TICKET_VALUE_HELP = None # see `get_ticket_value_help`
    TICKET_VALUE_ENUM_LIST = None # see `get_ticket_value_enum_list`

    # Model instance variables

    vars      = None  # see `ModelVariableAccessor`
    constants = None  # see `ModelConstantAccessor`
    sources   = None  # see `SourceAccessor`
    sconfig   = None  # syllabus configuration

    def __init__(self, syllabus_id):
        self.vars = ModelVariableAccessor(self)
        self.constants = ModelConstantAccessor(self)
        from trac.evaluation.sources import SourceAccessor
        self.sources = SourceAccessor(self)
        self.syllabus_id = syllabus_id

        # initialized later (component activation)
        self.env = None
        self.config = None
        self.configs = None
        self.sconfig = None # same as self.configs.syllabus(syllabus_id)
        self.log = None

    # methods to override

    def get_ticket_value(self, ticket):
        '''Return ticket value'''
        raise NotImplementedError

    # API

    def get_ticket_value_help(self):
        '''Return help (in wiki format) for ticket value evaluation.'''
        return self.TICKET_VALUE_HELP or ''

    def get_ticket_value_enum_list(self):
        '''Return list of enums used in ticket value calculation.'''
        return self.TICKET_VALUE_ENUM_LIST or []

    def get_project_eval_criteria(self):
        '''Return criteria for project evaluation.

        `PROJECT_EVAL_CRITERIA` must be defined as dict with criteria for project evaluation:
        {
            <criteria_alias>: {
                'order': <num>,
                'label': <unicode>,
                'description': <unicode>,
                'scale': <Scale>,
            }
        }
        '''
        return self.PROJECT_EVAL_CRITERIA.copy()

    def get_individual_rating_var(self):
        '''Return variable for individual rating evaluation.
        '''
        if self.VAR_INDIVIDUAL_RATING:
            return self.vars[self.VAR_INDIVIDUAL_RATING]

    def get_project_rating_var(self):
        '''Return variable for project rating evaluation.
        '''
        if self.VAR_PROJECT_RATING:
            return self.vars[self.VAR_PROJECT_RATING]

    def get_final_rating_var(self):
        '''Return variable for final rating evaluation.
        '''
        if self.VAR_FINAL_RATING:
            return self.vars[self.VAR_FINAL_RATING]

    def get_project_rating_vars(self):
        '''Return variables for project rating evaluation.
        These variables must support project area and no clustering.
        '''
        if self.VARS_PROJECT_RATING:
            vars = [self.vars[var] for var in self.VARS_PROJECT_RATING]
            return filter(lambda var: SubjectArea.PROJECT in var.subject_support and
                       ClusterArea.NONE in var.cluster_support, vars)
        return []

    def get_individual_rating_vars(self):
        '''Return variables for individual rating evaluation.
        These variables must support user area and no clustering.
        '''
        if self.VARS_INDIVIDUAL_RATING:
            vars = [self.vars[var] for var in self.VARS_INDIVIDUAL_RATING]
            return filter(lambda var: SubjectArea.USER in var.subject_support and
                       ClusterArea.NONE in var.cluster_support, vars)
        return []

    def get_milestone_rating_vars(self):
        '''Return variables for milestone rating evaluation.
        These variables must support milestone clustering and project area.
        '''
        if self.VARS_MILESTONE_RATING:
            vars = [self.vars[var] for var in self.VARS_MILESTONE_RATING]
            return filter(lambda var: SubjectArea.PROJECT in var.subject_support and
                       ClusterArea.MILESTONE in var.cluster_support, vars)
        return []

    def get_milestone_team_eval_vars(self, role=UserRole.DEVELOPER):
        '''Return variables for milestone team evaluation.
        These variables must support milestone clustering and project and/or user area.
        `role` determines the variables list to show.
        '''
        if role == UserRole.DEVELOPER:
            var_list = self.VARS_MILESTONE_TEAM_EVAL_DEVELOPER
        elif role == UserRole.MANAGER:
            var_list = self.VARS_MILESTONE_TEAM_EVAL_MANAGER
        if var_list:
            mvars = [self.vars[var] for var in var_list]
            return filter(lambda var: ClusterArea.MILESTONE in var.cluster_support, mvars)
        return []

    def get_enum_value(self, type_, value):
        '''Return numeric value for string enum value.

        `type_` - enum type, e.g. "priority"
        `value` - string enum value, e.g. "critical"

        `ENUM_MAP` must be defined as enum string-numeric value mapping:
        {
            '<enum type>': {
                '<enum value 1>': <number>,
                ...
                '': <number> # optional value for case when field is not set
                '*': <number> # optional default value for type
            },
            ...
        }
        '''
        if type_ not in self.ENUM_MAP:
            return 0
        value = (value or '').lower()
        m = self.ENUM_MAP[type_]
        if value in m:
            return m[value]
        elif '*' in m:
            return m['*']
        return 0




DEBUG = False

class ModelVariable(object):

    __metaclass__ = ModelVariableMetaclass

    # class variables to overload in subclasses

    model_cls = None

    subject_support      = set()
    cluster_support      = set([ClusterArea.NONE])

    # not used currently
    time_groupby_support = set()
    subj_groupby_support = set()

    scale = Scale()

    alias = None
    label = None
    description = None

    def __init__(self, model):
        self.model = model
        self._set_default_state()

    def get(self):
        area = self._state['area']
        if area not in self.subject_support:
            raise EvalVariableError(_(
                'Variable "%(alias)s" (%(label)s) doesn\'t support area "%(area)s"',
                alias=self.alias, label=self.label, area=SubjectArea.label(area)))
        if ClusterArea.NONE not in self.cluster_support:
            for clust in self.cluster_support:
                if ClusterArea.state_var(clust) in self._state:
                    break
            else:
                cl_available = u', '.join([ClusterArea.label(cl) for cl in self.cluster_support])
                raise EvalVariableError(_(
                        'Variable requires clustering (available clusters: %(clusters)s) '
                        'but no appropriate arguments defined in var state',
                        clusters=cl_available))
        try:
            value = self._get()
            value = self.scale.get(value)
        except EvalModelError:
            raise
        except Exception, e:
            if DEBUG:
                raise
            msg = exception_to_unicode(e)
            raise EvalModelError(_('Error occurred while getting variable value: %(msg)s', msg=msg))
        return value

    def _get(self):
        raise NotImplementedError

    def __getitem__(self, arg):
        return self._state.get(arg)

    # Area setup methods

    def project(self, pid):
        s = self._state
#        if s['area'] != SubjectArea.USER:
        s['area'] = SubjectArea.PROJECT
        s['project_id'] = pid
        return self

    def user(self, username):
        self._state.update({
            'area': SubjectArea.USER,
            'username': username
        })
        return self

    # not used currently
    def group(self, gid):
        self._state.update({
            'area': SubjectArea.GROUP,
            'group_id': gid
        })
        return self

    # not used currently
    def syllabus(self, sid):
        self._state.update({
            'area': SubjectArea.SYLLABUS,
            'syllabus_id': sid
        })
        return self

    def milestone(self, milestone):
        self._state['milestone'] = milestone
        return self

    # Other methods

    # not used currently
    def period(self, begin=None, end=None):
        self._state['period'] = {
            'begin': begin,
            'end': end
        }
        return self

    # not used currently
    def group_by(self, time=None, subj=None, first_by=None):
        self._state['groupby'] = {
            'time': time,
            'subj': subj,
            'first_by': first_by
        }
        return self


    # Methods for state manipulation

    def _set_default_state(self):
        self._state = {
            'area': None
        }

    def clear_state(self):
        self._set_default_state()

    def copy_state(self, other, args=None):
        '''Copy state from other variable
        `args` - limit arguments to copy

        >>> var1 = ModelVariable(None)
        >>> var2 = ModelVariable(None)
        >>> state       = { 's1': 2, 's4': 5 }
        >>> var1._state = state.copy()
        >>> var2._state = { 's1': 7, 's2': 6 }
        >>> var2.copy_state(var1)
        >>> all(map(lambda k: var1._state[k] == var2._state[k], state))
        True
        >>> # do not modify var2-only args
        >>> var2._state['s2'] == 6
        True
        '''
        s = self._state
        so = other._state
        if args:
            for arg in args:
                if arg not in so:
                    continue
                s[arg] = so[arg]
        else:
            s.update(so)

    def __gt__(self, other):
        '''Copy state from self to other.
        Supports ModelVariable and ModelSource classes.
        '''
        if isinstance(other, ModelVariable):
            other.copy_state(self)
        elif isinstance(other, ModelSource):
            self.set_query_area(other)

    def __lt__(self, other):
        '''Copy state from other to self.'''
        if isinstance(other, ModelVariable):
            self.copy_state(other)

    def set_query_area(self, query):
        '''Copy area and necessary arguments from variable state
        to query state using query methods user(), project(), etc.

        >>> from trac.evaluation.sources.api import ModelSource
        >>> model = EvaluationModel(None)
        >>> srcquery = ModelSource(model)
        >>> var1 = ModelVariable(None)
        >>> var1.project(10).set_query_area(srcquery)
        >>> all(map(lambda k: var1._state[k] == srcquery._state[k], {'area': SubjectArea.PROJECT, 'project_id': 10}))
        True
        >>> srcquery = ModelSource(model)
        >>> var1.project(5).user('dev').set_query_area(srcquery)
        >>> all(map(lambda k: var1._state[k] == srcquery._state[k], {'area': SubjectArea.USER, 'project_id': 5, 'username': 'dev'}))
        True
        '''
        q = query
        s = self._state
        area = s['area']
        if area == SubjectArea.USER:
            q.project(s['project_id']).user(s['username'])
        elif area == SubjectArea.PROJECT:
            q.project(s['project_id'])
        elif area == SubjectArea.GROUP:
            q.group(s['group_id'])
        elif area == SubjectArea.SYLLABUS:
            q.syllabus(s['syllabus_id'])

        if 'milestone' in s:
            q.milestone(s['milestone'])


class ModelConstant(object):

    __metaclass__ = ModelConstantMetaclass

    # class variables to overload in subclasses

    model_cls = None

    alias = None
    label = None
    description = None

    scale = Scale()

    default_value = None

    def __init__(self, model):
        self.model = model
        self._current_value = None

    def reload(self):
        self._current_value = None

    def reset(self):
        self.set(self.default_value)

    def get(self):
        if self._current_value is None:
            val = self._get_from_conf()
            self._current_value = val
        return self._current_value

    def _get_from_conf(self):
        c = self.model.sconfig
        type_ = self.scale.type
        if type_ is bool:
            func = c.getbool
        else:
            func = c.get
        val = func('evaluation-constants', self.alias.lower(), self.default_value)
        try:
            return self.scale.get(val)
        except:
            return self.default_value

    def set(self, value):
        value = self.scale.get(value)
        self.model.sconfig.set('evaluation-constants', self.alias.lower(), value)



class ModelSource(object):
    '''Base class for evaluation model source class'''

    model = None
    env   = None

    def __init__(self, model):
        self.model = model
        self.env   = model.env
        self._state = {
            'area': None, # query subject area
        }

    # Base implementation for query area setup methods
    # may be overriden

    def reset(self):
        self._state = {
            'area': None,
        }
        return self

    def project(self, project_id):
        s = self._state
        s['area'] = SubjectArea.PROJECT
        s['project_id'] = project_id
        return self

    def user(self, username):
        self._state.update({
            'area': SubjectArea.USER,
            'username': username
        })
        return self

    def group(self, group_id):
        self._state.update({
            'area': SubjectArea.GROUP,
            'group_id': group_id
        })
        return self

    def syllabus(self, syllabus_id):
        self._state.update({
            'area': SubjectArea.SYLLABUS,
            'syllabus_id': syllabus_id
        })
        return self

    def milestone(self, milestone_name):
        self._state['milestone'] = milestone_name
        return self

    # Util methods

    def check_state(self, *args):
        '''Check if all specified args defined (not None) in the state'''
        s = self._state
        return all(map(lambda x: x is not None, [s.get(k) for k in args]))

    def check_state_and_raise(self, *args):
        '''Call `check_state` and raise exception on false'''
        check = self.check_state(*args)
        if not check:
            raise MissedQueryArgumentsError(_('Some mandatory arguments for model source query are missed.'))

