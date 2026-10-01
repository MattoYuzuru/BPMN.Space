# Frontend: сборка Vite в node, раздача статики и прокси /api через Caddy.
# Контекст сборки — корень репозитория (npm workspaces + docs/api для контракта).
FROM node:24-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/
RUN npm ci --workspace frontend --ignore-scripts --no-audit --no-fund
COPY frontend frontend
RUN npm run build --workspace frontend

FROM caddy:2-alpine
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /repo/frontend/dist /srv
