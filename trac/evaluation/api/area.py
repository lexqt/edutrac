from trac.util.translation import _, N_


class SubjectArea(object):
    USER     = 1
    PROJECT  = 2
    GROUP    = 3 # e.g. Student group
    SYLLABUS = 4

    _labels = {
        USER: N_('User'),
        PROJECT: N_('Project'),
        GROUP: N_('Group'),
        SYLLABUS: N_('Syllabus'),
    }

    @classmethod
    def label(cls, area):
        if area not in cls._labels:
            return _('<Unknown area>')
        return _(cls._labels[area])

class TimeArea(object):
    DAY = 1

class ClusterArea(object):
    NONE      = 0
    MILESTONE = 1

    _labels = {
        NONE: N_('Without clustering'),
        MILESTONE: N_('Milestone'),
    }

    @classmethod
    def label(cls, clust):
        if clust not in cls._labels:
            return _('<Unknown cluster>')
        return _(cls._labels[clust])

    @classmethod
    def state_var(cls, area):
        if area == cls.MILESTONE:
            return 'milestone'

