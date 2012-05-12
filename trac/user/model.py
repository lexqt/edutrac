from trac.util.translation import _

from sqlalchemy import Column, Integer, String, Text, SmallInteger, Boolean
from sqlalchemy.orm import relationship, backref
from trac.db_sqlalchemy import ModelBase, groupmeta_rel, teamgroup_rel, team_members


__all__ = ['User', 'Team', 'Group', 'Metagroup']




class User(ModelBase):
    '''User model class'''

    __tablename__ = 'users'

    # declare fields
    id       = Column('id', Integer, primary_key=True, autoincrement=True)
    username = Column('username', String(255), nullable=False, unique=True)
    password = Column('password', String(255))



class Team(ModelBase):
    '''Team model class'''

    __tablename__ = 'teams'

    # declare fields
    id   = Column('id', Integer, primary_key=True, autoincrement=True)
    name = Column('name', String(255), nullable=False)

    # relations
    members = relationship(User, secondary=team_members, backref='teams')

    # backrefs
    group   = None  # see `Group.teams`
    project = None  # see `Project.team`

    def __init__(self, name, description=''):
        self.name = name
        self.description = description

class Group(ModelBase):
    '''Group model class'''

    __tablename__ = 'groups'

    # declare fields
    id          = Column('id', Integer, primary_key=True, autoincrement=True)
    name        = Column('name', String(255), nullable=False)
    description = Column('description', Text, server_default='')

    # relations
    teams = relationship(Team, secondary=teamgroup_rel, backref=backref('group', uselist=False))

    # backrefs
    metagroup = None  # see `Metagroup.groups`

    def __init__(self, name, description=''):
        self.name = name
        self.description = description


class Metagroup(ModelBase):
    '''Metagroup model class'''

    __tablename__ = 'metagroups'

    # declare fields
    id     = Column('id', Integer, primary_key=True, autoincrement=True)
    name   = Column('name', String(255), nullable=False)
    year   = Column('year', SmallInteger, nullable=False)
    active = Column('active', Boolean, nullable=False, server_default='TRUE')

    # relations
    groups = relationship(Group, secondary=groupmeta_rel,
                          backref=backref('metagroup', uselist=False))

    # backrefs
    syllabus = None  # see `Syllabus.metagroups`

    def __init__(self, name=None, year=None, active=None):
        self.name = name
        self.year = year
        self.active = active


