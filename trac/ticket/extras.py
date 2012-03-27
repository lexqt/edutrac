from trac.core import implements, Component
from trac.ticket.api import ITicketManipulator
from trac.config import ListOption, IntOption
from trac.project.api import ProjectManagement
from trac.util.translation import _


__all__ = ['ExtraTicketControl']



class ExtraTicketControl(Component):

    # Syllabus options
    busy_statuses = ListOption('ticket-workflow-config', 'busy_status', default='assigned', sep='|',
                        doc="""List of statuses used to count tickets,
                        which owner is really working on""", switcher=True)

    # Project options
    max_busy = IntOption('ticket-workflow-config', 'max_busy', 100, switcher=True)

    implements(ITicketManipulator)

    # ITicketManipulator methods

    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket, action):
        pid = ticket.pid
        syllabus_id = ProjectManagement(self.env).get_project_syllabus(pid)
        res = []

        busy_statuses = self.busy_statuses.syllabus(syllabus_id)
        owner = ticket['owner']
        if not owner or ticket['status'] not in busy_statuses:
            return res

        db = self.env.get_read_db()
        cursor = db.cursor()

        query = '''
            SELECT id
            FROM ticket
            WHERE owner=%s AND status IN %s
            '''
        cursor.execute(query, (owner, tuple(busy_statuses)))

        cnt = cursor.rowcount
        is_new_assign = True
        for row in cursor:
            if row[0] == ticket.id:
                is_new_assign = False
                break

        max_cnt = self.max_busy.project(ticket.pid)

        if is_new_assign:
            cnt += 1

        if cnt > max_cnt:
            res.append(('owner', _('Can not assign user %(user)s to ticket.'
                       ' User is already working on %(cnt)s task(s)', user=owner, cnt=max_cnt)))

        return res

