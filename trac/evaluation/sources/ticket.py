from operator import (
    and_, or_, inv, add, mul, div, sub, mod, truediv, lt, le, ne, gt, ge, eq, neg
    )

#from inspect import currentframe
from lazy import lazy

from sqlalchemy import Integer, Numeric
from sqlalchemy.sql import func, cast

from trac.util.translation import _

from trac.ticket.api import TicketSystem
from trac.project.api import ProjectManagement

from trac.evaluation.api.model import ModelSource
from trac.evaluation.api.area import SubjectArea
from trac.evaluation.api.error import EvalSourceError

__all__ = ['Query', 'Info',                                         # sources
           'Field', 'Resolution', 'Status', 'Owner', 'Reporter',    # fields
           'Milestone', 'Type', 'Priority', 'Severity', 'Version',
           'Component', 'Keywords', 'CreateTime', 'ChangeTime'
           'TicketValue',                                           # extra attributes
           'InProjectUsers',                                        # special expressions
           'Count', 'Sum', 'Avg',                                   # function expressions
           ]



class OpExpression(object):
    '''Wrapper class for ticket query expression.
    It MUST NOT store any dynamic data in self so that it can be
    copied and reused safely for other ticket queries.
    All real work takes place in `process` method, that manipulates
    ticket query object and implements expression logic by changing
    query state.
    '''

    def __init__(self, operation=None, *args):
        self.op = operation
        self.args = args

#    def cur_method(self):
#        return currentframe(1).f_code.co_name

    def __and__(self, other):
        return OpExpression(and_, self, other)

    def __or__(self, other):
        return OpExpression(or_, self, other)

    def __invert__(self):
        return OpExpression(inv, self)

    def __neg__(self):
        return OpExpression(neg, self)

    def __eq__(self, other):
        return OpExpression(eq, self, other)

    def __ne__(self, other):
        return OpExpression(ne, self, other)

    def __gt__(self, other):
        return OpExpression(gt, self, other)

    def __ge__(self, other):
        return OpExpression(ge, self, other)

    def __lt__(self, other):
        return OpExpression(lt, self, other)

    def __le__(self, other):
        return OpExpression(le, self, other)

    def __add__(self, other):
        return OpExpression(add, self, other)

    def __sub__(self, other):
        return OpExpression(sub, self, other)

    def __mul__(self, other):
        return OpExpression(mul, self, other)

    def __div__(self, other):
        return OpExpression(div, self, other)

    def __mod__(self, other):
        return OpExpression(mod, self, other)

    def __truediv__(self, other):
        return OpExpression(truediv, self, other)

    def in_(self, others):
        return OpExpression('in_', self, list(others))

    def compare(self, other):
        '''Compare two OpExpression objects'''
        return self.op == other.op and self.args == other.args

    @classmethod
    def process_args(cls, args, ticket_query):
        return map(lambda a: cls._process_arg(a, ticket_query), args)

    @classmethod
    def _process_arg(cls, arg, ticket_query):
        if isinstance(arg, (list, tuple, set)):
            return cls.process_args(arg, ticket_query)
        if isinstance(arg, OpExpression):
            return arg.process(ticket_query)
        return arg

    def __call__(self, ticket_query):
        return self.process(ticket_query)

    def process(self, ticket_query):
        '''Returns object of sqlalchemy.sql.expression.ClauseElement subclass.
        Applies side effects on ticket_query (adds columns, etc).

        Should be overridden in OpExpression subclasses'''
        args = self.process_args(self.args, ticket_query)
        if self.op is None:
            return # ability to call super method in subclasses to preprocess args
        arg1 = args[0]
        arg2 = args[1:]
        if hasattr(self.op, '__call__'):
            return self.op(arg1, *arg2)
        method = getattr(arg1, self.op)
        return method(*arg2)



class InProjectUsers(OpExpression):

    def __init__(self, expr, role=None, allow_empty=False):
        self.expr = expr
        self.role = role
        self.allow_empty = allow_empty

    def compare(self, other):
        return self.expr.compare(other.expr) and self.role == other.role \
                                             and self.allow_empty == other.allow_empty

    def process(self, ticket_query):
        project_id = int(ticket_query._state['project_id'])
        users = ticket_query.projman.get_project_users(project_id)
        expr = self.expr.in_(users)
        if self.allow_empty:
            expr = expr | (self.expr == None)
        return expr.process(ticket_query)


class TicketAttribute(OpExpression):

    def __init__(self, attr_name):
        self.attr_name = attr_name

    def compare(self, other):
        return self.attr_name == other.attr_name

    def process(self, ticket_query):
        raise NotImplementedError



class Field(TicketAttribute):

    def process(self, ticket_query):
        tq = ticket_query
        name = self.attr_name
        if name in tq._state['attr_columns']:
            return tq._query_parts['used_cols'][name]
        field = tq._ticket_fields.get(name)
        if field is None:
            raise ValueError('There is no "%s" ticket field' % name)
        tables = tq.sa_metadata.tables
        if 'custom' in field:
            table = tables['ticket_custom'].alias('tc_'+name)
            col = table.c.value.label(name)
            ftype = field['type']
            if ftype == 'int':
                col = cast(col, Integer)
            elif ftype == 'float':
                col = cast(col, Numeric)
            col = func.coalesce(col, field.get('value'))
            on_expr = (table.c.ticket == tables['ticket'].c.id) &\
                      (table.c.name == name)
            params = {
                'outer': True,
                'table': table,
                'on': on_expr
            }
            tq._query_parts['joins'].append(params)
        else:
            table = tables['ticket']
            col = table.c[name]
        tq._state['attr_columns'].add(name)
        tq._query_parts['used_cols'][name] = col
        return col



class ExtraAttr(TicketAttribute):

    def process(self, ticket_query):
        tq = ticket_query
        name = self.attr_name
        if name in tq._state['extra_columns']:
            return tq._query_parts['used_cols'][name]
        tables = tq.sa_metadata.tables

        if name == 'ticket_value':
            table = tables['ticket_evaluation']
            col = table.c.value.label(name)
            on_expr = (table.c.ticket_id == tables['ticket'].c.id)
            params = {
                'outer': True,
                'table': table,
                'on': on_expr
            }
            tq._query_parts['joins'].append(params)
        else:
            raise ValueError('Unknown ticket extra attribute')

        tq._state['extra_columns'].add(name)
        tq._query_parts['used_cols'][name] = col
        return col


## Ticket extra attributes ##

class TicketValue(ExtraAttr):

    def __init__(self):
        super(TicketValue, self).__init__('ticket_value')


## Basic ticket fields ##

class Status(Field):

    def __init__(self):
        super(Status, self).__init__('status')

class Resolution(Field):

    def __init__(self):
        super(Resolution, self).__init__('resolution')

class Owner(Field):

    def __init__(self):
        super(Owner, self).__init__('owner')

class Reporter(Field):

    def __init__(self):
        super(Reporter, self).__init__('reporter')

class Milestone(Field):

    def __init__(self):
        super(Milestone, self).__init__('milestone')

class Type(Field):

    def __init__(self):
        super(Type, self).__init__('type')

class Priority(Field):

    def __init__(self):
        super(Priority, self).__init__('priority')

class Severity(Field):

    def __init__(self):
        super(Severity, self).__init__('severity')

class Version(Field):

    def __init__(self):
        super(Version, self).__init__('version')

class Component(Field):

    def __init__(self):
        super(Component, self).__init__('component')

class Keywords(Field):

    def __init__(self):
        super(Keywords, self).__init__('keywords')

class CreateTime(Field):

    def __init__(self):
        super(CreateTime, self).__init__('time')

class ChangeTime(Field):

    def __init__(self):
        super(ChangeTime, self).__init__('changetime')




class FuncExpression(OpExpression):

    def __init__(self, func_name, *args):
        super(FuncExpression, self).__init__(None, *args)
        self.func_name = func_name

    def compare(self, other):
        return self.func_name == other.func_name and self.args == other.args

    def process(self, ticket_query):
        super(FuncExpression, self).process(ticket_query)
        sa_func = getattr(func, self.func_name)
        args = [arg(ticket_query)
                    if isinstance(arg, OpExpression)
                    else arg
                for arg in self.args]
        res = sa_func(*args)
        ticket_query._state['func_columns'].add(str(res))
        return res

class Count(FuncExpression):

    def __init__(self, *args):
        super(Count, self).__init__('count', *args)

class Sum(FuncExpression):

    def __init__(self, *args):
        super(Sum, self).__init__('sum', *args)

class Avg(FuncExpression):

    def __init__(self, *args):
        super(Avg, self).__init__('avg', *args)



class Query(ModelSource):

    def __init__(self, model):
        super(Query, self).__init__(model)
        self.info   = Info(self.model)
        self.projman = ProjectManagement(self.env)
        self.sa_metadata = self.env.get_sa_metadata()
        self.sa_conn     = self.env.get_sa_connection()
        self.reset()

    def reset(self):
        self._state = {
            'area': None, # query subject area
            'user_area_field': Owner(), # field expr used for user area filtering
            'columns': [], # columns to select (OpExpression objects)
            'attr_columns': set(), # all used attribute columns (names)
            'extra_columns': set(), # all used extra attribute columns (names)
            'func_columns': set(), # all used func columns (names)
            'where_exprs': [],
            'aggregate': False, # is aggregate op applied
#            'aggregate_expr': None,
            'group_by': False,
            'scalar': False,
        }
        self._query_parts = {
            'joins': [], # {outer: bool, table: table_obj, on: on_expression}
            'used_cols': {}, # all used columns (sqlalchemy column objects)
            'select_cols': set(), # columns to select (names)
        }
        lazy.invalidate(self, '_ticket_fields')
        return self

    @lazy # init in execute()
    def _ticket_fields(self):
        id_kwargs = {}
        s = self._state
        a = s['area']
        q = self.info.reset()
        if a == SubjectArea.USER or a == SubjectArea.PROJECT:
            q.project(s['project_id'])
        elif a == SubjectArea.GROUP or a == SubjectArea.SYLLABUS:
            q.project(s['syllabus_id'])
        return q.ticket_fields()

    # Area setup methods

    def user(self, username, field_expr=None):
        if field_expr is None:
            field_expr = self._state['user_area_field']
        else:
            field_expr = self._instantiate_expr(field_expr)
        self._state.update({
            'area': SubjectArea.USER,
            'username': username,
            'user_field_expr': field_expr,
        })
        return self

    def user_field(self, field_expr):
        field_expr = self._instantiate_expr(field_expr)
        self._state['user_area_field'] = field_expr
        return self

    def group(self, gid):
        self._state.update({
            'area': SubjectArea.GROUP,
            'group_id': gid,
            'syllabus_id': self.projman.get_group_syllabus(gid)
        })
        return self

    def syllabus(self, sid):
        self._state.update({
            'area': SubjectArea.SYLLABUS,
            'syllabus_id': sid
        })
        return self

    # Other methods

    def where(self, op_expr):
        '''Append query filter expression'''
        op_expr = self._instantiate_expr(op_expr)
        self._state['where_exprs'].append(op_expr)
        return self

    def limit_to_project_users(self, op_expr, role=None, allow_empty=False):
        op_expr = self._instantiate_expr(op_expr)
        self.where(InProjectUsers(op_expr, role=role, allow_empty=allow_empty))
        return self

    def milestone(self, name):
        self.where(Milestone() == name)
        return self

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

    # Columns control methods

    def only(self, *cols):
        '''Retrieve only specified columns.
        Columns must be valid OpExpression objects.'''
        cols = map(self._instantiate_expr, cols)
        self._state.update({
            'columns': list(cols)
        })
        return self

    # Terminal methods

    def count(self):
        '''Count matched query items'''
        self._state.update({
            'aggregate': True,
        })
        self.only(Count())
        if not self._state['group_by']:
            self._state['scalar'] = True
            self._state['none_value'] = 0
        return self.execute()

    def sum(self, expr):
        '''Return sum of specified expression'''
        expr = self._instantiate_expr(expr)
        self._state.update({
            'aggregate': True,
        })
        self.only(Sum(expr))
        if not self._state['group_by']:
            self._state['scalar'] = True
            self._state['none_value'] = 0
        return self.execute()

    def get(self):
        '''Alias for `execute`'''
        return self.execute()

    def execute(self):
        '''Execute query and return rows matching to query state.
        Return single value if state['scalar'] is True.
        '''
        conn = self.sa_conn
        metadata = self.sa_metadata
        s  = self._state
        qp = self._query_parts
        area = s['area']

        tickets      = metadata.tables['ticket']
        project_info = metadata.tables['project_info']

        if area == SubjectArea.USER:
            self.where(s['user_field_expr'] == s['username'])

        cols = OpExpression.process_args(s['columns'], self)
        where_exprs = OpExpression.process_args(s['where_exprs'], self)

        q_from = tickets
        if area == SubjectArea.SYLLABUS or area == SubjectArea.GROUP:
            qp['joins'].append({
                'outer': False,
                'table': project_info,
                'on': None
            })
        if qp['joins']:
            for j in qp['joins']:
                q_from = q_from.join(j['table'], j['on'], isouter=j['outer'])

        q = q_from.select()

        if area == SubjectArea.USER or area == SubjectArea.PROJECT:
            q = q.where(tickets.c.project_id==s['project_id'])
        elif area == SubjectArea.SYLLABUS:
            q = q.where(project_info.c.syllabus_id==s['syllabus_id'])
        elif area == SubjectArea.GROUP:
            q = q.where(project_info.c.group_id==s['group_id'])

        if cols:
            q = q.with_only_columns(cols)

        if where_exprs:
            for expr in where_exprs:
                q = q.where(expr)

        res = conn.execute(q)
        if s['scalar']:
            val = res.scalar()
            if val is None and 'none_value' in s:
                return s['none_value']
            return val
        rows = res.fetchall()
        if len(cols) == 1:
            return [r[0] for r in rows]
        return rows

    def _instantiate_expr(self, expr):
        if not isinstance(expr, type):
            return expr
        return expr()


class Info(ModelSource):

    def __init__(self, model):
        super(Info, self).__init__(model)
        self.ts = TicketSystem(self.env)

    def ticket_fields(self):
        self._check_ts_ready()
        kwargs = self._form_kwargs()
        return self.ts.get_ticket_fields(**kwargs)

    def min_max(self, field, project_id=None, syllabus_id=None):
        self._check_ts_ready()
        if isinstance(field, basestring):
            fields = self.ticket_fields()
            field = fields[field]
        if 'model_class' not in field:
            return None, None
        cls = field['model_class']
        if not hasattr(cls, 'get_min_max'):
            return None, None
        kwargs = self._form_kwargs()
        return cls.get_min_max(self.env, **kwargs)

    def _form_kwargs(self):
        kwargs = {}
        s = self._state
        if s['area'] == SubjectArea.PROJECT:
            kwargs['pid'] = s['project_id']
        elif s['area'] == SubjectArea.SYLLABUS:
            kwargs['syllabus_id'] = s['syllabus_id']
        return kwargs

    def _check_ts_ready(self):
        if self._state['area'] not in (SubjectArea.PROJECT, SubjectArea.SYLLABUS):
            raise EvalSourceError(_('Unsupported subject query areas'))

