from trac.core import implements, Component, ExtensionPoint, TracError
from trac.perm import IPermissionRequestor, IPermissionGroupProvider, IPermissionPolicy, PermissionSystem
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket
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



# Created by Norman Rasmussen on 2008-08-19.
# Copyright (c) 2008 Norman Rasmussen. All rights reserved.
# Based on the PrivateTicketsPlugin by Noah Kantrowitz


class VirtualTicketPermissionsPolicy(Component):
    """Central tasks for the VirtualTicketPermissions plugin."""

    implements(IPermissionRequestor, IPermissionPolicy)

    group_providers = ExtensionPoint(IPermissionGroupProvider)

    blacklist = ListOption('virtualticketpermissions', 'group_blacklist', default='anonymous, authenticated',
                           doc='Groups that do not affect the common membership check.')

    virtual_permissions = set([
        'TICKET_IS_REPORTER',
        'TICKET_IS_OWNER',
        'TICKET_IS_CC',
        'TICKET_IS_REPORTER_GROUP',
        'TICKET_IS_OWNER_GROUP',
        'TICKET_IS_CC_GROUP',
    ])

    # IPermissionPolicy(Interface)
    def check_permission(self, action, username, resource, perm):
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
            return self.check_ticket_permissions(action, perm, resource)
        return None

    # IPermissionRequestor methods
    def get_permission_actions(self):
        actions = ['TICKET_IS_REPORTER', 'TICKET_IS_OWNER', 'TICKET_IS_CC']
        group_actions = ['TICKET_IS_REPORTER_GROUP', 'TICKET_IS_OWNER_GROUP', 'TICKET_IS_CC_GROUP']
        all_actions = actions + [(a+'_GROUP', [a]) for a in actions]
        return all_actions + [('TICKET_IS_SELF', actions), ('TICKET_IS_GROUP', group_actions)]

    # Public methods
    def check_ticket_permissions(self, action, perm, res):
        """Return if this req is generating permissions for the given ticket ID."""
        try:
            tkt = Ticket(self.env, res.id)
        except TracError:
            return None # Ticket doesn't exist

        if action == 'TICKET_IS_SELF':
            return tkt['reporter'] == perm.username or \
                   perm.username == tkt['owner'] or \
                   perm.username in [x.strip() for x in tkt['cc'].split(',')]

        if action == 'TICKET_IS_REPORTER':
            return tkt['reporter'] == perm.username

        if action == 'TICKET_IS_CC':
            return perm.username in [x.strip() for x in tkt['cc'].split(',')]

        if action == 'TICKET_IS_OWNER':
            return perm.username == tkt['owner']

        if action == 'TICKET_IS_GROUP':
            result = self._check_group(perm.username, tkt['reporter']) or \
                     self._check_group(perm.username, tkt['owner'])
            for user in tkt['cc'].split(','):
                #self.log.debug('Private: CC check: %s, %s', req.authname, user.strip())
                if self._check_group(perm.username, user.strip()):
                    result = True
            return result

        if action == 'TICKET_IS_REPORTER_GROUP':
            return self._check_group(perm.username, tkt['reporter'])

        if action == 'TICKET_IS_OWNER_GROUP':
            return self._check_group(perm.username, tkt['owner'])

        if action == 'TICKET_IS_CC_GROUP':
            result = False
            for user in tkt['cc'].split(','):
                #self.log.debug('Private: CC check: %s, %s', req.authname, user.strip())
                if self._check_group(perm.username, user.strip()):
                    result = True
            return result

        # We should never get here
        return None

    # Internal methods
    def _check_group(self, user1, user2):
        """Check if user1 and user2 share a common group."""
        user1_groups = self._get_groups(user1)
        user2_groups = self._get_groups(user2)
        both = user1_groups.intersection(user2_groups)
        both -= set(self.blacklist)

        #self.log.debug('PrivateTicket: %s&%s = (%s)&(%s) = (%s)', user1, user2, ','.join(user1_groups), ','.join(user2_groups), ','.join(both))
        return bool(both)

    def _get_groups(self, user):
        # Get initial subjects
        groups = set([user])
        for provider in self.group_providers:
            for group in provider.get_permission_groups(user):
                groups.add(group)

        perms = PermissionSystem(self.env).get_all_permissions()
        repeat = True
        while repeat:
            repeat = False
            for subject, action in perms:
                if subject in groups and action.islower() and action not in groups:
                    groups.add(action)
                    repeat = True

        return groups

