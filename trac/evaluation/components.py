from trac.core import Component, implements
from trac.ticket.api import ITicketChangeListener
from trac.db import with_transaction
from trac.evaluation.api import EvaluationManagement


class TicketStatistics(Component):

    implements(ITicketChangeListener)

    def __init__(self):
        self.em = EvaluationManagement(self.env)

    # ITicketChangeListener methods

    def ticket_created(self, tkt):
        self.ticket_changed(tkt, '', tkt['reporter'], None)

    def ticket_changed(self, tkt, comment, author, old_values):
        assert tkt.pid is not None
        is_new = old_values is None
        self.update_ticket(tkt, is_new=is_new)

    def ticket_deleted(self, tkt):
        # values from ticket_evaluation removed ON CASCADE
        pass

    #

    def update_ticket(self, ticket, is_new=False):
        value = self.em.get_model_by_project(ticket.pid).get_ticket_value(ticket)
        self.update_ticket_value(ticket.id, value, insert=is_new)

    def update_ticket_value(self, ticket_id, value, insert=False):
        @with_transaction(self.env)
        def update_value(db):
            if insert:
                query = '''
                    INSERT INTO ticket_evaluation (ticket_id, value)
                    VALUES (%s, %s)
                    '''
                params = (ticket_id, value)
            else:
                query = '''
                    UPDATE ticket_evaluation
                    SET value=%s
                    WHERE ticket_id=%s
                    '''
                params = (value, ticket_id)
            cursor = db.cursor()
            cursor.execute(query, params)

