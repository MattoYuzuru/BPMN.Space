# Единая точка входа для людей, агентов и git-хуков. Описание целей: `make help`.
# Все проверки идут по всему репозиторию: правка бэкенда проверяет и фронтенд, и контракт между ними.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV := uv run --directory backend
NPM_FRONT := npm run --workspace frontend

.PHONY: help setup up down logs dev-backend dev-frontend \
        format lint typecheck design-lint check-fast test test-backend test-frontend \
        build contract-check openapi gen-api check e2e screenshots secrets verify mr-report

help: ## Список команд
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Установить зависимости, браузер для e2e и git-хуки
	npm ci
	cd backend && uv sync --frozen
	npx --workspace frontend playwright install chromium

up: ## Поднять стек в Docker: http://localhost:8080
	docker compose up -d --build --wait

down: ## Остановить стек
	docker compose down

logs: ## Логи стека
	docker compose logs -f --tail=100

dev-backend: ## Backend с автоперезагрузкой на :8000
	$(UV) uvicorn app.main:app --reload --port 8000

dev-frontend: ## Frontend dev-сервер на :5173 (проксирует /api на :8000)
	$(NPM_FRONT) dev

format: ## Автоформатирование всего кода
	npx biome check --write .
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint: ## Линтеры без исправлений
	npx biome check .
	$(UV) ruff format --check .
	$(UV) ruff check .
	$(UV) lint-imports

design-lint: ## Правила дизайн-системы (docs/frontend/styleguide.md)
	$(NPM_FRONT) lint:design

typecheck: ## Типы фронтенда и бэкенда
	$(NPM_FRONT) typecheck
	npx pyright

check-fast: lint design-lint typecheck ## Быстрые проверки (агенты запускают после правок)

test-backend: ## pytest с покрытием ≥80%
	$(UV) pytest --cov --cov-report=term-missing:skip-covered

test-frontend: ## vitest
	$(NPM_FRONT) test

test: test-backend test-frontend ## Все unit- и интеграционные тесты

build: ## Production-сборка фронтенда
	$(NPM_FRONT) build

openapi: ## Выгрузить OpenAPI из backend в docs/api/openapi.json
	$(UV) python -m app.openapi_export > docs/api/openapi.json

gen-api: openapi ## OpenAPI + TS-типы фронтенда
	$(NPM_FRONT) gen:api

contract-check: ## Контракт API: backend ↔ docs/api/openapi.json ↔ TS-типы
	scripts/contract-check.sh

check: check-fast test contract-check build ## Полная проверка (pre-push)

e2e: ## e2e Playwright против стека в Docker
	docker compose up -d --build --wait
	$(NPM_FRONT) e2e

screenshots: ## Скриншоты ключевых экранов в reports/screenshots
	docker compose up -d --build --wait
	$(NPM_FRONT) e2e -- --project=screenshots

secrets: ## Поиск секретов во всех файлах
	npx secretlint --maskSecrets "**/*"

verify: ## Всё + e2e + отчёт reports/verify-<sha>.md (перед MR)
	scripts/verify.sh

mr-report: ## Опубликовать отчёт verify комментарием в MR текущей ветки
	scripts/mr-report.sh
