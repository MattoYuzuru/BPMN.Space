"""Интерфейс LLM-пайплайна (RFC §5.1): два шага — «анализ» и «структура».

Сейчас его реализует `mock.py` (записанные ответы из `app/fixtures/playbook.py`).
TODO(real): #5 Pydantic AI-агенты поверх OpenAI-совместимого API (`agents.py`), фабрика
провайдеров из config.py (`providers.py`, LLM_BASE_URL / LLM_MODEL / LLM_OUTPUT_MODE),
промпты и few-shot в `prompts/`. «Структура» возвращает IR, который компилирует
`domain/compiler.py` (IR → ProcessGraph → XML) с repair-циклом до 3 кругов (RFC §5.3–5.4).
Логи вызовов модели — таблица `llm_call` (#6).
"""

from typing import Protocol

from app.domain.analysis import AnalysisResult, DiagramDraft, RunContext


class PipelineError(Exception):
    """Модель не справилась (после repair-кругов). Сообщение — для пользователя."""


class ProcessPipeline(Protocol):
    @property
    def model_name(self) -> str: ...

    async def analyze(self, context: RunContext) -> AnalysisResult:
        """Участники, шаги, условия → обновления прежних вопросов и новые вопросы."""
        ...

    async def structure(self, context: RunContext, analysis: AnalysisResult) -> DiagramDraft:
        """Схема процесса с координатами и трассировкой «элемент → цитата»."""
        ...
