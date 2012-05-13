class EvalModelError(Exception):
    '''Base exception class for all eval model errors'''

class EvalVariableError(EvalModelError):
    '''Base exception class for all errors occurred
    during eval variables processing'''

class EvalSourceError(EvalModelError):
    '''Base exception class for all errors occurred
    while querying eval sources'''

class DataNotReadyError(EvalSourceError):
    '''Exception for the cases when some data is not yet
    ready for processing (e.g. not collected yet)'''

class MissedQueryArgumentsError(EvalSourceError):
    '''Exception for the cases when some mandatory
    arguments to perform source query are not set'''
