from trac.core import Component
from trac.config import IntOption

from trac.project.api import ProjectManagement



class MilestoneEvaluation(Component):
    """
    This class provides API to control milestone evaluation.
    """

    milestone_eval_sum = IntOption('evaluation', 'milestone_eval_sum', default='100',
                        doc="""Sum, that should be distributed between developers in a team.""", switcher=True)

    def __init__(self):
        md = self.env.get_sa_metadata()
        self.ev_tab  = md.tables['team_milestone_evaluation']
        self.res_tab = md.tables['team_milestone_evaluation_results']

    def get_completed(self, username, pid, milestone):
        '''Return (<bool>, <datetime>) or None'''
        assert username
        res = self._get_completed_query(pid, milestone, username)
        return res and (res['complete'], res['completed_on'])

    def get_completed_all(self, pid, milestone):
        '''Return dict {<username>: (<bool>, <datetime>) or None, ...}'''
        pm = ProjectManagement(self.env)
        users = pm.get_project_users(pid)
        res = self._get_completed_query(pid, milestone)
        res = {r['username']: (r['complete'], r['completed_on']) for r in res}
        return {u: res.get(u) for u in users}

    def check_completed_all(self, pid, milestone):
        pm = ProjectManagement(self.env)
        users = pm.get_project_users(pid)
        t = self.ev_tab
        q = t.select().with_only_columns([t.c.username]).\
                where((t.c.project_id==pid) & (t.c.milestone==milestone))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        users_compl = [r[0] for r in res.fetchall()]
        if not users_compl:
            return False
        return set(users) <= set(users_compl)

    def _get_completed_query(self, pid, milestone, username=None):
        t = self.ev_tab
        where_expr = (t.c.project_id==pid) & (t.c.milestone==milestone)
        columns = [t.c.complete, t.c.completed_on]
        if username:
            where_expr = where_expr & (t.c.username==username)
        else:
            columns = t.c.username + columns
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
                     [t.c.target, t.c.value, t.c.comment]).where((t.c.author==username) &
                                               (t.c.project_id==pid) &
                                               (t.c.milestone==milestone))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        res = res.fetchall()
        return res or []

    def save_results(self, author, pid, milestone, completed_on, results, is_new=False):
        '''Save milestone team evaluation results.
        `results` is list of dicts {'target': ..., 'value': ..., 'comment': ...}
        '''
        rt = self.res_tab
        et = self.ev_tab
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
