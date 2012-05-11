# Copyright (C) 2012 Aleksey A. Porfirov

from trac.core import Component, implements, TracError
from trac.admin.api import IAdminPanelProvider, AdminArea

from trac.web.chrome import ITemplateProvider, Chrome, add_notice, add_warning
from trac.util.translation import _

from trac.project.api import ProjectManagement

from trac.project.model import Syllabus, Project
from trac.user.model import Metagroup, Team
from sqlalchemy.orm.exc import NoResultFound

import formencode
from formencode import validators
from formencode.foreach import ForEach
from trac.util.formencode_addons import process_form


class SyllabusAddForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    name = validators.String(not_empty=True, strip=True, min=4, max=255)

class SyllabusModifyForm(SyllabusAddForm):

    description = validators.String()


class ProjectAddForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    name = validators.String(not_empty=True, strip=True, min=4, max=255)

class ProjectModifyForm(ProjectAddForm):

    description = validators.String()




class ProjectManagementAdmin(Component):

    implements(ITemplateProvider, IAdminPanelProvider)

    def __init__(self):
        self.pm = ProjectManagement(self.env)

    # IAdminPanelProvider

    def get_admin_panels(self, req):
        if req.perm.has_permission('TRAC_ADMIN'):
            yield ('syllabuses', _('Syllabuses'), 'syllabuses', _('Syllabuses'),
                   set([AdminArea.GLOBAL]))
            yield ('syllabuses', _('Syllabuses'), 'metagroup-syllabus', _('Metagroup-Syllabus'),
                   set([AdminArea.GLOBAL]))
            yield ('projects', _('Projects'), 'projects', _('Projects'),
                   set([AdminArea.GLOBAL]))
            yield ('projects', _('Projects'), 'team-project', _('Team-Project'),
                   set([AdminArea.GLOBAL]))

    def render_admin_panel(self, req, cat, page, path_info, area, area_id):
        req.perm.require('TRAC_ADMIN')
        if page == 'syllabuses':
            syllabus_id = int(path_info) if path_info else None
            return self._syllabuses_panel(req, syllabus_id)
        elif page == 'metagroup-syllabus':
            gid = int(path_info) if path_info else None
            return self._metagroup_rel_panel(req, gid)
        elif page == 'projects':
            pid = int(path_info) if path_info else None
            return self._projects_panel(req, pid)
        elif page == 'team-project':
            tid = int(path_info) if path_info else None
            return self._team_rel_panel(req, tid)

    def _syllabuses_panel(self, req, syllabus_id=None):
        session = self.env.get_sa_session()
        if syllabus_id is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try: 
                syllabus = session.query(Syllabus).\
                                   filter(Syllabus.id == syllabus_id).one()
            except NoResultFound:
                raise TracError(_("Syllabus #%(id)s doesn't exist", id=syllabus_id))

            if req.method == 'POST':
                errs = None
                if req.args.has_key('save'):
                    validator = SyllabusModifyForm()
                    changes, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        for key, val in changes.iteritems():
                            setattr(syllabus, key, val)
                        session.commit()
                        add_notice(req, _('Your changes have been saved.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('recreate_conf'):
                    Syllabus.remove_config(self.env, syllabus.id)
                    Syllabus.add_config(self.env, syllabus.id)
                    add_notice(req, _('Syllabus configuration has been recreated.'))
                elif req.args.has_key('default_conf'):
                    config = self.configs.syllabus(syllabus.id)
                    Syllabus.set_default_config(self.env, config)
                    config.save()
                    add_notice(req, _('Default syllabus configuration has been loaded.'))

                for err in errs or ():
                    add_warning(req, err)
            data = {
                'view': 'detail',
                'item': syllabus,
                'name': req.args.get('name', syllabus.name),
                'description': req.args.get('description', syllabus.description),
            }
            Chrome(self.env).add_wiki_toolbars(req)

        else:
            # List view page

            if req.method == 'POST':
                if req.args.has_key('add'):
                    validator = SyllabusAddForm()
                    args, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        new_s = Syllabus(**args)
                        session.add(new_s)
                        session.commit()
                        Syllabus.add_config(self.env, new_s.id)
                        add_notice(req, _('New syllabus have been added.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove'):
                    validator = ForEach(validators.Int())
                    ids, errs = process_form(req.args.getlist('sel'), validator)
                    if not errs:
                        session.begin()
                        session.query(Syllabus).\
                                filter(Syllabus.id.in_(ids)).delete(False)
                        session.commit()
                        for id in ids:
                            Syllabus.remove_config(self.env, id)
                        add_notice(req, _('The selected items have been removed.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            items = session.query(Syllabus).order_by(Syllabus.id).all()
            data = {
                'items': items,
                'name': req.args.get('name'),
            }
        return 'admin_syllabuses.html', data

    def _projects_panel(self, req, project_id=None):
        session = self.env.get_sa_session()
        if project_id is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try: 
                project = session.query(Project).\
                                   filter(Project.id == project_id).one()
            except NoResultFound:
                raise TracError(_("Project #%(id)s doesn't exist", id=project_id))

            if req.method == 'POST':
                errs = None
                if req.args.has_key('save'):
                    validator = ProjectModifyForm()
                    changes, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        for key, val in changes.iteritems():
                            setattr(project, key, val)
                        session.commit()
                        add_notice(req, _('Your changes have been saved.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove_conf'):
                    Syllabus.remove_config(self.env, project.id)
                    add_notice(req, _('Project configuration has been removed.'))

                for err in errs or ():
                    add_warning(req, err)
            data = {
                'view': 'detail',
                'item': project,
                'name': req.args.get('name', project.name),
                'description': req.args.get('description', project.description),
            }
            Chrome(self.env).add_wiki_toolbars(req)

        else:
            # List view page

            if req.method == 'POST':
                if req.args.has_key('add'):
                    validator = ProjectAddForm()
                    args, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        new_s = Project(**args)
                        session.add(new_s)
                        session.commit()
                        add_notice(req, _('New project have been added.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove'):
                    validator = ForEach(validators.Int())
                    ids, errs = process_form(req.args.getlist('sel'), validator)
                    if not errs:
                        session.begin()
                        session.query(Project).\
                                filter(Project.id.in_(ids)).delete(False)
                        session.commit()
                        for id in ids:
                            Project.remove_config(self.env, id)
                        add_notice(req, _('The selected items have been removed.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            items = session.query(Project).order_by(Project.id).all()
            data = {
                'items': items,
                'name': req.args.get('name'),
            }
        return 'admin_projects.html', data

    def _metagroup_rel_panel(self, req, gid):
        session = self.env.get_sa_session()
        if gid is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            session.begin()
            try: 
                metagroup, syllabus_id = session.query(Metagroup, Syllabus.id).\
                                   outerjoin(Syllabus, Metagroup.syllabus).\
                                   filter(Metagroup.id == gid).one()
            except NoResultFound:
                raise TracError(_("Metagroup #%(id)s doesn't exist", id=gid))

            if req.method == 'POST':
                if req.args.has_key('save'):
                    # TODO: check request arg
                    new_id = req.args.getint('linked_syllabus')
                    if new_id != syllabus_id:
                        err = None
                        if new_id is None:
                            # delete
                            metagroup.syllabus = None
                        else:
                            syllabus = session.query(Syllabus).get(new_id)
#                            other_gid = session.query(Metagroup.id).\
#                                                filter(Metagroup.syllabus==syllabus).\
#                                                scalar()
                            if syllabus is None:
                                err = _("Syllabus #%(id)s doesn't exist", id=new_id)
                                add_warning(req, err)
#                            elif other_gid is not None:
#                                err = _('Syllabus #%(sid)s is already connected with '
#                                        'another metagroup #%(gid)s', sid=new_id, gid=other_gid)
#                                add_warning(req, err)
                            else:
                                metagroup.syllabus = syllabus

                        if not err:
                            session.commit()
                            add_notice(req, _('Your changes have been saved.'))
                            req.redirect(req.panel_href())

            syllabuses = session.query(Syllabus.id, Syllabus.name).all()
            data = {
                'view': 'detail',
                'metagroup': metagroup,
                'syllabuses': syllabuses,
                'syllabus_id': syllabus_id,
            }

        else:
            # List view page

            items = session.query(Metagroup, Syllabus).\
                            outerjoin(Syllabus, Metagroup.syllabus).\
                            order_by(Metagroup.id).all()
            data = {
                'items': items,
            }
        return 'admin_metagroup_rel.html', data

    def _team_rel_panel(self, req, tid):
        session = self.env.get_sa_session()
        if tid is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            session.begin()
            try: 
                team, project_id = session.query(Team, Project.id).\
                                   outerjoin(Project, Team.project).\
                                   filter(Team.id == tid).one()
            except NoResultFound:
                raise TracError(_("Team #%(id)s doesn't exist", id=tid))

            if req.method == 'POST':
                if req.args.has_key('save'):
                    # TODO: check request arg
                    new_id = req.args.getint('linked_project')
                    if new_id != project_id:
                        err = None
                        if new_id is None:
                            # delete
                            team.project = None
                        else:
                            project = session.query(Project).get(new_id)
                            other_tid = session.query(Team.id).\
                                                filter(Team.project==project).\
                                                scalar()
                            if other_tid is not None:
                                err = _('Project #%(pid)s is already connected with '
                                        'another team #%(tid)s', pid=new_id, tid=other_tid)
                                add_warning(req, err)
                            elif project is None:
                                err = _("Project #%(id)s doesn't exist", id=new_id)
                                add_warning(req, err)
                            else:
                                team.project = project

                        if not err:
                            session.commit()
                            add_notice(req, _('Your changes have been saved.'))
                            req.redirect(req.panel_href())

            projects = session.query(Project.id, Project.name).all()
            data = {
                'view': 'detail',
                'team': team,
                'projects': projects,
                'project_id': project_id,
            }

        else:
            # List view page

            items = session.query(Team, Project).\
                            outerjoin(Project, Team.project).\
                            order_by(Team.id).all()
            data = {
                'items': items,
            }
        return 'admin_team_rel.html', data

    # ITemplateProvider

    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return []

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        ClearSilver templates.
        """
        from pkg_resources import resource_filename
        return [resource_filename(__name__, 'templates')]

