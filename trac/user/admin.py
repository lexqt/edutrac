# Copyright (C) 2012 Aleksey A. Porfirov

from trac.core import Component, implements, TracError
from trac.admin.api import IAdminPanelProvider, AdminArea

from trac.web.chrome import ITemplateProvider, Chrome, add_notice, add_warning
from trac.util.translation import _

from trac.user.model import Metagroup, Group, Team, User
from trac.project.model import Project
from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound
from trac.db_sqlalchemy import project_permissions

import formencode
from formencode import validators, variabledecode
from formencode.foreach import ForEach
from trac.util.formencode_addons import process_form

from trac.user.api import UserManagement



class MetagroupAddForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    name = validators.String(not_empty=True, strip=True, min=4, max=255)
    year = validators.Int(not_empty=True, min=1900)

class MetagroupModifyForm(MetagroupAddForm):

    active = validators.Bool()


class GroupAddForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    name = validators.String(not_empty=True, strip=True, min=4, max=255)

class GroupModifyForm(GroupAddForm):

    description = validators.String()
    metagroup = validators.Int(min=0, if_empty=None)


class TeamAddForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    name = validators.String(not_empty=True, min=4, max=255)

class TeamModifyForm(TeamAddForm):

    group = validators.Int(min=0, if_empty=None)


class SelectedTeamMembers(formencode.Schema):

    members = formencode.ForEach(validators.Int(), convert_to_list=True)


class PermGroupsFields(formencode.Schema):

    developer  = validators.Bool()
    teamleader = validators.Bool()

_perms_map = {
    'developer': 'Developer',
    'teamleader': 'TeamLeader',
}

class AddTeamMemberForm(formencode.Schema):

    allow_extra_fields = True
    filter_extra_fields = True

    pre_validators = [variabledecode.NestedVariables()]

    username = validators.String(not_empty=True, min=1, max=255)
    team = validators.Int(not_empty=True, min=0)
    permgroups = PermGroupsFields()

    def _to_python(self, value_dict, state):
        self.assert_dict(value_dict, state)
        value_dict.setdefault('permgroups', [])
        return super(AddTeamMemberForm, self)._to_python(value_dict, state)


class UserManagementAdmin(Component):
    """
    Provides admin interface for user groups management.
    """

    implements(ITemplateProvider, IAdminPanelProvider)

    def __init__(self):
        self.um = UserManagement(self.env)

    # IAdminPanelProvider

    def get_admin_panels(self, req):
        if req.perm.has_permission('TRAC_ADMIN'):
            yield ('groups', _('Groups'), 'metagroups', _('Metagroups'),
                   set([AdminArea.GLOBAL]))
            yield ('groups', _('Groups'), 'groups', _('Groups'),
                   set([AdminArea.GLOBAL]))
            yield ('groups', _('Groups'), 'teams', _('Teams'),
                   set([AdminArea.GLOBAL]))
            yield ('groups', _('Groups'), 'team-members', _('Team members'),
                   set([AdminArea.GLOBAL]))

    def render_admin_panel(self, req, cat, page, path_info, area, area_id):
        req.perm.require('TRAC_ADMIN')
        if page == 'metagroups':
            gid = int(path_info) if path_info else None
            return self._metagroups_panel(req, gid)
        elif page == 'groups':
            gid = int(path_info) if path_info else None
            return self._groups_panel(req, gid)
        elif page == 'teams':
            tid = int(path_info) if path_info else None
            return self._teams_panel(req, tid)
        elif page == 'team-members':
            tid = int(path_info) if path_info else None
            return self._members_panel(req, tid)

    def _metagroups_panel(self, req, gid):
        session = self.env.get_sa_session()
        if gid is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try: 
                metagroup = session.query(Metagroup).\
                                   filter(Metagroup.id == gid).one()
            except NoResultFound:
                raise TracError(_("Metagroup #%(id)s doesn't exist", id=gid))

            if req.method == 'POST':
                errs = None
                if req.args.has_key('save'):
                    validator = MetagroupModifyForm()
                    changes, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        for key, val in changes.iteritems():
                            setattr(metagroup, key, val)
                        session.commit()
                        add_notice(req, _('Your changes have been saved.'))
                        req.redirect(req.panel_href())

                for err in errs or ():
                    add_warning(req, err)
            data = {
                'view': 'detail',
                'item': metagroup,
                'name': req.args.get('name', metagroup.name),
                'year': req.args.getint('year', metagroup.year),
                'active': req.args.get('active', metagroup.active),
            }

        else:
            # List view page

            if req.method == 'POST':
                if req.args.has_key('add'):
                    validator = MetagroupAddForm()
                    args, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        new_s = Metagroup(**args)
                        session.add(new_s)
                        session.commit()
                        add_notice(req, _('New metagroup have been added.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove'):
                    validator = ForEach(validators.Int())
                    ids, errs = process_form(req.args.getlist('sel'), validator)
                    if not errs:
                        session.begin()
                        session.query(Metagroup).\
                                filter(Metagroup.id.in_(ids)).delete(False)
                        session.commit()
                        add_notice(req, _('The selected items have been removed.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            items = session.query(Metagroup).order_by(Metagroup.id).all()
            data = {
                'items': items,
                'name': req.args.get('name'),
                'year': req.args.get('year'),
            }
        return 'admin_metagroups.html', data

    def _groups_panel(self, req, gid=None):
        session = self.env.get_sa_session()
        if gid is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try: 
                group, metagroup_id = session.query(Group, Metagroup.id).\
                                              outerjoin(Metagroup, Group.metagroup).\
                                              filter(Group.id == gid).one()
            except NoResultFound:
                raise TracError(_("Group #%(id)s doesn't exist", id=gid))

            if req.method == 'POST':
                errs = []
                if req.args.has_key('save'):
                    validator = GroupModifyForm()
                    changes, errs = process_form(req.args, validator)
                    session.begin()
                    if not errs:
                        # update group-metagroup connection
                        new_metagroup_id = changes.pop('metagroup')
                        if new_metagroup_id != metagroup_id:
                            if new_metagroup_id is None:
                                group.metagroup = None
                            else:
                                metagroup = session.query(Metagroup).get(new_metagroup_id)
                                if metagroup:
                                    group.metagroup = metagroup
                                else:
                                    errs.append(_("Metagroup #%(id)s doesn't exist", id=new_metagroup_id))
                    if not errs:
                        # update group fields
                        for key, val in changes.iteritems():
                            setattr(group, key, val)
                        session.commit()
                        add_notice(req, _('Your changes have been saved.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            metagroups = session.query(Metagroup.id, Metagroup.name).all()
            data = {
                'view': 'detail',
                'item': group,
                'name': req.args.get('name', group.name),
                'description': req.args.get('description', group.description),
                'metagroups': metagroups,
                'metagroup_id': metagroup_id,
            }
            Chrome(self.env).add_wiki_toolbars(req)

        else:
            # List view page

            if req.method == 'POST':
                if req.args.has_key('add'):
                    validator = GroupAddForm()
                    args, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        new_s = Group(**args)
                        session.add(new_s)
                        session.commit()
                        add_notice(req, _('New group have been added.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove'):
                    validator = ForEach(validators.Int())
                    ids, errs = process_form(req.args.getlist('sel'), validator)
                    if not errs:
                        session.begin()
                        session.query(Group).\
                                filter(Group.id.in_(ids)).delete(False)
                        session.commit()
                        add_notice(req, _('The selected items have been removed.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            items = session.query(Group, Metagroup.id, Metagroup.name).\
                            outerjoin(Metagroup, Group.metagroup).\
                            order_by(Group.id).all()
            data = {
                'items': items,
                'name': req.args.get('name'),
            }
        return 'admin_groups.html', data

    def _teams_panel(self, req, tid=None):
        session = self.env.get_sa_session()
        if tid is not None:
            # Details page

            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try: 
                team, group_id = session.query(Team, Group.id).\
                                              outerjoin(Group, Team.group).\
                                              filter(Team.id == tid).one()
            except NoResultFound:
                raise TracError(_("Team #%(id)s doesn't exist", id=tid))

            if req.method == 'POST':
                errs = []
                if req.args.has_key('save'):
                    validator = TeamModifyForm()
                    changes, errs = process_form(req.args, validator)
                    session.begin()
                    if not errs:
                        # update group-metagroup connection
                        new_group_id = changes.pop('group')
                        if new_group_id != group_id:
                            if new_group_id is None:
                                team.group = None
                            else:
                                group = session.query(Group).get(new_group_id)
                                if group:
                                    team.group = group
                                else:
                                    errs.append(_("Group #%(id)s doesn't exist", id=new_group_id))
                    if not errs:
                        # update group fields
                        for key, val in changes.iteritems():
                            setattr(team, key, val)
                        session.commit()
                        add_notice(req, _('Your changes have been saved.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            groups = session.query(Group.id, Group.name).all()
            data = {
                'view': 'detail',
                'item': team,
                'name': req.args.get('name', team.name),
                'groups': groups,
                'group_id': group_id,
            }

        else:
            # List view page

            if req.method == 'POST':
                if req.args.has_key('add'):
                    validator = TeamAddForm()
                    args, errs = process_form(req.args, validator)
                    if not errs:
                        session.begin()
                        new_t = Team(**args)
                        session.add(new_t)
                        session.commit()
                        add_notice(req, _('New team have been added.'))
                        req.redirect(req.panel_href())
                elif req.args.has_key('remove'):
                    validator = ForEach(validators.Int())
                    ids, errs = process_form(req.args.getlist('sel'), validator)
                    if not errs:
                        session.begin()
                        session.query(Team).\
                                filter(Team.id.in_(ids)).delete(False)
                        session.commit()
                        add_notice(req, _('The selected items have been removed.'))
                        req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            items = session.query(Team, Group.id, Group.name).\
                            outerjoin(Group, Team.group).\
                            order_by(Team.id).all()
            data = {
                'items': items,
                'name': req.args.get('name'),
            }
        return 'admin_teams.html', data

    def _members_panel(self, req, tid=None):
        session = self.env.get_sa_session()
        if tid is not None:
            if req.args.has_key('cancel'):
                req.redirect(req.panel_href())

            try:
                team, project = session.query(Team, Project).\
                                           outerjoin(Project, Team.project).\
                                           filter(Team.id==tid).one()
            except NoResultFound:
                add_warning(req, _("Team #%(id)s doesn't exist", id=tid))
                req.redirect(req.panel_href())
            if project is None:
                add_warning(req, _('Selected team is not connected with any project. '
                                   'You were redirected to "team-project connection" page.'))
                req.redirect(req.href.admin('projects', 'team-project', tid))
            dev_perm = project_permissions.alias('dev_perm')
            tl_perm  = project_permissions.alias('tl_perm')
            def select_perm(tbl, name):
                return (func.count(tbl.c.action)==1).label(name)
            members = session.query(User,
                                    select_perm(dev_perm, 'developer'),
                                    select_perm(tl_perm,  'teamleader')).\
                           join(User, Team.members).\
                           order_by(User.username).\
                           outerjoin(Project, Team.project).\
                           outerjoin(dev_perm, (dev_perm.c.project_id==Project.id) &
                                               (dev_perm.c.username==User.username) &
                                               (dev_perm.c.action=='Developer')).\
                           outerjoin(tl_perm,  (tl_perm.c.project_id==Project.id) &
                                               (tl_perm.c.username==User.username) &
                                               (tl_perm.c.action=='TeamLeader')).\
                           group_by(User.id).\
                           filter(Team.id==tid).all()
            if not members:
                add_warning(req, _('Selected team is empty.'))
                req.redirect(req.panel_href())
            if req.method == 'POST':
                if req.args.has_key('save'):
                    form = variabledecode.variable_decode(req.args)
                    form = form.get('members', {})
                    validator = PermGroupsFields()
                    for member, developer, teamleader in members:
                        old_perms = {
                            'developer': developer,
                            'teamleader': teamleader,
                        }
                        new_perms = validator.to_python(form.get(str(member.id)))
                        for key, val in new_perms.iteritems():
                            if val == old_perms[key]:
                                continue
                            Project.set_permission(self.env, project.id, member.username,
                                                   _perms_map[key], grant=val)
                    add_notice(req, _('Your changes have been saved.'))
                    req.redirect(req.panel_href())

            data = {
                'view': 'detail',
                'team': team,
                'team_project': project,
                'members': members,
            }
            return 'admin_members.html', data

        if req.method == 'POST':
            if req.args.has_key('remove'):
                teams = variabledecode.variable_decode(req.args)
                teams = teams.get('team', {})
                to_remove = {}
                errs = []
                if teams:
                    validator = SelectedTeamMembers()
                    for tid, arr in teams.iteritems():
                        ids, errs = process_form(arr, validator)
                        if errs:
                            break
                        to_remove[tid] = ids['members']
                    else:
                        for tid, ids in to_remove.iteritems():
                            session.begin()
                            try:
                                team, project_id = session.query(Team, Project.id).\
                                                           outerjoin(Project, Team.project).\
                                                           filter(Team.id==tid).one()
                            except NoResultFound:
                                session.rollback()
                                errs = [_("Team #%(id)s doesn't exist", id=tid)]
                            for member in team.members:
                                if member.id in ids:
                                    member.teams.remove(team)
                                    if project_id is not None:
                                        Project.revoke_permission(self.env, project_id, member.username)
                            session.commit()
                        else:
                            add_notice(req, _('The selected items have been removed.'))
                            req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

            elif req.args.has_key('add'):
                validator = AddTeamMemberForm()
                form, errs = process_form(req.args, validator)
                if not errs:
                    username   = form['username']
                    team_id    = form['team']
                    permgroups = form['permgroups']
                    session.begin()
                    try:
                        team, project_id = session.query(Team, Project.id).\
                                                   outerjoin(Project, Team.project).\
                                                   filter(Team.id==team_id).one()
                    except NoResultFound:
                        errs = [_("Team #%(id)s doesn't exist", id=team_id)]
                if not errs:
                    user = session.query(User).filter(User.username==username).first()
                    if not user:
                        errs = [_("User %(username)s doesn't exist", username=username)]
                if not errs:
                    if team in user.teams:
                        errs = [_("User %(username)s is already a member of selected team.",
                                  username=username)]
                if not errs:
                    user.teams.append(team)
                    add_notice(req, _("User %(username)s has been added to selected team",
                                      username=username))
                    if any(permgroups.values()):
                        if project_id is not None:
                            for k, perm in _perms_map.iteritems():
                                if permgroups[k]:
                                    Project.grant_permission(self.env, project_id, username, perm)
                            add_notice(req, _("User %(username)s has been added to selected "
                                              "permission groups.", username=username))
                        else:
                            add_warning(req, _("Can not add user to specified permission groups "
                                               "as selected team is not connected with any project."))
                    session.commit()
                    req.redirect(req.panel_href())

                for err in errs:
                    add_warning(req, err)

        teams = session.query(Team.id, Team.name).all()
        members = session.query(Team, Project, User.id, User.username).\
                          join(User, Team.members).\
                          outerjoin(Project, Team.project).\
                          order_by(Team.id, User.username).all()
        data = {
            'teams': teams,
            'members': members,
        }
        return 'admin_members.html', data

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
