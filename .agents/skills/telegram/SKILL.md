---
name: telegram
description: Discover Telegram source containers and read permitted group content.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/telegram/telegram.sh dialogs
scripts/telegram/telegram.sh metadata --peer PEER_ID
scripts/telegram/telegram.sh topics --peer PEER_ID
scripts/telegram/telegram.sh inspect --peer PEER_ID --limit 100
```

Read-only. DMs, self and groups with <=2 people are forbidden. Unknown participant count blocks reads. Do not join or send. Topic-specific reads use --topic-id. A metadata timeout must not erase the map or sessions.

All student state belongs in ignored data/. Never commit secrets or source content.

Discovery returns only groups and channels, including archived ones, in an automatically selected finite academic period. No setup config editing is required. Moscow is the default timezone. During a module, use its teaching dates; between modules, use the last completed module's start through the current moment. Run scripts/hse/hse.sh period to see the named module and resolved window. --since and --until independently override dates, inclusive in the configured timezone. Optional local module.start/end overrides support atypical programs. Outside the published calendar coverage, update the calendar or pass both dates; never invent future schedules. There is no --all. Unknown activity is excluded and counted. The window filters last dialog activity, not the age of subsequently read messages. Choose relevant groups yourself, without keyword filters; content commands verify participant access live.
