---
name: tracks
description: Maintain a student’s local map from tracks to source containers.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/tracks/tracks.sh list
scripts/tracks/tracks.sh show TRACK_ID
scripts/tracks/tracks.sh replace --file PATH_TO_REVIEWED_MAP
```

Read AGENTS.md and the schema example in README. Persist only navigation metadata in data/tracks.json. Shared sources and candidate links are supported. Do not populate a requirements database, message cache or copied documents.

All student state belongs in ignored data/. Never commit secrets or source content.
