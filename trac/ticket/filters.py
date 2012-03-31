# Module is primarily based on BlackMagicTicketTweaksPlugin
# BlackMagicTicketTweaksPlugin copyright:

# Copyright (c) 2008, Stephen Hansen
# Copyright (c) 2009, Rowan Wookey www.obsidianproject.co.uk
# 
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
#     * Redistributions of source code must retain the above copyright 
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <ORGANIZATION> nor the names of its
#       contributors may be used to endorse or promote products derived from
#       this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ----------------------------------------------------------------------------

# Also includes modifications from TimingAndEstimationPlugin
# http://www.trac-hacks.org/wiki/TimingAndEstimationPlugin

# EduTrac adaptation
# (c) Aleksey A. Porfirov, 2012

import threading
import re

from genshi.builder import tag
from genshi.core import Stream
from genshi.filters.transform import Transformer

from trac.core import Component, implements
from trac.config import ListOption
from trac.web.chrome import add_stylesheet, add_script
from trac.ticket.api import ITicketManipulator, TicketSystem
from trac.web.api import ITemplateStreamFilter, IRequestFilter
from trac.util.translation import _

from trac.project.api import ProjectManagement


__all__ = ['TicketFieldFilters']


def textOf(self, **keys):
    return self.render('text', None, **keys)

Stream.textOf = textOf



# Helper stream function

def disable_field(stream, field):
    def select_helper(stream):
        s = Stream(stream)
        name = s.select('@name').textOf()
        opt = s.select('//option[@selected]')
        if not opt: s.select('//option[position()=1]')
        text = opt.select("text()").textOf()
        value = s.select('@value').textOf()
        if not value: value = text

        for kind,data,pos in tag.span(text, id=("field-%s"%field)).generate():
            yield kind,data,pos
        for kind,data,pos in tag.input(value=value, name=name, type="hidden").generate():
            yield kind,data,pos

    def helper(field_stream):
        s = Stream(field_stream)
        value = s.select('@value').textOf()
        name = s.select('@name').textOf()
        for kind,data,pos in tag.span(value, id=("field-%s"%field)).generate():
            yield kind,data,pos
        for kind,data,pos in tag.input(value=value, name=name, type="hidden").generate():
            yield kind,data,pos

    stream = stream | Transformer( '//select[@id="field-%s"]' % field ).filter(select_helper)
    stream = stream | Transformer( '//input[@id="field-%s"]' % field ).filter(helper)
    return stream


def remove_field(stream, field, label=None):
    """Removes a field from the form area.
    If label is not None also calls remove_changelog"""
    stream = stream | Transformer('//label[@for="field-%s"]' % field).replace(" ")
    stream = stream | Transformer('//*[@id="field-%s"]' % field).replace(" ")
    stream = remove_header(stream , field)
    if label is not None:
        stream = remove_changelog(stream, label)
    return stream

def remove_header(stream, field):
    """ Removes the display from the ticket properties """
    stream = stream | \
        Transformer('//th[@id="h_%s"]' % field).replace(tag.th(id="h_%s" % field))
    stream = stream | \
        Transformer('//td[@headers="h_%s"]' % field).replace(tag.th(id="h_%s" % field))
    return stream

def remove_changelog(self, stream, label):
    """Removes entries from the visible changelog"""
    check = label
    def helper(field_stream):
        try:
            s = Stream(field_stream)
            # without None as the second value we get str instead of unicode
            # and that causes things to break sometimes
            f = s.select('//strong/text()').textOf(strip_markup=True).lower()
            if check != f: #if we are the field just skip it
                #identity stream filter
                for kind, data, pos in s:
                    yield kind, data, pos
        except Exception, e:
            self.log.exception('ChangeLog: Stream Filter Exception');
            raise e
    stream = stream | Transformer('//ul[@class="changes"]/li').filter(helper)
    return stream


def hide_field(stream, field):
    """Replaces a field from the form area with an input type=hidden"""
    def helper (field_stream):
        type_ = Stream(field_stream).select('@type').textOf()
        if type_ == 'checkbox':
            if Stream(field_stream).select('@checked').textOf() == "checked":
                value = 1
            else:
                value = 0
        else:
            value = Stream(field_stream).select('@value').textOf()
        name = Stream(field_stream).select('@name').textOf()
        for kind,data,pos in tag.input(value=value,
                                       type="hidden", name=name).generate():
            yield kind,data,pos

    def select_helper(stream):
        s = Stream(stream)
        name = s.select('@name').textOf()
        opt = s.select('//option[@selected]')
        if not opt: s.select('//option[position()=1]')
        text = opt.select("text()").textOf()
        value = s.select('@value').textOf()
        if not value: value = text
        for kind,data,pos in tag.input(value=value, name=name, type="hidden").generate():
            yield kind,data,pos

    stream = stream | Transformer('//label[@for="field-%s"]' % field).replace(" ")
    stream = stream | Transformer('//input[@id="field-%s"]' % field).filter(helper)
    stream = stream | Transformer('//select[@id="field-%s"]' % field).filter(select_helper)

    return remove_header(stream , field)



class TicketFieldFilters(Component):

    implements(ITemplateStreamFilter, ITicketManipulator, IRequestFilter)

    csection = 'ticket-fields-filters'

    fields = ListOption(csection, 'fields', '',
                        doc='''Fields to apply extra filters''', switcher=True)

    def __init__(self):
        self._conf_cache_lock = threading.Lock()
        self._conf_cache = {}

    def _read_fields_config(self, syllabus_id):
        config = self.configs.syllabus(syllabus_id)
        fields = self.fields.syllabus(syllabus_id)
        self.env.log.debug("Reading ticket fields filters config for: %s" %  fields)
        res = {}
        for e in fields:
            res[e]=dict()
            perms                = config.getlist(self.csection, '%s.permission' % e, [])
            res[e]["permission"] = {perm.upper(): denial.lower() for perm, denial in [s.split(':') for s in perms]}
            res[e]["disable"]    = config.getbool(self.csection, '%s.disable' % e, False)
            res[e]["hide"]       = config.getbool(self.csection, '%s.hide' % e, False)
            res[e]["remove"]     = config.getbool(self.csection, '%s.remove' % e, False)
        self.env.log.debug("Result: %s " %  res)
        return res

    def get_fields_config(self, syllabus_id):
        syllabus_id = int(syllabus_id)
        with self._conf_cache_lock:
            if syllabus_id not in self._conf_cache:
                self._conf_cache[syllabus_id] = self._read_fields_config(syllabus_id)
            return self._conf_cache[syllabus_id]

    def _denied_fields(self, perm, syllabus_id, with_labels=False):
        fields = self.fields.syllabus(syllabus_id)
        conf   = self.get_fields_config(syllabus_id)
        res = []
        for f in fields:
            fconf = conf[f]
            if fconf['hide'] or fconf['remove']:
                res.append(f)
            elif fconf['permission']:
                for p, action in fconf['permission'].iteritems():
                    if p in perm:
                        continue
                    if action in ('hide', 'remove'):
                        res.append(f)
                        break
        if with_labels:
            fs = TicketSystem(self.env).get_ticket_fields(syllabus_id=syllabus_id)
            res = [(r, fs[r]['label']) for r in res]
        return res

    # IRequestFilter

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        #report page        
        if template == "report_view.html":
            syllabus_id = data['report']['syllabus_id']
            dfields = self._denied_fields(req.perm, syllabus_id)
            for row in data["row_groups"]:
                for l in row:
                    if isinstance(l,list):
                        for t in l:
                            id = t["id"]
                            for cell_group in t["cell_groups"]:
                                for group in cell_group:
                                    for field in cell_group:
                                        c = field["header"]["col"].lower()
                                        if c in dfields:
                                            field["value"] = ''

        #query page                                                            
        elif template == "query.html":
            syllabus_id = data['query'].syllabus_id
            dfields = self._denied_fields(req.perm, syllabus_id)
            #remove ticket fields user doesn't have access to
            for i in range(len(data["tickets"])):
                ticket = data["tickets"][i]
                for c in ticket:
                    if c in dfields:
                        data["tickets"][i][c]=''

        # ticket page
        elif template == 'ticket.html':
            add_script(req, "common/js/whitespace_remover.js")

        return template, data, content_type
    

    # ITicketManipulator methods

    def validate_ticket(self, req, ticket, action):
        self.env.log.debug('TicketFieldFilters: Validating ticket #%s' % ticket.id)
        res = []
        syllabus_id = ProjectManagement(self.env).get_project_syllabus(ticket.pid)

        fields = self.fields.syllabus(syllabus_id)
        conf   = self.get_fields_config(syllabus_id)

        for f in fields:
            editable = True
            fconf = conf[f]
            if ticket._old.get(f) is not None:
                if fconf['hide'] or fconf['remove'] or fconf['disable']:
                    editable = False
                elif fconf['permission']:
                    for perm, action in fconf['permission'].iteritems():
                        if perm in req.perm:
                            continue
                        if action in ('hide', 'remove', 'disable'):
                            editable = False
                            break

            # if field cannot be modified by user
            if not editable:
                res.append((f, _('Access denied to modifying field "%(field)s"', field=f)))
                self.env.log.debug('Invalid ticket. Access to field "%s" denied.' % f)

        return res

    # ITemplateStreamFilter

    def filter_stream(self, req, method, filename, stream, data):
        #remove matches from custom queries due to the fact ticket permissions are checked after this stream is manipulated so the count cannot be updated.
        if filename == "query.html":
            stream |= Transformer('//div[@class="query"]/h1/span[@class="numrows"]/text()').replace("")

#            def make_col_helper(field):
#                def column_helper (column_stream):
#                    s =  Stream(column_stream)
#                    val = s.select('//input/@value').render()
#                    if val.lower() != field.lower(): #if we are the field just skip it
#                        #identity stream filter
#                        for kind, data, pos in s:
#                            yield kind, data, pos        
#                return column_helper
#    
#            for (field, label) in denied_fields(self, req):
#                # remove from the list of addable 
#                stream = stream | Transformer(
#                    '//select[@id="add_filter"]/option[@value="%s"]' % field
#                    ).replace(" ")
#    
#                # remove from the list of columns
#                stream = stream | Transformer(
#                    '//fieldset[@id="columns"]/div/label'
#                    ).filter(make_col_helper(field))
#                        
#                # remove from the results table
#                stream = stream | Transformer(
#                    '//th[@class="%s"]' % field
#                    ).replace(" ")
#                stream = stream | Transformer(
#                    '//td[@class="%s"]' % field
#                    ).replace(" ")
#                
#                # remove from the filters
#                stream = stream | Transformer(
#                    '//tr[@class="%s"]' % field
#                    ).replace(" ")

        elif filename == "ticket.html":
            tkt = data['ticket']
            syllabus_id = ProjectManagement(self.env).get_project_syllabus(tkt.pid)
            fields = self.fields.syllabus(syllabus_id)
            conf   = self.get_fields_config(syllabus_id)

            for f in fields:
                fconf = conf[f]
                do_hide = do_disable = do_remove = False
                if fconf['permission']:
                    for perm, action in fconf['permission'].iteritems():
                        if perm in req.perm:
                            continue
                        if action == 'hide':
                            do_hide = True
                            break
                        elif action == 'disable':
                            do_disable = True
                            break
                        elif action == 'remove':
                            do_remove = True
                            break
                if not (do_hide or do_disable or do_remove):
                    if fconf['hide']:
                        do_hide = True
                    elif fconf['disable']:
                        do_disable = True
                    elif fconf['remove']:
                        do_remove = True

                if do_hide:
                    stream = hide_field(stream, f)
                elif do_disable:
                    stream = disable_field(stream, f)
                elif do_remove:
                    stream = remove_field(stream, f)

#        elif filename == "timeline.html":
#            syllabus_id = data['syllabus_id']
#            dlabels = [label for (f, label) in self._denied_fields(req.perm, syllabus_id, with_labels=True)]
#            commasRE = re.compile(r',\s(,\s)+', re.I)
#            def helper(field_stream):
#                try:
#                    s = Stream(field_stream)
#                    # without None as the second value we get str instead of unicode
#                    # and that causes things to break sometimes
#                    f = s.select('//text()').textOf(strip_markup=True).lower()
#                    if f not in dlabels: #if we are the field just skip it
#                        #identity stream filter
#                        for kind, data, pos in s:
#                            yield kind, data, pos
#                except Exception, e:
#                    self.log.exception('Timeline: Stream Filter Exception');
#                    raise e
#    
#            def comma_cleanup(stream):
#                text = Stream(stream).textOf()
#                self.log.debug( 'Timeline: Commas %r %r' , text, commasRE.sub( text, ', ' ) );
#                text = commasRE.sub( ', ' , text)
#                for kind, data, pos in tag(text):
#                    yield kind, data, pos
#    
#            stream = stream | Transformer('//dd[@class="editedticket"]/i').filter(helper)
#            stream = stream | Transformer('//dd[@class="editedticket"]/text()').filter(comma_cleanup)

        return stream

