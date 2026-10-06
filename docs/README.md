# Документация

- [Архитектура и API](rfc/0001-architecture.md)
- [Совместная работа в реальном времени](rfc/0002-realtime-collaboration.md)
- [Воспроизведение BPMN и модель бизнес-времени](rfc/0003-process-playback-and-timing.md)
- Backend:
  - [Аккаунты и общий доступ к проектам](backend/auth-and-sharing.md)
  - [Постоянное хранение данных](backend/persistence.md)
  - [Онбординг: тур, чек-лист, учебные материалы](backend/onboarding.md)
  - [Что ещё заглушено и что нужно для настоящей реализации](backend/mock.md)
  - [Настройка LLM и распознавания речи](backend/подключение-провайдеров.md)
- [Frontend: принципы и устройство](frontend/README.md)
- [Деплой на VM](deployment.md)
- ADR:
  - [Cookie-сессии и роли доступа к проектам](adr/0001-auth-and-project-sharing.md)
  - [Ограничение частоты запросов и Secure-cookie](adr/0002-rate-limits-and-secure-cookies.md)
  - [Присутствие и история версий](adr/0003-presence-and-version-history.md)
  - [Realtime-комнаты и защита от конфликтных сохранений](adr/0004-realtime-collaboration.md)
  - [Локальное воспроизведение и отдельная модель длительностей](adr/0005-process-playback.md)
