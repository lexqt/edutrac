from trac.evaluation.api.model import ModelSource
from trac.evaluation.api.error import EvalSourceError

from trac.util.translation import _
from trac.user.api import UserManagement, GroupLevel, UserRole
from trac.project.api import ProjectManagement

__all__ = ['Info']



class Info(ModelSource):

    def __init__(self, model):
        super(Info, self).__init__(model)
        self.userman = UserManagement(self.env)
        self.projman = ProjectManagement(self.env)
        self._state.update({
            'role': UserRole.DEVELOPER,
        })

    def role(self, role):
        self._state['role'] = role

    def team_size(self):
        self._check_project()
        s = self._state
        return self.projman.get_project_user_count(s['project_id'], role=UserRole.DEVELOPER)

    def users(self):
        self._check_project()
        s = self._state
        return self.projman.get_project_users(s['project_id'], s['role'])

    def _check_project(self):
        if 'project_id' not in self._state:
            raise EvalSourceError(_('Project must be defined to get team size'))

