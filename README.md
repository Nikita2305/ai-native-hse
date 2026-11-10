# AI Native HSE

Самостоятельный набор read-only утилит и навыков для агента студента ВШЭ.
Он даёт доступ к внешним системам и хранит локальную карту **«трек → источники»**.
Треком может быть предмет, практика, диплом или другой поток обязательств.
Решение учебных задач и накопление базы прочитанных материалов в этот каркас не входят.

Чужие настройки, курсы, чаты и секреты в комплект не входят. Доступ к исходному
приватному репозиторию Roots не нужен. Для источника Roots нужен собственный аккаунт
Roots Cloud и токен с необходимой областью доступа.

## Установка

Linux/macOS, Python 3.11+, bash и curl. Базовая установка не требует Node:

```bash
git clone git@github.com:Nikita2305/ai-native-hse.git
cd ai-native-hse
bash scripts/setup/setup.sh
bash scripts/check/check.sh
bash scripts/doctor/doctor.sh
```

Установка создаёт `.venv/`, готовые настройки, пустую карту треков и ссылки
на навыки для Claude. Повторный запуск не заменяет существующие настройки.
`data/` целиком исключена из git; её можно перенести через `HSE_DATA_DIR`.
Python-клиент Roots использует только стандартную библиотеку; Telethon нужен Telegram.

### Автоматический учебный период

Ничего заполнять не нужно. Инструменты определяют текущий модуль по сегодняшней
дате в часовом поясе Москвы. Внутри модуля используются его начало и конец;
между модулями (в том числе на сессии и каникулах) — начало последнего завершившегося
модуля и текущий момент. Поэтому переписки после окончания занятий не обрезаются.
Посмотреть выбранный период: `bash scripts/hse/hse.sh period`.

Встроены типовые календари [2025/26](https://studyabroad.hse.ru/incoming/year),
[2026/27](https://www.hse.ru/pubs/share/direct/1138696873.pdf) и
[2027/28](https://www.hse.ru/mirror/pubs/share/1205356126.pdf).
График на последующие годы не экстраполируется: после 31.08.2028 понадобится
обновление календаря или явный период. У отдельных программ график отличается.
Для нужного запроса переопределите одну или обе границы через `--since` / `--until`
(даты включительны, по Москве). Безлимитной выдачи нет.

Почта и календарь используют необязательный Node.js 20+ / Playwright:

```bash
bash scripts/setup/setup.sh --browser
bash scripts/check/check.sh --browser
```

На Linux для Chromium могут понадобиться системные библиотеки; установщик
Playwright сообщит недостающие пакеты. Интерактивный вход требует графической сессии.
На сервере можно импортировать Playwright storage state, полученный на своём компьютере.

## Подключение источников

Все пути ниже относятся к **своей** установке. Секреты вводите в локальные файлы
с правами `600`, не в аргументы команд и не в публичный чат.
Не используйте личные аккаунты при запуске тестов.

### Roots

Создайте `data/auth/roots.env`:

```dotenv
ROOTS_BASE_URL=https://roots.zapostim.com
ROOTS_TOKEN=YOUR_OWN_ACCESS_TOKEN
```

```bash
bash scripts/roots/roots.sh projects
bash scripts/roots/roots.sh items --project PROJECT_ID --limit 20 --pages 2
bash scripts/roots/roots.sh item ITEM_ID
bash scripts/roots/roots.sh item ITEM_ID --transcript --offset 0 --chars 8000
bash scripts/roots/roots.sh tags --project PROJECT_ID
```

Токен сервиса начинается с `ra_`. Клиент читает только GET endpoints.
Список items содержит превью; полный текст читается командой item --transcript,
страницы — до `has_more: false`. `next_cursor` означает оставшиеся страницы списка.
Повторяемый `--tag`, `--q`, `--since`, `--cursor` доступны для items.
`--env-file PATH` выбирает отдельный профиль и не смешивает его с токеном окружения.
Без него ROOTS_* из окружения имеют приоритет над файлом.

### Telegram

Получите свои `api_id` / `api_hash` Telegram API и создайте локальный файл
`data/auth/telegram-login.json`: `{"api_id": 12345, "api_hash": "YOUR_HASH", "phone": "+YOUR_NUMBER"}`.

```bash
bash scripts/telegram/telegram.sh send-code --secret-file data/auth/telegram-login.json
# Сохраните полученный код в приватный файл data/auth/telegram-code.txt:
bash scripts/telegram/telegram.sh sign-in --secret-file data/auth/telegram-code.txt
# Если включён 2FA, положите пароль в приватный файл:
bash scripts/telegram/telegram.sh password --secret-file data/auth/telegram-password.txt
bash scripts/telegram/telegram.sh dialogs
bash scripts/telegram/telegram.sh metadata --peer PEER_ID
bash scripts/telegram/telegram.sh topics --peer PEER_ID
bash scripts/telegram/telegram.sh inspect --peer PEER_ID --limit 100
bash scripts/telegram/telegram.sh history --peer PEER_ID --topic-id TOPIC_ID --limit 100
```

После входа удалите одноразовые файлы кода и пароля. Сессия находится в
`data/auth/telegram/`. Личные диалоги, боты, Saved Messages, группы/каналы
с ≤2 участниками не читаются. Неизвестный состав блокирует чтение.
В списке источников нет личных диалогов, ботов и «Избранного».
`dialogs` выводит метаданные групп и каналов, у которых последняя активность
попадает в заданный период, включая архивные: ID, название, username, тип, дату
активности и известное число участников. Период выбирается автоматически по модулю;
`dialogs --since 2030-09-01 --until 2030-09-30` задаёт свой период.
Чаты с неизвестной датой исключаются и учитываются в `unknown_activity_excluded`.
Фильтра по названию нет. Агент выбирает релевантные источники и вызывает
`metadata --peer ID` для проверки состава. `CONTENT_ACCESS_NOT_VERIFIED` означает,
что право чтения ещё не проверено. Каждая команда чтения проверяет состав заново.
Период ограничивает список чатов, а не давность сообщений при последующем чтении.
Метаданные Telegram перечисляются для отбора; тела сообщений не читаются.

`inspect` читает последние N сообщений и до 50 закрепов; это не полная история.
Для следующей страницы истории передайте `--before-id` с минимальным ID прошлой выборки.
`topics` перечисляет до 2000 топиков и сообщает `complete`.
`media --peer ID --message-id ID` возвращает base64 вложения до 25 MiB.
Вступление в чаты, отправка сообщений и отметка прочитанного не выполняются.
При временном отказе проверки не удаляются ни карта источников, ни сессии.
Подтверждённо запрещённое содержимое не сохраняется; постоянного кеша нет.

### Smart LMS

Создайте приватный файл `data/auth/hse-login.json` с обязательными логином и паролем: `{"username":"YOUR_LOGIN","password":"YOUR_PASSWORD"}`.

```bash
bash scripts/lms/lms.sh login --secret-file data/auth/hse-login.json
bash scripts/lms/lms.sh courses
bash scripts/lms/lms.sh page --course-id COURSE_ID
bash scripts/lms/lms.sh contents --course-id COURSE_ID
bash scripts/lms/lms.sh grades --course-id COURSE_ID
bash scripts/lms/lms.sh calendar --year YEAR --month MONTH
```

SSO cookies сохраняются в `data/auth/lms/cookies.txt`. После входа файл пароля можно удалить.
При MFA или изменении SSO команда сообщит об ошибке: универсальный обход не предусмотрен.
Разрешены перечисление курсов, содержимое через известные read API, inline-страница курса,
собственные оценки и календарь Moodle. Произвольные activity pages не открываются,
чтобы не менять completion state. Вложения LMS автоматически не скачиваются.
ПУД и сервис решения капч в проект не включены.

### Почта и календарь ЕЛК

Почтовый аккаунт выбирается при входе в браузере; `folders` и `sync` возвращают
его адреса в поле `account`. Адрес почты в конфиге не нужен.

```bash
bash scripts/mail/mail.sh login
bash scripts/calendar/calendar.sh login
# Альтернатива интерактивному входу (импорт сам по себе не проверяет сессию):
bash scripts/mail/mail.sh import-state --state-file /private/path/state.json
bash scripts/doctor/doctor.sh --online
bash scripts/mail/mail.sh folders
bash scripts/mail/mail.sh sync --since 2030-09-01 --until 2030-09-30 --limit 100 --folder 1
bash scripts/mail/mail.sh attachment --mid MESSAGE_ID --hid PART_ID --name FILE_NAME
bash scripts/calendar/calendar.sh sync --since 2030-09-01 --until 2030-09-30
bash scripts/calendar/calendar.sh profile
bash scripts/calendar/calendar.sh refresh-session
```

Общая браузерная сессия находится в `data/auth/browser/state.json`. Вход настраивается
для почты и ЕЛК отдельно, сохранённые cookies объединяются через текущий context.
Mailbox UI блокируется при входе; чтение почты использует allowlist web API models
и проверяет unread flags выбранных писем до и после чтения. Отправка и изменение
флагов недоступны. При параллельной работе в почте проверка может завершиться ошибкой.
По умолчанию читается Inbox; ID Отправленных и других папок получите через folders.
`limited: true` означает неполную выборку. Вложения перечисляются отдельно,
attachment возвращает base64. ЕЛК показывает занятия, а не все сроки сдачи работ.
`--since`/`--until` можно опустить: используется автоматический учебный период.
Внутренние API ВШЭ и Яндекса могут меняться: ошибки схемы/авторизации требуют проверки адаптера.

### SmartPro

Использует собственные SSO cookies после входа LMS:

```bash
bash scripts/smartpro/smartpro.sh user
bash scripts/smartpro/smartpro.sh participant PARTICIPANT_ID
bash scripts/smartpro/smartpro.sh vacancy VACANCY_ID
bash scripts/smartpro/smartpro.sh project PROJECT_ID
```

ID найдите в своём аккаунте, чужие ID не поставляются. Просмотр собственного профиля
не требует выбора роли. Для чтения entity, если активная роль ещё не выбрана, можно явно добавить `--select-student-role`: это единственное разрешённое
изменение состояния входа, и только при единственной роли EPP_STUDENT.
Заявки, согласования и оценки инструмент не изменяет. Некоторые entity endpoints
могут требовать дополнительный контекст вашей программы; такой ответ не является
подтверждением отсутствия заявки.

## Модель хранения: навигация, не база материалов

Постоянно хранятся только настройки, сессии и `data/tracks.json`:

```json
{
  "version": 1,
  "tracks": [
    {"id": "example-course", "title": "Пример предмета", "status": "active"}
  ],
  "sources": [
    {"id": "example-folder", "kind": "external", "title": "Материалы курса",
     "locator": {"url": "https://example.org/course"}}
  ],
  "links": [
    {"track_id": "example-course", "source_id": "example-folder",
     "status": "candidate", "basis": "Требует проверки принадлежности курсу",
     "checked_at": "2030-09-01"}
  ]
}
```

Здесь всё вымышленное. Один источник может относиться к нескольким трекам;
общие чаты и командные чаты — отдельные источники. Уточнение привязки меняет
`candidate` на `confirmed`, с основанием `basis` и датой проверки `checked_at`.
Статусы трека: active, planned, completed, review.

Допустимые locator по kind:

| kind | locator |
|---|---|
| roots | project_id |
| telegram | peer_id, topic_id (необязательно) |
| lms | course_id |
| mail | folder, subject_terms, body_terms |
| calendar | titles |
| smartpro | entity, id |
| external | url |

```bash
bash scripts/tracks/tracks.sh list
bash scripts/tracks/tracks.sh show example-course
bash scripts/tracks/tracks.sh validate
bash scripts/tracks/tracks.sh replace --file /private/path/reviewed-map.json
```

Агент поддерживает карту после обнаружения и проверки источников. Утилита replace
валидирует связи и атомарно заменяет карту; это не автоматический классификатор.
При вопросе агент читает карту, обращается к источникам заново и отвечает со ссылками.
Сообщения, письма и документы выводятся в stdout; служебные копии живут только
во временном каталоге команды. При обычном завершении и исключениях каталог удаляется;
жёсткое завершение процесса или сбой ОС могут оставить временные файлы в системном temp.
Не перенаправляйте вывод в постоянный архив. Только по явной просьбе пользователя
сохраняйте готовый ответ в ignored `data/output/`.
Поиска по локальному кешу, базы требований и истории синхронизации нет.

## Навыки и диагностика

Канонические навыки: `.agents/skills/{roots,telegram,lms,mail,calendar,smartpro,tracks,hse}`.
Codex и Cursor используют `.agents/skills/`. Для Claude Code выполните
`bash scripts/link-skills/link-skills.sh` (setup уже делает это).
Скрипт создаёт относительные ссылки в `.claude/skills/` и не перезаписывает чужие файлы.
На Windows используйте WSL. Общие правила — AGENTS.md; CLAUDE.md указывает на них.

`check.sh` — синтетические проверки без сети, аккаунтов, Node и личных данных.
`check.sh --browser` добавляет тесты browser adapter и требует browser setup.
`doctor.sh` проверяет зависимости и наличие конфигурации, не утверждая, что вход действителен.
`doctor.sh --online` проверяет настроенные источники без чтения тел писем/сообщений.
LMS проверяется через метаданные курсов, SmartPro — через SSO профиль без выбора роли.
Если сессия или зависимость отсутствует, источник остаётся непроверенным. Диагностика не хранит дату «последней синхронизации», поскольку её нет.

## Структура

- `scripts/<utility>/` — отдельные CLI и установочные утилиты.
- `scripts/browser/` — общий необязательный Node transport почты и календаря.
- `src/ai_native_hse/` — общие Python-модули и реализация CLI.
- `scripts/hse/templates/` — пустые обезличенные шаблоны.
- `tests/` — только искусственные fixtures.
- `data/`, `.venv/`, browser node_modules и ссылки Claude — локальные, ignored.

Лицензия: PolyForm Noncommercial 1.0.0, см. LICENSE и NOTICE.
