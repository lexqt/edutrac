#from trac.evaluation.sources.ticket import *
#from trac.evaluation.sources.user import *

from trac.evaluation.sources import ticket as tktsrc
from trac.evaluation.sources import user as usersrc
from trac.evaluation.sources import milestone as mssrc



class SourceAccessor(object):

    def __init__(self, model):
        self.model = model

    def __getitem__(self, name):
        if name == 'ticket':
            return tktsrc.Query(self.model.env)
        elif name == 'milestone':
            return mssrc.TeamEvalQuery(self.model.env)
        elif name == 'milestone_info':
            return mssrc.Info(self.model.env)


