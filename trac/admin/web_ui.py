# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Aleksey A. Porfirov
# Copyright (C) 2005-2009 Edgewall Software
# Copyright (C) 2005 Jonas Borgström <jonas@edgewall.com>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.com/license.html.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/.
#
# Author: Jonas Borgström <jonas@edgewall.com>

import os
import pkg_resources
import re
import shutil

from genshi import HTML
from genshi.builder import tag

from trac.admin.api import IAdminPanelProvider, AdminArea
from trac.core import *
from trac.loader import get_plugin_info, get_plugins_dir
from trac.perm import PermissionSystem, IPermissionRequestor
from trac.util.compat import partial
from trac.util.text import exception_to_unicode, \
                            unicode_to_base64, unicode_from_base64
from trac.util.translation import _, ngettext, tag_
from trac.web import HTTPNotFound, IRequestHandler
from trac.web.chrome import add_notice, add_stylesheet, \
                            add_warning, Chrome, INavigationContributor, \
                            ITemplateProvider
from trac.wiki.formatter import format_to_html

from trac.user.api import UserRole
from trac.project.api import ProjectManagement

from trac.user.model import Metagroup, Group, User
from trac.project.model import Syllabus, Project



class AdminModule(Component):
    """Web administration interface provider and panel manager."""

    implements(INavigationContributor, IRequestHandler, ITemplateProvider)

    panel_providers = ExtensionPoint(IAdminPanelProvider)

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'admin'

    def get_navigation_items(self, req):
        # The 'Admin' navigation item is only visible if at least one
        # admin panel is available
        if self._has_panels(req):
            yield 'mainnav', 'admin', tag.a(_('Admin'), href=req.href.admin(),
                                            title=_('Administration'))

    # IRequestHandler methods

    def match_request(self, req):
        if req.path_info.startswith('/admin/select'):
            return True

        match = re.match('/admin(?:/(s|m|g|p)/(\d+))?(?:/([^/]+)(?:/([^/]+)(?:/(.+))?)?)?$',
                         req.path_info)
        if match:
            req.args['admin_area'] = AdminArea.from_string(match.group(1))
            req.args['admin_area_id'] = int(match.group(2) or 0)
            req.args['cat_id'] = match.group(3)
            req.args['panel_id'] = match.group(4)
            req.args['path_info'] = match.group(5)
            return True

    def process_request(self, req):
        pid  = req.project # is project data ready
        role = req.data['role']

        if req.path_info.startswith('/admin/select'):
            return self._do_area_select(req, role)

        area    = req.args.get('admin_area')
        area_id = req.args.get('admin_area_id')

        redirect = False
        if area == AdminArea.GLOBAL and role != UserRole.ADMIN:
            if UserRole.PROJECT_MANAGER in role:
                area    = AdminArea.PROJECT
                area_id = req.data['project_id']
                redirect = True
            elif UserRole.GROUP_MANAGER in role:
                area    = AdminArea.GROUP
                area_id = req.data['group_id']
                redirect = True
            if redirect:
                req.redirect(req.href('admin', AdminArea.href_part(area, area_id)))

        self._check_access(req, area, area_id)

        panels, providers = self._get_panels(req, area)
        if not panels:
            raise HTTPNotFound(_('No administration panels available'))

        def _panel_order_key(p):
            if p[0] == 'general':
                if p[2] == 'basics':
                    return 1
                else:
                    return p[2]
            return p
        panels.sort(key=_panel_order_key)

        cat_id = req.args.get('cat_id') or panels[0][0]
        panel_id = req.args.get('panel_id')
        path_info = req.args.get('path_info')
        if not panel_id:
            try:
                panel_id = filter(
                            lambda panel: panel[0] == cat_id, panels)[0][2]
            except IndexError:
                raise HTTPNotFound(_('Unknown administration panel'))

        provider = providers.get((cat_id, panel_id), None)
        if not provider:
            raise HTTPNotFound(_('Unknown administration panel'))

        href_args = ['admin', AdminArea.href_part(area, area_id), cat_id, panel_id]
        panel_href = partial(req.href, *href_args)
        req.panel_href = panel_href

        arg_cnt = provider.render_admin_panel.func_code.co_argcount - 1
        args = [req, cat_id, panel_id, path_info]
        if arg_cnt == 6:
            args += [area, area_id]
        template, data = provider.render_admin_panel(*args)

        data.update({
            'area': area,
            'area_id': area_id,
            'area_label': AdminArea.label(area, area_id),
            'active_cat': cat_id, 'active_panel': panel_id,
            'admin_area_href': partial(req.href, 'admin', AdminArea.href_part(area, area_id)),
            'panel_href': panel_href,
            'panels': [{
                'category': {'id': panel[0], 'label': panel[1]},
                'panel': {'id': panel[2], 'label': panel[3]}
            } for panel in panels]
        })

        add_stylesheet(req, 'common/css/admin.css')
        return template, data, None

    def _do_area_select(self, req, role):
        areas = []
        if UserRole.PROJECT_MANAGER in role:
            areas.append(AdminArea.PROJECT)
        if UserRole.GROUP_MANAGER in role:
            areas.append(AdminArea.GROUP)
        if UserRole.ADMIN in role:
            areas.append(AdminArea.METAGROUP)
            areas.append(AdminArea.SYLLABUS)
            areas.append(AdminArea.GLOBAL)
        areas.reverse()

        links = []
        def add_link(header, area, area_id, name):
            links.append((header,
                          req.href.admin(AdminArea.href_part(area, area_id)),
                          name))

        session = self.env.get_sa_session()

        for area in areas:
            if area == AdminArea.GLOBAL:
                add_link(_('System'), area, None, _('Global admin area'))
            elif area == AdminArea.SYLLABUS:
                header = _('Syllabus')
                items = session.query(Syllabus.id, Syllabus.name).order_by(Syllabus.id).all()
                for id, name in items:
                    add_link(header, area, id, name)
            elif area == AdminArea.METAGROUP:
                header = _('Metagroup')
                items = session.query(Metagroup.id, Metagroup.name).order_by(Metagroup.id).all()
                for id, name in items:
                    add_link(header, area, id, name)
            elif area == AdminArea.GROUP:
                header = _('Group')
                if role == UserRole.ADMIN:
                    items = session.query(Group.id, Group.name).order_by(Group.id).all()
                elif UserRole.GROUP_MANAGER in role:
                    user = session.query(User).filter(User.username==req.authname).one()
                    items = [(g.id, g.name) for g in user.managed_groups]
                for id, name in items:
                    add_link(header, area, id, name)
            elif area == AdminArea.PROJECT:
                header = _('Project')
                if role == UserRole.ADMIN:
                    items = session.query(Project.id, Project.name).order_by(Project.id).all()
                elif UserRole.PROJECT_MANAGER in role:
                    items = self.pm.get_user_projects(req.authname, role, with_names=True)
                for id, name in items:
                    add_link(header, area, id, name)

        data = {
            'links': links,
        }
        return 'admin_select.html', data, None

    def _check_access(self, req, area, area_id):
        role = UserRole.ADMIN  # default required role
        if req.data['role'] == role:
            # Administrator can access everything
            return True
        if area == AdminArea.GROUP:
            role = UserRole.GROUP_MANAGER
        elif area == AdminArea.PROJECT:
            role = UserRole.PROJECT_MANAGER
        return self._require_role(req, role, area, area_id)

    def _require_role(self, req, role, area, area_id):
        if role not in req.data['role']:
            from trac.project.sys import PostloginModule
            switch_url = PostloginModule(self.env).role_switch_url(req.href)
            raise TracError(tag_('Role %(role)s required to access %(admin_area)s. '
                                 'You may %(change_role)s and try to access admin page again.',
                                 role=tag.strong(UserRole.label(role)),
                                 admin_area=tag.strong(AdminArea.label(area, area_id)),
                                 change_role=tag.a(_('change role'), href=switch_url)))

        if not self.pm.has_role(req.authname, role, area_id):
            raise TracError(_('Insufficient rights to access %(admin_area)s',
                              admin_area=AdminArea.label(area, area_id)))

    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        return []

    def get_templates_dirs(self):
        return [pkg_resources.resource_filename('trac.admin', 'templates')]

    # Internal methods

    def _has_panels(self, req):
        for provider in self.panel_providers:
            if list(provider.get_admin_panels(req)):
                return True
        return False

    def _get_panels(self, req, area):
        """Return a list of available admin panels for specifies `area`."""
        panels = []
        providers = {}

        for provider in self.panel_providers:
            p = list(provider.get_admin_panels(req) or [])
            for panel in p:
                if len(panel) == 4:
                    # legacy form, implicit GLOBAL area
                    areas = (AdminArea.GLOBAL,)
                else:
                    areas = panel[4]
                    panel = panel[:4]
                if area not in areas:
                    continue
                providers[(panel[0], panel[2])] = provider
                panels.append(panel)

        return panels, providers


def _save_config(config, req, log, notices=None):
    """Try to save the config, and display either a success notice or a
    failure warning.
    """
    try:
        config.save()
        if notices is None:
            notices = [_('Your changes have been saved.')]
        for notice in notices:
            add_notice(req, notice)
    except Exception, e:
        log.error('Error writing to trac.ini: %s', exception_to_unicode(e))
        add_warning(req, _('Error writing to trac.ini, make sure it is '
                           'writable by the web server. Your changes have '
                           'not been saved.'))


class BasicsAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', _('General'), 'basics', _('Basic Settings'))

    def render_admin_panel(self, req, cat, page, path_info):
        req.perm.require('TRAC_ADMIN')

        if req.method == 'POST':
            for option in ('name', 'url', 'descr'):
                self.config.set('project', option, req.args.get(option))
            _save_config(self.config, req, self.log)
            req.redirect(req.href.admin(cat, page))

        data = {
            'name': self.env.project_name,
            'description': self.env.project_description,
            'url': self.env.project_url
        }
        Chrome(self.env).add_textarea_grips(req)
        return 'admin_basics.html', {'environment': data}


class LoggingAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', _('General'), 'logging', _('Logging'))

    def render_admin_panel(self, req, cat, page, path_info):
        log_type = self.env.log_type
        log_level = self.env.log_level
        log_file = self.env.log_file
        log_dir = os.path.join(self.env.path, 'log')

        log_types = [
            dict(name='none', label=_('None'), selected=log_type == 'none', disabled=False),
            dict(name='stderr', label=_('Console'),
                 selected=log_type == 'stderr', disabled=False),
            dict(name='file', label=_('File'), selected=log_type == 'file',
                 disabled=False),
            dict(name='syslog', label=_('Syslog'), disabled=os.name != 'posix',
                 selected=log_type in ('unix', 'syslog')),
            dict(name='eventlog', label=_('Windows event log'),
                 disabled=os.name != 'nt',
                 selected=log_type in ('winlog', 'eventlog', 'nteventlog')),
        ]

        log_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

        if req.method == 'POST':
            changed = False

            new_type = req.args.get('log_type')
            if new_type not in [t['name'] for t in log_types]:
                raise TracError(
                    _('Unknown log type %(type)s', type=new_type),
                    _('Invalid log type')
                )
            if new_type != log_type:
                self.config.set('logging', 'log_type', new_type)
                changed = True
                log_type = new_type

            if log_type == 'none':
                self.config.remove('logging', 'log_level')
                changed = True
            else:
                new_level = req.args.get('log_level')
                if new_level not in log_levels:
                    raise TracError(
                        _('Unknown log level %(level)s', level=new_level),
                        _('Invalid log level'))
                if new_level != log_level:
                    self.config.set('logging', 'log_level', new_level)
                    changed = True
                    log_level = new_level

            if log_type == 'file':
                new_file = req.args.get('log_file', 'trac.log')
                if new_file != log_file:
                    self.config.set('logging', 'log_file', new_file)
                    changed = True
                    log_file = new_file
                if not log_file:
                    raise TracError(_('You must specify a log file'),
                                    _('Missing field'))
            else:
                self.config.remove('logging', 'log_file')
                changed = True

            if changed:
                _save_config(self.config, req, self.log),
            req.redirect(req.href.admin(cat, page))

        data = {
            'type': log_type, 'types': log_types,
            'level': log_level, 'levels': log_levels,
            'file': log_file, 'dir': log_dir
        }
        return 'admin_logging.html', {'log': data}


class PermissionAdminPanel(Component):

    implements(IAdminPanelProvider, IPermissionRequestor)

    # IPermissionRequestor methods
    def get_permission_actions(self):
        actions = ['PERMISSION_GRANT', 'PERMISSION_REVOKE']
        return actions + [('PERMISSION_ADMIN', actions)]

    # IAdminPanelProvider methods
    def get_admin_panels(self, req):
        if 'PERMISSION_GRANT' in req.perm or 'PERMISSION_REVOKE' in req.perm:
            yield ('general', _('General'), 'perm', _('Permissions'),
                   set([AdminArea.GLOBAL, AdminArea.SYLLABUS, AdminArea.PROJECT]))

    def render_admin_panel(self, req, cat, page, path_info, area, area_id):
        perm = PermissionSystem(self.env)

        perm_get_kwargs = {}
        perm_change_kwargs = {}
        if area == AdminArea.SYLLABUS:
            perm_get_kwargs.update({
                'syllabus_id': area_id,
                'inherit': False,
            })
            perm_change_kwargs['syllabus_id'] = area_id
        elif area == AdminArea.PROJECT:
            perm_get_kwargs.update({
                'project_id': area_id,
                'inherit': False,
            })
            perm_change_kwargs['project_id'] = area_id

        all_permissions = perm.get_all_permissions(**perm_get_kwargs)
        all_actions = perm.get_actions()

        if req.method == 'POST':
            subject = req.args.get('subject', '').strip()
            action = req.args.get('action')
            group = req.args.get('group', '').strip()

            if subject and subject.isupper() or \
                   group and group.isupper():
                raise TracError(_('All upper-cased tokens are reserved for '
                                  'permission names'))

            # Grant permission to subject
            if req.args.get('add') and subject and action:
                req.perm.require('PERMISSION_GRANT')
                if action not in all_actions:
                    raise TracError(_('Unknown action'))
                req.perm.require(action)
                if (subject, action) not in all_permissions:
                    perm.grant_permission(subject, action, **perm_change_kwargs)
                    add_notice(req, _('The subject %(subject)s has been '
                                      'granted the permission %(action)s.',
                                      subject=subject, action=action))
                    req.redirect(req.panel_href())
                else:
                    add_warning(req, _('The permission %(action)s was already '
                                       'granted to %(subject)s.',
                                       action=action, subject=subject))

            # Add subject to group
            elif req.args.get('add') and subject and group:
                req.perm.require('PERMISSION_GRANT')
                kwargs = perm_get_kwargs.copy()
                kwargs['inherit'] = True
                for action in perm.get_user_permissions(group, **kwargs):
                    if not action in all_actions: # plugin disabled?
                        self.env.log.warn("Adding %s to group %s: " \
                            "Permission %s unavailable, skipping perm check." \
                            % (subject, group, action))
                    else:
                        req.perm.require(action)
                if (subject, group) not in all_permissions:
                    perm.grant_permission(subject, group, **perm_change_kwargs)
                    add_notice(req, _('The subject %(subject)s has been added '
                                      'to the group %(group)s.',
                                      subject=subject, group=group))
                    req.redirect(req.panel_href())
                else:
                    add_warning(req, _('The subject %(subject)s was already '
                                       'added to the group %(group)s.',
                                       subject=subject, group=group))

            # Remove permissions action
            elif req.args.get('remove') and req.args.get('sel'):
                req.perm.require('PERMISSION_REVOKE')
                sel = req.args.get('sel')
                sel = isinstance(sel, list) and sel or [sel]
                for key in sel:
                    subject, action = key.split(':', 1)
                    subject = unicode_from_base64(subject)
                    action = unicode_from_base64(action)
                    if (subject, action) in perm.get_all_permissions(**perm_get_kwargs):
                        perm.revoke_permission(subject, action, **perm_change_kwargs)
                add_notice(req, _('The selected permissions have been '
                                  'revoked.'))
                req.redirect(req.panel_href())

        return 'admin_perms.html', {
            'actions': all_actions,
            'perms': all_permissions,
            'unicode_to_base64': unicode_to_base64
        }


class PluginAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', _('General'), 'plugin', _('Plugins'))

    def render_admin_panel(self, req, cat, page, path_info):
        req.perm.require('TRAC_ADMIN')

        if req.method == 'POST':
            if 'install' in req.args:
                self._do_install(req)
            elif 'uninstall' in req.args:
                self._do_uninstall(req)
            else:
                self._do_update(req)
            anchor = ''
            if req.args.has_key('plugin'):
                anchor = '#no%d' % (int(req.args.get('plugin')) + 1)
            req.redirect(req.href.admin(cat, page) + anchor)

        return self._render_view(req)

    # Internal methods

    def _do_install(self, req):
        """Install a plugin."""
        if not req.args.has_key('plugin_file'):
            raise TracError(_('No file uploaded'))
        upload = req.args['plugin_file']
        if isinstance(upload, unicode) or not upload.filename:
            raise TracError(_('No file uploaded'))
        plugin_filename = upload.filename.replace('\\', '/').replace(':', '/')
        plugin_filename = os.path.basename(plugin_filename)
        if not plugin_filename:
            raise TracError(_('No file uploaded'))
        if not plugin_filename.endswith('.egg') and \
                not plugin_filename.endswith('.py'):
            raise TracError(_('Uploaded file is not a Python source file or '
                              'egg'))

        target_path = os.path.join(self.env.path, 'plugins', plugin_filename)
        if os.path.isfile(target_path):
            raise TracError(_('Plugin %(name)s already installed',
                              name=plugin_filename))

        self.log.info('Installing plugin %s', plugin_filename)
        flags = os.O_CREAT + os.O_WRONLY + os.O_EXCL
        try:
            flags += os.O_BINARY
        except AttributeError:
            # OS_BINARY not available on every platform
            pass
        target_file = os.fdopen(os.open(target_path, flags, 0666), 'w')
        try:
            shutil.copyfileobj(upload.file, target_file)
            self.log.info('Plugin %s installed to %s', plugin_filename,
                          target_path)
        finally:
            target_file.close()

        # TODO: Validate that the uploaded file is actually a valid Trac plugin

        # Make the environment reset itself on the next request
        self.env.config.touch()

    def _do_uninstall(self, req):
        """Uninstall a plugin."""
        plugin_filename = req.args.get('plugin_filename')
        if not plugin_filename:
            return
        plugin_path = os.path.join(self.env.path, 'plugins', plugin_filename)
        if not os.path.isfile(plugin_path):
            return
        self.log.info('Uninstalling plugin %s', plugin_filename)
        os.remove(plugin_path)

        # Make the environment reset itself on the next request
        self.env.config.touch()

    def _do_update(self, req):
        """Update component enablement."""
        components = req.args.getlist('component')
        enabled = req.args.getlist('enable')
        added, removed = [], []

        # FIXME: this needs to be more intelligent and minimize multiple
        # component names to prefix rules

        for component in components:
            is_enabled = bool(self.env.is_component_enabled(component))
            must_enable = component in enabled
            if is_enabled != must_enable:
                self.config.set('components', component,
                                is_enabled and 'disabled' or 'enabled')
                self.log.info('%sabling component %s',
                              is_enabled and 'Dis' or 'En', component)
                if must_enable:
                    added.append(component)
                else:
                    removed.append(component)

        if added or removed:
            def make_list(items):
                parts = [item.rsplit('.', 1) for item in items]
                return tag.table(tag.tbody(
                    tag.tr(tag.td(c, class_='trac-name'),
                           tag.td('(%s.*)' % m, class_='trac-name'))
                    for m, c in parts), class_='trac-pluglist')

            added.sort()
            removed.sort()
            notices = []
            if removed:
                msg = ngettext('The following component has been disabled:',
                               'The following components have been disabled:',
                               len(removed))
                notices.append(tag(msg, make_list(removed)))
            if added:
                msg = ngettext('The following component has been enabled:',
                               'The following components have been enabled:',
                               len(added))
                notices.append(tag(msg, make_list(added)))

            _save_config(self.config, req, self.log, notices)

    def _render_view(self, req):
        plugins = get_plugin_info(self.env, include_core=True)

        def safe_wiki_to_html(context, text):
            try:
                return format_to_html(self.env, context, text)
            except Exception, e:
                self.log.error('Unable to render component documentation: %s',
                               exception_to_unicode(e, traceback=True))
                return tag.pre(text)

        data = {
            'plugins': plugins, 'show': req.args.get('show'),
            'readonly': not os.access(get_plugins_dir(self.env),
                                      os.F_OK + os.W_OK),
            'safe_wiki_to_html': safe_wiki_to_html,
        }
        return 'admin_plugins.html', data
