from trac.evaluation.api.model import ModelVariable, \
    SubjectArea, ClusterArea, \
    RatioScale
from trac.evaluation.sources import tktsrc


class CountTickets(ModelVariable):
    '''Count tickets using several filters'''

    scale = RatioScale(int)

    # parameters to override

    # Expression for ticket query.
    # E.g.:
    # filter_tickets = (
    #             (tktsrc.Status()=='closed') &
    #             (tktsrc.Resolution()=='done')
    #             )
    filter_tickets = None

    # Is it necessary to limit users to team members only
    # for project area queries
    limit_project_users = True

    # Expression to determine ticket field used to limit users
    limit_project_users_field = tktsrc.Owner()

    # Allow field used to filter query to be empty,
    # e.g. tickets with owner - nobody.
    limit_allow_empty = False

    # Field expression used for user area query filtering
    user_field = tktsrc.Owner()

    def extra_filter(self, query):
        '''Do some more specific query filtration before its execution'''

    def _get(self):
        q = self.model.sources['ticket']
        q.user_field(self.user_field)
        self > q
        if self.filter_tickets:
            q.where(self.filter_tickets)
        if self.limit_project_users and self['area'] == SubjectArea.PROJECT:
            q.limit_to_project_users(self.limit_project_users_field, allow_empty=self.limit_allow_empty)
        self.extra_filter(q)
        res = q.count()
        return res


class MultiVars(ModelVariable):
    '''Process several model variables'''

    # Variables names
    var_list = None

    def process_variables(self, *variables):
        '''Process declared variables (set state, get value, combine)
        '''
        raise NotImplementedError

    def _get(self):
        variables = []
        for name in self.var_list:
            var = self.model.vars[name]
            variables.append(var)
        value = self.process_variables(*variables)
        return value


class TwoVarsRatio(ModelVariable):
    '''Ratio of two variables (var1 / var2)'''

    # Variables names
    var1 = None
    var2 = None

    # Convert var1 type to the type of current var.
    # May be usefull when doing division of two integer variables
    # but want to get accurate float value.
    convert_type = True

    def _get(self):
        var1  = self.model.vars[self.var1]
        var2  = self.model.vars[self.var2]
        self > var1
        self > var2
        var1 = var1.get()
        var2 = var2.get()
        if not var2:
            return 0
        if self.convert_type:
            var1 = self.scale.type(var1)
        return var1 / var2


class TeamMilestoneVariable(ModelVariable):

    cluster_support = ClusterArea.MILESTONE

    # Include authors in evaluation data for one user.
    # without authors: data = [ val1, val2, ... ]
    # with authors:    data = { 'user1': val1, 'user2': val2, ... }
    with_authors = False

    # If all users must complete evaluation forms to get
    # variable value or partial data can be used
    all_completed = True

    # Only approved results should be fetched and used
    only_approved = False

    def process_results(self, results, msum, team_size):
        '''Process evaluation data.

        `results`: <user_data> for user area
                   { 'user1': <user_data>, ... } for project area
        `msum`: sum that should be distributed among team members
        `team_size`: project team size
        For contents of <user_data> - see `with_authors`.
        '''
        raise NotImplementedError

    def _get(self):
        s = self._state
        q = self.model.sources['milestone_team']
        minfo = self.model.sources['milestone_info']
        uinfo = self.model.sources['user_info']
        self > q
        vals = q.earned_values(with_usernames=self.with_authors,
                               all_completed=self.all_completed,
                               only_approved=self.only_approved)
        msum = minfo.get_team_eval_sum(syllabus_id=self.model.syllabus_id)
        team_size = uinfo.project(s['project_id']).team_size()
        value = self.process_results(vals, msum, team_size)
        return value

class ProjectCriteria(ModelVariable):

    subject_support = SubjectArea.PROJECT

    # If values of all project evaluation criteria must be defined
    all_completed = True

    def process_criteria(self, criteria, values):
        '''Process evaluation data.

        `criteria`: see `EvaluationModel.PROJECT_EVAL_CRITERIA`
        `values`: dict { <criterion alias>: <value> }
        '''
        raise NotImplementedError

    def _get(self):
        criteria = self.model.get_project_eval_criteria()
        q = self.model.sources['project']
        self > q
        values = q.get(all_completed=self.all_completed)
        value = self.process_results(criteria, values)
        return value


class ProjectMilestones(ModelVariable):

    subject_support = SubjectArea.PROJECT

    # Process only completed milestones
    only_completed = True

    # Process only approved milestones
    only_approved = True

    def process_milestones(self, milestones, total_weight):
        '''Process milestones data.

        `milestones`: dict { <milestone name>:
            {
                'name': <unicode>,
                'weight': <int>,
                'rating': <int 0..100>,
                'approved': <bool>,
                'completed': <bool>
            }
        }
        `total_weight`: sum of weights of all project milestones
        '''
        raise NotImplementedError

    def _get(self):
        q = self.model.sources['milestone']
        self > q
        q.include(weight=True, rating=True, approved=True, completed=True)
        milestones = q.get()
        total_weight = reduce(lambda s, m: s+m['weight'], milestones.values(), 0)
        if self.only_completed or self.only_approved:
            names = milestones.keys()
            for name in names:
                if self.only_completed and not milestones[name]['completed']:
                    del milestones[name]
                    continue
                if self.only_approved and not milestones[name]['approved']:
                    del milestones[name]
                    continue
        value = self.process_milestones(milestones, total_weight)
        return value

