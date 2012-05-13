from trac.core import Component, implements, TracError
from trac.admin.api import IAdminCommandProvider, IAdminPanelProvider, AdminArea

from trac.evaluation.api import EvaluationManagement
from trac.evaluation.api.scale import prepare_editable_var, create_scale_validator, create_group_validator

from trac.web.chrome import add_notice, add_warning
from trac.util.translation import _
from trac.util.formencode_addons import process_form




class EvaluationAdmin(Component):

    implements(IAdminCommandProvider, IAdminPanelProvider)

    def __init__(self):
        self.evmanager = EvaluationManagement(self.env)

    # IAdminPanelProvider

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('evaluation', _('Evaluation'), 'constants', _('Model constants'),
                   set([AdminArea.SYLLABUS]))

    def render_admin_panel(self, req, cat, page, path_info, area, area_id):
        req.perm.require('TRAC_ADMIN')
        if page == 'constants':
            return self._constants_panel(req, area_id)

    def _constants_panel(self, req, syllabus_id):
        model = self.evmanager.get_model(syllabus_id)
        constants = model.constants.all()
        if not constants:
            raise TracError(_('There are no defined constants in the evaluation model'))

        if req.method == 'POST':
            aliases = {c.alias: c for c in constants}
            errs = []

            if req.args.has_key('save'):
                params = {'not_empty': True}
                validator = create_group_validator(aliases, params)
                labels = {c.alias: c.label for c in constants}
                changes, errs = process_form(req.args, validator, labels)
                if not errs:
                    for name, new_val in changes.iteritems():
                        c = aliases[name]
                        c.set(new_val)
                    model.sconfig.save()
                    add_notice(req, _('Your changes have been saved.'))
                    req.redirect(req.panel_href())

            elif req.args.has_key('reset'):
                names = req.args.getlist('sel')
                for name in names:
                    if name not in aliases:
                        continue
                    c = aliases[name]
                    c.reset()
                model.sconfig.save()
                add_notice(req, _('Your changes have been saved.'))
                req.redirect(req.panel_href())

            for err in errs:
                add_warning(req, err)

        constants = sorted(constants, key=lambda v: v.label)
        values = []
        for c in constants:
            row = {
                'alias': c.alias,
                'label': c.label,
                'description': c.description,
                'scale': c.scale,
                'value': c.get(),
                'default_value': c.default_value,
            }
            values.append(row)
            # set input type, value help_text, row extra args
            info = prepare_editable_var(c.scale)
            row.update(info)

        data = {
            'constants': values,
        }
        return 'admin_evaluation_constants.html', data

    # IAdminCommandProvider
    
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

