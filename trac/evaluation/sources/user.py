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
        return self

    # Terminal methods

    def count(self):
        self.check_state_and_raise('project_id', 'role')
        s = self._state
        return self.projman.get_project_user_count(s['project_id'], role=s['role'])

    def users(self):
        self.check_state_and_raise('project_id')
        s = self._state
        return self.projman.get_project_users(s['project_id'], s['role'])

