# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2004 Jonas Borgström <jonas@edgewall.com>
# Copyright (C) 2005 Christopher Lenz <cmlenz@gmx.de>
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
#         Christopher Lenz <cmlenz@gmx.de>

from time import time

from trac.admin import AdminCommandError, IAdminCommandProvider
from trac.config import ExtensionOption, OrderedExtensionsOption
from trac.core import *
from trac.resource import Resource, get_resource_name
from trac.util.text import print_table, printout, wrap, exception_to_unicode
from trac.util.translation import _

__all__ = ['IPermissionRequestor', 'IPermissionStore',
           'IPermissionGroupProvider', 'PermissionError', 'PermissionSystem']


class PermissionError(StandardError):
    """Insufficient permissions to complete the operation"""

    def __init__ (self, action=None, resource=None, env=None, msg=None):
        StandardError.__init__(self)
        self.action = action
        self.resource = resource
        self.env = env
        self.msg = msg

    def __unicode__ (self):
        if self.action:
            if self.resource:
                return _('%(perm)s privileges are required to perform '
                         'this operation on %(resource)s',
                         perm=self.action, 
                         resource=get_resource_name(self.env, self.resource))
            else:
                return _('%(perm)s privileges are required to perform '
                         'this operation', perm=self.action)
        elif self.msg:
            return self.msg
        else:
            return _('Insufficient privileges to perform this operation.')


class IPermissionRequestor(Interface):
    """Extension point interface for components that define actions."""

    def get_permission_actions():
        """Return a list of actions defined by this component.
        
        The items in the list may either be simple strings, or
        `(string, sequence)` tuples. The latter are considered to be "meta
        permissions" that group several simple actions under one name for
        convenience.
        """


class IPermissionStore(Interface):
    """Extension point interface for components that provide storage and
    management of permissions."""

    def get_user_permissions(username, project_id=None, syllabus_id=None, inherit=True):
        """Return all permissions for the user with the specified name.
        And optionally for specified project or syllabus ID.
        If `inherit` is True, also retrieve permissions from higher levels.
        Project perms would include syllabus and global, syllabus - global,
        global - only itself.
        
        The permissions are returned as a dictionary where the key is the name
        of the permission, and the value is either `True` for granted
        permissions or `False` for explicitly denied permissions."""

    def get_users_with_permissions(permissions):
        """Retrieve a list of users that have any of the specified permissions.

        Users are returned as a list of usernames.
        """

    def get_all_permissions(project_id=None, syllabus_id=None, inherit=True):
        """Return all permissions for all users.
        Optional arguments have the same meaning as in `get_user_permissions`.

        The permissions are returned as a list of (subject, action)
        formatted tuples."""

    def grant_permission(username, action, project_id=None, syllabus_id=None):
        """Grant a user permission to perform an action."""

    def revoke_permission(username, action, project_id=None, syllabus_id=None):
        """Revokes the permission of the given user to perform an action."""


class IPermissionGroupProvider(Interface):
    """Extension point interface for components that provide information about
    user groups.
    """

    def get_permission_groups(username, project_id=None, inherit=True):
        """Return a list of names of the groups that the user with the specified
        name is a member of.
        `project_id` and `inherit` params have same meaning as in
        `IPermissionStore.get_user_permissions`.
        """


class IPermissionPolicy(Interface):
    """A security policy provider used for fine grained permission checks."""

    def check_permission(action, username, resource, perm, req=None):
        """Check that the action can be performed by username on the resource

        :param action: the name of the permission
        :param username: the username string or 'anonymous' if there's no
                         authenticated user
        :param resource: the resource on which the check applies.
                         Will be `None`, if the check is a global one and
                         not made on a resource in particular. Resource
                         can be used as project ID carrier.
        :param perm: the permission cache for that username and resource, 
                     which can be used for doing secondary checks on other
                     permissions. Care must be taken to avoid recursion.  
        :param req: request object. Can be used for dynamic permissions and
                    for cache. But can be None.

        :return: `True` if action is allowed, `False` if action is denied,
                 or `None` if indifferent. If `None` is returned, the next
                 policy in the chain will be used, and so on.

        Note that when checking a permission on a realm resource (i.e. when
        `.id` is `None`), this usually corresponds to some preliminary check
        done before making a fine-grained check on some resource.
        Therefore the `IPermissionPolicy` should be conservative and return:

         * `True` if the action *can* be allowed for some resources in
           that realm. Later, for specific resource, the policy will be able
           to return `True` (allow), `False` (deny) or `None` (don't decide).
         * `None` if the action *can not* be performed for *some* resources.
           This corresponds to situation where the policy is only interested
           in returning `False` or `None` on specific resources.
         * `False` if the action *can not* be performed for *any* resource in
           that realm (that's a very strong decision as that will usually
           prevent any fine-grained check to even happen).

        Note that performing permission checks on realm resources may seem
        redundant for now as the action name itself contains the realm, but
        this will probably change in the future (e.g. `'VIEW' in ...`).
        """


class DefaultPermissionStore(Component):
    """Default implementation of permission storage and group management.
    
    This component uses the `permission` table in the database to store both
    permissions and groups.
    """
    implements(IPermissionStore)

    group_providers = ExtensionPoint(IPermissionGroupProvider)

    def get_user_permissions(self, username, project_id=None, syllabus_id=None, inherit=True):
        """Return the permissions of the specified user.
        See `IPermissionStore.get_user_permissions`."""
        subjects = set([username])
        for provider in self.group_providers:
            subjects.update(provider.get_permission_groups(username, project_id, inherit) or [])

        levels = self._get_perm_levels(project_id, syllabus_id, inherit)

        args = []
        qs   = []
        if levels['p']:
            qs.append('''
                SELECT username, action
                FROM project_permissions
                WHERE project_id=%s AND username=%s
            ''')
            args.append(project_id)
            args.append(username)
        if levels['s']:
            if levels['p']:
                syllabus_id = ProjectManagement(self.env).get_project_syllabus(project_id)
            qs.append('''
                SELECT username, action
                FROM syllabus_permissions
                WHERE syllabus_id=%s
            ''')
            args.append(syllabus_id)
        if levels['g']:
            qs.append('SELECT username, action FROM permission')

        q = u'\nUNION\n'.join(qs)
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(q, args)
        rows = cursor.fetchall()

        actions = set()
        while True:
            num_users = len(subjects)
            num_actions = len(actions)
            for user, action in rows:
                if user in subjects:
                    if action.isupper() and action not in actions:
                        actions.add(action)
                    if not action.isupper() and action not in subjects:
                        # action is actually the name of the permission group
                        # here
                        subjects.add(action)
            if num_users == len(subjects) and num_actions == len(actions):
                break
        return list(actions)

    def get_users_with_permissions(self, permissions):
        """Retrieve a list of users that have any of the specified permissions
        
        Users are returned as a list of usernames.
        """
        # get_user_permissions() takes care of the magic 'authenticated' group.
        # The optimized loop we had before didn't.  This is very inefficient,
        # but it works.
        result = set()
        users = set([u[0] for u in self.env.get_known_users()])
        for user in users:
            userperms = self.get_user_permissions(user)
            for group in permissions:
                if group in userperms:
                    result.add(user)
        return list(result)

    def get_all_permissions(self, project_id=None, syllabus_id=None, inherit=True):
        """Return all permissions for all users.
        See `IPermissionStore.get_all_permissions`."""
        levels = self._get_perm_levels(project_id, syllabus_id, inherit)

        args = []
        qs   = []
        if levels['p']:
            qs.append('''
                SELECT username, action
                FROM project_permissions
                WHERE project_id=%s
            ''')
            args.append(project_id)
        if levels['s']:
            if levels['p']:
                syllabus_id = ProjectManagement(self.env).get_project_syllabus(project_id)
            qs.append('''
                SELECT username, action
                FROM syllabus_permissions
                WHERE syllabus_id=%s
            ''')
            args.append(syllabus_id)
        if levels['g']:
            qs.append('SELECT username, action FROM permission')

        q = u'\nUNION\n'.join(qs)
        db = self.env.get_read_db()
        cursor = db.cursor()
        cursor.execute(q, args)
        return [(row[0], row[1]) for row in cursor]

    def grant_permission(self, username, action, project_id, syllabus_id):
        """Grants a user the permission to perform the specified action."""
        args = [username, action]
        if project_id is not None:
            q = '''
                INSERT INTO project_permissions
                (username, action, project_id)
                VALUES (%s, %s, %s)
            '''
            args.append(project_id)
            log = '(project #%s)' % project_id
        elif syllabus_id is not None:
            q = '''
                INSERT INTO syllabus_permissions
                (username, action, syllabus_id)
                VALUES (%s, %s, %s)
            '''
            args.append(syllabus_id)
            log = '(syllabus #%s)' % syllabus_id
        else:
            q = '''
                INSERT INTO permission
                (username, action)
                VALUES (%s, %s)
            '''
            log = '(global)'
        @self.env.with_transaction()
        def do_grant(db):
            cursor = db.cursor()
            cursor.execute(q, args)
        self.log.info('Granted permission for %s to %s %s' % (action, username, log))

    def revoke_permission(self, username, action, project_id, syllabus_id):
        """Revokes a users' permission to perform the specified action."""
        args = [username, action]
        if project_id is not None:
            q = '''
                DELETE FROM project_permissions
                WHERE username=%s AND action=%s AND project_id=%s
            '''
            args.append(project_id)
            log = '(project #%s)' % project_id
        elif syllabus_id is not None:
            q = '''
                DELETE FROM syllabus_permissions
                WHERE username=%s AND action=%s AND syllabus_id=%s
            '''
            args.append(syllabus_id)
            log = '(syllabus #%s)' % syllabus_id
        else:
            q = '''
                DELETE FROM permission
                WHERE username=%s AND action=%s
            '''
            log = '(global)'
        @self.env.with_transaction()
        def do_revoke(db):
            cursor = db.cursor()
            cursor.execute(q, args)
        self.log.info('Revoked permission for %s to %s %s' % (action, username, log))

    def _get_perm_levels(self, project_id=None, syllabus_id=None, inherit=True):
        levels = {
            'g': False, # global
            's': False, # syllabus
            'p': False, # project
        }
        if inherit:
            levels['g'] = True
            if syllabus_id is not None:
                levels['s'] = True
            elif project_id is not None:
                levels['s'] = True
                levels['p'] = True
        else:
            if syllabus_id is not None:
                levels['s'] = True
            elif project_id is not None:
                levels['p'] = True
            else:
                levels['g'] = True

        return levels


class DefaultPermissionGroupProvider(Component):
    """Permission group provider providing the basic builtin permission groups
    'anonymous' and 'authenticated'."""

    required = True

    implements(IPermissionGroupProvider)

    def get_permission_groups(self, username, project_id=None, inherit=True):
        '''See `IPermissionGroupProvider.get_permission_groups`.'''
        if project_id is not None and not inherit:
            return []
        groups = ['anonymous']
        if username and username != 'anonymous':
            groups.append('authenticated')
        return groups


class DefaultPermissionPolicy(Component):
    """Default permission policy using the IPermissionStore system."""

    implements(IPermissionPolicy)

    # Number of seconds a cached user permission set is valid for.
    CACHE_EXPIRY = 5
    # How frequently to clear the entire permission cache
    CACHE_REAP_TIME = 60

    def __init__(self):
        self.permission_cache = {}
        self.last_reap = time()

    # IPermissionPolicy methods

    def check_permission(self, action, username, resource, perm, req):
        pid = resource.pid if resource else None
        if pid is None and req:
            pid = ProjectManagement(self.env).get_current_project(req, fail_on_none=False)
        if pid is not None:
            if req:
                cache = req.data['project_perm_cache']
                perms = cache.get(pid)
                if not perms:
                    perms = PermissionSystem(self.env). \
                            get_user_permissions(username, pid)
                    cache[pid] = perms
            else:
                perms = PermissionSystem(self.env). \
                        get_user_permissions(username, pid)
            return action in perms or None

        # Check only global permissions

        now = time()

        if now - self.last_reap > self.CACHE_REAP_TIME:
            self.permission_cache = {}
            self.last_reap = time()

        timestamp, permissions = self.permission_cache.get(username, (0, None))

        # Cache hit?
        if now - timestamp > self.CACHE_EXPIRY:
            # No, pull permissions from database.
            permissions = PermissionSystem(self.env). \
                          get_user_permissions(username)
            self.permission_cache[username] = (now, permissions)

        return action in permissions or None



class PermissionSystem(Component):
    """Permission management sub-system."""

    required = True

    implements(IPermissionRequestor)

    requestors = ExtensionPoint(IPermissionRequestor)

    store = ExtensionOption('trac', 'permission_store', IPermissionStore,
                            'DefaultPermissionStore',
        """Name of the component implementing `IPermissionStore`, which is used
        for managing user and group permissions.""")

    policies = OrderedExtensionsOption('trac', 'permission_policies',
        IPermissionPolicy,
        'VirtualTicketPermissionsPolicy, DefaultPermissionPolicy, LegacyAttachmentPolicy',
        False,
        """List of components implementing `IPermissionPolicy`, in the order in
        which they will be applied. These components manage fine-grained access
        control to Trac resources.
        Defaults to the DefaultPermissionPolicy (pre-0.11 behavior) and
        LegacyAttachmentPolicy (map ATTACHMENT_* permissions to realm specific
        ones)""")

    # Number of seconds a cached user permission set is valid for.
    CACHE_EXPIRY = 5
    # How frequently to clear the entire permission cache
    CACHE_REAP_TIME = 60

    def __init__(self):
        self.permission_cache = {}
        self.last_reap = time()

    # Public API

    def grant_permission(self, username, action, project_id=None, syllabus_id=None):
        """Grant the user with the given name permission to perform to specified
        action."""
        if action.isupper() and action not in self.get_actions():
            raise TracError(_('%(name)s is not a valid action.', name=action))

        self.store.grant_permission(username, action, project_id, syllabus_id)

    def revoke_permission(self, username, action, project_id=None, syllabus_id=None):
        """Revokes the permission of the specified user to perform an action."""
        self.store.revoke_permission(username, action, project_id, syllabus_id)

    def get_actions(self):
        actions = []
        for requestor in self.requestors:
            for action in requestor.get_permission_actions() or []:
                if isinstance(action, tuple):
                    actions.append(action[0])
                else:
                    actions.append(action)
        return actions

    def get_user_permissions(self, username=None, project_id=None, syllabus_id=None, inherit=True):
        """Return the permissions of the specified user.
        See `IPermissionStore.get_user_permissions`."""
        actions = []
        for requestor in self.requestors:
            actions += list(requestor.get_permission_actions() or [])
        permissions = {}
        if username:
            # Return all permissions that the given user has
            meta = {}
            for action in actions:
                if isinstance(action, tuple):
                    name, value = action
                    meta[name] = value
            def _expand_meta(action):
                permissions[action] = True
                if meta.has_key(action):
                    [_expand_meta(perm) for perm in meta[action]]
            for perm in self.store.get_user_permissions(username, project_id, syllabus_id, inherit) or []:
                _expand_meta(perm)
        else:
            # Return all permissions available in the system
            for action in actions:
                if isinstance(action, tuple):
                    permissions[action[0]] = True
                else:
                    permissions[action] = True
        return permissions

    def get_all_permissions(self, project_id=None, syllabus_id=None, inherit=True):
        """Return all permissions for all users.

        The permissions are returned as a list of (subject, action)
        formatted tuples."""
        return self.store.get_all_permissions(project_id, syllabus_id, inherit) or []

    def get_users_with_permission(self, permission):
        """Return all users that have the specified permission.
        
        Users are returned as a list of user names.
        """
        now = time()

        if now - self.last_reap > self.CACHE_REAP_TIME:
            self.permission_cache = {}
            self.last_reap = now

        timestamp, permissions = self.permission_cache.get(permission, 
                                                           (0, None))
        if now - timestamp <= self.CACHE_EXPIRY:
            return permissions

        parent_map = {}
        for requestor in self.requestors:
            for action in requestor.get_permission_actions() or []:
                if isinstance(action, tuple):
                    for child in action[1]:
                        parent_map.setdefault(child, []).append(action[0])

        satisfying_perms = set()
        def _append_with_parents(action):
            if action in satisfying_perms:
                return # avoid unneccesary work and infinite loops
            satisfying_perms.add(action)
            if action in parent_map:
                map(_append_with_parents, parent_map[action])
        _append_with_parents(permission)

        perms = self.store.get_users_with_permissions(satisfying_perms) or []
        self.permission_cache[permission] = (now, perms)

        return perms

    def expand_actions(self, actions):
        """Helper method for expanding all meta actions."""
        actions = list(actions)     # Consume actions if it is an iterator
        meta = {}
        for requestor in self.requestors:
            for m in requestor.get_permission_actions() or []:
                if isinstance(m, tuple):
                    meta[m[0]] = m[1]
        expanded_actions = set(actions)

        def expand_action(action):
            actions = meta.get(action, [])
            expanded_actions.update(actions)
            [expand_action(a) for a in actions]

        [expand_action(a) for a in actions]
        return expanded_actions

    def check_permission(self, action, username=None, resource=None, perm=None, req=None):
        """Return True if permission to perform action for the given resource
        is allowed."""
        if username is None:
            username = 'anonymous'
        if resource and resource.realm is None:
            resource = None
        for policy in self.policies:
            decision = policy.check_permission(action, username, resource,
                                               perm, req)
            if decision is not None:
                if not decision:
                    self.log.debug("%s denies %s performing %s on %r" %
                                   (policy.__class__.__name__, username,
                                    action, resource))
                return decision
        self.log.debug("No policy allowed %s performing %s on %r" %
                       (username, action, resource))
        return False

    # IPermissionRequestor methods

    def get_permission_actions(self):
        """Implement the global `TRAC_ADMIN` meta permission.
        
        Implements also the `EMAIL_VIEW` permission which allows for
        showing email addresses even if `[trac] show_email_addresses`
        is `false`.
        """
        actions = ['EMAIL_VIEW']
        for requestor in [r for r in self.requestors if r is not self]:
            for action in requestor.get_permission_actions() or []:
                if isinstance(action, tuple):
                    actions.append(action[0])
                else:
                    actions.append(action)
        return [('TRAC_ADMIN', actions), 'EMAIL_VIEW']


class PermissionCache(object):
    """Cache that maintains the permissions of a single user.

    Permissions are usually checked using the following syntax:
    
        'WIKI_MODIFY' in perm

    One can also apply more fine grained permission checks and
    specify a specific resource for which the permission should be available:
    
        'WIKI_MODIFY' in perm('wiki', 'WikiStart')

    If there's already a `page` object available, the check is simply:

        'WIKI_MODIFY' in perm(page.resource)

    If instead of a check, one wants to assert that a given permission is
    available, the following form should be used:
    
        perm.require('WIKI_MODIFY')

        or

        perm('wiki', 'WikiStart').require('WIKI_MODIFY')

        or

        perm(page.resource).require('WIKI_MODIFY')

    When using `require`,  a `PermissionError` exception is raised if the
    permission is missing.
    """

    __slots__ = ('env', 'username', '_resource', '_cache', '_req')

    def __init__(self, env, username=None, resource=None, cache=None,
                 groups=None, req=None):
        self.env = env
        self.username = username or 'anonymous'
        self._resource = resource
        self._req = req
        if cache is None:
            cache = {}
        self._cache = cache

    def _normalize_resource(self, realm_or_resource, pid, id, version):
        if realm_or_resource:
            return Resource(realm_or_resource, id, version, pid=pid)
        else:
            return self._resource

    def __call__(self, realm_or_resource, id=False, version=False, pid=False):
        """Convenience function for using thus: 
            'WIKI_VIEW' in perm(context) 
        or 
            'WIKI_VIEW' in perm(realm, id, version)
        or 
            'WIKI_VIEW' in perm(resource)

        """
        resource = Resource(realm_or_resource, id, version, pid=pid)
        if resource and self._resource and resource == self._resource:
            return self
        else:
            return PermissionCache(self.env, self.username, resource,
                                   self._cache, req=self._req)

    def has_permission(self, action, realm_or_resource=None, id=False,
                       version=False, pid=False):
        resource = self._normalize_resource(realm_or_resource, pid, id, version)
        return self._has_permission(action, resource)

    def _has_permission(self, action, resource):
        key = (self.username, hash(resource), action)
        cached = self._cache.get(key)
        if cached:
            cache_decision, cache_resource = cached
            if resource == cache_resource:
                return cache_decision
        perm = self
        if resource is not self._resource:
            perm = PermissionCache(self.env, self.username, resource,
                                   self._cache, req=self._req)
        decision = PermissionSystem(self.env). \
                   check_permission(action, perm.username, resource, perm, perm._req)
        self._cache[key] = (decision, resource)
        return decision

    __contains__ = has_permission

    def require(self, action, realm_or_resource=None, id=False, version=False, pid=False):
        resource = self._normalize_resource(realm_or_resource, pid, id, version)
        if not self._has_permission(action, resource):
            raise PermissionError(action, resource, self.env)
    assert_permission = require

    def permissions(self):
        """Deprecated (but still used by the HDF compatibility layer)"""
        self.env.log.warning('perm.permissions() is deprecated and '
                             'is only present for HDF compatibility')
        perm = PermissionSystem(self.env)
        actions = perm.get_user_permissions(self.username)
        return [action for action in actions if action in self]


class PermissionAdmin(Component):
    """trac-admin command provider for permission system administration."""
    
    implements(IAdminCommandProvider)
    
    # IAdminCommandProvider methods
    
    def get_admin_commands(self):
        yield ('permission list', '[user]',
               'List permission rules',
               self._complete_list, self._do_list)
        yield ('permission add', 'G|S<id>|P<id> <user> <action> [action] [...]',
               'Add a new permission rule',
               self._complete_add, self._do_add)
        yield ('permission remove', 'G|S<id>|P<id> <user> <action> [action] [...]',
               'Remove a permission rule',
               self._complete_remove, self._do_remove)
    
    def get_user_list(self):
        return set(user for (user, action) in 
                   PermissionSystem(self.env).get_all_permissions())
    
    def get_user_perms(self, user):
        return [action for (subject, action) in
                PermissionSystem(self.env).get_all_permissions()
                if subject == user]
    
    def _complete_list(self, args):
        if len(args) == 1:
            return self.get_user_list()
    
    def _complete_add(self, args):
        if len(args) == 2:
            return self.get_user_list()
        elif len(args) >= 3:
            return (set(PermissionSystem(self.env).get_actions())
                    - set(self.get_user_perms(args[0])) - set(args[1:-1]))
    
    def _complete_remove(self, args):
        if len(args) == 2:
            return self.get_user_list()
        elif len(args) >= 3:
            return set(self.get_user_perms(args[0])) - set(args[1:-1])
    
    def _do_list(self, user=None):
        permsys = PermissionSystem(self.env)
        if user:
            rows = []
            perms = permsys.get_user_permissions(user)
            for action in perms:
                if perms[action]:
                    rows.append((user, action))
        else:
            rows = permsys.get_all_permissions()
        rows.sort()
        print_table(rows, [_('User'), _('Action')])
        print
        printout(_("Available actions:"))
        actions = permsys.get_actions()
        actions.sort()
        text = ', '.join(actions)
        printout(wrap(text, initial_indent=' ', subsequent_indent=' ', 
                      linesep='\n'))
        print
    
    def _do_add(self, area_id, user, *actions):
        kwargs = {}
        if area_id.startswith('S'):
            kwargs['syllabus_id'] = int(area_id[1:])
        elif area_id.startswith('P'):
            kwargs['pid'] = int(area_id[1:])
        permsys = PermissionSystem(self.env)
        if user.isupper():
            raise AdminCommandError(_('All upper-cased tokens are reserved '
                                      'for permission names'))
        for action in actions:
            try:
                permsys.grant_permission(user, action, **kwargs)
            except Exception, e:
                printout(exception_to_unicode(e))
    
    def _do_remove(self, area_id, user, *actions):
        kwargs = {}
        if area_id.startswith('S'):
            kwargs['syllabus_id'] = int(area_id[1:])
        elif area_id.startswith('P'):
            kwargs['pid'] = int(area_id[1:])
        permsys = PermissionSystem(self.env)
        rows = permsys.get_all_permissions()
        for action in actions:
            try:
                if action == '*':
                    for row in rows:
                        if user != '*' and user != row[0]:
                            continue
                        permsys.revoke_permission(row[0], row[1], **kwargs)
                else:
                    for row in rows:
                        if action != row[1]:
                            continue
                        if user != '*' and user != row[0]:
                            continue
                        permsys.revoke_permission(row[0], row[1], **kwargs)
            except Exception, e:
                printout(exception_to_unicode(e))



from trac.project.api import ProjectManagement
