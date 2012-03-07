import datetime

from sqlalchemy import Table, Column, Integer, BigInteger, String, Text, MetaData, ForeignKey, TypeDecorator

from trac.util.datefmt import from_utimestamp, to_utimestamp



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

tickets = Table('ticket', metadata,
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


