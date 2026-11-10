---
name: roots
description: Read Roots Cloud projects, items and transcripts with the student’s own token.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/roots/roots.sh projects
scripts/roots/roots.sh items --project PROJECT_ID --pages 2
scripts/roots/roots.sh item ITEM_ID --transcript --offset 0 --chars 8000
```

Configure data/auth/roots.env. Follow next_cursor and has_more; listing previews are not full transcripts. Use --env-file for isolated profiles. No Node is needed.

All student state belongs in ignored data/. Never commit secrets or source content.
