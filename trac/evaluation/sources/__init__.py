from trac.evaluation.sources import ticket as tktsrc
from trac.evaluation.sources import user as usersrc
from trac.evaluation.sources import milestone as mssrc
from trac.evaluation.sources import project as projsrc



class SourceAccessor(object):

    _source_aliases = {
        'ticket':           tktsrc.Query,
        'project':          projsrc.ProjectFormQuery,
        'milestone':        mssrc.Query,
        'milestone_team':   mssrc.TeamEvalQuery,
        'milestone_info':   mssrc.Info,
        'user_info':        usersrc.Info,
    }

    def __init__(self, model):
        self.model = model

    def __getitem__(self, name):
        cls = self._source_aliases.get(name)
        if cls:
            return cls(self.model)
        raise ValueError('Unknown source name argument')


