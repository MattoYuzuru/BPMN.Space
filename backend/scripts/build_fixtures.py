"""Генератор фикстур mock-бэкенда: BPMN-схемы демо-проектов и примеры для `examples/`.

Запуск из корня репозитория (нужны Node ≥ 20 и интернет для первого `npx`):

    uv run --directory backend python scripts/build_fixtures.py          # пересобрать и проверить
    uv run --directory backend python scripts/build_fixtures.py --check  # только проверить готовые

Что делает:
1. Описания процессов ниже (`DIAGRAMS`) → семантический BPMN 2.0: collaboration + participant +
   laneSet, `incoming`/`outgoing` у каждого узла, подписанные ветки шлюзов с `conditionExpression`.
2. Координаты (DI) — `npx -y bpmn-auto-layout@2.0.0-alpha.2 <file> --stdout` (та же версия,
   что будет в сервисе bpmn-tools, RFC §6).
3. Проверки: XSD (lxml, официальные схемы OMG из `app/domain/bpmn/xsd/`) и
   `npx -y bpmnlint` с конфигом `bpmnlint:recommended` — ошибок быть не должно.
   Осознанное предупреждение одно: `fake-join` в `tp861_v1` (ранняя версия возвращает цикл
   прямо в задачу; v2 это исправляет шлюзом-слиянием — так показываем пользу проверки).
4. Учебные материалы («Примеры») → `app/fixtures/samples/` (`.docx` тура собирается stdlib-ом).
   `--samples` собирает только их, без Node: `uv run python scripts/build_fixtures.py --samples`.
5. Результат → `app/fixtures/bpmn/<name>.bpmn`; копии схем, исходных текстов и
   `project-finances.docx` (настоящий .docx из `texts/tp861_finances.md`) → `examples/`.

Скрипт не входит в `make check`: он нужен, только если меняются схемы или тексты.
Тест `tests/test_fixtures_bpmn.py` проверяет XSD у готовых файлов при каждом прогоне pytest.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring
from xml.sax.saxutils import escape

from lxml import etree

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
FIXTURES = BACKEND / "app" / "fixtures"
BPMN_DIR = FIXTURES / "bpmn"
TEXTS = FIXTURES / "texts"
XSD = BACKEND / "app" / "domain" / "bpmn" / "xsd" / "BPMN20.xsd"
EXAMPLES = ROOT / "examples"
SAMPLES = FIXTURES / "samples"

LAYOUT = ["npx", "-y", "bpmn-auto-layout@2.0.0-alpha.2"]
LINT = ["npx", "-y", "bpmnlint@11.14.0"]
EXPECTED_WARNINGS = {("tp861_v1", "fake-join", "Task_CheckCompleteness")}

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
register_namespace("bpmn", BPMN)
register_namespace("xsi", XSI)

TAGS = {
    "start": "startEvent",
    "end": "endEvent",
    "task": "task",
    "user": "userTask",
    "send": "sendTask",
    "receive": "receiveTask",
    "manual": "manualTask",
    "xor": "exclusiveGateway",
    "and": "parallelGateway",
}


@dataclass(frozen=True)
class N:
    id: str
    kind: str
    name: str
    lane: str


@dataclass(frozen=True)
class F:
    source: str
    target: str
    name: str = ""
    condition: str = ""


@dataclass
class Diagram:
    key: str
    participant: str
    lanes: list[tuple[str, str]]
    nodes: list[N]
    flows: list[F]
    examples: list[str] = field(default_factory=list)
    # Потоки, которые bpmn-auto-layout ведёт в обход всей дорожки: перекладываем коротким
    # ортогональным маршрутом «вправо → по вертикали → вправо» (см. reroute()).
    reroute: list[str] = field(default_factory=list)


# --- Технологическое присоединение (ПП РФ № 861): три версии ----------------------------------

A, G, FIN, S = "Lane_Applicant", "Lane_Grid", "Lane_Finance", "Lane_Supplier"
V1, V2, V3 = 1, 2, 3  # v1 — ранняя с допущениями, v2 — после ответов, v3 — после «Финансов»


def tp861(version: int) -> Diagram:
    lanes = [(A, "Заявитель"), (G, "Сетевая организация")]
    if version >= V3:
        lanes.append((FIN, "Финансовый отдел"))
    lanes.append((S, "Гарантирующий поставщик"))

    offer_small = {
        1: "Разместить в личном кабинете договор, счёт и ТУ",
        2: "Разместить договор, счёт и ТУ (10 рабочих дней)",
        3: "Разместить договор и ТУ (10 рабочих дней)",
    }[version]
    nodes = [
        N("StartEvent_Need", "start", "Требуется присоединение", A),
        N("Task_SubmitApplication", "send", "Подать заявку через личный кабинет", A),
        N("Task_CheckCompleteness", "user", "Проверить комплектность заявки", G),
        N("Gateway_Complete", "xor", "Комплект полный?", G),
        N("Task_NotifyMissing", "send", "Уведомить о недостающих сведениях", G),
        N("Task_AddDocuments", "user", "Дополнить заявку", A),
        N("Gateway_Power", "xor", "Мощность до 150 кВт?", G),
        N("Task_OfferSmall", "send", offer_small, G),
        N("Task_OfferLarge", "send", "Направить договор и ТУ (20 рабочих дней)", G),
        N("Gateway_PowerMerge", "xor", "", G),
        N(
            "Task_PayAndSign",
            "user",
            "Принять условия договора" if version >= V3 else "Оплатить счёт и принять условия",
            A,
        ),
        N("Gateway_WorksFork", "and", "", A),
        N("Task_ApplicantWorks", "manual", "Выполнить мероприятия по ТУ на своём участке", A),
        N("Task_GridWorks", "manual", "Выполнить мероприятия по ТУ до границы участка", G),
        N("Gateway_WorksJoin", "and", "", G),
        N(
            "Task_Inspection",
            "user",
            "Провести выездной осмотр"
            if version >= V2
            else "Провести осмотр и допустить прибор учёта",
            G,
        ),
        N("Task_SignAct", "user", "Присоединить и составить акт о ТП", G),
        N("Task_SupplyContract", "user", "Заключить договор с заявителем", S),
        N("EndEvent_Connected", "end", "Присоединение выполнено", S),
    ]
    flows = [
        F("StartEvent_Need", "Task_SubmitApplication"),
        F("Task_CheckCompleteness", "Gateway_Complete"),
        F("Gateway_Complete", "Task_NotifyMissing", "Нет", "комплект неполный"),
        F("Task_NotifyMissing", "Task_AddDocuments"),
        F("Gateway_Complete", "Gateway_Power", "Да", "комплект полный"),
        F("Gateway_Power", "Task_OfferSmall", "Да", "мощность до 150 кВт"),
        F("Gateway_Power", "Task_OfferLarge", "Нет", "мощность больше 150 кВт"),
        F("Task_OfferSmall", "Gateway_PowerMerge"),
        F("Task_OfferLarge", "Gateway_PowerMerge"),
        F("Gateway_PowerMerge", "Task_PayAndSign"),
        F("Gateway_WorksFork", "Task_ApplicantWorks"),
        F("Gateway_WorksFork", "Task_GridWorks"),
        F("Task_ApplicantWorks", "Gateway_WorksJoin"),
        F("Task_GridWorks", "Gateway_WorksJoin"),
        F("Gateway_WorksJoin", "Task_Inspection"),
        F("Task_SupplyContract", "EndEvent_Connected"),
    ]
    if version == V1:
        # Ранняя версия: цикл возвращается прямо в задачу (bpmnlint: fake-join — предупреждение).
        flows += [
            F("Task_SubmitApplication", "Task_CheckCompleteness"),
            F("Task_AddDocuments", "Task_CheckCompleteness"),
        ]
    else:
        nodes.insert(2, N("Gateway_CheckMerge", "xor", "", G))
        flows += [
            F("Task_SubmitApplication", "Gateway_CheckMerge"),
            F("Task_AddDocuments", "Gateway_CheckMerge"),
            F("Gateway_CheckMerge", "Task_CheckCompleteness"),
        ]
    if version >= V3:
        nodes += [
            N("Task_IssueInvoice", "user", "Сформировать счёт на оплату", FIN),
            N("Task_PayInvoice", "user", "Оплатить счёт", A),
        ]
        flows += [
            F("Task_PayAndSign", "Task_IssueInvoice"),
            F("Task_IssueInvoice", "Task_PayInvoice"),
            F("Task_PayInvoice", "Gateway_WorksFork"),
        ]
    else:
        flows.append(F("Task_PayAndSign", "Gateway_WorksFork"))
    if version >= V2:
        nodes += [
            N("Task_MeterAdmission", "user", "Допустить прибор учёта в эксплуатацию", G),
            N("Task_SendToSupplier", "send", "Направить акт поставщику", G),
        ]
        flows += [
            F("Task_Inspection", "Task_MeterAdmission"),
            F("Task_MeterAdmission", "Task_SignAct"),
            F("Task_SignAct", "Task_SendToSupplier"),
            F("Task_SendToSupplier", "Task_SupplyContract"),
        ]
    else:
        flows += [
            F("Task_Inspection", "Task_SignAct"),
            F("Task_SignAct", "Task_SupplyContract"),
        ]
    return Diagram(
        key=f"tp861_v{version}",
        participant="Технологическое присоединение к электросетям",
        lanes=lanes,
        nodes=nodes,
        flows=flows,
        examples=[f"tp861/output/diagram-v{version}.bpmn"],
        reroute=["Flow_NotifyMissing_AddDocuments"],
    )


# --- Вывод оборудования в ремонт ----------------------------------------------------------------

OW, D, C, B = "Lane_Owner", "Lane_Dispatch", "Lane_Operators", "Lane_Brigade"
REPAIR = Diagram(
    key="repair_outage",
    participant="Вывод оборудования в ремонт",
    lanes=[
        (OW, "Собственник оборудования"),
        (D, "Диспетчерский центр"),
        (C, "Оперативный персонал"),
        (B, "Ремонтная бригада"),
    ],
    nodes=[
        N("StartEvent_Planned", "start", "Ремонт включён в график", OW),
        N("Task_PrepareRequest", "user", "Подготовить диспетчерскую заявку", OW),
        N("Task_SubmitRequest", "send", "Подать заявку в диспетчерский центр", OW),
        N("Task_ReviewRequest", "user", "Рассмотреть заявку с учётом режимов", D),
        N("Gateway_Approved", "xor", "Вывод в ремонт допустим?", D),
        N("Task_NotifyRefusal", "send", "Сообщить об отказе и причинах", D),
        N("EndEvent_Refused", "end", "Заявка отклонена", D),
        N("Task_CommandOutage", "user", "Дать команду на вывод в ремонт", D),
        N("Task_Switching", "manual", "Выполнить переключения по бланку", C),
        N("Task_PrepareWorkplace", "manual", "Подготовить рабочее место и допустить бригаду", C),
        N("Gateway_WorksMerge", "xor", "", B),
        N("Task_RepairWorks", "manual", "Выполнить ремонтные работы", B),
        N("Gateway_InTime", "xor", "Работы укладываются в срок?", B),
        N("Task_ExtendRequest", "send", "Запросить продление заявки", OW),
        N("Task_ApproveExtension", "user", "Согласовать продление", D),
        N("Task_ReportReady", "send", "Сообщить о готовности к вводу", OW),
        N("Task_CommandReturn", "user", "Дать команду на ввод в работу", D),
        N("Task_ReturnToService", "manual", "Ввести оборудование в работу", C),
        N("EndEvent_InService", "end", "Оборудование в работе", C),
    ],
    flows=[
        F("StartEvent_Planned", "Task_PrepareRequest"),
        F("Task_PrepareRequest", "Task_SubmitRequest"),
        F("Task_SubmitRequest", "Task_ReviewRequest"),
        F("Task_ReviewRequest", "Gateway_Approved"),
        F("Gateway_Approved", "Task_NotifyRefusal", "Нет", "вывод недопустим по режиму"),
        F("Task_NotifyRefusal", "EndEvent_Refused"),
        F("Gateway_Approved", "Task_CommandOutage", "Да", "заявка разрешена"),
        F("Task_CommandOutage", "Task_Switching"),
        F("Task_Switching", "Task_PrepareWorkplace"),
        F("Task_PrepareWorkplace", "Gateway_WorksMerge"),
        F("Gateway_WorksMerge", "Task_RepairWorks"),
        F("Task_RepairWorks", "Gateway_InTime"),
        F("Gateway_InTime", "Task_ExtendRequest", "Нет", "срок не выдерживается"),
        F("Task_ExtendRequest", "Task_ApproveExtension"),
        F("Task_ApproveExtension", "Gateway_WorksMerge"),
        F("Gateway_InTime", "Task_ReportReady", "Да", "работы завершены в срок"),
        F("Task_ReportReady", "Task_CommandReturn"),
        F("Task_CommandReturn", "Task_ReturnToService"),
        F("Task_ReturnToService", "EndEvent_InService"),
    ],
    examples=["repair-outage/output/diagram.bpmn"],
)

# --- Наряд-допуск ------------------------------------------------------------------------------

IS, AD, FR = "Lane_Issuer", "Lane_Admitter", "Lane_Foreman"
WORK_PERMIT = Diagram(
    key="work_permit",
    participant="Работы в электроустановке по наряду-допуску",
    lanes=[(IS, "Выдающий наряд"), (AD, "Допускающий"), (FR, "Производитель работ")],
    nodes=[
        N("StartEvent_Need", "start", "Работы запланированы", IS),
        N("Task_IssuePermit", "user", "Выписать наряд-допуск и меры безопасности", IS),
        N("Gateway_PrepFork", "and", "", AD),
        N("Task_Disconnect", "manual", "Выполнить отключения и заземление", AD),
        N("Task_CheckCrew", "user", "Проверить состав бригады и средства защиты", FR),
        N("Gateway_PrepJoin", "and", "", AD),
        N("Gateway_CheckMerge", "xor", "", AD),
        N("Task_CheckWorkplace", "user", "Проверить подготовку рабочего места", AD),
        N("Gateway_WorkplaceReady", "xor", "Рабочее место готово?", AD),
        N("Task_FixRemarks", "manual", "Устранить замечания", AD),
        N("Task_Briefing", "user", "Провести целевой инструктаж и допуск", AD),
        N("Task_DoWork", "manual", "Выполнить работы", FR),
        N("Task_ClearWorkplace", "manual", "Убрать рабочее место и вывести бригаду", FR),
        N("Task_ClosePermit", "user", "Закрыть наряд-допуск", AD),
        N("EndEvent_Closed", "end", "Наряд закрыт", AD),
    ],
    flows=[
        F("StartEvent_Need", "Task_IssuePermit"),
        F("Task_IssuePermit", "Gateway_PrepFork"),
        F("Gateway_PrepFork", "Task_Disconnect"),
        F("Gateway_PrepFork", "Task_CheckCrew"),
        F("Task_Disconnect", "Gateway_PrepJoin"),
        F("Task_CheckCrew", "Gateway_PrepJoin"),
        F("Gateway_PrepJoin", "Gateway_CheckMerge"),
        F("Gateway_CheckMerge", "Task_CheckWorkplace"),
        F("Task_CheckWorkplace", "Gateway_WorkplaceReady"),
        F("Gateway_WorkplaceReady", "Task_FixRemarks", "Нет", "есть замечания"),
        F("Task_FixRemarks", "Gateway_CheckMerge"),
        F("Gateway_WorkplaceReady", "Task_Briefing", "Да", "замечаний нет"),
        F("Task_Briefing", "Task_DoWork"),
        F("Task_DoWork", "Task_ClearWorkplace"),
        F("Task_ClearWorkplace", "Task_ClosePermit"),
        F("Task_ClosePermit", "EndEvent_Closed"),
    ],
    examples=["work-permit/output/diagram.bpmn"],
)

# --- Закупка по 223-ФЗ -------------------------------------------------------------------------

IN, PR, CM = "Lane_Initiator", "Lane_Procurement", "Lane_Commission"
PROCUREMENT = Diagram(
    key="procurement_223",
    participant="Закупка способом запроса котировок",
    lanes=[(IN, "Инициатор закупки"), (PR, "Отдел закупок"), (CM, "Закупочная комиссия")],
    nodes=[
        N("StartEvent_Need", "start", "Возникла потребность", IN),
        N("Task_Request", "user", "Сформировать заявку и техническое задание", IN),
        N("Task_CheckPlan", "user", "Проверить наличие в плане закупок", PR),
        N("Gateway_InPlan", "xor", "Закупка есть в плане?", PR),
        N("Task_AmendPlan", "user", "Внести изменения в план закупок", PR),
        N("Gateway_PlanMerge", "xor", "", PR),
        N("Task_Publish", "send", "Разместить извещение в ЕИС", PR),
        N("Task_CollectBids", "receive", "Принять заявки участников", PR),
        N("Task_Evaluate", "user", "Рассмотреть и оценить заявки", CM),
        N("Gateway_HasBids", "xor", "Есть допущенные заявки?", CM),
        N("Task_Failed", "user", "Закрыть закупку без договора", CM),
        N("EndEvent_Failed", "end", "Закупка не состоялась", CM),
        N("Task_Protocol", "user", "Подписать итоговый протокол", CM),
        N("Task_Contract", "user", "Заключить договор с победителем", PR),
        N("EndEvent_Contract", "end", "Договор заключён", PR),
    ],
    flows=[
        F("StartEvent_Need", "Task_Request"),
        F("Task_Request", "Task_CheckPlan"),
        F("Task_CheckPlan", "Gateway_InPlan"),
        F("Gateway_InPlan", "Task_AmendPlan", "Нет", "закупки нет в плане"),
        F("Gateway_InPlan", "Gateway_PlanMerge", "Да", "закупка есть в плане"),
        F("Task_AmendPlan", "Gateway_PlanMerge"),
        F("Gateway_PlanMerge", "Task_Publish"),
        F("Task_Publish", "Task_CollectBids"),
        F("Task_CollectBids", "Task_Evaluate"),
        F("Task_Evaluate", "Gateway_HasBids"),
        F("Gateway_HasBids", "Task_Failed", "Нет", "допущенных заявок нет"),
        F("Task_Failed", "EndEvent_Failed"),
        F("Gateway_HasBids", "Task_Protocol", "Да", "есть допущенные заявки"),
        F("Task_Protocol", "Task_Contract"),
        F("Task_Contract", "EndEvent_Contract"),
    ],
)

# --- Договор энергоснабжения -------------------------------------------------------------------

CO, SU, GR = "Lane_Consumer", "Lane_Supplier", "Lane_Grid"
SUPPLY = Diagram(
    key="supply_contract",
    participant="Заключение договора энергоснабжения",
    lanes=[(CO, "Потребитель"), (SU, "Гарантирующий поставщик"), (GR, "Сетевая организация")],
    nodes=[
        N("StartEvent_Need", "start", "Обращение потребителя", CO),
        N("Task_Submit", "send", "Подать заявление и документы", CO),
        N("Gateway_CheckMerge", "xor", "", SU),
        N("Task_CheckDocs", "user", "Проверить комплект документов", SU),
        N("Gateway_DocsOk", "xor", "Комплект полный?", SU),
        N("Task_RequestDocs", "send", "Запросить недостающие документы", SU),
        N("Task_ProvideDocs", "user", "Представить документы", CO),
        N("Gateway_Fork", "and", "", SU),
        N("Task_RequestGrid", "send", "Запросить у сети документы о ТП", SU),
        N("Task_ConfirmGrid", "user", "Подтвердить документы о ТП и учёте", GR),
        N("Task_PrepareDraft", "user", "Подготовить проект договора", SU),
        N("Gateway_Join", "and", "", SU),
        N("Task_SendDraft", "send", "Направить договор потребителю", SU),
        N("Task_Sign", "user", "Подписать договор", CO),
        N("EndEvent_Signed", "end", "Договор заключён", CO),
    ],
    flows=[
        F("StartEvent_Need", "Task_Submit"),
        F("Task_Submit", "Gateway_CheckMerge"),
        F("Gateway_CheckMerge", "Task_CheckDocs"),
        F("Task_CheckDocs", "Gateway_DocsOk"),
        F("Gateway_DocsOk", "Task_RequestDocs", "Нет", "документов не хватает"),
        F("Task_RequestDocs", "Task_ProvideDocs"),
        F("Task_ProvideDocs", "Gateway_CheckMerge"),
        F("Gateway_DocsOk", "Gateway_Fork", "Да", "комплект полный"),
        F("Gateway_Fork", "Task_RequestGrid"),
        F("Gateway_Fork", "Task_PrepareDraft"),
        F("Task_RequestGrid", "Task_ConfirmGrid"),
        F("Task_ConfirmGrid", "Gateway_Join"),
        F("Task_PrepareDraft", "Gateway_Join"),
        F("Gateway_Join", "Task_SendDraft"),
        F("Task_SendDraft", "Task_Sign"),
        F("Task_Sign", "EndEvent_Signed"),
    ],
    reroute=["Flow_RequestDocs_ProvideDocs"],
)

DIAGRAMS = [tp861(1), tp861(2), tp861(3), REPAIR, WORK_PERMIT, PROCUREMENT, SUPPLY]

# Исходные тексты примеров → examples/<пример>/input/
EXAMPLE_INPUTS = {
    "tp861/input/regulation.md": "tp861_regulation.md",
    "tp861/input/meeting-note.txt": "tp861_meeting_note.txt",
    "tp861/input/project-finances.md": "tp861_finances.md",
    "repair-outage/input/regulation.md": "repair_outage.md",
    "work-permit/input/regulation.md": "work_permit.md",
}


def _flow_id(flow: F) -> str:
    def short(node_id: str) -> str:
        return node_id.split("_", 1)[-1]

    return f"Flow_{short(flow.source)}_{short(flow.target)}"


def semantic_xml(diagram: Diagram) -> str:
    """Семантическая часть BPMN без координат: их добавит bpmn-auto-layout."""
    ids = [n.id for n in diagram.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{diagram.key}: повторяются id узлов")
    for flow in diagram.flows:
        if flow.source not in ids or flow.target not in ids:
            raise ValueError(f"{diagram.key}: поток {flow} ссылается на несуществующий узел")

    key = diagram.key
    root = Element(
        f"{{{BPMN}}}definitions",
        {
            "id": f"Definitions_{key}",
            "targetNamespace": "http://arkhitektor.local/bpmn",
            "exporter": "Архитектор BPMN-диаграмм",
            "exporterVersion": "0.1.0",
        },
    )
    collaboration = SubElement(root, f"{{{BPMN}}}collaboration", {"id": f"Collaboration_{key}"})
    SubElement(
        collaboration,
        f"{{{BPMN}}}participant",
        {"id": f"Participant_{key}", "name": diagram.participant, "processRef": f"Process_{key}"},
    )
    process = SubElement(
        root, f"{{{BPMN}}}process", {"id": f"Process_{key}", "isExecutable": "false"}
    )
    lane_set = SubElement(process, f"{{{BPMN}}}laneSet", {"id": f"LaneSet_{key}"})
    for lane_id, lane_name in diagram.lanes:
        lane = SubElement(lane_set, f"{{{BPMN}}}lane", {"id": lane_id, "name": lane_name})
        for node in diagram.nodes:
            if node.lane == lane_id:
                SubElement(lane, f"{{{BPMN}}}flowNodeRef").text = node.id

    _add_nodes(process, diagram)
    _add_flows(process, diagram)

    indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode") + "\n"


def _add_nodes(process: Element, diagram: Diagram) -> None:
    for node in diagram.nodes:
        attrs = {"id": node.id}
        if node.name:
            attrs["name"] = node.name
        element = SubElement(process, f"{{{BPMN}}}{TAGS[node.kind]}", attrs)
        for flow in diagram.flows:
            if flow.target == node.id:
                SubElement(element, f"{{{BPMN}}}incoming").text = _flow_id(flow)
        for flow in diagram.flows:
            if flow.source == node.id:
                SubElement(element, f"{{{BPMN}}}outgoing").text = _flow_id(flow)


def _add_flows(process: Element, diagram: Diagram) -> None:
    for flow in diagram.flows:
        attrs = {"id": _flow_id(flow), "sourceRef": flow.source, "targetRef": flow.target}
        if flow.name:
            attrs["name"] = flow.name
        element = SubElement(process, f"{{{BPMN}}}sequenceFlow", attrs)
        if flow.condition:
            condition = SubElement(
                element,
                f"{{{BPMN}}}conditionExpression",
                {f"{{{XSI}}}type": "bpmn:tFormalExpression"},
            )
            condition.text = flow.condition


def layout(xml: str, workdir: Path, key: str) -> str:
    source = workdir / f"{key}.semantic.bpmn"
    source.write_text(xml, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 — фиксированная команда, без shell
        [*LAYOUT, str(source), "--stdout"], capture_output=True, text=True, check=True
    )
    if result.stderr.strip():
        print(f"  {key}: предупреждения раскладки:\n{result.stderr}", file=sys.stderr)
    return result.stdout if result.stdout.endswith("\n") else result.stdout + "\n"


def reroute(xml: str, flow_ids: list[str]) -> str:
    """Короткий маршрут для потоков, которые раскладчик увёл в обход дорожки."""
    if not flow_ids:
        return xml
    ns = {
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        "bpmn": BPMN,
    }
    tree = etree.fromstring(xml.encode("utf-8"))

    def bounds(element_id: str) -> tuple[float, float, float, float]:
        found = tree.find(f".//bpmndi:BPMNShape[@bpmnElement='{element_id}']/dc:Bounds", ns)
        if found is None:
            raise ValueError(f"нет фигуры {element_id}")
        return tuple(float(found.get(k)) for k in ("x", "y", "width", "height"))  # type: ignore[return-value]

    for flow_id in flow_ids:
        flow = tree.find(f".//bpmn:sequenceFlow[@id='{flow_id}']", ns)
        edge = tree.find(f".//bpmndi:BPMNEdge[@bpmnElement='{flow_id}']", ns)
        if flow is None or edge is None:
            raise ValueError(f"нет потока {flow_id}")
        sx, sy, sw, sh = bounds(flow.get("sourceRef"))
        tx, ty, _, th = bounds(flow.get("targetRef"))
        start, end = (sx + sw, sy + sh / 2), (tx, ty + th / 2)
        middle = round((start[0] + end[0]) / 2)
        for waypoint in edge.findall("di:waypoint", ns):
            edge.remove(waypoint)
        for x, y in (start, (middle, start[1]), (middle, end[1]), end):
            waypoint = etree.SubElement(edge, f"{{{ns['di']}}}waypoint")
            waypoint.set("x", str(round(x)))
            waypoint.set("y", str(round(y)))
    etree.indent(tree, space="  ")
    body = etree.tostring(tree, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def check_xsd(path: Path) -> None:
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    document = etree.parse(str(path))
    if not schema.validate(document):
        raise SystemExit(f"XSD: {path.name}: {schema.error_log}")


def check_lint(paths: list[Path], workdir: Path) -> None:
    config = workdir / ".bpmnlintrc"
    config.write_text(json.dumps({"extends": "bpmnlint:recommended"}), encoding="utf-8")
    for path in paths:
        result = subprocess.run(  # noqa: S603 — фиксированная команда, без shell
            [*LINT, "--config", str(config), str(path)], capture_output=True, text=True, check=False
        )
        lines = [line.split() for line in result.stdout.splitlines() if line.strip()]
        issues = [
            (parts[0], parts[1], parts[-1])
            for parts in lines
            if parts[1:2] in (["error"], ["warning"])
        ]
        errors = [issue for issue in issues if issue[1] == "error"]
        unexpected = [
            issue
            for issue in issues
            if issue[1] == "warning" and (path.stem, issue[2], issue[0]) not in EXPECTED_WARNINGS
        ]
        if errors or unexpected or (result.returncode != 0 and not issues):
            raise SystemExit(f"bpmnlint: {path.name}:\n{result.stdout}{result.stderr}")
        warnings = [f"{issue[2]} ({issue[0]})" for issue in issues]
        print(
            f"  {path.name}: XSD ok, bpmnlint ok"
            + (f", предупреждения: {warnings}" if warnings else "")
        )


def write_docx(text: str, target: Path) -> None:
    """Минимальный настоящий .docx (OOXML) без сторонних библиотек: абзац на строку.

    Без сжатия: результат zlib зависит от версии библиотеки, а файл коммитится и сверяется тестом.
    """
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in text.splitlines()
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for name, body in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 29, 12, 0, 0))
            archive.writestr(info, body, compress_type=zipfile.ZIP_STORED)


def sample_files() -> dict[str, bytes]:
    """Учебные материалы («Примеры», `app/fixtures/samples.py`): имя файла → содержимое.

    Тур: `.docx` — записка со встречи и дополнение с намеренными пробелами в процессе
    (по ним модель стабильно задаёт 2–4 вопроса); остальные материалы — копии текстов.
    """

    def text(name: str) -> str:
        return (TEXTS / name).read_text(encoding="utf-8").strip()

    with tempfile.TemporaryDirectory() as tmp:
        docx = Path(tmp) / "note.docx"
        write_docx(
            "\n".join(
                [
                    "Записка со встречи — техприсоединение",
                    text("tp861_meeting_note.txt"),
                    text("tour_note_addendum.txt"),
                ]
            ),
            docx,
        )
        docx_bytes = docx.read_bytes()
    return {
        "tp861-meeting-note.docx": docx_bytes,
        "repair-outage.md": (text("repair_outage.md") + "\n").encode("utf-8"),
        "work-permit.txt": (text("work_permit.md") + "\n").encode("utf-8"),
    }


def build_samples(*, check: bool = False) -> None:
    """Записывает материалы в `samples/`; с `check` — только сверяет с готовыми файлами."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for name, content in sample_files().items():
        target = SAMPLES / name
        if check:
            if not target.exists() or target.read_bytes() != content:
                sys.exit(f"{target.relative_to(ROOT)} устарел: запустите make fixtures")
        else:
            target.write_bytes(content)
    print(f"Учебные материалы: {len(sample_files())} файла в {SAMPLES.relative_to(ROOT)}")


def copy_examples() -> None:
    for relative, text_name in EXAMPLE_INPUTS.items():
        target = EXAMPLES / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEXTS / text_name, target)
    write_docx(
        (TEXTS / "tp861_finances.md").read_text(encoding="utf-8"),
        EXAMPLES / "tp861" / "input" / "project-finances.docx",
    )
    for diagram in DIAGRAMS:
        for relative in diagram.examples:
            target = EXAMPLES / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BPMN_DIR / f"{diagram.key}.bpmn", target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="только проверить готовые файлы")
    parser.add_argument(
        "--samples", action="store_true", help="только учебные материалы (без Node и раскладки)"
    )
    args = parser.parse_args()

    if args.samples:
        build_samples(check=args.check)
        return

    BPMN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        if not args.check:
            for diagram in DIAGRAMS:
                print(f"Раскладка {diagram.key}…")
                xml = reroute(layout(semantic_xml(diagram), workdir, diagram.key), diagram.reroute)
                (BPMN_DIR / f"{diagram.key}.bpmn").write_text(xml, encoding="utf-8")
        paths = [BPMN_DIR / f"{diagram.key}.bpmn" for diagram in DIAGRAMS]
        for path in paths:
            check_xsd(path)
        check_lint(paths, workdir)
    build_samples(check=args.check)
    if not args.check:
        copy_examples()
        print(f"Готово: {len(DIAGRAMS)} схем в {BPMN_DIR.relative_to(ROOT)}, примеры в examples/")


if __name__ == "__main__":
    main()
