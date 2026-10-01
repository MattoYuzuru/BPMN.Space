"""Записанные «ответы модели» для mock-пайплайна (`app/llm/mock.py`).

Правила срабатывают по содержимому источников, а не по id проекта: поэтому одинаково работают
и в засеянном демо-проекте, и в проекте, созданном из примера, и при загрузке
`examples/tp861/input/project-finances.docx` вручную.
Все цитаты обязаны дословно встречаться в текстах `texts/` — это проверяет тест фикстур.
"""

from app.domain.models import QuestionKind as K
from app.domain.models import Severity as S  # noqa: N817
from app.fixtures.types import DiagramRule, Playbook, QuestionRule, ResolutionRule

# --- Технологическое присоединение (ПП РФ № 861) ----------------------------------------------

TP_NOTIFY = "Кто направляет заявителю уведомление о недостающих сведениях?"
TP_BOUNDARY = "Заявитель ровно на 150 кВт попадает в ветку «до 150 кВт» или «больше 150 кВт»?"
TP_INVOICE = "Кто выставляет счёт на оплату технологического присоединения?"
TP_DEADLINE = "Что происходит, если заявитель не дополнил заявку в срок?"
TP_TERM = (
    "Какой срок размещения договора для заявителей до 150 кВт: 10 рабочих дней по регламенту "
    "или 5, как сказали на встрече?"
)
TP_ORDER = "Осмотр и допуск прибора учёта — это последовательные шаги или один выезд?"
TP_INVOICE_TIME = (
    "Когда выставляется счёт: вместе с договором, как в регламенте, или после принятия условий, "
    "как в документе «Финансы проекта»?"
)

TP_SIGNATURE = "Сетевая организация проверяет комплектность заявки"
TP_NOTE_SIGNATURE = "Осмотр делаем одним выездом вместе с монтёрами учёта"
TP_FINANCE_SIGNATURE = "формирует финансовый отдел сетевой организации"

TP_QUESTIONS = (
    QuestionRule(
        trigger="заявителю направляется уведомление",
        kind=K.MISSING_ACTOR,
        severity=S.MAJOR,
        text=TP_NOTIFY,
        assumption="Уведомление направляет сетевая организация",
        element_ids=("Task_NotifyMissing",),
    ),
    QuestionRule(
        trigger="Для заявителей мощностью до 150 кВт",
        kind=K.AMBIGUOUS_CONDITION,
        severity=S.MINOR,
        text=TP_BOUNDARY,
        assumption="Граница включительно: 150 кВт — ветка «до 150 кВт»",
        element_ids=("Gateway_Power",),
    ),
    QuestionRule(
        trigger="размещаются условия типового договора, счёт и технические условия",
        kind=K.MISSING_ACTOR,
        severity=S.MAJOR,
        text=TP_INVOICE,
        assumption="Счёт выставляет сетевая организация вместе с договором",
        element_ids=("Task_OfferSmall", "Task_OfferLarge"),
    ),
    QuestionRule(
        trigger="заявитель дополняет заявку",
        kind=K.MISSING_OUTCOME,
        severity=S.MAJOR,
        text=TP_DEADLINE,
        assumption="Через 20 рабочих дней без ответа заявка аннулируется",
        element_ids=("Gateway_Complete", "Task_AddDocuments"),
    ),
    QuestionRule(
        trigger="мы обычно укладываемся в пять рабочих дней",
        kind=K.CONFLICT,
        severity=S.BLOCKER,
        text=TP_TERM,
        assumption="Срок по регламенту — 10 рабочих дней",
        element_ids=("Task_OfferSmall",),
    ),
    QuestionRule(
        trigger=TP_NOTE_SIGNATURE,
        kind=K.UNCLEAR_ORDER,
        severity=S.MINOR,
        text=TP_ORDER,
        assumption="Последовательно: сначала осмотр, затем допуск прибора учёта",
        element_ids=("Task_Inspection", "Task_MeterAdmission"),
    ),
    QuestionRule(
        trigger="после того, как заявитель принял условия договора",
        kind=K.CONFLICT,
        severity=S.MAJOR,
        text=TP_INVOICE_TIME,
        assumption="Счёт формирует финансовый отдел после принятия условий договора",
        element_ids=("Task_PayAndSign", "Task_OfferSmall"),
    ),
)

TP_RESOLUTIONS = (
    ResolutionRule(
        question=TP_NOTIFY,
        evidence=(
            "Уведомление о недостающих документах отправляет сетевая организация "
            "через личный кабинет"
        ),
    ),
    ResolutionRule(
        question=TP_INVOICE,
        evidence=(
            "Счёт на оплату технологического присоединения формирует финансовый отдел "
            "сетевой организации"
        ),
    ),
)

_TP_TRACE_BASE = {
    "Task_SubmitApplication": "направляет заявку на технологическое присоединение через личный",
    "Task_CheckCompleteness": TP_SIGNATURE,
    "Gateway_Complete": "Если сведений или документов не хватает",
    "Task_NotifyMissing": "заявителю направляется уведомление",
    "Task_AddDocuments": "заявитель дополняет заявку",
    "Gateway_Power": "Срок подготовки документов зависит от максимальной мощности",
    "Task_OfferSmall": "размещаются условия типового договора, счёт и технические условия",
    "Task_OfferLarge": "направляет проект договора и технические условия в течение 20 рабочих",
    "Task_PayAndSign": "Договор считается заключённым с даты оплаты заявителем счёта",
    "Task_ApplicantWorks": "заявитель — в границах своего участка",
    "Task_GridWorks": "сетевая организация — до границ участка заявителя",
    "Task_Inspection": "проводит осмотр присоединяемых электроустановок",
    "Task_SignAct": "составляется акт об осуществлении технологического присоединения",
    "Task_SupplyContract": "заключает с заявителем договор энергоснабжения",
}
TP_TRACE_V1 = dict(_TP_TRACE_BASE)
TP_TRACE_V2 = {
    **_TP_TRACE_BASE,
    "Task_NotifyMissing": "Уведомление о недостающих документах отправляет сетевая организация",
    "Task_OfferSmall": "в течение 10 рабочих дней с даты получения полной заявки",
    "Task_MeterAdmission": "допуск прибора учёта в эксплуатацию",
    "Task_SendToSupplier": "направляет акт гарантирующему поставщику",
}
TP_TRACE_V3 = {
    **TP_TRACE_V2,
    "Task_PayAndSign": "после того, как заявитель принял условия договора",
    "Task_IssueInvoice": "Счёт на оплату технологического присоединения формирует финансовый отдел",
    "Task_PayInvoice": "Счёт направляется заявителю в личный кабинет",
}

TP_DIAGRAMS = (
    DiagramRule(fixture="tp861_v1", requires=(TP_SIGNATURE,), trace=TP_TRACE_V1),
    DiagramRule(fixture="tp861_v2", requires=(TP_SIGNATURE, TP_NOTE_SIGNATURE), trace=TP_TRACE_V2),
    DiagramRule(
        fixture="tp861_v3", requires=(TP_SIGNATURE, TP_FINANCE_SIGNATURE), trace=TP_TRACE_V3
    ),
)

# --- Вывод оборудования в ремонт ---------------------------------------------------------------

REPAIR_WORKPLACE = "Кто готовит рабочее место — оперативный персонал или ремонтная бригада?"
REPAIR_REFUSAL = "Что делает собственник после отказа: переносит ремонт или подаёт заявку заново?"
REPAIR_EXTENSION = "Сколько раз можно продлевать заявку?"

REPAIR_QUESTIONS = (
    QuestionRule(
        trigger="готовит рабочее место и допускает ремонтную бригаду",
        kind=K.MISSING_ACTOR,
        severity=S.MAJOR,
        text=REPAIR_WORKPLACE,
        assumption="Рабочее место готовит оперативный персонал",
        element_ids=("Task_PrepareWorkplace",),
    ),
    QuestionRule(
        trigger="отказывает в заявке и сообщает причины собственнику",
        kind=K.MISSING_OUTCOME,
        severity=S.MAJOR,
        text=REPAIR_REFUSAL,
        assumption="Процесс завершается, ремонт переносится в следующий график",
        element_ids=("Gateway_Approved", "EndEvent_Refused"),
    ),
    QuestionRule(
        trigger="собственник запрашивает продление заявки",
        kind=K.AMBIGUOUS_CONDITION,
        severity=S.MINOR,
        text=REPAIR_EXTENSION,
        assumption="Продление допускается один раз",
        element_ids=("Task_ExtendRequest",),
    ),
)

REPAIR_DIAGRAM = DiagramRule(
    fixture="repair_outage",
    requires=("Диспетчерский центр рассматривает заявку",),
    trace={
        "Task_PrepareRequest": "готовит диспетчерскую заявку на основании утверждённого графика",
        "Task_SubmitRequest": "подаёт её в диспетчерский центр",
        "Task_ReviewRequest": "Диспетчерский центр рассматривает заявку",
        "Gateway_Approved": "Если вывод в ремонт недопустим по режиму",
        "Task_NotifyRefusal": "отказывает в заявке и сообщает причины собственнику",
        "Task_CommandOutage": "диспетчер даёт команду на вывод оборудования в ремонт",
        "Task_Switching": "выполняет переключения по бланку переключений",
        "Task_PrepareWorkplace": "готовит рабочее место и допускает ремонтную бригаду",
        "Task_RepairWorks": "Ремонтная бригада выполняет работы",
        "Task_ExtendRequest": "собственник запрашивает продление заявки",
        "Task_ApproveExtension": "диспетчерский центр согласует продление",
        "Task_ReportReady": "собственник сообщает о готовности оборудования к вводу в работу",
        "Task_CommandReturn": "Диспетчер даёт команду на ввод",
        "Task_ReturnToService": "оперативный персонал вводит оборудование в работу",
    },
)

# --- Наряд-допуск ------------------------------------------------------------------------------

PERMIT_SUPERVISION = "Кто наблюдает за бригадой, если производитель работ отлучился?"
PERMIT_REMARKS = "Какие замечания к рабочему месту откладывают допуск бригады?"

PERMIT_QUESTIONS = (
    QuestionRule(
        trigger="Производитель работ руководит выполнением работ",
        kind=K.MISSING_ACTOR,
        severity=S.BLOCKER,
        text=PERMIT_SUPERVISION,
        assumption="Работы приостанавливаются до возвращения производителя работ",
        element_ids=("Task_DoWork",),
    ),
    QuestionRule(
        trigger="Если есть замечания",
        kind=K.AMBIGUOUS_CONDITION,
        severity=S.MAJOR,
        text=PERMIT_REMARKS,
        assumption="Любое отклонение от мер безопасности, указанных в наряде",
        element_ids=("Gateway_WorkplaceReady",),
    ),
)

PERMIT_DIAGRAM = DiagramRule(
    fixture="work_permit",
    requires=("выписывает наряд-допуск",),
    trace={
        "Task_IssuePermit": "выписывает наряд-допуск и определяет меры безопасности",
        "Task_Disconnect": "выполняет отключения и устанавливает заземления",
        "Task_CheckCrew": "проверяет состав бригады и наличие средств защиты",
        "Task_CheckWorkplace": "допускающий проверяет подготовку рабочего места",
        "Task_FixRemarks": "допускающий устраняет их",
        "Task_Briefing": "допускающий проводит целевой инструктаж",
        "Task_DoWork": "Производитель работ руководит выполнением работ",
        "Task_ClearWorkplace": "убирает рабочее место и выводит бригаду",
        "Task_ClosePermit": "Допускающий закрывает наряд-допуск",
    },
)

# --- Закупка по 223-ФЗ -------------------------------------------------------------------------

PROCUREMENT_SINGLE = (
    "Если допущена только одна заявка, договор заключается с единственным участником?"
)
PROCUREMENT_PLAN = "Кто утверждает изменения в плане закупок?"

PROCUREMENT_QUESTIONS = (
    QuestionRule(
        trigger="Если допущенных заявок нет",
        kind=K.AMBIGUOUS_CONDITION,
        severity=S.MAJOR,
        text=PROCUREMENT_SINGLE,
        assumption="Да, договор заключается с единственным допущенным участником",
        element_ids=("Gateway_HasBids",),
    ),
    QuestionRule(
        trigger="вносит изменения в план закупок",
        kind=K.MISSING_ACTOR,
        severity=S.MINOR,
        text=PROCUREMENT_PLAN,
        assumption="Изменения утверждает руководитель отдела закупок",
        element_ids=("Task_AmendPlan",),
    ),
)

PROCUREMENT_DIAGRAM = DiagramRule(
    fixture="procurement_223",
    requires=("размещает извещение о проведении запроса котировок",),
    trace={
        "Task_Request": "формирует заявку на закупку с техническим заданием",
        "Task_CheckPlan": "проверяет, есть ли закупка в плане закупок",
        "Task_AmendPlan": "вносит изменения в план закупок",
        "Task_Publish": "размещает извещение о проведении запроса котировок в ЕИС",
        "Task_CollectBids": "принимает заявки участников",
        "Task_Evaluate": "Закупочная комиссия рассматривает и оценивает заявки",
        "Task_Failed": "комиссия признаёт закупку несостоявшейся",
        "Task_Protocol": "комиссия подписывает итоговый протокол",
        "Task_Contract": "заключает договор с победителем",
    },
)

# --- Договор энергоснабжения -------------------------------------------------------------------

SUPPLY_GRID = "Что происходит, если сетевая организация не подтвердила документы о присоединении?"
SUPPLY_PACKAGE = "Какие документы входят в обязательный комплект?"

SUPPLY_QUESTIONS = (
    QuestionRule(
        trigger="Сетевая организация подтверждает документы",
        kind=K.MISSING_OUTCOME,
        severity=S.MAJOR,
        text=SUPPLY_GRID,
        assumption="Гарантирующий поставщик повторяет запрос через 5 рабочих дней",
        element_ids=("Task_ConfirmGrid",),
    ),
    QuestionRule(
        trigger="с комплектом документов",
        kind=K.AMBIGUOUS_CONDITION,
        severity=S.MINOR,
        text=SUPPLY_PACKAGE,
        assumption="Комплект — по перечню на сайте гарантирующего поставщика",
        element_ids=("Task_CheckDocs",),
    ),
)

SUPPLY_RESOLUTIONS = (
    ResolutionRule(
        question=SUPPLY_PACKAGE,
        evidence=(
            "Обязательный комплект — заявление, документы на объект и документы о присоединении"
        ),
    ),
)

SUPPLY_DIAGRAM = DiagramRule(
    fixture="supply_contract",
    requires=("Гарантирующий поставщик проверяет комплект документов",),
    trace={
        "Task_Submit": "подаёт гарантирующему поставщику заявление",
        "Task_CheckDocs": "Гарантирующий поставщик проверяет комплект документов",
        "Task_RequestDocs": "запрашивает недостающие документы",
        "Task_ProvideDocs": "потребитель их представляет",
        "Task_RequestGrid": "запрашивает у сетевой организации документы о технологическом",
        "Task_ConfirmGrid": "Сетевая организация подтверждает документы",
        "Task_PrepareDraft": "готовит проект договора",
        "Task_SendDraft": "направляет договор потребителю",
        "Task_Sign": "потребитель подписывает договор",
    },
)

PLAYBOOK = Playbook(
    questions=(
        *TP_QUESTIONS,
        *REPAIR_QUESTIONS,
        *PERMIT_QUESTIONS,
        *PROCUREMENT_QUESTIONS,
        *SUPPLY_QUESTIONS,
    ),
    resolutions=(*TP_RESOLUTIONS, *SUPPLY_RESOLUTIONS),
    diagrams=(
        *TP_DIAGRAMS,
        REPAIR_DIAGRAM,
        PERMIT_DIAGRAM,
        PROCUREMENT_DIAGRAM,
        SUPPLY_DIAGRAM,
    ),
)

# Ответы и заметки, которые сид кладёт в демо-проекты (их цитируют правила выше).
TP_ANSWER_TERM = (
    "Ориентируемся на регламент — 10 рабочих дней. Пять дней — внутренний целевой срок отдела, "
    "в схему его не включаем."
)
PERMIT_ANSWER_REMARKS = (
    "Допуск откладывается, если не вывешены плакаты, не установлены заземления "
    "или не проверено отсутствие напряжения."
)
PROCUREMENT_ANSWER_PLAN = (
    "Изменения в план закупок утверждает закупочная комиссия на ближайшем заседании."
)
SUPPLY_NOTE = (
    "Созвонился с юристом гарантирующего поставщика. Обязательный комплект — заявление, "
    "документы на объект и документы о присоединении, полный перечень опубликован на сайте."
)
