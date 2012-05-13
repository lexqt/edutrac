import os
import shutil
import tarfile
import tempfile

from trac.core import Component, implements, TracError
from trac.admin.api import IAdminCommandProvider, IAdminPanelProvider, AdminArea

from trac.evaluation.api import EvaluationManagement
from trac.evaluation.api.scale import prepare_editable_var, create_scale_validator, create_group_validator

from trac.web.chrome import add_notice, add_warning
from trac.util.translation import _
from trac.util.text import exception_to_unicode
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
            yield ('evaluation', _('Evaluation'), 'packages', _('Packages'),
                   set([AdminArea.GLOBAL, AdminArea.SYLLABUS]))

    def render_admin_panel(self, req, cat, page, path_info, area, area_id):
        req.perm.require('TRAC_ADMIN')
        if page == 'constants':
            return self._constants_panel(req, area_id)
        if page == 'packages':
            return self._packages_panel(req, area, area_id)

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

    def _packages_panel(self, req, area, area_id):
        if area == AdminArea.GLOBAL:
            return self._packages_global_panel(req)
        elif area == AdminArea.SYLLABUS:
            return self._packages_syllabus_panel(req, area_id)

    def _get_packages(self):
        pkgs_path = os.path.join(self.env.path, 'evaluation')
        packages = os.listdir(pkgs_path)
        return [p for p in packages if os.path.isdir(os.path.join(pkgs_path, p))]

    def _packages_global_panel(self, req):
        pkgs_path = os.path.join(self.env.path, 'evaluation')
        packages = self._get_packages()

        if req.method == 'POST':
            if req.args.has_key('remove'):
                del_pkgs = req.args.getlist('sel')
                for pkg in del_pkgs:
                    if pkg not in packages:
                        continue
                    try:
                        shutil.rmtree(os.path.join(pkgs_path, pkg))
                        add_notice(req, _('Package %(pkg)s removed successfully',
                                          pkg=pkg))
                    except OSError, e:
                        add_warning(req, _('Error occurred while removing package %(pkg)s: %(exc)s',
                                           pkg=pkg, exc=exception_to_unicode(e)))
                    self.evmanager.clear_model_cache()
                    req.redirect(req.panel_href())

            elif req.args.has_key('upload'):
                self._do_unpload_pkg(req)
                req.redirect(req.panel_href())

            elif req.args.has_key('clearcache'):
                self.evmanager.clear_model_cache()
                add_notice(req, _("Evaluation models' cache cleared successfully"))
                req.redirect(req.panel_href())

        data = {
            'packages': packages,
        }
        return 'admin_evaluation_packages.html', data

    def _packages_syllabus_panel(self, req, syllabus_id):
        packages = self._get_packages()
        sconfig = self.configs.syllabus(syllabus_id)
        current_pkg = sconfig.get('evaluation', 'package')

        if req.method == 'POST':
            if req.args.has_key('select'):
                new_pkg = req.args.get('sel')
                if new_pkg not in packages:
                    raise TracError(_('Unknown evaluation model package'))
                if new_pkg != current_pkg:
                    sconfig.set('evaluation', 'package', new_pkg)
                    sconfig.save()
                    self.evmanager.clear_model_cache(syllabus_id=syllabus_id)
                    add_notice(req, _('Your changes have been saved.'))
                req.redirect(req.panel_href())

            elif req.args.has_key('clearcache'):
                self.evmanager.clear_model_cache(syllabus_id=syllabus_id)
                add_notice(req, _("Syllabus evaluation model's cache cleared successfully"))
                req.redirect(req.panel_href())

        data = {
            'packages': packages,
            'current_pkg': current_pkg,
        }
        return 'admin_syllabus_evaluation_package.html', data

    def _do_unpload_pkg(self, req):
        if not req.args.has_key('pkg_file'):
            raise TracError(_('No file uploaded'))
        upload = req.args['pkg_file']
        if isinstance(upload, unicode) or not upload.filename:
            raise TracError(_('No file uploaded'))
        pkg_filename = upload.filename.replace('\\', '/').replace(':', '/')
        pkg_filename = os.path.basename(pkg_filename)
        if not pkg_filename:
            raise TracError(_('No file uploaded'))
        if pkg_filename.endswith('.tar.gz') or pkg_filename.endswith('.tar.bz'):
            pkg_name = pkg_filename[:-7]
        elif pkg_filename.endswith('.tar'):
            pkg_name = pkg_filename[:-4]
        else:
            raise TracError(_('Uploaded file is not a supported archive file'))

        target_path = os.path.join(self.env.path, 'evaluation', pkg_name)
        if os.path.isdir(target_path):
            raise TracError(_('Package %(name)s already exists',
                              name=pkg_name))

        def py_files(members):
            for tarinfo in members:
                if os.path.splitext(tarinfo.name)[1] == ".py":
                    yield tarinfo

        try:
            tmpdir = tempfile.mkdtemp()
            with tarfile.open(fileobj=upload.file) as tar:
                tar.extractall(tmpdir, members=py_files(tar))
            from_path = os.path.join(tmpdir, pkg_name)
            if not os.path.isdir(from_path):
                raise TracError(_('Invalid package structure: directory %(dirname)s missed.',
                                  dirname=pkg_name))
            self.log.info('Copying evaluation package %s', pkg_name)
            shutil.copytree(from_path, target_path)
            add_notice(req, _('Package %(pkg)s uploaded successfully',
                              pkg=pkg_name))
        except tarfile.TarError, e:
            raise TracError(_('Error occurred while unpacking package tarball: %(err)s',
                              err=exception_to_unicode(e)))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _do_delete_pkg(self, req):
        plugin_filename = req.args.getlist('sel')
        if not plugin_filename:
            return
        plugin_path = os.path.join(self.env.path, 'plugins', plugin_filename)
        if not os.path.isfile(plugin_path):
            return
        self.log.info('Uninstalling plugin %s', plugin_filename)
        os.remove(plugin_path)

        # Make the environment reset itself on the next request
        self.env.config.touch()


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

