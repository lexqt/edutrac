from trac.core import Component, implements
from trac.admin.api import IAdminCommandProvider




class EvaluationAdmin(Component):

    implements(IAdminCommandProvider)

    # IAdminCommandProvider methods
    
    def get_admin_commands(self):
        yield ('evaluation tickets update project', '<pid>',
               'Update tickets values (for all tickets by project)',
               None, self._do_update_tickets_project)

    def _do_update_tickets_project(self, pid):
        from trac.evaluation.components import TicketStatistics
        from trac.ticket.model import Ticket
        ts = TicketStatistics(self.env)
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute('''
            SELECT id FROM ticket WHERE project_id=%s
            ''', (pid,))
        rows = cursor.fetchall()
        if not rows:
            return
        ids = [r[0] for r in rows]
        cursor.close()
        for id_ in ids:
            print 'Updating value for ticket #%s' % id_
            ticket = Ticket(self.env, id_)
            ts.update_ticket(ticket)

