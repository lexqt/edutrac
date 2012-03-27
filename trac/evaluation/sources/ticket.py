from operator import (
    and_, or_, inv, add, mul, div, sub, mod, truediv, lt, le, ne, gt, ge, eq, neg
    )

#from inspect import currentframe
from lazy import lazy

from sqlalchemy import Integer, Numeric
from sqlalchemy.sql import func, cast

from trac.ticket.api import TicketSystem
from trac.project.api import ProjectManagement

from trac.evaluation.api import SubjectArea

__all__ = ['Query', 'Info',
           'Field', 'Resolution', 'Status',
           'ExtraAttr',
           'Count']



class OpExpression(object):

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

    def __contains__(self, others):
        return OpExpression(self.cur_method(), self, list(others))

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


class Status(Field):

    def __init__(self):
        super(Status, self).__init__('status')


class Resolution(Field):

    def __init__(self):
        super(Resolution, self).__init__('resolution')


class FuncExpression(OpExpression):

    def __init__(self, func_name, *args):
        super(FuncExpression, self).__init__(None, *args)
        self.func_name = func_name

    def compare(self, other):
        return self.func_name == other.func_name and self.args == other.args

    def process(self, ticket_query):
        super(FuncExpression, self).process(ticket_query)
        sa_func = getattr(func, self.func_name)
        res = sa_func(*self.args)
        ticket_query._state['func_columns'].add(str(res))
        return res

class Count(FuncExpression):

    def __init__(self, *args):
        super(Count, self).__init__('count', *args)



class Query(object):

    def __init__(self, env):
        self.env = env
        self.info   = Info(env)
        self.projman = ProjectManagement(env)
        self.sa_metadata = env.get_sa_metadata()
        self.sa_conn     = env.get_sa_connection()
        self._state = {
            'area': None, # query subject area
            'columns': set(), # columns to select
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
            'used_cols': {}, # all used columns (column objects)
            'select_cols': set(), # columns to select (names)
        }

    @lazy # init in execute()
    def _ticket_fields(self):
        id_kwargs = {}
        s = self._state
        a = s['area']
        if a == SubjectArea.USER or a == SubjectArea.PROJECT:
            id_kwargs['project_id'] = s['project_id']
        elif a == SubjectArea.GROUP or a == SubjectArea.SYLLABUS:
            id_kwargs['syllabus_id'] = s['syllabus_id']
        return self.info.get_ticket_fields(**id_kwargs)

    # Area setup methods

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
        self._state['where_exprs'].append(op_expr)

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
        self._state.update({
            'columns': set(cols)
        })
        return self

    # Terminal methods

    def count(self):
        self._state.update({
            'aggregate': True,
#            'aggregate_expr': Count
        })
        self.only(Count())
        if not self._state['group_by']:
            self._state['scalar'] = True
        return self.execute()

    def execute(self):
        conn = self.sa_conn
        metadata = self.sa_metadata
        s  = self._state
        qp = self._query_parts
        area = s['area']

        tickets      = metadata.tables['ticket']
        project_info = metadata.tables['project_info']

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
        if area == SubjectArea.USER:
            q = q.where(tickets.c.owner==s['username'])
        elif area == SubjectArea.SYLLABUS:
            q = q.where(project_info.c.syllabus_id==s['syllabus_id'])
        elif area == SubjectArea.GROUP:
            q = q.where(project_info.c.studgroup_id==s['group_id'])

        if cols:
            q = q.with_only_columns(cols)

        if where_exprs:
            for expr in where_exprs:
                q = q.where(expr)

        res = conn.execute(q)
        if s['scalar']:
            return res.scalar()
        rows = res.fetchall()
#        r = reduce(lambda s,a: s+a[0], ids, 0)
        return rows




class Info(object):

    def __init__(self, env):
        self.env = env
        self.ts = TicketSystem(self.env)

    def get_ticket_fields(self, project_id=None, syllabus_id=None):
        return self.ts.get_ticket_fields(pid=project_id, syllabus_id=syllabus_id)

    def get_min_max(self, field, project_id=None, syllabus_id=None):
        if isinstance(field, basestring):
            fields = self.get_ticket_fields(project_id, syllabus_id)
            field = fields[field]
        if 'model_class' not in field:
            return None, None
        cls = field['model_class']
        if not hasattr(cls, 'get_min_max'):
            return None, None
        return cls.get_min_max(self.env, pid=project_id, syllabus_id=syllabus_id)


