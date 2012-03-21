import datetime

from sqlalchemy import Table, Column, MetaData, TypeDecorator, ForeignKey, ForeignKeyConstraint,\
    Integer, BigInteger, String, Text, Boolean, DateTime

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

users = Table('users', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('username', String(255), nullable=False, unique=True),
    Column('password', String(255)),
)

projects = Table('projects', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('name', String(255), nullable=False, unique=True),
    Column('description', Text, server_default=''),
)

ticket = Table('ticket', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
    Column('type', Text),
    Column('time', IntegerUTimestamp, index=True),
    Column('changetime', IntegerUTimestamp),
    Column('component', Text),
    Column('severity', Text),
    Column('priority', Text),
    Column('owner', Text),
    Column('reporter', Text),
    Column('cc', Text),
    Column('version', Text),
    Column('milestone', Text),
    Column('status', Text, index=True),
    Column('resolution', Text),
    Column('summary', Text),
    Column('description', Text),
    Column('keywords', Text),
)

ticket_custom = Table('ticket_custom', metadata,
    Column('ticket', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True),
    Column('name', Text, primary_key=True),
    Column('value', Text),
)

ticket_change = Table('ticket_change', metadata,
    Column('ticket', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True, index=True),
    Column('time', IntegerUTimestamp, primary_key=True, index=True),
    Column('author', Text),
    Column('field', Text, primary_key=True),
    Column('oldvalue', Text),
    Column('newvalue', Text),
)

ticket_evaluation = Table('ticket_evaluation', metadata,
    Column('ticket_id', Integer, ForeignKey('ticket.id', ondelete='CASCADE'), primary_key=True),
    Column('value', Integer, nullable=False, server_default='0'),
)

team_milestone_evaluation = Table('team_milestone_evaluation', metadata,
    Column('username', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('project_id', Integer, primary_key=True),
    Column('milestone', String(255), primary_key=True),
    Column('complete', Boolean, server_default='TRUE', nullable=False),
    Column('completed_on', UTCDateTime, server_default='CURRENT_TIMESTAMP', nullable=False),
    ForeignKeyConstraint(['milestone', 'project_id'], ['milestone.name', 'milestone.project_id'], ondelete='CASCADE', onupdate='CASCADE'),
)

team_milestone_evaluation_results = Table('team_milestone_evaluation_results', metadata,
    Column('author', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('target', String(255), ForeignKey('users.username', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True),
    Column('project_id', Integer, primary_key=True),
    Column('milestone', String(255), primary_key=True),
    Column('value', Integer, nullable=False, server_default='0'),
    Column('comment', Text, server_default='', nullable=False),
    ForeignKeyConstraint(['milestone', 'project_id'], ['milestone.name', 'milestone.project_id'], ondelete='CASCADE', onupdate='CASCADE'),
)

# Repository system

repository = Table('repository', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', Text, primary_key=True),
    Column('value', Text),
)


# Views

project_info = Table('project_info', metadata,
    Column('project_id', Integer, ForeignKey('projects.id'), primary_key=True),
    Column('active', Boolean),
    Column('team_id', Integer, ForeignKey('teams.id'), nullable=False),
    Column('studgroup_id', Integer, ForeignKey('student_groups.id'), nullable=False),
    Column('metagroup_id', Integer, ForeignKey('metagroups.id'), nullable=False),
    Column('syllabus_id', Integer, ForeignKey('syllabuses.id'), nullable=False),
)

