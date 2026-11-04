# Каталог провайдеров для ключей пользователя

- Дата: 2026-11-04
- Статус: черновой список для [RFC-0006](../rfc/0006-tools-connectors-and-derived-sources.md),
  ссылки и условия **не перепроверены**
- Назначение: подсказки «Где взять ключ» в настройках и выбор первых адаптеров

Бесплатные уровни, стартовые кредиты и цены меняются часто. В интерфейс они попадают из
данных в коде с датой проверки, а не из этого файла. Перед реализацией адаптера откройте страницу
провайдера и обновите строку.

Колонка «РФ» отмечает провайдеров с размещением данных в России: это важно для записей
совещаний энергокомпании (см. «Конфиденциальность» в RFC-0006).

## Модели (LLM)

| Провайдер | Где взять ключ | Что закрывает | Заметки |
|---|---|---|---|
| Anthropic (Claude) | https://platform.claude.com/settings/keys | LLM, vision, PDF, `web_search`, `web_fetch`, `code_execution` | окно 1M у Opus/Sonnet/Haiku 5.5; `count_tokens` бесплатно; Batch API −50% |
| OpenAI | https://platform.openai.com/api-keys | LLM, vision, распознавание речи, TTS | у рассуждающих моделей нет `temperature` |
| Google AI Studio (Gemini) | https://aistudio.google.com/apikey | LLM, vision, **видео целиком**, аудио | кандидат для `video_understanding` |
| DeepSeek | https://platform.deepseek.com/api_keys | LLM | совместимый API, уже поддержан |
| OpenRouter | https://openrouter.ai/settings/keys | LLM многих провайдеров | совместимый API |
| Yandex Cloud (YandexGPT) | https://console.yandex.cloud | LLM | РФ |

## Распознавание речи

| Провайдер | Где взять ключ | Таймкоды | Говорящие | Заметки |
|---|---|---|---|---|
| Deepgram | https://console.deepgram.com | да | да | уже поддержан; стартовый кредит |
| AssemblyAI | https://www.assemblyai.com/dashboard | да | да | длинные файлы по URL |
| OpenAI (transcribe) | https://platform.openai.com/api-keys | да | зависит от модели | тот же ключ, что LLM |
| Groq (Whisper) | https://console.groq.com/keys | да | нет | быстро и дёшево, есть бесплатный уровень |
| ElevenLabs (Scribe) | https://elevenlabs.io/app/settings/api-keys | да | да | тот же ключ даёт TTS |
| Yandex SpeechKit | https://console.yandex.cloud | да | да | РФ |

## OCR и чтение документов

| Провайдер | Где взять ключ | Заметки |
|---|---|---|
| Claude (PDF и изображения) | ключ Anthropic | PDF до 600 страниц и 32 МБ на запрос; дороже специализированного OCR на больших сканах |
| Mistral OCR | https://console.mistral.ai/api-keys | документ в markdown с таблицами |
| Yandex Vision OCR | https://console.yandex.cloud | РФ, хорошо с русским |
| Google Document AI | https://console.cloud.google.com | формы и таблицы |
| Azure Document Intelligence | https://portal.azure.com | формы и таблицы |

## Понимание видео

| Провайдер | Где взять ключ | Заметки |
|---|---|---|
| Gemini | https://aistudio.google.com/apikey | видео на вход целиком, ответ с таймкодами |
| Twelve Labs | https://playground.twelvelabs.io | индексация и поиск по видео |
| Без отдельного ключа | — | кадры через ffmpeg + `vision` любой модели (RFC-0006, «Видео») |

## Веб-поиск и чтение страниц

| Провайдер | Где взять ключ | Что закрывает | Заметки |
|---|---|---|---|
| Claude `web_search` / `web_fetch` | ключ Anthropic | поиск и чтение | оплата за поиск; `web_fetch` читает только адреса, уже появившиеся в разговоре |
| Exa | https://dashboard.exa.ai/api-keys | поиск по смыслу, содержимое страниц | стартовые кредиты |
| Tavily | https://app.tavily.com | поиск для агентов | бесплатный месячный лимит |
| Brave Search API | https://api-dashboard.search.brave.com | поиск | собственный индекс |
| Jina Reader | https://jina.ai/reader | страница → текст | работает и без ключа с низким лимитом |
| Firecrawl | https://www.firecrawl.dev/app/api-keys | обход сайта, страница → markdown | |

Закрытые страницы (Confluence, порталы за логином) этим списком не закрываются: только через
агента пользователя ([RFC-0007](../rfc/0007-external-agents-mcp.md)).

## Синтез речи (низкий приоритет)

| Провайдер | Где взять ключ |
|---|---|
| ElevenLabs | https://elevenlabs.io/app/settings/api-keys |
| OpenAI TTS | https://platform.openai.com/api-keys |
| Yandex SpeechKit | https://console.yandex.cloud |
