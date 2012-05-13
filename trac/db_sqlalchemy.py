import datetime

from sqlalchemy import Table, Column, MetaData, TypeDecorator, ForeignKey, ForeignKeyConstraint,\
    Integer, BigInteger, SmallInteger, String, Text, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base

from trac.util.datefmt import from_utimestamp, to_utimestamp, utc



class UTCDateTime(TypeDecorator):

    impl = DateTime

    def process_bind_param(self, value, engine):
        if value is not None:
            value = value.astimezone(utc)
            return datetime.datetime(value.year, value.month, value.day,
                            value.hour, value.minute, value.second,
                            value.microsecond)

    def process_result_value(self, value, engine):
        if value is not None:
            return datetime.datetime(value.year, value.month, value.day,
                            value.hour, value.minute, value.second,
                            value.microsecond, tzinfo=utc)



class IntegerUTimestamp(TypeDecorator):
    """A type that decorates Integer, converts to unix time on
    the way in and to datetime.datetime objects on the way out."""
    impl = BigInteger

    def process_bind_param(self, value, _):
        """Assumes a datetime.datetime"""
        if value is None:
            return None # support nullability
        elif isinstance(value, datetime.datetime):
#            return int(time.mktime(value.timetuple()))
            return to_utimestamp(value)
        raise ValueError("Can operate only on datetime values. "
                         "Offending value type: {0}".format(type(value).__name__))
    def process_result_value(self, value, _):
        if value is not None: # support nullability
#            return datetime.datetime.fromtimestamp(float(value))
            return from_utimestamp(value)



metadata = MetaData()
ModelBase = declarative_base(metadata=metadata)




groupmeta_rel = Table('groupmeta_rel', metadata,
    Column('metagroup_id', Integer, ForeignKey('metagroups.id', ondelete='CASCADE'), primary_key=True),
    Column('group_id',     Integer, ForeignKey('groups.id', ondelete='CASCADE'),     primary_key=True, unique=True),
)
teamgroup_rel = Table('teamgroup_rel', metadata,
    Column('group_id', Integer, ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True),
    Column('team_id',  Integer, ForeignKey('teams.id', ondelete='CASCADE'),  primary_key=True, unique=True),
)
team_members = Table('team_members', metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('team_id', Integer, ForeignKey('teams.id', ondelete='CASCADE'), primary_key=True),
)


group_managers = Table('group_managers', metadata,
    Column('user_id',  Integer, ForeignKey('users.id', ondelete='CASCADE'),  primary_key=True),
    Column('group_id', Integer, ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True),
)


metagroup_syllabus_rel = Table('metagroup_syllabus_rel', metadata,
    Column('metagroup_id', Integer, ForeignKey('metagroups.id', ondelete='CASCADE'), primary_key=True),
    Column('syllabus_id',  Integer, ForeignKey('syllabuses.id', ondelete='CASCADE'), primary_key=True),
)
team_project_rel = Table('team_project_rel', metadata,
    Column('team_id',    Integer, ForeignKey('teams.id', ondelete='CASCADE'),    primary_key=True),
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True, unique=True),
)



project_permissions = Table('project_permissions', metadata,
    Column('username',   String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('project_id', Integer,     ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
    Column('action',     String(255), primary_key=True),
)




ticket = Table('ticket', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
    Column('type', String(255)),
    Column('time', IntegerUTimestamp, index=True),
    Column('changetime', IntegerUTimestamp),
    Column('component', String(255)),
    Column('severity', String(255)),
    Column('priority', String(255)),
    Column('owner', String(255), ForeignKey('users.username', ondelete='SET NULL', onupdate='CASCADE')),
    Column('reporter', String(255), ForeignKey('users.username', ondelete='SET NULL', onupdate='CASCADE')),
    Column('cc', Text),
    Column('version', String(255)),
    Column('milestone', String(255)),
    Column('status', String(255), index=True),
    Column('resolution', String(255)),
    Column('summary', String(255)),
    Column('description', Text),
    Column('keywords', Text),
)

ticket_custom = Table('ticket_custom', metadata,
    Column('ticket', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True),
    Column('name', String(255), primary_key=True),
    Column('value', Text),
)

ticket_change = Table('ticket_change', metadata,
    Column('ticket', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True, index=True),
    Column('time', IntegerUTimestamp, primary_key=True, index=True),
    Column('author', String(255), ForeignKey('users.username', ondelete='SET NULL', onupdate='CASCADE')),
    Column('field', String(255), primary_key=True),
    Column('oldvalue', Text),
    Column('newvalue', Text),
)

ticket_evaluation = Table('ticket_evaluation', metadata,
    Column('ticket_id', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True),
    Column('value', Integer, nullable=False, server_default='0'),
)

milestone = Table('milestone', metadata,
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('name', String(255), primary_key=True),
    Column('due', IntegerUTimestamp),
#    Column('completed', IntegerUTimestamp),
    Column('completed', Integer),
    Column('description', Text),
    Column('weight', Integer, nullable=False, server_default='0'),
    Column('rating', Integer, nullable=False, server_default='0'),
    Column('approved', Boolean, nullable=False, server_default='FALSE'),
)


team_milestone_evaluation = Table('team_milestone_evaluation', metadata,
    Column('username', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('project_id', Integer, primary_key=True),
    Column('milestone', String(255), primary_key=True),
    Column('complete', Boolean, server_default='TRUE', nullable=False),
    Column('completed_on', UTCDateTime, server_default='CURRENT_TIMESTAMP', nullable=False),
    Column('approved', Boolean, server_default='FALSE', nullable=False),
    ForeignKeyConstraint(['milestone', 'project_id'], ['milestone.name', 'milestone.project_id'], ondelete='CASCADE', onupdate='CASCADE'),
)

team_milestone_evaluation_results = Table('team_milestone_evaluation_results', metadata,
    Column('author', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('target', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('project_id', Integer, primary_key=True),
    Column('milestone', String(255), primary_key=True),
    Column('value', Integer, nullable=False, server_default='0'),
    Column('public_comment', Text, server_default='', nullable=False),
    Column('private_comment', Text, server_default='', nullable=False),
    ForeignKeyConstraint(['milestone', 'project_id'], ['milestone.name', 'milestone.project_id'], ondelete='CASCADE', onupdate='CASCADE'),
)

project_evaluation = Table('project_evaluation', metadata,
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('criterion', String(255), primary_key=True),
    Column('value', Text, server_default='', nullable=False),

)

# Repository system

repository = Table('repository', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(255), primary_key=True),
    Column('value', Text),
)


# Views

project_info = Table('project_info', metadata,
    Column('project_id', Integer, ForeignKey('projects.id'), primary_key=True),
    Column('active', Boolean),
    Column('team_id', Integer, ForeignKey('teams.id'), nullable=False),
    Column('group_id', Integer, ForeignKey('groups.id'), nullable=False),
    Column('metagroup_id', Integer, ForeignKey('metagroups.id'), nullable=False),
    Column('syllabus_id', Integer, ForeignKey('syllabuses.id'), nullable=False),
)

