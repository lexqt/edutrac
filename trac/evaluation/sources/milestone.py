import itertools

from trac.util.translation import _

from trac.project.api import ProjectManagement
from trac.evaluation.api.model import EvalSourceError, DataNotReadyError, ModelSource
from trac.evaluation.api.area import SubjectArea
from trac.evaluation.milestone import MilestoneEvaluation

__all__ = ['Info', 'TeamEvalQuery']



class Info(ModelSource):

    def __init__(self, model):
        super(Info, self).__init__(model)
        self.meval = MilestoneEvaluation(self.env)
        self.projman = ProjectManagement(self.env)

    def get_team_eval_sum(self, project_id=None, syllabus_id=None):
        if project_id is not None:
            syllabus_id = self.projman.get_project_syllabus(project_id)
        return self.meval.milestone_eval_sum.syllabus(syllabus_id)



class TeamEvalQuery(ModelSource):
    '''Source for milestone team evaluation results'''

    def __init__(self, model):
        super(TeamEvalQuery, self).__init__(model)
        self.projman = ProjectManagement(self.env)
        self.meval = MilestoneEvaluation(self.env)
        sa_metadata  = self.env.get_sa_metadata()
        self.ev_tab  = sa_metadata.tables['team_milestone_evaluation']
        self.res_tab = sa_metadata.tables['team_milestone_evaluation_results']

    # simplify area setup methods

    def project(self, pid):
        self._state['project_id'] = pid
        return self

    def user(self, username):
        self._state['username'] = username
        return self

    # Terminal methods

    def data_ready(self, all_completed=True, any_approved=False):
        if not self.check_state('project_id', 'milestone'):
            raise EvalSourceError(_('Not enough state arguments for team evaluation data query'))
        check = True
        if all_completed:
            check &= self.meval.check_completed_all(self._state['project_id'], self._state['milestone'])
        if check and any_approved:
            check &= self.meval.check_approved_any(self._state['project_id'], self._state['milestone'])
        return check

    def earned_values(self, with_usernames=False, all_completed=True, only_approved=False):
        if not self.check_state('project_id', 'milestone'):
            raise EvalSourceError(_('Not enough state arguments for team evaluation data query'))
        if not self.data_ready(all_completed, only_approved):
            raise DataNotReadyError(_('Team evaluation data is not ready'))

        s = self._state
        conn = self.env.get_sa_connection()
        members = self.projman.get_project_users(s['project_id'])
        if only_approved:
            t = self.ev_tab
            q = t.select().with_only_columns([t.c.username]).\
                    where((t.c.project_id==s['project_id']) & (t.c.milestone==s['milestone']) &
                          (t.c.approved==True))
            res = conn.execute(q)
            approved_members = [r[0] for r in res.fetchall()]
            members = set(members) & set(approved_members)

        t = self.res_tab
        cols = [t.c.value]
        if with_usernames:
            cols.insert(0, t.c.author)
        q = t.select().where(t.c.author.in_(members) &
                            (t.c.project_id==s['project_id']) &
                            (t.c.milestone==s['milestone'])
                            )
        one_user = 'username' in s
        if one_user:
            q = q.where((t.c.target==s['username']))
        else:
            cols.append(t.c.target)
            q = q.order_by(t.c.target)
        q = q.with_only_columns(cols)
        res = conn.execute(q)
        res = res.fetchall()

        def get_user_results(res):
            if with_usernames:
                return {r['author']: r['value'] for r in res}
            else:
                return [r[0] for r in res]

        if not one_user:
            ret = {}
            for target, results in itertools.groupby(res, lambda r: r['target']):
                ret[target] = get_user_results(results)
            return ret

        return get_user_results(res)



class Query(ModelSource):
    '''Source for milestone data'''

    def __init__(self, model):
        super(Query, self).__init__(model)
        md = self.env.get_sa_metadata()
        self.m_tab = md.tables['milestone']
        self._state.update({
            'props': (),
        })

    user = lambda self, x: self

    _supported_props = set(['weight', 'rating', 'approved', 'completed'])

    def include(self, **props):
        '''Include milestone properties in query results.
        Should be called like: query.include(weight=True, rating=True)
        Available properties: weight, rating, approved, completed.
        '''
        props = filter(lambda p: props[p] and p in self._supported_props, props)
        if props:
            self._state['props'] = props

    # Terminal methods

    def get(self):
        s = self._state
        if s['area'] != SubjectArea.PROJECT:
            raise EvalSourceError(_('Unsupported query area'))
        project_id = s['project_id']
        single = 'milestone' in s
        with_props = bool(s['props'])

        t = self.m_tab
        q = t.select().where(t.c.project_id==project_id)
        if single:
            q = q.where(t.c.name==s['milestone'])
        cols = [] if single else [t.c.name]
        if with_props:
            for prop in s['props']:
                if prop == 'completed':
                    col = (t.c.completed != 0).label(prop)
                else:
                    col = t.c[prop]
                cols.append(col)
        q = q.with_only_columns(cols)

        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        if single:
            if len(cols) == 1:
                return res.scalar()
            return res.fetchone()
        return { row['name']: row for row in res.fetchall() }


