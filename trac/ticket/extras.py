from trac.core import implements, Component, TracError
from trac.perm import IPermissionRequestor, IPermissionPolicy
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket
from trac.config import ListOption, IntOption
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
        syllabus_id = ticket.syllabus_id
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


# Reduced version of VirtualTicketPermissionsPolicy
# Original by Norman Rasmussen on 2008-08-19.
# Copyright (c) 2008 Norman Rasmussen. All rights reserved.
# Based on the PrivateTicketsPlugin by Noah Kantrowitz


class VirtualTicketPermissionsPolicy(Component):
    """Central tasks for the VirtualTicketPermissions plugin."""

    implements(IPermissionRequestor, IPermissionPolicy)

    virtual_permissions = set([
        'TICKET_IS_REPORTER',
        'TICKET_IS_OWNER',
        'TICKET_IS_NOT_OWNER',
        'TICKET_IS_CC',
    ])

    # IPermissionPolicy

    def check_permission(self, action, username, resource, perm, req):
        if username == 'anonymous' or \
           not action in self.virtual_permissions:
            # In these two cases, checking makes no sense
            return None
        if 'TRAC_ADMIN' in perm:
            # In this case, checking makes no sense
            return True

        # Look up the resource parentage for a ticket.
        while resource:
            if resource.realm == 'ticket':
                break
            resource = resource.parent
        if resource and resource.realm == 'ticket' and resource.id is not None:
            return self._check_ticket_permissions(action, perm, resource)
        return None

    # IPermissionRequestor

    def get_permission_actions(self):
        return list(self.virtual_permissions)

    # Internal methods

    def _check_ticket_permissions(self, action, perm, res):
        """Return if this req is generating permissions for the given ticket."""
        try:
            tkt = Ticket(self.env, res.id)
        except TracError:
            return None # Ticket doesn't exist

        if action == 'TICKET_IS_OWNER':
            return perm.username == tkt['owner']

        if action == 'TICKET_IS_NOT_OWNER':
            return perm.username != tkt['owner']

        if action == 'TICKET_IS_REPORTER':
            return tkt['reporter'] == perm.username

        if action == 'TICKET_IS_CC':
            return perm.username in [x.strip() for x in tkt['cc'].split(',')]

