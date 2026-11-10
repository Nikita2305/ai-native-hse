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

Discovery returns only groups and channels, including archived ones, without keyword or date filtering. Private dialogs, bots and Saved Messages are excluded before constructing output. Choose relevant sources from the metadata yourself; call metadata --peer ID for selected groups. CONTENT_ACCESS_NOT_VERIFIED means no participant check has run yet. Never classify sources using hardcoded tool keyword lists.
