__all__ = ['EvaluationModel', 'SubjectArea', 'TimeArea', 'ModelVariable', 'ModelConstant',
           'Scale', 'IntervalScale', 'AbsoluteScale', 'UnityScale']



class ModelVariableAccessor(object):

    def __init__(self, model):
        self.model = model

    def __getitem__(self, alias):
        return ModelVariableMetaclass.get_variable(self.model, alias)



class EvaluationModel(object):

    def __init__(self):
        self.vars = ModelVariableAccessor(self)
        from trac.evaluation.sources import SourceAccessor
        self.sources = SourceAccessor(self)
        self.env = None # initialized later (component activation)

    def get_ticket_value(self, ticket):
        raise NotImplementedError





class ModelVariableMetaclass(type):

    # per-model "variable_alias: variable_class" registry
    _registry = {}

    def __new__(mcs, name, bases, d):
        new_class = type.__new__(mcs, name, bases, d)
        alias = d.get('alias')
        model_cls = d.get('model_cls')
        if alias and model_cls:
            mcs._registry.setdefault(model_cls,{}).update({alias: new_class})
        return new_class

    @classmethod
    def get_variable(cls, model, alias):
        var_cls = cls._registry[model.__class__][alias]
        return var_cls(model)



class SubjectArea(object):
    USER     = 1
    PROJECT  = 2
    GROUP    = 3 # e.g. Student group
    SYLLABUS = 4

class TimeArea(object):
    DAY = 1


class Scale(object):

    def __init__(self, type):
        self.type_ = type

    def get(self, value):
        value = self.type_(value)
        value = self._get(value)
        return value

    def _get(self, value):
        return value

class IntervalScale(Scale):

    def __init__(self, type, min=None, max=None):
        super(IntervalScale, self).__init__(type)
        self.min_ = min
        self.max_ = max

    def _get(self, value):
        if self.min_ is not None and value < self.min_:
            return self.min_
        if self.max_ is not None and value > self.max_:
            return self.max_
        return value

class AbsoluteScale(IntervalScale):

    def __init__(self, type, max=None):
        super(AbsoluteScale, self).__init__(type, min=type(0), max=max)

class UnityScale(IntervalScale):

    def __init__(self):
        super(UnityScale, self).__init__(float, min=0.0, max=1.0)


class ModelVariable(object):

    __metaclass__ = ModelVariableMetaclass

    # class variables to overload in subclasses

    model_cls = None

    subj_type            = set()
    time_groupby_support = set()
    subj_groupby_support = set()

    scale = Scale(lambda a: a)

    alias = None
    label = None
    description = None

    def __init__(self, model):
        self.model = model
        self._state = {
            'area': None
        }

    def get(self):
        area = self._state['area']
        if area not in self.subj_type:
            raise ValueError('Variable "%s" doesn\'t support area %s' % (self.alias, area))
        value = self._get()
        value = self.scale.get(value)
        return value

    def _get(self):
        raise NotImplementedError

    # Area setup methods

    def team(self, team_id):
        raise NotImplementedError

    def project(self, pid):
        s = self._state
        if s['area'] != SubjectArea.USER:
            s['area'] = SubjectArea.PROJECT
        s['project_id'] = pid
        return self

    def user(self, username):
        self._state.update({
            'area': SubjectArea.USER,
            'username': username
        })
        return self

    def group(self, gid):
        self._state.update({
            'area': SubjectArea.GROUP,
            'group_id': gid
        })
        return self

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

    def period(self, begin=None, end=None):
        self._state['period'] = {
            'begin': begin,
            'end': end
        }
        return self

    def group_by(self, time=None, subj=None, first_by=None):
        self._state['groupby'] = {
            'time': time,
            'subj': subj,
            'first_by': first_by
        }
        return self


    #

    def clone_state(self, other, params=()):
        raise NotImplementedError

    def set_query_area(self, query):
        q = query
        s = self._state
        area = s['area']
        if area == SubjectArea.USER:
            q.user(s['username']).project(s['project_id'])
        elif area == SubjectArea.PROJECT:
            q.project(s['project_id'])
        elif area == SubjectArea.GROUP:
            q.group(s['group_id'])
        elif area == SubjectArea.SYLLABUS:
            q.syllabus(s['syllabus_id'])

        if 'milestone' in s:
            q.milestone(s['milestone'])


class ModelConstant(object):

    alias = 'constant'
    label = None
    description = None

    min_value     = None
    max_value     = None
    default_value = None

    _current_value = None

    def get(self):
        raise NotImplementedError


