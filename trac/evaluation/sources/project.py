from formencode import Invalid
from trac.util.translation import _

from trac.evaluation.api.model import ModelSource
from trac.evaluation.api.area import SubjectArea
from trac.evaluation.api.error import EvalSourceError, DataNotReadyError
from trac.evaluation.project import ProjectEvaluation

__all__ = ['ProjectFormQuery']



class ProjectFormQuery(ModelSource):

    def __init__(self, model):
        super(ProjectFormQuery, self).__init__(model)
        self.peval = ProjectEvaluation(self.env)
        self._state.update({
            'area': SubjectArea.PROJECT,
            'criterion': '*',
        })

    # area setup methods
    def project(self, pid):
        self._state['project_id'] = pid
        return self
    user      = lambda self, x: self
    milestone = lambda self, x: self

    def criterion(self, alias):
        self._state['criterion'] = alias
        return self

    def get(self, all_completed=True):
        '''Get criteria values for project

        Return single value if single criterion was set in state
        or dict { <criterion alias>: <value>}

        `all_completed`: success only if data is ready for all criteria / selected criterion
        '''
        s = self._state
        criterion = s['criterion']
        single = criterion != '*'
        criteria = self.model.get_project_eval_criteria()

        if single and criterion not in criteria:
            raise EvalSourceError(_('Criterion "%(name)s" is not defined in project evaluation criteria',
                                    name=criterion))

        dbvals = self.peval.fetch_db_data(s['project_id'], single and criterion or None)
        if all_completed:
            params = {}
        else:
            # no exceptions, just None for invalid and missed values
            params = {
                'if_invalid': None,
                'if_empty': None,
                'if_missing': None,
            }
        if single:
            validator = self.peval.create_criterion_validator(criteria[criterion]['scale'], params)
        else:
            validator = self.peval.create_validator(criteria, params)

        try:
            return validator.to_python(dbvals)
        except Invalid:
            raise DataNotReadyError(_('Some project evaluation data is not ready or invalid'))
