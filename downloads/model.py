# -*- coding: utf-8 -*-

from trac.evaluation.api import EvaluationModel, ModelVariable, ModelConstant, \
        SubjectArea, ClusterArea, \
        UnityScale, RatioScale, PercentScale, BooleanScale, NominalScale, OrdinalScale, \
        EvalVariableError, \
        varlib, UserRole, get_enum_equivalents, revert_enum
from trac.evaluation.sources import tktsrc as ts

class Model(EvaluationModel):

    ENUM_MAP = {
        'priority': {
            u'второстепенная': 1,
            u'минорная': 2,
            u'обычная': 3,
            u'важная': 4,
            u'критическая': 5,
            '*': 1,
        },
        'resolution': {
            'done': 1,
            'invalid': 0,
            'outdated': 0,
            'incomplete': 1,
            'reassigned': 1,
            '*': 1,
        },
        'severity': {
            u'простейшая': 1,
            u'простая': 2,
            u'обычная': 3,
            u'сложнее среднего': 4,
            u'трудная': 5,
            '*': 1,
        },
        'type': {
            u'программирование': 1,
            u'проектирование': 1,
            u'документирование': 1,
            u'исправление ошибки': 1,
            u'подготовка данных': 1,
            u'тестирование': 1,
            u'точка планирования': 0,
            u'оценивание': 0,
            '*': 1,
        },
    }

    TICKET_VALUE_HELP = u'''
Стоимость задачи рассчитывается на основе значений следующих свойств:

 * приоритет;
 * серьезность;
 * модификатор стоимости;
 * тип задачи;

Формула для расчета: **тип** * (**приоритет** * **серьезность** + **модификатор стоимости**).

Значение стоимости округляется до целого и не может быть отрицательным.

Подходите с ответственностью к выставлению значений для указанных свойств задач.

Если задаче выставлен высокий **приоритет** (повышающий её стоимость),
то и выполнена задача должна быть в назначенный крайний срок. В противном случае
если задача была выполнена с большим запозданием, её приоритет по факту снизился
и должен быть **изменен перед закрытием задачи**.

Если свойства задачи по её завершении соответствуют действительности, но
исполнитель выполнил её очень //оперативно// или сделал что-то //сверх поставленной задачи//,
это необходимо отразить с помощью **модификатора стоимости** — выставить бонус.
'''
    TICKET_VALUE_ENUM_LIST = ('type', 'priority', 'severity')

    VAR_PROJECT_RATING    = 'project_rating'
    VAR_INDIVIDUAL_RATING = 'individual_rating'
    VAR_FINAL_RATING      = 'final_rating'

    VARS_MILESTONE_RATING = ('milestone_expert', 'valid_tickets', 'completed_tickets', 'earned_by_tickets_target',
                             'completion', 'completion_by_val', 'avg_severity')

    VARS_MILESTONE_TEAM_EVAL_MANAGER   = ('milestone_peer_grade',          'individual_earned_rating',
                                          'earned_by_tickets', 'completed_tickets', 'created_tickets', 'avg_severity')
    VARS_MILESTONE_TEAM_EVAL_DEVELOPER = ('milestone_peer_grade_afterall', 'individual_earned_rating',
                                          'earned_by_tickets', 'completed_tickets', 'created_tickets', 'avg_severity')

    VARS_PROJECT_RATING = ('project_rating', 'completion', 'completion_by_val',
                           'milestones_total', 'project_expert', 'earned_by_tickets_target', 'avg_severity')
    VARS_INDIVIDUAL_RATING = ('final_rating', 'individual_rating', 'individual_earned_rating',
                              'peer_individual_rating', 'completed_tickets', 'created_tickets', 'avg_severity')

    PROJECT_EVAL_CRITERIA = {
        'completion': {
            'order': 1,
            'label': u'Готовность проекта',
            'description': u'Завершенность разработки программы, являвшейся целью проекта.',
            'scale': PercentScale(),
        },
        'swing_practice': {
            'order': 2,
            'label': u'Успех освоения Java Swing',
            'description': u'Насколько хорошо освоен Swing, если судить по функциональности и интерфейсам разработанной программы.',
            'scale': PercentScale(),
        },
        'good_teamwork': {
            'order': 3,
            'label': u'Успешно работали в команде [Бонус]',
            'description': u'Слаженно ли проходила коллективная работа, получены ли навыки командой работы.',
            'scale': BooleanScale(),
        },
        'test_crit1': {
            'order': 4,
            'label': u'Наибольший успех достигнут в',
            'description': u'Тестовый критерий с номинальной шкалой. Не используется при формировании оценки.',
            'scale': NominalScale([u'проектирование интерфейсов', u'разработка алгоритмов']),
        },
        'test_crit2': {
            'order': 5,
            'label': u'Выполнение работ, сдача этапов и т.д. в срок',
            'description': u'Тестовый критерий с порядковой шкалой. Не используется при формировании оценки.',
            'scale': OrdinalScale({u'всегда': 5, u'почти всегда': 4, u'обычно': 3, u'редко': 2, u'никогда': 1}),
        },
    }


    def get_ticket_value(self, ticket):
        tkt = ticket
        p = self.get_enum_value('priority', tkt['priority'])
        s = self.get_enum_value('severity', tkt['severity'])
        t = self.get_enum_value('type', tkt['type'])
        m = int(tkt['modifier'] or 0)
        base_value = int(round(max(0, t * (p * s + m) )))
        return base_value



class CompletedTicketsVar(varlib.CountTickets):

    model_cls = Model

    subject_support = (SubjectArea.USER, SubjectArea.PROJECT)
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.CountTickets specific vars
    filter_tickets = (
                (ts.Status()=='closed') &
                (ts.Resolution()=='done')
                )

    alias = 'completed_tickets'
    label = u'Количество выполненных задач'
    description = u'''
Количество выполненных задач (закрытые как done карточки).
'''

class CreatedTicketsVar(varlib.CountTickets):

    model_cls = Model

    subject_support = (SubjectArea.USER, SubjectArea.PROJECT)
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.CountTickets specific vars
    filter_tickets = ~ (
                (ts.Status()=='closed') &
                (ts.Resolution()!='done')
                )
    limit_project_users_field = ts.Reporter()
    limit_allow_empty = False
    user_field = ts.Reporter()

    alias = 'created_tickets'
    label = u'Количество созданных задач'
    description = u'''
Количество созданных членами команды валидных задач
(исключены закрытые как невалидные или неактуальные).
'''

class ValidTicketsVar(varlib.CountTickets):

    model_cls = Model

    subject_support = (SubjectArea.USER, SubjectArea.PROJECT)
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.CountTickets specific vars
    filter_tickets = ~ (
                (ts.Status()=='closed') &
                (ts.Resolution()!='done')
                )
    limit_allow_empty = True

    alias = 'valid_tickets'
    label = u'Количество всех валидных задач'
    description = u'''
Количество всех валидных задач (исключены закрытые как невалидные или неактуальные).
Подсчитываются только те задачи, у которых либо еще нет исполнителя, либо исполнителем
является член команды.
'''

class CompletionVar(varlib.TwoVarsRatio):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.PROJECT
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.TwoVarsRatio specific vars
    var1 = 'completed_tickets'
    var2 = 'valid_tickets'

    alias = 'completion'
    label = u'Завершенность по задачам'
    description = u'''
Отношение количества выполненных задач к числу всех валидных задач.
'''


class CompletionByValuesVar(varlib.TwoVarsRatio):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.PROJECT
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.TwoVarsRatio specific vars
    var1 = 'earned_by_tickets'
    var2 = 'ticket_values_sum'

    alias = 'completion_by_val'
    label = u'Завершенность по задачам (с учетом стоимостей)'
    description = u'''
Отношение суммы стоимостей выполненных задач к сумме стоимостей всех валидных задач.
'''


class EarnedByTicketsVar(ModelVariable):

    model_cls = Model

    scale = RatioScale(int)

    subject_support = (SubjectArea.USER, SubjectArea.PROJECT)
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    alias = 'earned_by_tickets'
    label = u'Заработано по стоимости задач'
    description = u'''
Баллы, заработанные за выполненные задачи. Рассчитывается
суммированием стоимостей задач.
'''

    def _get(self):
        q = self.model.sources['ticket']
        self > q
        q.where(
                (ts.Status()=='closed') &
                (ts.Resolution()=='done')
                )
        if self['area'] == SubjectArea.PROJECT:
            q.limit_to_project_users(ts.Owner())
        res = q.sum(ts.TicketValue())
        return res


class ValidTicketValuesSum(ModelVariable):

    model_cls = Model

    scale = RatioScale(int)

    subject_support = SubjectArea.PROJECT
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    alias = 'ticket_values_sum'
    label = u'Суммарная стоимость задач'
    description = u'''
Сумма стоимостей всех валидных задач (завершенных и незавершенных).
'''

    def _get(self):
        q = self.model.sources['ticket']
        self > q
        q.where(~(
                    (ts.Status()=='closed') &
                    (ts.Resolution()!='done')
                 )
                )
        q.limit_to_project_users(ts.Owner())
        res = q.sum(ts.TicketValue())
        return res


class EarnedByTicketsSumTarget(ModelVariable):

    model_cls = Model

    scale = RatioScale(float)

    subject_support = SubjectArea.PROJECT
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    alias = 'earned_by_tickets_target'
    label = u'Целевая сумма баллов за задачи'
    description = u'''
Сумма стоимостей всех валидных задач (завершенных и незавершенных),
приходящаяся в среднем на каждого члена команды.
'''

    def _get(self):
        esum = self.model.vars['ticket_values_sum']
        self > esum
        total = esum.get()
        uinfo = self.model.sources['user_info']
        self > uinfo
        size = uinfo.role(UserRole.DEVELOPER).count()
        return float(total) / size


class TeamMilestoneGrade(varlib.TeamMilestoneVariable):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.USER
    cluster_support = ClusterArea.MILESTONE

    # varlib.TeamMilestoneVariable specific vars
    with_authors  = False
    all_completed = False
    only_approved = True

    alias = 'milestone_peer_grade'
    label = u'Оценка по взаимному оцениванию за этап'
    description = u'''
Значение, полученное суммированием и усреднением результатов взаимного оценивания.
'''

    def process_results(self, results, msum, team_size):
        cnt = len(results)
        if not cnt:
            raise EvalVariableError(u'Данные по взаимному оцениванию отсутствуют')
        value = ( sum(results) / float(cnt * msum) ) * team_size
        return value

class TeamMilestoneGradeAfterAll(TeamMilestoneGrade):

    model_cls = Model

    all_completed = True

    alias = 'milestone_peer_grade_afterall'
    label = u'Оценка по взаимному оцениванию (пройдено всеми) за этап'
    description = u'''
Значение, полученное суммированием и усреднением результатов взаимного оценивания.
Значение может быть получено только после того, как формы взаимного оценивания
заполнят все члены команды.
'''



class ExpertProjectGrade(varlib.ProjectCriteria):

    model_cls = Model

    scale = UnityScale()

    # varlib.ProjectCriteria specific vars
    all_completed = True

    alias = 'project_expert'
    label = u'Экспертная оценка проекта'
    description = u'''
Оценка, сформированная по данным электронного анкетирования
для оценивания результатов выполнения проекта.
'''

    def process_results(self, criteria, values):
        compl_weight = self.model.constants['exp_project_completion']
        learn_weight = self.model.constants['exp_learning_objectives']
        bonus = values['good_teamwork'] and 0.05 or 0
        value = compl_weight * values['completion'] / 100 + \
                learn_weight * values['swing_practice'] / 100 + \
                bonus
        return value


class MilestoneExpertRating(ModelVariable):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.PROJECT
    cluster_support = ClusterArea.MILESTONE

    alias = 'milestone_expert'
    label = u'Экспертная оценка за этап'
    description = u'''
Рейтинг, выставленный менеджером за этап.
'''

    def _get(self):
        q = self.model.sources['milestone']
        self > q
        q.include(rating=True)
        r = q.get()
        return float(r) / 100


class MilestonesResultsVar(varlib.ProjectMilestones):

    model_cls = Model

    scale = UnityScale()

    # varlib.ProjectMilestones specific vars
    only_approved  = True
    only_completed = False

    alias = 'milestones_total'
    label = u'Оценка за все этапы'
    description = u'''
Оценка, сформированная по рейтингам и весам, выставленным для этапов проекта.
'''

    def process_milestones(self, milestones, total_weight):
        approved_cnt = len(milestones)
        if not approved_cnt:
            raise EvalVariableError(u'В проекте нет ни одного утвержденного этапа')
#        completed_list = [data for data in milestones.values() if data['completed']]
        mlist = milestones.values() # незавершенным можно просто не ставить рейтинг
                                    # или выставлять промежуточный
        if not total_weight:
            sum_func = lambda s, m: s+m['rating']
            norm = 100.0 * approved_cnt
        else:
            sum_func = lambda s, m: s + m['weight']*m['rating']
            norm = 100.0 * total_weight
        total_rating = reduce(sum_func, mlist, 0)
        return total_rating / norm


class ProjectRating(varlib.MultiVars):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.PROJECT

    # varlib.MultiVars specific vars
    var_list = ('completion_by_val', 'milestones_total', 'project_expert')

    alias = 'project_rating'
    label = u'Итоговая оценка за проект'
    description = u'''
Итоговая оценка за проект, сформированная суммированием с весами
1) степени завершенности проекта по задачам (с учетом их стоимостей);
2) оценки за все этапы проекта;
3) экспертной оценки проекта.
'''

    def process_variables(self, completion, ms_total, expert):
        self > completion
        self > ms_total
        self > expert
        completion_weight = self.model.constants['project_completion']
        milestones_weight = self.model.constants['project_milestones']
        expert_weight     = self.model.constants['project_expert']
        completion = completion.get()
        ms_total   = ms_total.get()
        expert     = expert.get()
        value = completion_weight * completion + \
                milestones_weight * ms_total + \
                expert_weight * expert
        return value



class IndividualEarnedRatio(varlib.MultiVars):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.USER
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    # varlib.MultiVars specific vars
    var_list = ('earned_by_tickets', 'earned_by_tickets_target')

    alias = 'individual_earned_rating'
    label = u'Индивидуальный вклад по задачам'
    description = u'''
Индивидуальная оценка, рассчитанная как отношение баллов за выполненные
задачи к целевой сумме баллов по задачам (сумме стоимостей всех валидных
задач (завершенных и незавершенных), приходящаяся в среднем на каждого
члена команды).
'''

    def process_variables(self, earned, target):
        self > earned
        self > target
        target.project(self['project_id']) # вернуть область запроса "проект"
        u = earned.get()
        t = target.get()
        if not t:
            return 0
        value = float(u) / t
        return value



class PeerIndividualRating(varlib.ProjectMilestones):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.USER

    # varlib.ProjectMilestones specific vars
    only_approved  = True
    only_completed = False

    alias = 'peer_individual_rating'
    label = u'Индивидуальная оценка по взаимному оцениванию'
    description = u'''
Индивидуальная оценка, рассчитанная суммированием результатов
взаимного оценивания за утвержденные этапы проекта с учетом весов этапов.
'''

    def process_milestones(self, milestones, total_weight):
        peergrade = self.model.vars['milestone_peer_grade']

        # суммирование с учетом весов этапов (если веса используются)
        self > peergrade
        approved_cnt = len(milestones)
        if not approved_cnt:
            raise EvalVariableError(u'В проекте нет ни одного утвержденного этапа')

        mlist = milestones.values()
        if not total_weight:
            sum_func = lambda s, m: s + peergrade.milestone(m['name']).get()
            norm = approved_cnt
        else:
            sum_func = lambda s, m: s + m['weight'] * peergrade.milestone(m['name']).get()
            norm = total_weight
        total_rating = reduce(sum_func, mlist, 0)
        peertotal = total_rating / norm

        return peertotal


class IndividualRating(varlib.MultiVars):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.USER

    # varlib.MultiVars specific vars
    var_list = ('individual_earned_rating', 'peer_individual_rating')

    alias = 'individual_rating'
    label = u'Индивидуальная оценка за проект'
    description = u'''
Индивидуальная оценка, рассчитанная суммированием индивидуального вклада
по задачам всего проекта и результатов взаимного оценивания за утвержденные
этапы проекта с учетом весов этапов.
'''

    def process_variables(self, earned, peer):
        earned_weight = self.model.constants['indiv_earned_weight']
        peer_weight   = self.model.constants['indiv_peer_weight']
        self > earned
        self > peer
        earned = earned.get()
        peer   = peer.get()

        value = earned_weight * earned + peer_weight * peer
        return value


class FinalRating(varlib.MultiVars):

    model_cls = Model

    scale = UnityScale()

    subject_support = SubjectArea.USER

    # varlib.MultiVars specific vars
    var_list = ('project_rating', 'individual_rating')

    alias = 'final_rating'
    label = u'Итоговая индивидуальная оценка'
    description = u'''
Итоговая индивидуальная оценка за проект, сформированная суммированием
с весами итоговой оценки за проект и индивидуальной оценки.
'''
    def process_variables(self, project, individual):
        self > individual
        project.project(self['project_id'])
        project_weight    = self.model.constants['final_project_weight']
        individual_weight = self.model.constants['final_individual_weight']
        project    = project.get()
        individual = individual.get()
        value = project_weight * project + \
                individual_weight * individual
        return value



# Extras #

class AvgSeverityVar(ModelVariable):

    model_cls = Model

    subject_support = (SubjectArea.USER, SubjectArea.PROJECT)
    cluster_support = (ClusterArea.NONE, ClusterArea.MILESTONE)

    alias = 'avg_severity'
    label = u'Средняя сложность выполненных задач'
    description = u'''
Средняя сложность выполненных задач, рассчитываемая с учетом
числовых эквивалентов для соответствующих значений сложности.
'''

    def _get(self):
        q = self.model.sources['ticket']
        self > q
        q.where(
                (ts.Status()=='closed') &
                (ts.Resolution()=='done')
                )
        if self['area'] == SubjectArea.PROJECT:
            q.limit_to_project_users(ts.Owner())
        q.only(ts.Severity)
        row  = q.get()
        if not row:
            raise EvalVariableError(u'Нет выполненных задач')

        nums = get_enum_equivalents(self.model, 'severity', row)
        num  = sum(nums) / float(len(nums))
        res  = revert_enum(self.model, 'severity', num)
        return res





###################
# Model constants #
###################

class ExpertProjectCompletionWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.7

    alias = 'exp_project_completion'
    label = u'[Эксперт] Вес оценки завершенности проекта'
    description = u'''
Вес оценки завершенности проекта для расчета экспертной оценки проекта.
'''

class ExpertLearningCompletionWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.3

    alias = 'exp_learning_objectives'
    label = u'[Эксперт] Суммарный вес целей обучения'
    description = u'''
Суммарный вес целей обучения для расчета экспертной оценки проекта.
'''


class ProjectCompletionWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.1

    alias = 'project_completion'
    label = u'[Итоговая за проект] Вес оценки завершенности проекта'
    description = u'''
Вес оценки завершенности проекта для расчета итоговой оценки за проект.
'''


class ProjectMilestonesWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.4

    alias = 'project_milestones'
    label = u'[Итоговая за проект] Вес суммарной оценки за этапы'
    description = u'''
Вес суммарной оценки за этапы проекта для расчета итоговой оценки за проект.
'''


class ProjectExpertWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.5

    alias = 'project_expert'
    label = u'[Итоговая за проект] Вес экспертной оценки проекта'
    description = u'''
Вес экспертной оценки проекта для расчета итоговой оценки за проект.
'''



class IndividualEarnedWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.5

    alias = 'indiv_earned_weight'
    label = u'[Индивидуальная за проект] Вес индивидуального вклада'
    description = u'''
Вес оценки индивидуального вклада для расчета индивидуальной
оценки за проект.
'''



class IndividualPeerWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.5

    alias = 'indiv_peer_weight'
    label = u'[Индивидуальная за проект] Вес оценки по взаимному оцениванию'
    description = u'''
Вес оценки по взаимному оцениванию для расчета индивидуальной
оценки за проект.
'''



class FinalProjectWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.5

    alias = 'final_project_weight'
    label = u'[Итоговая индивидуальная] Вес оценки за проект'
    description = u'''
Вес оценки за проект для расчета итоговой индивидуальной
оценки за проект.
'''



class FinalIndividualWeight(ModelConstant):

    model_cls = Model

    scale = UnityScale()
    default_value = 0.5

    alias = 'final_individual_weight'
    label = u'[Итоговая индивидуальная] Вес индивидуальной оценки за проект'
    description = u'''
Вес индивидуальной оценки за проект для расчета итоговой индивидуальной
оценки за проект.
'''


class TestBoolConstant(ModelConstant):

    model_cls = Model

    scale = BooleanScale()
    default_value = True

    alias = 'test_bool_constant'
    label = u'Тестовая константа Да/Нет'
    description = u'''
Тестовая константа со шкалой BooleanScale
'''



