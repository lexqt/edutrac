from sqlalchemy.sql import func

from trac.core import Component

from trac.project.api import ProjectManagement
from trac.evaluation.api import SubjectArea
from trac.evaluation.milestone import MilestoneEvaluation

__all__ = ['Info', 'TeamEvalQuery']



class Info(Component):

    def __init__(self):
#        self.env = env
        self.meval = MilestoneEvaluation(self.env)
        self.projman = ProjectManagement(self.env)

    def get_team_eval_sum(self, project_id=None, syllabus_id=None):
        if project_id is not None:
            syllabus_id = self.projman.get_project_syllabus(project_id)
        return self.meval.milestone_eval_sum.syllabus(syllabus_id)



class TeamEvalQuery(object):

    def __init__(self, env):
        self.env = env
        self.projman = ProjectManagement(self.env)
        self.meval = MilestoneEvaluation(self.env)
        self.sa_metadata = env.get_sa_metadata()
        self.sa_conn     = env.get_sa_connection()
        self.ev_tab  = self.sa_metadata.tables['team_milestone_evaluation']
        self.res_tab = self.sa_metadata.tables['team_milestone_evaluation_results']
        self._state = {
            'area': None, # query subject area
        }

    # Area setup methods

    def project(self, pid):
#        s = self._state
#        if s['area'] != SubjectArea.USER:
#            s['area'] = SubjectArea.PROJECT
#        s['project_id'] = pid
        self._state['project_id'] = pid
        return self

    def user(self, username):
#        self._state.update({
#            'area': SubjectArea.USER,
#            'username': username
#        })
        self._state['username'] = username
        return self

#    def group(self, gid):
#        self._state.update({
#            'area': SubjectArea.GROUP,
#            'group_id': gid,
#            'syllabus_id': self.projman.get_group_syllabus(gid)
#        })
#        return self
#
#    def syllabus(self, sid):
#        self._state.update({
#            'area': SubjectArea.SYLLABUS,
#            'syllabus_id': sid
#        })
#        return self

    def milestone(self, milestone):
        self._state['milestone'] = milestone
        return self

    # Terminal methods

    def data_ready(self):
        if not self._check_state('project_id', 'milestone'):
            raise ValueError('Not enough query state arguments')
        return self.meval.check_completed_all(self._state['project_id'], self._state['milestone'])

    def earned_values(self, with_usernames=False):
        if not self._check_state('username', 'project_id', 'milestone'):
            raise ValueError('Not enough query state arguments')
        if not self.data_ready():
            raise ValueError('Not enough data collected')

        s = self._state
        members = self.projman.get_project_users(s['project_id'])
        t = self.res_tab
        cols = [t.c.value]
        if with_usernames:
            cols.insert(0, t.c.author)
        q = t.select().with_only_columns(cols).where(t.c.author.in_(members) &
                                               (t.c.project_id==s['project_id']) &
                                               (t.c.milestone==s['milestone']) &
                                               (t.c.target==s['username']))
        conn = self.env.get_sa_connection()
        res = conn.execute(q)
        res = res.fetchall()
        if with_usernames:
            return {r['author']: r['value'] for r in res}
        else:
            return [r[0] for r in res]

    #

    def _check_state(self, *args):
        s = self._state
        return all(map(lambda x: x is not None, [s.get(k) for k in args]))
