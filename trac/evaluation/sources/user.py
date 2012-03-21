from trac.user.api import UserManagement, GroupLevel

__all__ = ['Info']



class Info(object):

    def __init__(self, env):
        self.env = env
        self.userman = UserManagement(self.env)

    def get_team_size(self, team_id):
        return self.userman.get_group_user_count(team_id, GroupLevel.TEAM)


