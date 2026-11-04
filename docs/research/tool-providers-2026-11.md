# Каталог провайдеров для ключей пользователя

- Дата: 2026-11-04
- Статус: проверено 04.11.2026 по страницам провайдеров и справке; цены и бесплатные уровни
  меняются, перед реализацией адаптера строку перепроверяйте
- Назначение: подсказки «Где взять ключ» в настройках и выбор первых адаптеров
  ([RFC-0006](../rfc/0006-tools-connectors-and-derived-sources.md))

В интерфейс подсказки попадают из данных в коде с датой проверки, а не из этого файла. Каталог
в коде не хранится: это отдельная задача интерфейса.

## Геоограничения и конфиденциальность

Это важнее цен. **Anthropic, OpenAI и Google Gemini официально не поддерживают Россию**
([Anthropic: supported countries](https://www.anthropic.com/supported-countries),
[OpenAI: supported countries](https://help.openai.com/en/articles/5347006-openai-api-supported-countries-and-territories),
[Gemini API: available regions](https://ai.google.dev/gemini-api/docs/available-regions)). Страницы
ключей Anthropic и OpenAI из РФ отдают «App unavailable». DeepSeek и Yandex Cloud из РФ работают.

Отсюда правило продукта: для записей совещаний с персональными данными основной выбор —
**Yandex Cloud** (размещение в РФ, 152-ФЗ); запись, уходящая в Anthropic/OpenAI/Google,
становится трансграничной передачей и требует законного основания у оператора. В настройках рядом
с такими ключами нужно предупреждение о конфиденциальности, а не только «где взять ключ».

Колонка «РФ» отмечает провайдеров с размещением данных в России.

## Модели (LLM)

| Провайдер | Где взять ключ | Что закрывает | Заметки |
|---|---|---|---|
| Anthropic (Claude) | https://platform.claude.com/settings/keys | LLM, vision, PDF, `web_search`, `web_fetch`, `code_execution` | РФ не поддержана. Окно 1M у Opus/Sonnet/Haiku 5.5; `count_tokens` бесплатно; Batch API −50%; кеш промпта 0.1×; `web_search` $10 за 1000 поисков |
| OpenAI | https://platform.openai.com/settings/organization/api-keys | LLM, vision, распознавание речи, TTS | РФ не поддержана. Ссылка на страницу ключей не подтверждена фетчером; у рассуждающих моделей нет `temperature` |
| Google AI Studio (Gemini) | https://aistudio.google.com/apikey | LLM, vision, видео целиком, аудио, TTS, поиск | РФ не поддержана; бесплатный уровень учит на данных. File API: 20 ГБ платно / 2 ГБ бесплатно; видео до 3 ч low res, до 1 ч high res |
| DeepSeek | https://platform.deepseek.com/api_keys | LLM, vision у flash | Страница ключей отдаёт 403 фетчеру — **не подтверждено**. 1M контекст; встроенные search/fetch $0,75/1000; $0,15–0,30 вход / $0,60–1,20 выход за 1M |
| OpenRouter | https://openrouter.ai/settings/keys | LLM многих провайдеров | Совместимый API, уже поддержан |
| Yandex Cloud (YandexGPT) | https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key | LLM | **РФ.** Нужен сервисный аккаунт → API-ключ (не IAM-токен); грант от 4000 ₽ на 60 дней |

## Распознавание речи

| Провайдер | Где взять ключ | Таймкоды | Говорящие | Заметки |
|---|---|---|---|---|
| Deepgram | https://console.deepgram.com | да | да | Уже поддержан. $200 стартовых без карты; Nova-3 $0,0077/мин, диаризация +$0,002/мин; файл до 2 ГБ; после ~10 мин приходит 504 — нужен callback; есть EU-эндпоинт |
| AssemblyAI | https://www.assemblyai.com/dashboard | да | да | $50 без карты; Universal-2 $0,15/ч, русский есть, диаризация +$0,02/ч; принимает **только по URL**, не файлом |
| OpenAI (transcribe) | https://platform.openai.com/settings/organization/api-keys | да | зависит от модели | РФ не поддержана; тот же ключ, что LLM |
| Groq (Whisper) | https://console.groq.com/keys | да | нет | Whisper turbo $0,04/ч; бесплатно 20 RPM / 2000 запросов в день; файл до 100 МБ; диаризации нет |
| ElevenLabs (Scribe) | https://elevenlabs.io/app/settings/api-keys | да | да | Scribe v2 $0,22/ч; тот же ключ даёт TTS |
| Yandex SpeechKit | https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key | да | да | **РФ.** Асинхронное распознавание до 4 ч / 1 ГБ; грант от 4000 ₽ на 60 дней |

## OCR и чтение документов

| Провайдер | Где взять ключ | Заметки |
|---|---|---|
| Claude (PDF и изображения) | https://platform.claude.com/settings/keys | PDF до 600 страниц и 32 МБ на запрос; дороже специализированного OCR на больших сканах |
| Mistral OCR | https://console.mistral.ai/api-keys | OCR 4.1: $4 за 1000 страниц ($5 с аннотациями), 40+ языков, таблицы — markdown |
| Yandex Vision OCR | https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key | **РФ**, хорошо с русским; 0,13–1,52 ₽ за страницу |
| Google Document AI | https://console.cloud.google.com/ai/document-ai | Не проверялось: ссылка ведёт на создание processor, тарифы смотреть в консоли |
| Azure Document Intelligence | https://portal.azure.com | Не проверялось: нужен ресурс Document Intelligence, тарифы меняются |

## Понимание видео

| Провайдер | Где взять ключ | Заметки |
|---|---|---|
| Gemini | https://aistudio.google.com/apikey | Видео на вход целиком, ответ с таймкодами; File API 20 ГБ платно / 2 ГБ бесплатно; до 3 ч low res, до 1 ч high res; РФ не поддержана |
| Twelve Labs | https://playground.twelvelabs.io | Индексация и поиск по видео; тарифы меняются 04.01.2027, бесплатные лимиты не подтверждены |
| Без отдельного ключа | — | Кадры через ffmpeg + `vision` любой модели (RFC-0006, «Видео») |

## Веб-поиск и чтение страниц

| Провайдер | Где взять ключ | Что закрывает | Заметки |
|---|---|---|---|
| Claude `web_search` / `web_fetch` | https://platform.claude.com/settings/keys | поиск и чтение | $10 за 1000 поисков; `web_fetch` читает только адреса, уже появившиеся в разговоре |
| Exa | https://dashboard.exa.ai/api-keys | поиск по смыслу, содержимое страниц | $20 стартовых кредитов и $10/мес |
| Tavily | https://app.tavily.com | поиск для агентов | 1000 кредитов/мес без карты; $0,008 за кредит сверх |
| Brave Search API | https://api-dashboard.search.brave.com | поиск | $5 кредитов/мес, карта обязательна; $5 за 1000 запросов; собственный индекс. Google CSE закрывается 01.01.2027 |
| Jina Reader | https://jina.ai/reader | страница → текст | Без ключа 20 RPM; с ключом 500 RPM / 10M токенов бесплатно |
| Firecrawl | https://www.firecrawl.dev/app/api-keys | обход сайта, страница → markdown | 1000 кредитов/мес без карты |

Закрытые страницы (Confluence, порталы за логином) этим списком не закрываются: только через
агента пользователя ([RFC-0007](../rfc/0007-external-agents-mcp.md)).

## Синтез речи (низкий приоритет)

| Провайдер | Где взять ключ | Заметки |
|---|---|---|
| ElevenLabs | https://elevenlabs.io/app/settings/api-keys | Тот же ключ, что Scribe |
| OpenAI TTS | https://platform.openai.com/settings/organization/api-keys | РФ не поддержана |
| Yandex SpeechKit | https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key | **РФ** |

## Что уже поддержано в коде (2026-11-04)

- **LLM:** Anthropic, OpenAI, OpenAI-совместимые (`openai_compatible`), модели и ключи из
  [ADR-0011](../adr/0011-user-llm-credentials.md). Ключ модели можно добавить и как общий ключ с
  типами `llm` и, например, `speech_to_text` — одна строка `user_credentials`.
- **Распознавание речи:** Deepgram, OpenAI, Groq, OpenAI-совместимый сервер с `/audio/transcriptions`
  (`backend/app/ingest/adapters/`). Выбор — маршрутизатор по ключам пользователя, серверный
  `STT_PROVIDER` остаётся запасным путём.
- **Заготовки контрактов:** `vision`, `ocr`, `video_understanding`, `web_search`, `web_fetch`, `tts`
  описаны интерфейсами адаптеров, но ещё не вызываются. Ключи этих типов появятся в настройках
  вместе с адаптерами волны 3.
