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

Discovery returns only groups and channels (including archived ones) whose last activity falls within a mandatory finite period. Before first use, fill data/config.json module.start, module.end (YYYY-MM-DD) and module.timezone. For current-module discovery, run dialogs without flags: it uses both configured dates. For another task, override either or both boundaries with --since / --until. Dates are inclusive in module.timezone (UTC if absent). Both boundaries must resolve from config or flags; missing/invalid bounds fail before connection. There is no --all or implicit 30-day fallback. Unknown activity dates are excluded and counted. This window filters dialog activity, not the age of messages read later. No keyword filtering applies. Private dialogs, bots and Saved Messages are excluded. Choose relevant sources yourself; call metadata --peer ID for selected groups. CONTENT_ACCESS_NOT_VERIFIED means no participant check has run yet.
