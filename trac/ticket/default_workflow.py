# -*- coding: utf-8 -*-
#
# Copyright (C) 2006-2009 Edgewall Software
# Copyright (C) 2006 Alec Thomas
# Copyright (C) 2007 Eli Carter
# Copyright (C) 2007 Christian Boos <cboos@neuf.fr>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Eli Carter

import pkg_resources
import threading

from genshi.builder import tag

from trac.core import *
from trac.perm import PermissionSystem
from trac.env import IEnvironmentSetupParticipant
from trac.config import Configuration, ExtensionOption, ListOption, OrderedExtensionsOption
from trac.ticket.api import ITicketActionController, ITicketManipulator, TicketSystem
from trac.ticket.model import Resolution
from trac.util.text import obfuscate_email_address
from trac.util.translation import _, tag_
from trac.web.chrome import Chrome

from trac.project.api import ProjectManagement
from trac.user.api import UserManagement

# -- Utilities for the ConfigurableTicketWorkflow

def parse_workflow_config(rawactions):
    """Given a list of options from [ticket-workflow]"""
    actions = {}
    for option, value in rawactions:
        parts = option.split('.')
        action = parts[0]
        if action not in actions:
            actions[action] = {'oldstates': '', 'newstate': ''}
        if len(parts) == 1:
            # Base name, of the syntax: old,states,here -> newstate
            try:
                oldstates, newstate = [x.strip() for x in value.split('->')]
            except ValueError:
                continue # Syntax error, a warning will be logged later
            actions[action]['newstate'] = newstate
            actions[action]['oldstates'] = oldstates
        else:
            action, attribute = option.split('.')
            actions[action][attribute] = value
    # Fill in the defaults for every action, and normalize them to the desired
    # types
    def as_list(key):
        value = attributes.get(key, '')
        return [item for item in (x.strip() for x in value.split(',')) if item]
    
    for action, attributes in actions.items():
        attributes['alias'] = action
        # Default the 'name' attribute to the name used in the ini file
        if 'name' not in attributes:
            attributes['name'] = action
        # If not specified, an action is not the default.
        attributes['default'] = int(attributes.get('default', 0))
        # If operations are not specified, that means no operations
        attributes['operations'] = as_list('operations')
        # If no permissions are specified, then no permissions are needed
        attributes['permissions'] = as_list('permissions')
        # Normalize the oldstates
        attributes['oldstates'] = as_list('oldstates')
        # Normalize include/exclude types
        attributes['includetype'] = map(lambda s: s.lower(), as_list('includetype'))
        attributes['excludetype'] = map(lambda s: s.lower(), as_list('excludetype'))
    return actions

def get_workflow_config(config):
    """Usually passed self.config, this will return the parsed ticket-workflow
    section.
    """
    raw_actions = list(config.options('ticket-workflow'))
    actions = parse_workflow_config(raw_actions)
    return actions

def load_workflow_config_snippet(config, filename):
    """Loads the ticket-workflow section from the given file (expected to be in
    the 'workflows' tree) into the provided config.
    """
    filename = pkg_resources.resource_filename('trac.ticket',
                    'workflows/%s' % filename)
    new_config = Configuration(filename)
    for name, value in new_config.options('ticket-workflow'):
        config.set('ticket-workflow', name, value)


class IValidUserProvider(Interface):

    def get_users(self, req, ticket, next_action_obj):
        """Returns a list of valid usernames for set_owner ticket actions"""
        raise NotImplementedError


class ConfigurableTicketWorkflow(Component):
    """Ticket action controller which provides actions according to a
    workflow defined in trac.ini.
    
    The workflow is idefined in the `[ticket-workflow]` section of the
    [wiki:TracIni#ticket-workflow-section trac.ini] configuration file.
    """

    action_controllers = OrderedExtensionsOption('ticket', 'workflow',
        ITicketActionController, default='ConfigurableTicketWorkflow',
        include_missing=False, syllabus_switcher=True,
        doc="""Ordered list of workflow controllers to use for ticket actions
            (''since 0.11'').""")

    valid_user_provider = ExtensionOption('ticket-workflow-config', 'valid_user_provider',
                                           IValidUserProvider, 'UserGroupProvider')
    
    implements(ITicketActionController, IEnvironmentSetupParticipant, ITicketManipulator)

    def __init__(self, *args, **kwargs):
        self.pm = ProjectManagement(self.env)
        self._actions = {} # syllabus_id: actions
        self._actions_lock = threading.Lock()

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        """When an environment is created, we provide the basic-workflow,
        unless a ticket-workflow section already exists.
        """
        if not 'ticket-workflow' in self.config.sections():
            load_workflow_config_snippet(self.config, 'basic-workflow.ini')
            self.config.save()
            actions = get_workflow_config(self.config)

    def environment_needs_upgrade(self, db):
        """The environment needs an upgrade if there is no [ticket-workflow]
        section in the config.
        """
#        return not list(self.config.options('ticket-workflow'))
        return False

    def upgrade_environment(self, db):
        """Insert a [ticket-workflow] section using the original-workflow"""
        load_workflow_config_snippet(self.config, 'original-workflow.ini')
        self.config.save()
        actions = get_workflow_config(self.config)
        info_message = """

==== Upgrade Notice ====

The ticket Workflow is now configurable.

Your environment has been upgraded, but configured to use the original
workflow. It is recommended that you look at changing this configuration to use
basic-workflow. 

Read TracWorkflow for more information (don't forget to 'wiki upgrade' as well)

"""
        self.log.info(info_message.replace('\n', ' ').replace('==', ''))
        print info_message

    # ITicketActionController methods

    def get_ticket_actions(self, req, ticket):
        """Returns a list of (weight, action) tuples that are valid for this
        request and this ticket."""
        # Get the list of actions that can be performed

        # Determine the current status of this ticket.  If this ticket is in
        # the process of being modified, we need to base our information on the
        # pre-modified state so that we don't try to do two (or more!) steps at
        # once and get really confused.
        status = ticket._old.get('status', ticket['status']) or 'new'

        ticket_type = (ticket.get_value_or_default('type') or '').lower()
        ticket_perm = req.perm(ticket.resource)

        all_actions = self.get_actions(ticket=ticket, req=req).items()
        filtered_actions = []

        for action_name, action_info in all_actions:
            oldstates = action_info['oldstates']
            if oldstates == ['*'] or status in oldstates:
                # This action is valid in this state. Check permissions.
                required_perms = action_info['permissions']
                if not self._is_action_allowed(ticket_perm, required_perms):
                    continue
                # Check action include/exclude type
                # Check order: Exclude, Include
                exclude = action_info['excludetype']
                include = action_info['includetype']
                if ticket_type in exclude:
                    continue
                # if include is empty list, consider there are no restrictions
                elif include and ticket_type not in include:
                    continue
                filtered_actions.append((action_info['default'],
                                        action_name))
        if not (status in ['new', 'closed'] or \
                    status in self.get_available_statuses(ticket.pid)) \
                and 'TICKET_ADMIN' in ticket_perm:
            # State no longer exists - add a 'reset' action if admin.
            filtered_actions.append((0, '_reset'))
        return filtered_actions

    def _is_action_allowed(self, ticket_perm, required_perms):
        if not required_perms:
            return True
        # modified to assume required_perms as AND-values list not OR-values
        for permission in required_perms:
            if permission not in ticket_perm:
                return False
        return True

    def get_all_status(self, syllabus_id):
        """Return a list of all states described by the configuration.

        """
        all_status = set()
        for action_name, action_info in self.get_actions(syllabus_id=syllabus_id).items():
            all_status.update(action_info['oldstates'])
            all_status.add(action_info['newstate'])
        all_status.discard('*')
        all_status.discard('')
        return all_status
        
    def render_ticket_action_control(self, req, ticket, action):

        self.log.debug('render_ticket_action_control: action "%s"' % action)

        this_action = self.get_actions(ticket=ticket, req=req)[action]
        status = this_action['newstate']
        operations = set(this_action['operations'])
        current_owner = ticket._old.get('owner', ticket['owner'] or '(none)')
        if not (Chrome(self.env).show_email_addresses
                or 'EMAIL_VIEW' in req.perm(ticket.resource)):
            format_user = obfuscate_email_address
        else:
            format_user = lambda address: address
        current_owner = format_user(current_owner)

        control = [] # default to nothing
        hints = []
        if 'reset_workflow' in operations:
            control.append(tag("from invalid state "))
            hints.append(_("Current state no longer exists"))
        if 'del_owner' in operations:
            hints.append(_("The ticket will be disowned"))
        if 'set_owner' in operations:
            id = 'action_%s_reassign_owner' % action
            selected_owner = req.args.get(id, req.authname)

            owners = self.get_valid_owners(req, ticket, this_action)

            if owners == None:
                owner = req.args.get(id, req.authname)
                control.append(tag_('to %(owner)s',
                                    owner=tag.input(type='text', id=id,
                                                    name=id, value=owner)))
                hints.append(_("The owner will be changed from "
                               "%(current_owner)s",
                               current_owner=current_owner))
            elif len(owners) == 1:
                owner = tag.input(type='hidden', id=id, name=id,
                                  value=owners[0])
                formatted_owner = format_user(owners[0])
                control.append(tag_('to %(owner)s ',
                                    owner=tag(formatted_owner, owner)))
                if ticket['owner'] != owners[0]:
                    hints.append(_("The owner will be changed from "
                                   "%(current_owner)s to %(selected_owner)s",
                                   current_owner=current_owner,
                                   selected_owner=formatted_owner))
            else:
                control.append(tag_('to %(owner)s', owner=tag.select(
                    [tag.option(x, value=x,
                                selected=(x == selected_owner or None))
                     for x in owners],
                    id=id, name=id)))
                hints.append(_("The owner will be changed from "
                               "%(current_owner)s",
                               current_owner=current_owner))
        if 'set_owner_to_self' in operations and \
                ticket._old.get('owner', ticket['owner']) != req.authname:
            hints.append(_("The owner will be changed from %(current_owner)s "
                           "to %(authname)s", current_owner=current_owner,
                           authname=req.authname))
        if 'set_previous_owner' in operations:
            new_owner = self.get_previous_owner(ticket) or '(none)'
            hints.append(_("The owner will be changed from "
                           "%(current_owner)s to %(selected_owner)s",
                           current_owner=current_owner,
                           selected_owner=new_owner))
        if 'set_resolution' in operations:
            resolutions = self.get_valid_resolutions(this_action, ticket)
            if not resolutions:
                raise TracError(_("Your workflow attempts to set a resolution "
                                  "but none is defined (configuration issue, "
                                  "please contact your Trac admin)."))
            id = 'action_%s_resolve_resolution' % action
            if len(resolutions) == 1:
                resolution = tag.input(type='hidden', id=id, name=id,
                                       value=resolutions[0])
                control.append(tag_('as %(resolution)s',
                                    resolution=tag(resolutions[0],
                                                   resolution)))
                hints.append(_("The resolution will be set to %(name)s",
                               name=resolutions[0]))
            else:
                selected_option = req.args.get(id, 
                        TicketSystem(self.env).default_resolution)
                control.append(tag_('as %(resolution)s',
                                    resolution=tag.select(
                    [tag.option(x, value=x,
                                selected=(x == selected_option or None))
                     for x in resolutions],
                    id=id, name=id)))
                hints.append(_("The resolution will be set"))
        if 'del_resolution' in operations:
            hints.append(_("The resolution will be deleted"))
        if 'leave_status' in operations:
            control.append(_('as %(status)s ',
                             status= ticket._old.get('status',
                                                     ticket['status'])))
        else:
            if status != '*':
                hints.append(_("Next status will be '%(name)s'", name=status))
        if 'notify_owner' in operations:
            hints.append(_('Owner will be notified by email'))
        if 'comment' in operations:
            comment_hint = _("Leave comment without any change to ticket")
            if this_action.get('notify'):
                users = self.valid_user_provider.get_users(req, ticket, this_action)
                if users:
                    id = 'action_%s_comment_notify' % action
                    selected_user = req.args.get(id, ticket['reporter'])
                    control.append(tag.select(
                                            [tag.option(x, value=x,
                                             selected=(x == selected_user or None))
                                             for x in users],
                                        id=id, name=id))
                    hints.append(comment_hint +
                                     _(' and notify only selected user'))
                else:
                    hints.append(comment_hint)
            else:
                hints.append(comment_hint)
        return (this_action['name'], tag(*control), '. '.join(hints))

    def get_ticket_changes(self, req, ticket, action):
        this_action = self.get_actions(ticket=ticket, req=req)[action]

        # Enforce permissions
        if not self._has_perms_for_action(req, this_action, ticket.resource):
            # The user does not have any of the listed permissions, so we won't
            # do anything.
            return {}

        updated = {}
        # Status changes
        status = this_action['newstate']
        if status != '*':
            updated['status'] = status

        for operation in this_action['operations']:
            if operation == 'reset_workflow':
                updated['status'] = 'new'
            elif operation == 'del_owner':
                updated['owner'] = None
            elif operation == 'set_owner':
                newowner = req.args.get('action_%s_reassign_owner' % action,
                                    this_action.get('set_owner'))
                # If there was already an owner, we get a list, [new, old],
                # but if there wasn't we just get new.
                if type(newowner) == list:
                    newowner = newowner[0]
                updated['owner'] = newowner
            elif operation == 'set_owner_to_self':
                updated['owner'] = req.authname
            elif operation == 'set_previous_owner':
                updated['owner'] = self.get_previous_owner(ticket)
            elif operation == 'del_resolution':
                updated['resolution'] = None
            elif operation == 'set_resolution':
                newresolution = req.args.get('action_%s_resolve_resolution' % \
                                             action,
                                this_action.get('set_resolution'))
                updated['resolution'] = newresolution
            elif operation == 'comment' and this_action.get('notify'):
                id = 'action_%s_comment_notify' % action
                selected_user = req.args.get(id)
                if selected_user:
                    ticket.notify_target_recipients = [selected_user]

            # leave_status is just a no-op here, so we don't look for it.

        # safe, not a side effect
        # after for loop because owner may be updated
        if 'notify_owner' in this_action['operations']:
            owner = updated.get('owner') or ticket['owner']
            if owner:
                ticket.notify_extra_recipients = [owner]

        return updated

    def apply_action_side_effects(self, req, ticket, action):
        pass

    # ITicketManipulator methods

    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket, action):
        res = []
        if not action:
            return res
        ops = action['operations']
        if 'comment' in ops:
            if ticket._old:
                res.append((None, _('You can not change ticket fields for "comment" operation.')))
                self.log.info('FOOOOOOOOOL: %s', ticket._old)
            if action.get('notify'):
                users = self.valid_user_provider.get_users(req, ticket, action)
                id = 'action_%s_comment_notify' % action['alias']
                selected_user = req.args.get(id)
                if users and selected_user not in users:
                    res.append((None, '"%s" is not valid user to notify for "%s" action'
                                        % (selected_user, action['alias'])))
        if 'set_owner' in ops:
            owners = self.get_valid_owners(req, ticket, action)
            if ticket['owner'] not in owners:
                res.append(('owner', '"%s" is not valid owner for "%s" action'
                                    % (ticket['owner'], action['alias'])))
        if 'set_resolution' in ops:
            resolutions = self.get_valid_resolutions(action, ticket)
            if ticket['resolution'] not in resolutions:
                res.append(('resolution', '"%s" is not valid resolution for "%s" action'
                                    % (ticket['resolution'], action['alias'])))
        return res

    # Internal methods

    def _has_perms_for_action(self, req, action, resource):
        required_perms = action['permissions']
        if required_perms:
            for permission in required_perms:
                if permission in req.perm(resource):
                    break
            else:
                # The user does not have any of the listed permissions
                return False
        return True

    def _prepare_actions(self, actions):
        if not '_reset' in actions:
            # Special action that gets enabled if the current status no longer
            # exists, as no other action can then change its state. (#5307)
            actions['_reset'] = {
                'default': 0,
                'alias': '_reset',
                'name': 'reset',
                'newstate': 'new',
                'oldstates': [],  # Will not be invoked unless needed
                'operations': ['reset_workflow'],
                'permissions': []}
        self.log.debug('Workflow actions at initialization: %s\n' %
                       str(actions))
        for name, info in actions.iteritems():
            if not info['newstate']:
                self.log.warning("Ticket workflow action '%s' doesn't define "
                                 "any transitions", name)
        return actions

    # Public methods (for other ITicketActionControllers that want to use
    #                 our config file and provide an operation for an action)
    
    # UNUSED method!
#    def get_actions_by_operation(self, operation):
#        """Return a list of all actions with a given operation
#        (for use in the controller's get_all_status())
#        """
#        actions = [(info['default'], action) for action, info
#                   in self.actions.items()
#                   if operation in info['operations']]
#        return actions

    def get_actions_by_operation_for_req(self, req, ticket, operation):
        """Return list of all actions with a given operation that are valid
        in the given state for the controller's get_ticket_actions().

        If state='*' (the default), all actions with the given operation are
        returned.
        """
        # Be sure to look at the original status.
        status = ticket._old.get('status', ticket['status'])
        actions = [(info['default'], action) for action, info
                   in self.get_actions(ticket=ticket, req=req).items()
                   if operation in info['operations'] and
                      ('*' in info['oldstates'] or
                       status in info['oldstates']) and
                      self._has_perms_for_action(req, info, ticket.resource)]
        return actions

    # Public methods

    def get_available_actions(self, req, ticket):
        """Returns a sorted list of available actions"""
        # The list should not have duplicates.
        actions = {}
        sid = self.pm.get_project_syllabus(ticket.pid)
        for controller in self.action_controllers(sid):
            weighted_actions = controller.get_ticket_actions(req, ticket) or []
            for weight, action in weighted_actions:
                if action in actions:
                    actions[action] = max(actions[action], weight)
                else:
                    actions[action] = weight
        all_weighted_actions = [(weight, action) for action, weight in
                                actions.items()]
        return [x[1] for x in sorted(all_weighted_actions, reverse=True)]

    def get_available_statuses(self, pid=None, syllabus_id=None):
        """Returns a sorted list of all the states all of the action
        controllers know about."""
        valid_states = set()
        if syllabus_id is not None:
            sid = int(syllabus_id)
        elif pid is not None:
            sid = self.pm.get_project_syllabus(pid)
        else:
            raise NotImplementedError('Global ticket statuses are not implemented.')
        for controller in self.action_controllers(sid):
            valid_states.update(controller.get_all_status(syllabus_id=sid) or [])
        return sorted(valid_states)

    def get_actions(self, pid=None, syllabus_id=None, ticket=None, req=None):
        # only one of pid, syllabus_id or ticket is required
        # req is optional for cache
        sid = syllabus_id
        if ticket is not None:
            pid = ticket.pid
        if pid is not None:
            sid = self.pm.get_project_syllabus(pid)
        if sid is not None:
            sid = int(sid)
            with self._actions_lock:
                if sid not in self._actions:
                    syl_config = self.configs.syllabus(sid)
                    actions = get_workflow_config(syl_config)
                    actions = self._prepare_actions(actions)
                    self._actions[sid] = actions
                return self._actions[sid]
        raise TypeError('You must specify one of id''s or ticket argument')

    def get_valid_owners(self, req, ticket, action):
        if action.has_key('set_owner'):
            owners = [x.strip() for x in
                      action['set_owner'].split(',')]
        else:
            owners = self.valid_user_provider.get_users(req, ticket, action,
                                                        'owner_realm', 'owner_perm_group')
        return owners

    def get_valid_resolutions(self, action, ticket):
        if action.has_key('set_resolution'):
            resolutions = [x.strip() for x in
                           action['set_resolution'].split(',')]
        else:
            resolutions = [val.name for val in Resolution.select(self.env, pid=ticket.pid)]
        return resolutions

    def get_previous_owner(self, ticket):
        current_owner = ticket._old.get('owner', ticket['owner'])
        res = ticket.get_from_changelog('owner', new=current_owner)
        if res:
            return res[1]



class UserGroupProvider(Component):

    implements(IValidUserProvider)

    default_owner_realms = ListOption('ticket-workflow-config', 'default_owner_realm', 'team', sep='|',
        doc="""Default owner realms for set_owner ticket actions.""", switcher=True)

    def get_users(self, req, ticket, next_action, realm_key=None, perm_group_key=None):
        if realm_key is None:
            realm_key = 'user_realm'
        if perm_group_key is None:
            perm_group_key = 'user_perm_group'
        realms = action_getlist(next_action, realm_key, sep='|')
        if not realms:
            realms = self.default_owner_realms.project(ticket.pid)
        perm_groups = action_getlist(next_action, perm_group_key, sep='|')

        users = UserManagement(self.env).get_project_users(ticket.pid, realms, perm_groups)
        return sorted(users)


def action_getlist(action_obj, name, default=None, sep=',', keep_empty=False):
    """Return a list of values that have been specified as a single
    comma-separated option.

    A different separator can be specified using the `sep` parameter. If
    the `skip_empty` parameter is set to `True`, empty elements are omitted
    from the list.
    
    Copied from Section.getlist() in trac/config.py
    """
    value = action_obj.get(name, default)
    items = None
    if value:
        if isinstance(value, basestring):
            items = [item.strip() for item in value.split(sep)]
        else:
            items = list(value)
        if not keep_empty:
            items = filter(None, items)
    return items        

