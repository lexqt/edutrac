# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2005 Jonas Borgström <jonas@edgewall.com>
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
# Author: Jonas Borgström <jonas@edgewall.com>

import copy
import re

from genshi.builder import tag

from trac.cache import cached
from trac.config import *
from trac.core import *
from trac.perm import IPermissionRequestor, PermissionCache, PermissionSystem
from trac.resource import IResourceManager
from trac.util import Ranges
from trac.util.text import shorten_line
from trac.util.translation import _, N_, gettext
from trac.wiki import IWikiSyntaxProvider, WikiParser

from trac.user.api import UserManagement

class ITicketActionController(Interface):
    """Extension point interface for components willing to participate
    in the ticket workflow.

    This is mainly about controlling the changes to the ticket ''status'',
    though not restricted to it.
    """

    def get_ticket_actions(req, ticket):
        """Return an iterable of `(weight, action)` tuples corresponding to
        the actions that are contributed by this component.
        That list may vary given the current state of the ticket and the
        actual request parameter.

        `action` is a key used to identify that particular action.
        (note that 'history' and 'diff' are reserved and should not be used
        by plugins)
        
        The actions will be presented on the page in descending order of the
        integer weight. The first action in the list is used as the default
        action.

        When in doubt, use a weight of 0."""

    def get_all_status(syllabus_id):
        """Returns an iterable of all the possible values for the ''status''
        field this action controller knows about.
        ''syllabus_id'' indicates syllabus id.

        This will be used to populate the query options and the like.
        It is assumed that the initial status of a ticket is 'new' and
        the terminal status of a ticket is 'closed'.
        """

    def render_ticket_action_control(req, ticket, action):
        """Return a tuple in the form of `(label, control, hint)`

        `label` is a short text that will be used when listing the action,
        `control` is the markup for the action control and `hint` should
        explain what will happen if this action is taken.
        
        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_ticket_actions`.

        Note that the radio button for the action has an `id` of
        `"action_%s" % action`.  Any `id`s used in `control` need to be made
        unique.  The method used in the default ITicketActionController is to
        use `"action_%s_something" % action`.
        """

    def get_ticket_changes(req, ticket, action):
        """Return a dictionary of ticket field changes.

        This method must not have any side-effects because it will also
        be called in preview mode (`req.args['preview']` will be set, then).
        See `apply_action_side_effects` for that. If the latter indeed triggers
        some side-effects, it is advised to emit a warning
        (`trac.web.chrome.add_warning(req, reason)`) when this method is called
        in preview mode.

        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_ticket_actions`.
        """

    def apply_action_side_effects(req, ticket, action):
        """Perform side effects once all changes have been made to the ticket.

        Multiple controllers might be involved, so the apply side-effects
        offers a chance to trigger a side-effect based on the given `action`
        after the new state of the ticket has been saved.

        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_ticket_actions`.
        """


class ITicketChangeListener(Interface):
    """Extension point interface for components that require notification
    when tickets are created, modified, or deleted."""

    def ticket_created(ticket):
        """Called when a ticket is created."""

    def ticket_changed(ticket, comment, author, old_values):
        """Called when a ticket is modified.
        
        `old_values` is a dictionary containing the previous values of the
        fields that have changed.
        """

    def ticket_deleted(ticket):
        """Called when a ticket is deleted."""


class ITicketManipulator(Interface):
    """Miscellaneous manipulation of ticket workflow features."""

    def prepare_ticket(req, ticket, fields, actions):
        """Not currently called, but should be provided for future
        compatibility."""

    def validate_ticket(req, ticket, action):
        """Validate a ticket after it's been populated from user input.
        
        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be `None` to indicate an overall problem with the
        ticket. Therefore, a return value of `[]` means everything is OK."""


class IMilestoneChangeListener(Interface):
    """Extension point interface for components that require notification
    when milestones are created, modified, or deleted."""

    def milestone_created(milestone):
        """Called when a milestone is created."""

    def milestone_changed(milestone, old_values):
        """Called when a milestone is modified.

        `old_values` is a dictionary containing the previous values of the
        milestone properties that changed. Currently those properties can be
        'name', 'due', 'completed', or 'description'.
        """

    def milestone_deleted(milestone):
        """Called when a milestone is deleted."""


class TicketFieldsStore(object):
    """Project dependent store for ticket fields"""

    _proj_instances = {}
    _syll_instances = {}
    def __new__(cls, env, pid=None, syllabus_id=None, *args, **kwargs):
        if pid is not None:
            id_ = int(pid)
            kwargs['pid'] = id_
            stor = cls._proj_instances
        elif syllabus_id is not None:
            id_ = int(syllabus_id)
            kwargs['syllabus_id'] = id_
            stor = cls._syll_instances
        else:
            raise NotImplementedError('Global ticket fields store is not implemented.')
        if id_ not in stor:
            stor[id_] = super(TicketFieldsStore, cls).__new__(cls, env, *args, **kwargs)
        return stor[id_]

    #TODO: change init arguments?
    def __init__(self, env, pid=None, syllabus_id=None, ticket_system=None):
        self.env = env
        if pid is not None:
            id_ = pid
            self.pid = pid
            from trac.project.api import ProjectManagement
            self.syllabus_id = ProjectManagement(self.env).get_project_syllabus(pid)
            fields_cache_level = 'pid'
        elif syllabus_id is not None:
            id_ = syllabus_id
            self.pid = None
            self.syllabus_id = syllabus_id
            fields_cache_level = 'sid'
        self.id_ = id_
        modname = TicketFieldsStore.__module__
        clsname = TicketFieldsStore.__name__
        self._cache_fields        = '%s.%s.fields:%s.%s'         % (modname, clsname, fields_cache_level, self.id_)
        self._cache_custom_fields = '%s.%s.custom_fields:sid.%s' % (modname, clsname, self.syllabus_id)
        if ticket_system is None:
            ticket_system = TicketSystem(self.env)
        self.ts = ticket_system

    @cached('_cache_fields')
    def fields(self, db):
        """Return the list of fields available for tickets."""
        from trac.ticket import model

        fields = []

        # Basic text fields
        fields.append({'name': 'project_id', 'type': 'id',
                       'label': N_('Project ID'),
                       'notnull': True, 'skip': True})
        fields.append({'name': 'summary', 'type': 'text',
                       'label': N_('Summary')})
        fields.append({'name': 'reporter', 'type': 'text',
                       'label': N_('Reporter')})

        # Owner field, by default text but can be changed dynamically 
        # into a drop-down depending on configuration (restrict_owner=true)
        fields.append({'name': 'owner', 'type': 'text',
                       'label': N_('Owner')})

        # Description
        fields.append({'name': 'description', 'type': 'textarea',
                       'label': N_('Description')})

        # Default select and radio fields
        selects = [
                   ('status', N_('Status'), model.Status),
                   ('resolution', N_('Resolution'), model.Resolution),
                   ('type', N_('Type'), model.Type),
                   ('priority', N_('Priority'), model.Priority),
                   ('severity', N_('Severity'), model.Severity),
                   ]
        id_kwargs = {}
        if self.pid is not None:
            selects.extend([
                   ('milestone', N_('Milestone'), model.Milestone),
                   ('component', N_('Component'), model.Component),
                   ('version', N_('Version'), model.Version),
                ])
            id_kwargs['pid'] = self.pid
        else:
            id_kwargs['syllabus_id'] = self.syllabus_id

        fields.extend(self._prepare_selects_fields(selects, id_kwargs))

        # Advanced text fields
        fields.append({'name': 'keywords', 'type': 'text',
                       'label': N_('Keywords')})
        fields.append({'name': 'cc', 'type': 'text',
                       'label': N_('Cc')})

        # Date/time fields
        fields.append({'name': 'time', 'type': 'time',
                       'label': N_('Created')})
        fields.append({'name': 'changetime', 'type': 'time',
                       'label': N_('Modified')})

        fields.extend(self._prepare_custom_fields())

        from collections import OrderedDict
        fields_dict = OrderedDict()
        for field in fields:
            fields_dict[field['name']] = field

        return fields_dict

    @cached('_cache_custom_fields')
    def custom_fields(self, db):
        """Return the list of custom ticket fields available for tickets.
        Custom fields entirely defined on syllabus level."""
        fields = []
        config = self.ts.configs.syllabus(self.syllabus_id)['ticket-custom']
        for name in [option for option, value in config.options()
                     if '.' not in option]:
            field = {
                'name': name,
                'type': config.get(name),
                'order': config.getint(name + '.order', 0),
                'label': config.get(name + '.label') or name.capitalize(),
                'value': config.get(name + '.value', '')
            }
            if field['type'] == 'select' or field['type'] == 'radio':
                field['options'] = config.getlist(name + '.options', sep='|')
                if '' in field['options']:
                    field['optional'] = True
                    field['options'].remove('')
            elif field['type'] == 'text':
                field['format'] = config.get(name + '.format', 'plain')
            elif field['type'] == 'textarea':
                field['format'] = config.get(name + '.format', 'plain')
                field['width'] = config.getint(name + '.cols')
                field['height'] = config.getint(name + '.rows')
            fields.append(field)

        fields.sort(lambda x, y: cmp((x['order'], x['name']),
                                     (y['order'], y['name'])))
        return fields

    def _prepare_selects_fields(self, selects, id_kwargs):
        fields = []
        for name, label, cls in selects:
            options = [val.name for val in cls.select(self.env, **id_kwargs)]
            if not options:
                # Fields without possible values are treated as if they didn't
                # exist
                continue
            field = {'name': name, 'type': 'select', 'label': label,
                     'value': getattr(self.ts, 'default_' + name, ''),
                     'options': options, 'model_class': cls}
            if name in ('status', 'resolution'):
                field['type'] = 'radio'
                field['optional'] = True
            elif name in ('milestone', 'version'):
                field['optional'] = True
            fields.append(field)
        return fields

    def _prepare_custom_fields(self):
        fields = []
        for field in self.custom_fields:
            if field['name'] in [f['name'] for f in fields]:
                self.env.log.warning('Duplicate field name "%s" (ignoring)',
                                 field['name'])
                continue
            if field['name'] in self.ts.reserved_field_names:
                self.env.log.warning('Field name "%s" is a reserved name '
                                 '(ignoring)', field['name'])
                continue
            if not re.match('^[a-zA-Z][a-zA-Z0-9_]+$', field['name']):
                self.env.log.warning('Invalid name for custom field: "%s" '
                                 '(ignoring)', field['name'])
                continue
            field['custom'] = True
            fields.append(field)
        return fields



class TicketSystem(Component):
    implements(IPermissionRequestor, IWikiSyntaxProvider, IResourceManager)

    change_listeners = SyllabusExtensionPoint(ITicketChangeListener)
    milestone_change_listeners = ExtensionPoint(IMilestoneChangeListener)
    
    restrict_owner = BoolOption('ticket', 'restrict_owner', 'false',
        """Make the owner field of tickets use a drop-down menu.
        Be sure to understand the performance implications before activating
        this option. See
        [TracTickets#Assign-toasDrop-DownList Assign-to as Drop-Down List].
        
        Please note that e-mail addresses are '''not''' obfuscated in the
        resulting drop-down menu, so this option should not be used if
        e-mail addresses must remain protected.
        (''since 0.9'')""")

    skip_owner_on_new = BoolOption('ticket-workflow-config', 'skip_owner_on_new', 'true',
        """Do not allow to set owner on new ticket creation.
        Manipulations with owner will be controlled by workflow.""", switcher=True)

    default_version = Option('ticket', 'default_version', '',
        """Default version for newly created tickets.""")

    default_type = Option('ticket', 'default_type', 'task',
        """Default type for newly created tickets (''since 0.9'').""")

    default_priority = Option('ticket', 'default_priority', 'normal',
        """Default priority for newly created tickets.""")

    default_milestone = Option('ticket', 'default_milestone', '',
        """Default milestone for newly created tickets.""")

    default_component = Option('ticket', 'default_component', '',
        """Default component for newly created tickets.""")

    default_severity = Option('ticket', 'default_severity', 'normal',
        """Default severity for newly created tickets.""")

    default_summary = Option('ticket', 'default_summary', '',
        """Default summary (title) for newly created tickets.""")

    default_description = Option('ticket', 'default_description', '',
        """Default description for newly created tickets.""")

    default_keywords = Option('ticket', 'default_keywords', '',
        """Default keywords for newly created tickets.""")

    default_owner = Option('ticket', 'default_owner', '',
        """Default owner for newly created tickets.""")

    default_cc = Option('ticket', 'default_cc', '',
        """Default cc: list for newly created tickets.""")

    default_resolution = Option('ticket', 'default_resolution', 'fixed',
        """Default resolution for resolving (closing) tickets
        (''since 0.11'').""")

    def __init__(self):
        from trac.ticket.default_workflow import ConfigurableTicketWorkflow
        self.workflow = ConfigurableTicketWorkflow(self.env)

    # Public API

    @property
    def action_controllers(self):
        return self.workflow.action_controllers

    def get_available_actions(self, req, ticket):
        """Returns a sorted list of available actions"""
        return self.workflow.get_available_actions(req, ticket)

    def get_all_status(self, pid=None, syllabus_id=None):
        """Returns a sorted list of all the states all of the action
        controllers know about."""
        return self.workflow.get_available_statuses(pid=pid, syllabus_id=syllabus_id)

    def get_ticket_field_labels(self, pid=None, syllabus_id=None):
        """Produce a (name,label) mapping from `get_ticket_fields`."""
        labels = dict((n, f['label'])
                      for n, f in TicketSystem(self.env).get_ticket_fields(
                                pid=pid, syllabus_id=syllabus_id).iteritems())
        labels['attachment'] = _("Attachment")
        return labels

    def get_ticket_fields(self, pid=None, syllabus_id=None):
        """Returns list of fields available for tickets.

        Each field is a dict with at least the 'name', 'label' (localized)
        and 'type' keys.
        It may in addition contain the 'custom' key, the 'optional' and the
        'options' keys. When present 'custom' and 'optional' are always `True`.
        """
        stor = TicketFieldsStore(self.env, pid=pid, syllabus_id=syllabus_id)
        fields = copy.deepcopy(stor.fields)
        label = 'label' # workaround gettext extraction bug
        for n, f in fields.iteritems():
            f[label] = gettext(f[label])
        return fields

    def reset_ticket_fields(self, pid=None, syllabus_id=None):
        """Invalidate ticket field cache."""
        stor = TicketFieldsStore(self.env, pid=pid, syllabus_id=syllabus_id)
        del stor.fields

    reserved_field_names = ['report', 'order', 'desc', 'group', 'groupdesc',
                            'col', 'row', 'format', 'max', 'page', 'verbose',
                            'comment', 'or']

    def get_custom_fields(self, pid=None, syllabus_id=None):
        stor = TicketFieldsStore(self.env, pid=pid, syllabus_id=syllabus_id)
        return copy.deepcopy(stor.custom_fields)

    def get_field_synonyms(self):
        """Return a mapping from field name synonyms to field names.
        The synonyms are supposed to be more intuitive for custom queries."""
        # i18n TODO - translated keys
        return {'created': 'time', 'modified': 'changetime'}

    def eventually_restrict_owner(self, field, ticket=None):
        """Restrict given owner field to be a list of users having
        the TICKET_MODIFY permission (for the given ticket)
        """
        if self.restrict_owner:
            possible_owners = UserManagement(self.env).get_project_users(ticket.pid, ('team',))
            if possible_owners:
                possible_owners.sort()
                field['type'] = 'select'
                field['options'] = possible_owners
                field['optional'] = True

    # IPermissionRequestor methods

    def get_permission_actions(self):
        return ['TICKET_APPEND', 'TICKET_CREATE', 'TICKET_CHGPROP',
                'TICKET_VIEW', 'TICKET_EDIT_CC', 'TICKET_EDIT_DESCRIPTION',
                'TICKET_EDIT_COMMENT',
                ('TICKET_MODIFY', ['TICKET_APPEND', 'TICKET_CHGPROP']),
                ('TICKET_ADMIN', ['TICKET_CREATE', 'TICKET_MODIFY',
                                  'TICKET_VIEW', 'TICKET_EDIT_CC',
                                  'TICKET_EDIT_DESCRIPTION',
                                  'TICKET_EDIT_COMMENT'])]

    # IWikiSyntaxProvider methods

    def get_link_resolvers(self):
        return [('bug', self._format_link),
                ('ticket', self._format_link),
                ('comment', self._format_comment_link)]

    def get_wiki_syntax(self):
        yield (
            # matches #... but not &#... (HTML entity)
            r"!?(?<!&)#"
            # optional intertrac shorthand #T... + digits
            r"(?P<it_ticket>%s)%s" % (WikiParser.INTERTRAC_SCHEME,
                                      Ranges.RE_STR),
            lambda x, y, z: self._format_link(x, 'ticket', y[1:], y, z))

    def _format_link(self, formatter, ns, target, label, fullmatch=None):
        intertrac = formatter.shorthand_intertrac_helper(ns, target, label,
                                                         fullmatch)
        if intertrac:
            return intertrac
        try:
            link, params, fragment = formatter.split_link(target)
            r = Ranges(link)
            if len(r) == 1:
                num = r.a
                ticket = formatter.resource('ticket', num)
                from trac.ticket.model import Ticket
                if Ticket.id_is_valid(num) and \
                        'TICKET_VIEW' in formatter.perm(ticket):
                    # TODO: watch #6436 and when done, attempt to retrieve 
                    #       ticket directly (try: Ticket(self.env, num) ...)
                    cursor = formatter.db.cursor() 
                    cursor.execute("SELECT type,summary,status,resolution "
                                   "FROM ticket WHERE id=%s", (str(num),)) 
                    for type, summary, status, resolution in cursor:
                        title = self.format_summary(summary, status,
                                                    resolution, type)
                        href = formatter.href.ticket(num) + params + fragment
                        return tag.a(label, class_='%s ticket' % status, 
                                     title=title, href=href)
            else:
                ranges = str(r)
                if params:
                    params = '&' + params[1:]
                return tag.a(label, title='Tickets '+ranges,
                             href=formatter.href.query(id=ranges) + params)
        except ValueError:
            pass
        return tag.a(label, class_='missing ticket')

    def _format_comment_link(self, formatter, ns, target, label):
        resource = None
        if ':' in target:
            elts = target.split(':')
            if len(elts) == 3:
                cnum, realm, id = elts
                if cnum != 'description' and cnum and not cnum[0].isdigit():
                    realm, id, cnum = elts # support old comment: style
                resource = formatter.resource(realm, id)
        else:
            resource = formatter.resource
            cnum = target

        if resource:
            href = "%s#comment:%s" % (formatter.href.ticket(resource.id), cnum)
            title = _("Comment %(cnum)s for Ticket #%(id)s", cnum=cnum,
                      id=resource.id)
            return tag.a(label, href=href, title=title)
        else:
            return label
 
    # IResourceManager methods

    def get_resource_realms(self):
        yield 'ticket'

    def get_resource_description(self, resource, format=None, context=None,
                                 **kwargs):
        if format == 'compact':
            return '#%s' % resource.id
        elif format == 'summary':
            from trac.ticket.model import Ticket
            ticket = Ticket(self.env, resource.id)
            args = [ticket[f] for f in ('summary', 'status', 'resolution',
                                        'type')]
            return self.format_summary(*args)
        return _("Ticket #%(shortname)s", shortname=resource.id)

    def format_summary(self, summary, status=None, resolution=None, type=None):
        summary = shorten_line(summary)
        if type:
            summary = type + ': ' + summary
        if status:
            if status == 'closed' and resolution:
                status += ': ' + resolution
            return "%s (%s)" % (summary, status)
        else:
            return summary

    def resource_exists(self, resource):
        """
        >>> from trac.test import EnvironmentStub
        >>> from trac.resource import Resource, resource_exists
        >>> env = EnvironmentStub()

        >>> resource_exists(env, Resource('ticket', 123456))
        False

        >>> from trac.ticket.model import Ticket
        >>> t = Ticket(env)
        >>> int(t.insert())
        1
        >>> resource_exists(env, t.resource)
        True
        """
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM ticket WHERE id=%s", (resource.id,))
        latest_exists = bool(cursor.fetchall())
        if latest_exists:
            if resource.version is None:
                return True
            cursor.execute("""
                SELECT count(distinct time) FROM ticket_change WHERE ticket=%s
                """, (resource.id,))
            return cursor.fetchone()[0] >= resource.version
        else:
            return False

    def get_resource(self, realm, rsc_id, args):
        if realm == 'ticket':
            id_ = int(rsc_id)
            from trac.ticket.model import Ticket
            return Ticket(self.env, id_)

    def get_realm_info(self):
        return {
            'ticket': {
                'need_pid': False,
            }
        }

    def has_project_resources(self, realm):
        if realm == 'ticket':
            return True

    def has_global_resources(self, realm):
        if realm == 'ticket':
            return False

    def is_slave_realm(self, realm):
        if realm == 'ticket':
            return False

    def get_realm_table(self, realm):
        if realm == 'ticket':
            return 'ticket'

    def get_realm_id(self, realm):
        if realm == 'ticket':
            return 'id'

