# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2005 Jonas Borgström <jonas@edgewall.com>
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

from datetime import datetime
import os.path
import re
import shutil
import sys
import unicodedata

from genshi.builder import tag

from trac.admin import AdminCommandError, IAdminCommandProvider, PrefixList, \
                       console_datetime_format, get_dir_list
from trac.config import BoolOption, IntOption
from trac.core import *
from trac.env import IEnvironmentSetupParticipant
from trac.mimeview import *
from trac.perm import PermissionError, IPermissionPolicy
from trac.resource import *
from trac.search import search_to_sql, shorten_result
from trac.util import get_reporter_id, create_unique_file
from trac.util.datefmt import format_datetime, from_utimestamp, \
                              to_datetime, to_utimestamp, utc
from trac.util.text import exception_to_unicode, path_to_unicode, \
                           pretty_size, print_table, unicode_quote, \
                           unicode_unquote
from trac.util.translation import _, tag_
from trac.web import HTTPBadRequest, IRequestHandler
from trac.web.chrome import add_link, add_stylesheet, add_ctxtnav, \
                            INavigationContributor
from trac.web.href import Href
from trac.wiki.api import IWikiSyntaxProvider
from trac.wiki.formatter import format_to

from trac.project.api import ProjectManagement



class InvalidAttachment(TracError):
    """Exception raised when attachment validation fails."""


class IAttachmentChangeListener(Interface):
    """Extension point interface for components that require notification when
    attachments are created or deleted."""

    def attachment_added(attachment):
        """Called when an attachment is added."""

    def attachment_deleted(attachment):
        """Called when an attachment is deleted."""

    def attachment_reparented(attachment, old_parent_realm, old_parent_id, old_parent_pid):
        """Called when an attachment is reparented."""


class IAttachmentManipulator(Interface):
    """Extension point interface for components that need to manipulate
    attachments.
    
    Unlike change listeners, a manipulator can reject changes being committed
    to the database."""

    def prepare_attachment(req, attachment, fields):
        """Not currently called, but should be provided for future
        compatibility."""

    def validate_attachment(req, attachment):
        """Validate an attachment after upload but before being stored in Trac
        environment.
        
        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be any of `description`, `username`, `filename`,
        `content`, or `None` to indicate an overall problem with the
        attachment. Therefore, a return value of `[]` means everything is
        OK."""

class ILegacyAttachmentPolicyDelegate(Interface):
    """Interface that can be used by plugins to seemlessly participate to the
       legacy way of checking for attachment permissions.

       This should no longer be necessary once it becomes easier to 
       setup fine-grained permissions in the default permission store.
    """

    def check_attachment_permission(action, username, resource, perm):
        """Return the usual True/False/None security policy decision
           appropriate for the requested action on an attachment.

            :param action: one of ATTACHMENT_VIEW, ATTACHMENT_CREATE,
                                  ATTACHMENT_DELETE
            :param username: the user string
            :param resource: the `Resource` for the attachment. Note that when
                             ATTACHMENT_CREATE is checked, the resource `.id`
                             will be `None`. 
            :param perm: the permission cache for that username and resource
            """


class Attachment(object):

    def __init__(self, env, parent_realm_or_attachment_resource,
                 parent_id=None, filename=None, db=None, parent_pid=None):
        if isinstance(parent_realm_or_attachment_resource, Resource):
            self.resource = parent_realm_or_attachment_resource
        else:
            parent_rsc = Resource(parent_realm_or_attachment_resource,
                                  parent_id, pid=parent_pid)
            if parent_rsc.need_pid and parent_rsc.pid is None:
                raise TracError('Parent project ID is not set for attachment')
            # else
            # pid is None     -> attachment for global rsc
            # pid is not None -> attachment for project rsc
            self.resource = parent_rsc.child('attachment', filename)
        self.env = env
        self.parent_realm = self.resource.parent.realm
        self.parent_id = unicode(self.resource.parent.id)
        self.parent_pid = self.resource.parent.pid
        if self.resource.id:
            self._fetch(self.resource.id, db)
        else:
            self.filename = None
            self.description = None
            self.size = None
            self.date = None
            self.author = None
            self.ipnr = None

    def _set_filename(self, val):
        self.resource.id = val

    filename = property(lambda self: self.resource.id, _set_filename)

    def _fetch(self, filename, db=None):
        if not db:
            db = self.env.get_read_db()
        q = """
            SELECT filename,description,size,time,author,ipnr FROM attachment
            WHERE type=%s AND id=%s AND filename=%s {pid_cond}
            ORDER BY time
            """
        args = (self.parent_realm, unicode(self.parent_id), filename)
        q, args = self._format_pid_cond_query(q, args, self.parent_pid)
        cursor = db.cursor()
        cursor.execute(q, args)
        row = cursor.fetchone()
        cursor.close()
        if not row:
            self.filename = filename
            raise ResourceNotFound(_("Attachment '%(title)s' does not exist.",
                                     title=self.title),
                                   _('Invalid Attachment'))
        self.filename = row[0]
        self.description = row[1]
        self.size = row[2] and int(row[2]) or 0
        self.date = from_utimestamp(row[3])
        self.author = row[4]
        self.ipnr = row[5]

    @staticmethod
    def _format_pid_cond_query(q, args, parent_pid=None):
        if parent_pid is False:
            return q.format(pid_cond=''), args
        q = q.format(pid_cond = 'AND project_id=%s')
        args = list(args)
        args.append(parent_pid if parent_pid is not None else GLOBAL_PID)
        return q, args

    def _get_path(self, parent_realm, parent_id, parent_pid, filename):
        args = ['attachments']
        if parent_pid is not None:
            args.extend(['project', str(parent_pid)])
        args.extend([parent_realm, unicode_quote(parent_id)])
        path = os.path.join(self.env.path, *args)
        if filename:
            path = os.path.join(path, unicode_quote(filename))
        return os.path.normpath(path)
    
    @property
    def path(self):
        return self._get_path(self.parent_realm, self.parent_id, self.parent_pid, self.filename)

    @property
    def title(self):
        if self.parent_pid is not None:
            return 'P#%s:%s:%s: %s' % (self.parent_pid, self.parent_realm, self.parent_id, self.filename)
        else:
            return '%s:%s: %s' % (self.parent_realm, self.parent_id, self.filename)

    def delete(self, db=None):
        assert self.filename, 'Cannot delete non-existent attachment'

        @self.env.with_transaction(db)
        def do_delete(db):
            q = '''
                DELETE FROM attachment
                WHERE type=%s AND id=%s AND filename=%s {pid_cond}
            '''
            args = (self.parent_realm, self.parent_id, self.filename)
            q, args = self._format_pid_cond_query(q, args, self.parent_pid)
            cursor = db.cursor()
            cursor.execute(q, args)
            if os.path.isfile(self.path):
                try:
                    os.unlink(self.path)
                except OSError, e:
                    self.env.log.error('Failed to delete attachment '
                                       'file %s: %s',
                                       self.path,
                                       exception_to_unicode(e, traceback=True))
                    raise TracError(_('Could not delete attachment'))

        self.env.log.info('Attachment removed: %s' % self.title)

        for listener in AttachmentModule(self.env).change_listeners:
            listener.attachment_deleted(self)

    def reparent(self, new_realm, new_id, new_pid=None):
        assert self.filename, 'Cannot reparent non-existent attachment'
        new_id = unicode(new_id)
        
        @self.env.with_transaction()
        def do_reparent(db):
            cursor = db.cursor()
            new_path = self._get_path(new_realm, new_id, new_pid, self.filename)

            # Make sure the path to the attachment is inside the environment
            # attachments directory
            attachments_dir = os.path.join(os.path.normpath(self.env.path),
                                           'attachments')
            commonprefix = os.path.commonprefix([attachments_dir, new_path])
            if commonprefix != attachments_dir:
                raise TracError(_('Cannot reparent attachment "%(att)s" as '
                                  '%(realm)s:%(id)s is invalid', 
                                  att=self.filename, realm=new_realm,
                                  id=new_id))

            if os.path.exists(new_path):
                raise TracError(_('Cannot reparent attachment "%(att)s" as '
                                  'it already exists in %(realm)s:%(id)s', 
                                  att=self.filename, realm=new_realm,
                                  id=new_id))
            q = """
                UPDATE attachment SET type=%s, id=%s
                WHERE type=%s AND id=%s AND filename=%s {pid_cond}
            """
            args = (new_realm, new_id, self.parent_realm, self.parent_id, self.filename)
            q, args = self._format_pid_cond_query(q, args, self.parent_pid)
            cursor.execute(q, args)
            dirname = os.path.dirname(new_path)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            if os.path.isfile(self.path):
                try:
                    os.rename(self.path, new_path)
                except OSError, e:
                    self.env.log.error('Failed to move attachment file %s: %s',
                                       self.path,
                                       exception_to_unicode(e, traceback=True))
                    raise TracError(_('Could not reparent attachment %(name)s',
                                      name=self.filename))

        old_realm, old_id, old_pid = self.parent_realm, self.parent_id, self.parent_pid
        self.parent_realm, self.parent_id, self.parent_pid = new_realm, new_id, new_pid
        self.resource = Resource(new_realm, new_id, pid=new_pid).child('attachment',
                                                          self.filename)
        
        self.env.log.info('Attachment reparented: %s' % self.title)

        for listener in AttachmentModule(self.env).change_listeners:
            if hasattr(listener, 'attachment_reparented'):
                listener.attachment_reparented(self, old_realm, old_id, old_pid)

    def insert(self, filename, fileobj, size, t=None, db=None):
        self.filename = None
        self.size = size and int(size) or 0
        if t is None:
            t = datetime.now(utc)
        elif not isinstance(t, datetime): # Compatibility with 0.11
            t = to_datetime(t, utc)
        self.date = t

        # Make sure the path to the attachment is inside the environment
        # attachments directory
        attachments_dir = os.path.join(os.path.normpath(self.env.path),
                                       'attachments')
        commonprefix = os.path.commonprefix([attachments_dir, self.path])
        if commonprefix != attachments_dir:
            raise TracError(_('Cannot create attachment "%(att)s" as '
                              '%(realm)s:%(id)s is invalid', 
                              att=filename, realm=self.parent_realm,
                              id=self.parent_id))

        if not os.access(self.path, os.F_OK):
            os.makedirs(self.path)
        filename = unicode_quote(filename)
        path, targetfile = create_unique_file(os.path.join(self.path,
                                                           filename))
        try:
            # Note: `path` is an unicode string because `self.path` was one.
            # As it contains only quoted chars and numbers, we can use `ascii`
            basename = os.path.basename(path).encode('ascii')
            filename = unicode_unquote(basename)

            @self.env.with_transaction(db)
            def do_insert(db):
                cursor = db.cursor()
                pid = self.parent_pid if self.parent_pid is not None else GLOBAL_PID
                cursor.execute("INSERT INTO attachment (type,id,project_id,filename,size,time,description,author,ipnr)"
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                               (self.parent_realm, self.parent_id, pid, filename,
                                self.size, to_utimestamp(t), self.description,
                                self.author, self.ipnr))
                shutil.copyfileobj(fileobj, targetfile)
                self.resource.id = self.filename = filename

                self.env.log.info('New attachment: %s by %s', self.title,
                                  self.author)
        finally:
            targetfile.close()

        for listener in AttachmentModule(self.env).change_listeners:
            listener.attachment_added(self)


    @classmethod
    def select(cls, env, parent_realm_or_resource, parent_id=None, parent_pid=None, db=None):
        if not db:
            db = env.get_read_db()
        if isinstance(parent_realm_or_resource, Resource):
            resource = parent_realm_or_resource
        else:
            resource = Resource(parent_realm_or_resource, parent_id, pid=parent_pid)
        if resource.need_pid and resource.pid is None:
            raise TracError('Parent project ID is not set for attachment')
        parent_realm = resource.realm
        parent_id    = resource.id
        # if we don't need pid to select - do not use it
        parent_pid   = resource.pid if resource.need_pid else False
        q = '''
            SELECT filename,description,size,time,author,ipnr
            FROM attachment WHERE type=%s AND id=%s {pid_cond} ORDER BY time
            '''
        args = (parent_realm, unicode(parent_id))
        q, args = cls._format_pid_cond_query(q, args, parent_pid)
        cursor = db.cursor()
        cursor.execute(q, args)
        for filename, description, size, time, author, ipnr in cursor:
            attachment = Attachment(env, parent_realm, parent_id, parent_pid=parent_pid)
            attachment.filename = filename
            attachment.description = description
            attachment.size = size and int(size) or 0
            attachment.date = from_utimestamp(time or 0)
            attachment.author = author
            attachment.ipnr = ipnr
            yield attachment

    @classmethod
    def delete_all(cls, env, parent_realm_or_resource, parent_id=None, parent_pid=None, db=None):
        """Delete all attachments of a given resource."""
        attachment_dir = [None]
        @env.with_transaction(db)
        def do_delete(db):
            for attachment in list(cls.select(env, parent_realm_or_resource, parent_id, parent_pid,
                                              db)):
                attachment_dir[0] = os.path.dirname(attachment.path)
                attachment.delete()
        if attachment_dir[0]:
            try:
                os.rmdir(attachment_dir[0])
            except OSError, e:
                env.log.error("Can't delete attachment directory %s: %s",
                    attachment_dir[0], exception_to_unicode(e, traceback=True))

    @classmethod
    def reparent_all(cls, env, parent_realm, parent_id, parent_pid, new_realm, new_id, new_pid):
        """Reparent all attachments of a given resource to another resource."""
        attachment_dir = [None]
        @env.with_transaction()
        def do_reparent(db):
            for attachment in list(cls.select(env, parent_realm, parent_id, parent_pid,
                                              db)):
                attachment_dir = os.path.dirname(attachment.path)
                attachment.reparent(new_realm, new_id, new_pid)
        if attachment_dir[0]:
            try:
                os.rmdir(attachment_dir[0])
            except OSError, e:
                env.log.error("Can't delete attachment directory %s: %s",
                    attachment_dir[0], exception_to_unicode(e, traceback=True))
            
    def open(self):
        self.env.log.debug('Trying to open attachment at %s', self.path)
        try:
            fd = open(self.path, 'rb')
        except IOError:
            raise ResourceNotFound(_("Attachment '%(filename)s' not found",
                                     filename=self.filename))
        return fd


class AttachmentModule(Component):

    implements(IEnvironmentSetupParticipant, IRequestHandler,
               INavigationContributor, IWikiSyntaxProvider,
               IResourceManager)

    change_listeners = ExtensionPoint(IAttachmentChangeListener)
    manipulators = ExtensionPoint(IAttachmentManipulator)

    CHUNK_SIZE = 4096

    max_size = IntOption('attachment', 'max_size', 262144,
        """Maximum allowed file size (in bytes) for ticket and wiki 
        attachments.""")

    render_unsafe_content = BoolOption('attachment', 'render_unsafe_content',
                                       'false',
        """Whether attachments should be rendered in the browser, or
        only made downloadable.

        Pretty much any file may be interpreted as HTML by the browser,
        which allows a malicious user to attach a file containing cross-site
        scripting attacks.

        For public sites where anonymous users can create attachments it is
        recommended to leave this option disabled (which is the default).""")

    def __init__(self):
        self.rs = ResourceSystem(self.env)

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        """Create the attachments directory."""
        if self.env.path:
            os.mkdir(os.path.join(self.env.path, 'attachments'))

    def environment_needs_upgrade(self, db):
        return False

    def upgrade_environment(self, db):
        pass

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return req.args.get('realm')

    def get_navigation_items(self, req):
        return []

    # IRequestHandler methods

    def match_request(self, req):
#        match = re.match(r'/(raw-)?attachment/([^/]+)(?:/(.*))?$',
#                         req.path_info)
        match = re.match(r'/(raw-)?attachment/(.*)$',
                         req.path_info)
        if match:
            raw, path = match.groups()
            if raw:
                req.args['format'] = 'raw'
            if path:
#                if 'pid' in req.args:
#                    path = 'project/{0}/{1}'.format(req.args['pid'], path)
                req.args['path'] = path
            return True

    def process_request(self, req):
        parent_url = None
#        parent_realm = req.args.get('realm')
#        parent_pid = req.args.getint('pid')
        path = req.args.get('path')
        filename = None
        
        if not path:
            raise HTTPBadRequest(_('Bad request'))

#        parent_realm = Resource(parent_realm)
        action = req.args.get('action', 'view')
        if action == 'new':
            parent_url = path.rstrip('/')
        else:
            segments = path.split('/')
            parent_url = '/'.join(segments[:-1])
            filename = len(segments) > 1 and segments[-1]

#        parent = parent_realm(id=parent_id, pid=parent_pid)
#        url = '/'.join((parent_realm, parent_id))
        real_rsc = get_real_resource_from_url(self.env, parent_url, req.args)
        parent = real_rsc.resource
        res_pid = parent.pid

        # TODO: check if check is OK (pid, global, ...)
        # e.g. global wiki attachment - how to check WIKI_GLOBAL_ACTION

        # project check
        if res_pid is not None:
            pm = ProjectManagement(self.env)
            cur_pid = pm.get_current_project(req)
            if res_pid != cur_pid:
                pm.redirect_to_project(req, res_pid)

        
        # Link the attachment page to parent resource
        parent_name = get_resource_name(self.env, parent)
        parent_url = get_resource_url(self.env, parent, req.href)
        add_link(req, 'up', parent_url, parent_name)
        add_ctxtnav(req, _('Back to %(parent)s', parent=parent_name), 
                    parent_url)
        
        if action != 'new' and not filename: 
            # there's a trailing '/', show the list
            return self._render_list(req, parent)

        attachment = Attachment(self.env, parent.child('attachment', filename))
        
        if req.method == 'POST':
            if action == 'new':
                self._do_save(req, attachment)
            elif action == 'delete':
                self._do_delete(req, attachment)
        elif action == 'delete':
            data = self._render_confirm_delete(req, attachment)
        elif action == 'new':
            data = self._render_form(req, attachment)
        else:
            data = self._render_view(req, attachment)

        add_stylesheet(req, 'common/css/code.css')
        return 'attachment.html', data, None

    # IWikiSyntaxProvider methods
    
    def get_wiki_syntax(self):
        return []

    def get_link_resolvers(self):
        yield ('raw-attachment', self._format_link)
        yield ('attachment', self._format_link)

    # Public methods

    def attachment_data(self, context):
        """Return the list of viewable attachments.

        :param context: the rendering context corresponding to the parent
                        `Resource` of the attachments
        """
        parent = context.resource
        attachments = []
        for attachment in Attachment.select(self.env, parent):
            if 'ATTACHMENT_VIEW' in context.perm(attachment.resource):
                attachments.append(attachment)
        new_att = parent.child('attachment')
        return {'attach_href': get_resource_url(self.env, new_att,
                                                context.href, action='new'),
                'can_create': 'ATTACHMENT_CREATE' in context.perm(new_att),
                'attachments': attachments,
                'parent': context.resource}
    
    def get_history(self, start, stop, realm, pid):
        """Return an iterable of tuples describing changes to attachments on
        a particular object realm.

        The tuples are in the form (change, realm, id, filename, time,
        description, author). `change` can currently only be `created`.
        """
        is_global = pid is None
        if is_global and not self.rs.has_global_resources(realm):
            return
        has_project = self.rs.has_project_resources(realm)
        if not is_global and not has_project:
            return
        need_pid = Resource(realm).need_pid
        # Traverse attachment directory
        db = self.env.get_read_db()
        cursor = db.cursor()
        query = '''
            SELECT {sel_pid} a.type, a.id, a.filename, a.time, a.description, a.author
            FROM attachment a
            LEFT JOIN "{rsc_tab}" r ON CAST(r."{rsc_id}" AS varchar)=a.id
            WHERE a.time > %s AND a.time < %s AND a.type = %s {and_pid}
        '''
        rsc_tab = self.rs.get_realm_table(realm)
        rsc_id  = self.rs.get_realm_id(realm)
        sql_args = [to_utimestamp(start), to_utimestamp(stop), realm]
        if has_project:
            if is_global:
                sel_pid = 'r.project_id,'
                and_pid = ''
            else:
                sel_pid = ''
                and_pid = 'AND r.project_id=%s'
                sql_args.append(pid)
        else:
            sel_pid = ''
            and_pid = ''
        query = query.format(sel_pid=sel_pid, rsc_tab=rsc_tab, rsc_id=rsc_id, and_pid=and_pid)
        cursor.execute(query, sql_args)
        if is_global:
            raise NotImplementedError
            if has_project:
                for project_id, realm, id, filename, ts, description, author in cursor:
                    time = from_utimestamp(ts)
                    yield ('created', project_id, realm, id, filename, time, description, author)
        else:
            for realm, id, filename, ts, description, author in cursor:
                time = from_utimestamp(ts)
                yield ('created', realm, id, filename, time, description, author)

    def get_timeline_events(self, req, resource_realm, start, stop, pid):
        """Return an event generator suitable for ITimelineEventProvider.

        Events are changes to attachments on resources of the given
        `resource_realm.realm`.
        """
        for change, realm, id, filename, time, descr, author in \
                self.get_history(start, stop, resource_realm.realm, pid):
            attachment = resource_realm(id=id, pid=pid).child('attachment', filename)
            if 'ATTACHMENT_VIEW' in req.perm(attachment):
                yield ('attachment', time, author, (attachment, descr), self)

    def render_timeline_event(self, context, field, event):
        attachment, descr = event[3]
        if field == 'url':
            return self.get_resource_url(attachment, context.href)
        elif field == 'title':
            name = get_resource_name(self.env, attachment.parent)
            title = get_resource_summary(self.env, attachment.parent)
            return tag_("%(attachment)s attached to %(resource)s",
                        attachment=tag.em(os.path.basename(attachment.id)),
                        resource=tag.em(name, title=title))
        elif field == 'description':
            return format_to(self.env, None, context(attachment.parent), descr)
   
    def get_search_results(self, req, resource_realm, terms):
        """Return a search result generator suitable for ISearchSource.
        
        Search results are attachments on resources of the given 
        `resource_realm.realm` whose filename, description or author match 
        the given terms.
        """
        db = self.env.get_db_cnx()
        sql_query, args = search_to_sql(db, ['filename', 'description', 
                                        'author'], terms)
        cursor = db.cursor()
        cursor.execute("SELECT id,time,filename,description,author "
                       "FROM attachment "
                       "WHERE type = %s "
                       "AND " + sql_query, (resource_realm.realm, ) + args)
        
        for id, time, filename, desc, author in cursor:
            attachment = resource_realm(id=id).child('attachment', filename)
            if 'ATTACHMENT_VIEW' in req.perm(attachment):
                yield (get_resource_url(self.env, attachment, req.href),
                       get_resource_shortname(self.env, attachment),
                       from_utimestamp(time), author,
                       shorten_result(desc, terms))
    
    # IResourceManager methods
    
    def get_resource_realms(self):
        yield 'attachment'

    def get_resource_url(self, resource, href, **kwargs):
        """Return an URL to the attachment itself.

        A `format` keyword argument equal to `'raw'` will be converted
        to the raw-attachment prefix.
        """
        if not resource.parent:
            return None
        format = kwargs.get('format')
        prefix = 'attachment'
        if format == 'raw':
            kwargs.pop('format')
            prefix = 'raw-attachment'
#        parent_href = unicode_unquote(get_resource_url(self.env,
#                            resource.parent(version=None), Href('')))
        parent_href = get_resource_url(self.env, resource.parent(version=None))
        if not resource.id: 
            # link to list of attachments, which must end with a trailing '/' 
            # (see process_request)
            return href(prefix, parent_href) + '/'
        else:
            return href(prefix, parent_href, resource.id, **kwargs)

    def get_resource_description(self, resource, format=None, **kwargs):
        if not resource.parent:
            return _("Unparented attachment %(id)s", id=resource.id)
        if format == 'compact':
            return '%s (%s)' % (resource.id,
                    get_resource_name(self.env, resource.parent))
        elif format == 'summary':
            return Attachment(self.env, resource).description
        if resource.id:
            return _("Attachment '%(id)s' in %(parent)s", id=resource.id,
                     parent=get_resource_name(self.env, resource.parent))
        else:
            return _("Attachments of %(parent)s",
                     parent=get_resource_name(self.env, resource.parent))

    def resource_exists(self, resource):
        try:
            attachment = Attachment(self.env, resource)
            return os.path.exists(attachment.path)
        except ResourceNotFound:
            return False

    def get_realm_info(self):
        return {
            'attachment': {
                'need_pid': False,
            }
        }

    def has_project_resources(self, realm):
        if realm == 'attachment':
            return None

    def has_global_resources(self, realm):
        if realm == 'attachment':
            return None

    def is_slave_realm(self, realm):
        if realm == 'attachment':
            return True

    def get_realm_table(self, realm):
        if realm == 'attachment':
            return 'attachment'

    def get_realm_id(self, realm):
        if realm == 'attachment':
            return 'id'

    # Internal methods

    def _do_save(self, req, attachment):
        req.perm(attachment.resource).require('ATTACHMENT_CREATE')
        parent_resource = attachment.resource.parent
        if not resource_exists(self.env, parent_resource):
            raise ResourceNotFound(
                _("%(parent)s doesn't exist, can't create attachment",
                  parent=get_resource_name(self.env, parent_resource)))

        if 'cancel' in req.args:
            req.redirect(get_resource_url(self.env, parent_resource, req.href))

        upload = req.args['attachment']
        if not hasattr(upload, 'filename') or not upload.filename:
            raise TracError(_('No file uploaded'))
        if hasattr(upload.file, 'fileno'):
            size = os.fstat(upload.file.fileno())[6]
        else:
            upload.file.seek(0, 2) # seek to end of file
            size = upload.file.tell()
            upload.file.seek(0)
        if size == 0:
            raise TracError(_("Can't upload empty file"))

        # Maximum attachment size (in bytes)
        max_size = self.max_size
        if max_size >= 0 and size > max_size:
            raise TracError(_('Maximum attachment size: %(num)s bytes',
                              num=max_size), _('Upload failed'))

        # We try to normalize the filename to unicode NFC if we can.
        # Files uploaded from OS X might be in NFD.
        filename = unicodedata.normalize('NFC', unicode(upload.filename,
                                                        'utf-8'))
        filename = filename.replace('\\', '/').replace(':', '/')
        filename = os.path.basename(filename)
        if not filename:
            raise TracError(_('No file uploaded'))
        # Now the filename is known, update the attachment resource
        attachment.filename = filename
        attachment.description = req.args.get('description', '')
        attachment.author = get_reporter_id(req, 'author')
        attachment.ipnr = req.remote_addr

        # Validate attachment
        for manipulator in self.manipulators:
            for field, message in manipulator.validate_attachment(req,
                                                                  attachment):
                if field:
                    raise InvalidAttachment(
                        _('Attachment field %(field)s is invalid: %(message)s',
                          field=field, message=message))
                else:
                    raise InvalidAttachment(
                        _('Invalid attachment: %(message)s', message=message))

        if req.args.get('replace'):
            try:
                old_attachment = Attachment(self.env,
                                            attachment.resource(id=filename))
                if not (req.authname and req.authname != 'anonymous' \
                        and old_attachment.author == req.authname) \
                   and 'ATTACHMENT_DELETE' \
                                        not in req.perm(attachment.resource):
                    raise PermissionError(msg=_("You don't have permission to "
                        "replace the attachment %(name)s. You can only "
                        "replace your own attachments. Replacing other's "
                        "attachments requires ATTACHMENT_DELETE permission.",
                        name=filename))
                if (not attachment.description.strip() and
                    old_attachment.description):
                    attachment.description = old_attachment.description
                old_attachment.delete()
            except TracError:
                pass # don't worry if there's nothing to replace
        attachment.insert(filename, upload.file, size)

        req.redirect(get_resource_url(self.env, attachment.resource(id=None),
                                      req.href))

    def _do_delete(self, req, attachment):
        req.perm(attachment.resource).require('ATTACHMENT_DELETE')

        parent_href = get_resource_url(self.env, attachment.resource.parent,
                                       req.href)
        if 'cancel' in req.args:
            req.redirect(parent_href)

        attachment.delete()
        req.redirect(parent_href)

    def _render_confirm_delete(self, req, attachment):
        req.perm(attachment.resource).require('ATTACHMENT_DELETE')
        return {'mode': 'delete',
                'title': _('%(attachment)s (delete)',
                           attachment=get_resource_name(self.env,
                                                        attachment.resource)),
                'attachment': attachment}

    def _render_form(self, req, attachment):
        req.perm(attachment.resource).require('ATTACHMENT_CREATE')
        return {'mode': 'new', 'author': get_reporter_id(req),
            'attachment': attachment, 'max_size': self.max_size}

    def _render_list(self, req, parent):
        data = {
            'mode': 'list',
            'attachment': None, # no specific attachment
            'attachments': self.attachment_data(Context.from_request(req,
                                                                     parent))
        }

        return 'attachment.html', data, None

    def _render_view(self, req, attachment):
        req.perm(attachment.resource).require('ATTACHMENT_VIEW')
        can_delete = 'ATTACHMENT_DELETE' in req.perm(attachment.resource)
        req.check_modified(attachment.date, str(can_delete))

        data = {'mode': 'view',
                'title': get_resource_name(self.env, attachment.resource),
                'attachment': attachment}

        fd = attachment.open()
        try:
            mimeview = Mimeview(self.env)

            # MIME type detection
            str_data = fd.read(1000)
            fd.seek(0)
            
            mime_type = mimeview.get_mimetype(attachment.filename, str_data)

            # Eventually send the file directly
            format = req.args.get('format')
            if format in ('raw', 'txt'):
                if not self.render_unsafe_content:
                    # Force browser to download files instead of rendering
                    # them, since they might contain malicious code enabling 
                    # XSS attacks
                    req.send_header('Content-Disposition', 'attachment')
                if format == 'txt':
                    mime_type = 'text/plain'
                elif not mime_type:
                    mime_type = 'application/octet-stream'
                if 'charset=' not in mime_type:
                    charset = mimeview.get_charset(str_data, mime_type)
                    mime_type = mime_type + '; charset=' + charset
                req.send_file(attachment.path, mime_type)

            # add ''Plain Text'' alternate link if needed
            if (self.render_unsafe_content and 
                mime_type and not mime_type.startswith('text/plain')):
                plaintext_href = get_resource_url(self.env,
                                                  attachment.resource,
                                                  req.href, format='txt')
                add_link(req, 'alternate', plaintext_href, _('Plain Text'),
                         mime_type)

            # add ''Original Format'' alternate link (always)
            raw_href = get_resource_url(self.env, attachment.resource,
                                        req.href, format='raw')
            add_link(req, 'alternate', raw_href, _('Original Format'),
                     mime_type)

            self.log.debug("Rendering preview of file %s with mime-type %s"
                           % (attachment.filename, mime_type))

            data['preview'] = mimeview.preview_data(
                Context.from_request(req, attachment.resource), fd,
                os.fstat(fd.fileno()).st_size, mime_type,
                attachment.filename, raw_href, annotations=['lineno'])
            return data
        finally:
            fd.close()

    def _format_link(self, formatter, ns, target, label):
        link, params, fragment = formatter.split_link(target)
        ids = link.split(':', 4)
        attachment = None
        ok = True
        if len(ids) == 5:
            ok, pid = formatter.extract_pid(ids[1:3])
            if ok:
                ids.pop(2)
                ids.pop(1)
        else:
            pid = None
        if not ok:
            return tag.a(u'<bad formed Attachment link "{0}">'.format(link),
                         class_='missing attachment')
        if len(ids) == 3:
            known_realms = ResourceSystem(self.env).get_known_realms()
            # new-style attachment: TracLinks (filename:realm:id)
            if ids[1] in known_realms:
                attachment = Resource(ids[1], ids[2], pid=pid).child('attachment',
                                                            ids[0])
            else: # try old-style attachment: TracLinks (realm:id:filename)
                if ids[0] in known_realms:
                    attachment = Resource(ids[0], ids[1], pid=pid).child('attachment',
                                                                ids[2])
        else: # local attachment: TracLinks (filename)
            attachment = formatter.resource.child('attachment', link)
        if attachment and 'ATTACHMENT_VIEW' in formatter.perm(attachment):
            try:
                model = Attachment(self.env, attachment)
                raw_href = get_resource_url(self.env, attachment,
                                            formatter.href, format='raw')
                if ns.startswith('raw'):
                    return tag.a(label, class_='attachment',
                                 href=raw_href + params,
                                 title=get_resource_name(self.env, attachment))
                href = get_resource_url(self.env, attachment, formatter.href)
                title = get_resource_name(self.env, attachment)
                return tag(tag.a(label, class_='attachment', title=title,
                                 href=href + params),
                           tag.a(u'\u200b', class_='trac-rawlink',
                                 href=raw_href + params, title=_("Download")))
            except ResourceNotFound:
                pass
            # FIXME: should be either:
            #
            # model = Attachment(self.env, attachment)
            # if model.exists:
            #     ...
            #
            # or directly:
            #
            # if attachment.exists:
            #
            # (related to #4130)
        return tag.a(label, class_='missing attachment')


class LegacyAttachmentPolicy(Component):

    implements(IPermissionPolicy)
    
    delegates = ExtensionPoint(ILegacyAttachmentPolicyDelegate)

    # IPermissionPolicy methods

    _perm_maps = {
        'ATTACHMENT_CREATE': {'ticket': 'TICKET_APPEND', 'wiki': 'WIKI_MODIFY',
                              'milestone': 'MILESTONE_MODIFY'},
        'ATTACHMENT_VIEW': {'ticket': 'TICKET_VIEW', 'wiki': 'WIKI_VIEW',
                            'milestone': 'MILESTONE_VIEW'},
        'ATTACHMENT_DELETE': {'ticket': 'TICKET_ADMIN', 'wiki': 'WIKI_DELETE',
                              'milestone': 'MILESTONE_DELETE'},
    }

    def check_permission(self, action, username, resource, perm, req):
        perm_map = self._perm_maps.get(action)
        if not perm_map or not resource or resource.realm != 'attachment':
            return
        legacy_action = perm_map.get(resource.parent.realm)
        if legacy_action:
            decision = legacy_action in perm(resource.parent)
            if not decision:
                self.env.log.debug('LegacyAttachmentPolicy denied %s '
                                   'access to %s. User needs %s' %
                                   (username, resource, legacy_action))
            return decision
        else:
            for d in self.delegates:
                decision = d.check_attachment_permission(action, username,
                        resource, perm)
                if decision is not None:
                    return decision


class AttachmentAdmin(Component):
    """trac-admin command provider for attachment administration."""
    
    implements(IAdminCommandProvider)
    
    # IAdminCommandProvider methods
    
    def get_admin_commands(self):
        yield ('attachment list', '<[pid:]realm:id>',
               """List attachments of a resource
               
               The resource is identified by its realm and identifier (and opt. project id).""",
               self._complete_list, self._do_list)
        yield ('attachment add', '<[pid:]realm:id> <path> [author] [description]',
               """Attach a file to a resource
               
               The resource is identified by its realm and identifier (and opt. project id). The
               attachment will be named according to the base name of the file.
               """,
               self._complete_add, self._do_add)
        yield ('attachment remove', '<[pid:]realm:id> <name>',
               """Remove an attachment from a resource
               
               The resource is identified by its realm and identifier (and opt. project id).""",
               self._complete_remove, self._do_remove)
        yield ('attachment export', '<[pid:]realm:id> <name> [destination]',
               """Export an attachment from a resource to a file or stdout
               
               The resource is identified by its realm and identifier (and opt. project id). If no
               destination is specified, the attachment is output to stdout.
               """,
               self._complete_export, self._do_export)
    
    def get_realm_list(self):
        rs = ResourceSystem(self.env)
        return PrefixList([each + ":" for each in rs.get_known_realms()])
    
    def split_resource(self, resource):
        result = resource.split(':', 1)
        if not (2 <= len(result) <= 3):
            raise AdminCommandError(_("Invalid resource identifier '%(id)s'",
                                      id=resource))
        if len(result) == 2:
            result.insert(0, None)
        return result
    
    def get_attachment_list(self, resource):
        (pid, realm, id) = self.split_resource(resource)
        return [a.filename for a in Attachment.select(self.env, realm, id, pid)]
    
    def _complete_list(self, args):
        if len(args) == 1:
            return self.get_realm_list()
    
    def _complete_add(self, args):
        if len(args) == 1:
            return self.get_realm_list()
        elif len(args) == 2:
            return get_dir_list(args[1])
    
    def _complete_remove(self, args):
        if len(args) == 1:
            return self.get_realm_list()
        elif len(args) == 2:
            return self.get_attachment_list(args[0])
    
    def _complete_export(self, args):
        if len(args) < 3:
            return self._complete_remove(args)
        elif len(args) == 3:
            return get_dir_list(args[2])
    
    def _do_list(self, resource):
        (pid, realm, id) = self.split_resource(resource)
        print_table([(a.filename, pretty_size(a.size), a.author,
                      format_datetime(a.date, console_datetime_format),
                      a.description)
                     for a in Attachment.select(self.env, realm, id, pid)],
                    [_('Name'), _('Size'), _('Author'), _('Date'),
                     _('Description')])
    
    def _do_add(self, resource, path, author='trac', description=''):
        (pid, realm, id) = self.split_resource(resource)
        attachment = Attachment(self.env, realm, id, parent_pid=pid)
        attachment.author = author
        attachment.description = description
        f = open(path, 'rb')
        try:
            attachment.insert(os.path.basename(path), f, os.path.getsize(path))
        finally:
            f.close()
    
    def _do_remove(self, resource, name):
        (pid, realm, id) = self.split_resource(resource)
        attachment = Attachment(self.env, realm, id, name, parent_pid=pid)
        attachment.delete()
    
    def _do_export(self, resource, name, destination=None):
        (pid, realm, id) = self.split_resource(resource)
        attachment = Attachment(self.env, realm, id, name, parent_pid=pid)
        if destination is not None:
            if os.path.isdir(destination):
                destination = os.path.join(destination, name)
            if os.path.isfile(destination):
                raise AdminCommandError(_("File '%(name)s' exists",
                                          name=path_to_unicode(destination)))
        input = attachment.open()
        try:
            output = (destination is None) and sys.stdout \
                                           or open(destination, "wb")
            try:
                shutil.copyfileobj(input, output)
            finally:
                if destination is not None:
                    output.close()
        finally:
            input.close()

