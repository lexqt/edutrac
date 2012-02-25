import re

from trac.core import Component

class ProjectSystem(Component):
    """
    Project Management core component
    """

    def __init__(self):
        pass

    # Request init methods

    def init_request(self, req):
        self.extract_project_id(req)
        req._proj_syl_cache = {} # project_id: syllabus_id

    def extract_project_id(self, req):
        match = re.match(r'(.*)/project/(\d+)/?(.*)$', req.path_info)
        if match:
            req.args['pid'] = int(match.group(2))
            req.environ['PATH_INFO'] = str(match.group(1) + '/' + match.group(3)).rstrip('/')
            return True
        return False
