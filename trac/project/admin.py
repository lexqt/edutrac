from trac.core import Component, implements
from trac.admin.api import IAdminPanelProvider
from trac.web.chrome import ITemplateProvider

from api import ProjectManagement

class ProjectManagementAdmin(Component):
    """
    Provides admin interface for GroupManagement plugin.
    """

    implements(ITemplateProvider, IAdminPanelProvider)

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # IAdminPanelProvider

    def get_admin_panels(self, req):
        if req.perm.has_permission('TRAC_ADMIN'):
            yield ('projects', 'Projects', 'projects',   'Projects')
            yield ('projects', 'Projects', 'syllabuses', 'Syllabuses')

    def render_admin_panel(self, req, cat, page, version):
        req.perm.require('TRAC_ADMIN')
        if cat == 'projects' and page == 'projects':
            return ''

    # ITemplateProvider

    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return []

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        ClearSilver templates.
        """
        from pkg_resources import resource_filename
        return [resource_filename(__name__, 'templates')]

