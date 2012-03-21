from trac.core import Component, TracError
from trac.util.text import exception_to_unicode
from trac.config import Option

from trac.project.api import ProjectManagement
from trac.evaluation.api.model import EvaluationModel

__all__ = ['EvaluationManagement']



class EvaluationManagement(Component):

    models = {}

    package = Option('evaluation', 'package', default='',
                        doc="""Name of evaluation model package""", switcher=True)

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    def get_model(self, syllabus_id):
        syllabus_id = int(syllabus_id)
        if syllabus_id not in self.models:
            pkg = self.package.syllabus(syllabus_id)
            import os.path
            ev_path = os.path.join(self.env.path, 'evaluation')
            try:
                import imp
                fp, path, desc = imp.find_module(pkg, [ev_path])
                p = imp.load_module(pkg, fp, path, desc)
                if not issubclass(p.Model, EvaluationModel):
                    raise Exception('Syllabus evaluation package must define Model as subclass of EvaluationModel')
                model = p.Model()
            except Exception, e:
                raise TracError(exception_to_unicode(e), 'Error occurred while loading evaluation model')
            self.env.component_activated(model)
            model.sconfig = model.configs.syllabus(syllabus_id)
            self.models[syllabus_id] = model
        return self.models[syllabus_id]

    def get_model_by_project(self, project_id):
        syllabus_id = self.pm.get_project_syllabus(project_id)
        return self.get_model(syllabus_id)

