import threading

from trac.core import Component, TracError
from trac.util.text import exception_to_unicode
from trac.util.translation import _, N_
from trac.config import Option

from trac.project.api import ProjectManagement
from trac.evaluation.api.model import EvaluationModel

__all__ = ['EvaluationManagement']



class EvaluationManagement(Component):

    package = Option('evaluation', 'package', default='',
                        doc="""Name of evaluation model package""", switcher=True)

    def __init__(self):
        self._model_cache_lock = threading.Lock()
        self.pm = ProjectManagement(self.env)
        self._models = {}

    def get_model(self, syllabus_id):
        syllabus_id = int(syllabus_id)
        with self._model_cache_lock:
            if syllabus_id not in self._models:
                pkg = self.package.syllabus(syllabus_id)
                import os.path
                ev_path = os.path.join(self.env.path, 'evaluation')
                try:
                    import imp
                    fp, path, desc = imp.find_module(pkg, [ev_path])
                    p = imp.load_module(pkg, fp, path, desc)
                    if not issubclass(p.Model, EvaluationModel):
                        raise Exception(_('Syllabus evaluation package must contain '
                                          'class Model that is a subclass of EvaluationModel'))
                    model = p.Model(syllabus_id)
                except ImportError:
                    raise TracError(_('Can not import evaluation package "%(pkg_name)s" specified '
                                      ' in syllabus configuration', pkg_name=pkg),
                                    _('Error occurred while loading evaluation model'))
                except Exception, e:
                    raise TracError(exception_to_unicode(e,),
                                    _('Error occurred while loading evaluation model'))
                self.env.component_activated(model)
                model.sconfig = model.configs.syllabus(syllabus_id)
                self._models[syllabus_id] = model
            m = self._models[syllabus_id]
        return m

    def get_model_by_project(self, project_id):
        syllabus_id = self.pm.get_project_syllabus(project_id)
        return self.get_model(syllabus_id)

