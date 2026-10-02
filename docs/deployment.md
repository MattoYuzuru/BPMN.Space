# Деплой на демо-VM

Текущая production-схема — Ubuntu 24.04, Docker Compose, Caddy на порту 80 и FastAPI за внутренней сетью Compose. Деплой отправляет архив проверенного Git-коммита по SSH; VM не нужен доступ к приватному GitLab. GitLab CI/CD не используется.

## Один раз: подготовить VM

1. Установите Ubuntu 24.04 и разрешите входящий TCP 22 и 80 в сетевых правилах Selectel. Порт 8000 наружу не открывайте.
2. Каждый участник создаёт собственную пару SSH-ключей на своём компьютере, например `ssh-keygen -t ed25519 -C "имя-участника" -f ~/.ssh/arkhitektor_deploy`. На VM передаётся только публичный файл `~/.ssh/arkhitektor_deploy.pub`; приватный ключ остаётся у владельца.
3. Скопируйте bootstrap-скрипт на VM и один раз запустите его от `root`:

   ```bash
   scp scripts/bootstrap-vm.sh root@<IP_VM>:/root/bootstrap-vm.sh
   ssh root@<IP_VM> 'bash /root/bootstrap-vm.sh'
   ```

4. Каждый участник отправляет администратору только **публичный** файл `.pub`. Администратор добавляет ключ в аккаунт `deploy`:

   ```bash
   cat ~/.ssh/<имя_публичного_ключа>.pub | ssh root@<IP_VM> 'cat >> /home/deploy/.ssh/authorized_keys && chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 0600 /home/deploy/.ssh/authorized_keys'
   ```

   После настройки проверьте вход: `ssh deploy@<IP_VM>`. Пользователь `deploy` включён в группу `docker`, а значит имеет права уровня root: выдавайте SSH-доступ только доверенным членам команды.

## Один раз: положить секреты на VM

В корне локальной копии создайте `.env` из `.env.example` и добавьте ключи провайдеров. Загрузка отправляет только production-переменные по SSH в `/opt/arkhitektor/shared/.env`, выставляет права `0600` и не сохраняет секреты в релизах или Git.

```bash
DEPLOY_HOST=<IP_VM> scripts/upload-server-env.sh
```

Запускает её один администратор с актуальными ключами. Не пересылайте `.env` команде и не вставляйте значения ключей в команды, issue или сообщения. После загрузки значения не отображаются.

## Каждый релиз

1. Изменения должны попасть в `main` через Merge Request, а локальная копия должна быть чистой и обновлённой.
2. Выполните `make verify`; проверьте отчёт и SHA коммита.
3. Убедитесь, что `DEPLOY_HOST` указывает на VM команды, и выданы права SSH вашему публичному ключу.
4. Запустите с SHA коммита, который уже находится в `origin/main`:

   ```bash
   DEPLOY_HOST=<IP_VM> scripts/deploy.sh <commit-sha>
   ```

Скрипт архивирует коммит из Git, передаёт его по SSH в `/opt/arkhitektor/releases/<sha>`, собирает Compose-образы на VM и переключает `current`. Он ждёт `/health` до двух минут и при ошибке возвращает предыдущий релиз. Секретный `.env` хранится отдельно и не затрагивается. Текущий Compose пока не содержит PostgreSQL и пользовательских файлов, поэтому перед релизом прикладные данные не мигрируются.

## Проверка и восстановление

Откройте `http://<IP_VM>/`, затем проверьте главную страницу, `/health` и тестовые сценарии помощника/голосового ввода. Диагностика на VM:

```bash
ssh deploy@<IP_VM> 'cd /opt/arkhitektor/current && docker compose --env-file /opt/arkhitektor/shared/.env -p arkhitektor -f compose.yaml -f compose.prod.yaml ps'
ssh deploy@<IP_VM> 'cd /opt/arkhitektor/current && docker compose --env-file /opt/arkhitektor/shared/.env -p arkhitektor -f compose.yaml -f compose.prod.yaml logs --tail=100'
```

Порты 80 и 22 открыты, TLS-домен пока не настроен — HTTP подходит только для временного демо/тестирования. Не используйте production-ключи с публичным адресом без ограничений доступа; перед открытым демо добавьте домен, HTTPS и защиту от неавторизованных запросов.
